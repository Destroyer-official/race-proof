# RaceProof

> **Deterministic Concurrency Verification and Formal State-Space Analysis Engine for HTTP APIs.**  
> Analyzes concurrent HTTP response bursts to determine whether invariant violations occurred versus benign network variance.
> Operates downstream of security testing proxies and burst execution tools (Burp Suite, Turbo Intruder, mitmproxy, Postman, k6, Nuclei, OpenTelemetry, and WebSockets).

[![CI](https://github.com/Destroyer-official/race-proof/actions/workflows/ci.yml/badge.svg)](https://github.com/Destroyer-official/race-proof/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.15-blue)](https://www.python.org/)
[![Rust 1.80+](https://img.shields.io/badge/Rust-1.80%2B-orange)](https://www.rust-lang.org/)
[![SARIF 2.1.0](https://img.shields.io/badge/SARIF-2.1.0-green)](https://sarifweb.azurewebsites.net/)

---

## 1. Technical Overview

Automated burst generators fire concurrent HTTP requests at high volume. However, raw server responses contain non-deterministic variance (dynamic timestamps, CSRF nonces, session identifiers, and load-balancer jitter) that produce false positives when compared naively.

**RaceProof** evaluates captured response sets using formal differential analysis and mathematical model checking:

1. **Native Rust Core (`race_proof_core`)**:
   - **Parallel MinHash + Banded LSH Clustering ($B=32, R=4$)**: Clusters response bodies in linear time using multi-threaded `rayon` parallelism.
   - **64-bit SIMD SimHash & Hamming Distance**: Identifies near-duplicate response clusters and anomalous outliers.
   - **ReqRacer Sweep-Line Interval Overlap**: Calculates exact server-side processing windows and in-flight concurrency density ($\prec_{web}$).
2. **Semantic Diffing & Dynamic Field Masking**:
   - Automatically masks dynamic nonces, UUIDs, ISO-8601 timestamps, Unix epochs, and JWT tokens prior to structural diffing.
   - Detects stale reads and lost update conditions where concurrent requests return identical pre-commit state snapshots.
3. **Statistical Hypothesis Testing**:
   - Evaluates anomaly frequency using Wilson score 95% confidence bounds with continuity correction.
   - Computes binomial test p-values and applies Holm-Bonferroni correction across multi-test scenarios.
4. **Formal Verification Bridge (`race-proof prove`)**:
   - Generates formal **TLA+ Specifications (`WebApiRaceModel.tla`)** and TLC model checker configurations from API sessions.
   - Explores all thread interleavings via explicit state-space model checking and emits step-by-step counterexample execution traces.
5. **Anti-Hallucination Multi-Agent Swarm**:
   - Runs three analytical agents in parallel (Adversary Skeptic, Formal Prover, and Database Remediation Architect).
   - Requires formal invariant breach confirmation while rejecting noise, client errors, and HTTP 429 throttling.
6. **Standards-Compliant Output**:
   - Emits **SARIF 2.1.0** static analysis reports with execution `threadFlows`.
   - Generates cryptographically signed **in-toto Statement v1.0** attestations using Ed25519 keys.
   - Produces standalone interactive HTML audit dashboards with microsecond timing waterfall SVGs.

---

## 2. Ingestion Format Support

RaceProof automatically detects and parses logs from:
- **Burp Suite Turbo Intruder** (`.json` exports)
- **Burp Suite XML Item Exports** (`.xml` files with base64 decoding)
- **HTTP Archive (`.har`)**: Chrome DevTools, Burp Suite, OWASP ZAP, Proxyman
- **mitmproxy** (`.json` / flow dumps with microsecond timing)
- **Postman / Newman** (`.json` collection run reports via `newman -r json`)
- **k6 Load Testing** (`.ndjson` metric logs via `k6 run --out json`)
- **Nuclei Concurrency Templates** (`.jsonl` output)
- **OpenTelemetry (OTel)** (`.json` distributed trace exports with `resourceSpans`)
- **WebSocket Message Logs** (`.json` frame sequences with direction and opcode)
- **Raw HTTP Transcripts** (`.json` / `.txt`)

---

## 3. Ground-Truth Benchmark Corpus (`race_proof_bench`)

RaceProof includes a versioned benchmark corpus evaluated continuously in CI:

```bash
race-proof bench
```

### Verified Benchmark Scorecard (31 Ground-Truth Scenarios)

| Domain | Scenarios | True Positives | False Positives | True Negatives | False Negatives | Precision | Recall | F1 Score |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Fintech & Banking** | 5 | 3 | 0 | 2 | 0 | **100.0%** | **100.0%** | **1.0000** |
| **E-Commerce & Retail** | 5 | 3 | 0 | 2 | 0 | **100.0%** | **100.0%** | **1.0000** |
| **Auth & Identity** | 5 | 4 | 0 | 1 | 0 | **100.0%** | **100.0%** | **100.0%** |
| **GraphQL Mutations** | 3 | 2 | 0 | 1 | 0 | **100.0%** | **100.0%** | **1.0000** |
| **gRPC Microservices** | 3 | 2 | 0 | 1 | 0 | **100.0%** | **100.0%** | **1.0000** |
| **Distributed Queues** | 4 | 2 | 0 | 2 | 0 | **100.0%** | **100.0%** | **1.0000** |
| **Cache Stampede** | 2 | 1 | 0 | 1 | 0 | **100.0%** | **100.0%** | **1.0000** |
| **Cloud Storage TOCTOU** | 2 | 1 | 0 | 1 | 0 | **100.0%** | **100.0%** | **1.0000** |
| **WebSocket Message Ordering** | 2 | 1 | 0 | 1 | 0 | **100.0%** | **100.0%** | **1.0000** |
| **OVERALL COMPOSITE** | **31** | **19** | **0** | **12** | **0** | **100.0%** | **100.0%** | **1.0000** |

- **Precision**: `100.0%` (Zero False Discoveries)
- **Recall**: `100.0%`
- **Matthews Correlation Coefficient (MCC)**: `1.0000`
- **Average Evaluation Latency**: ~2.1 ms per scenario.

---

## 4. Installation

### From Source

```bash
git clone https://github.com/Destroyer-official/race-proof.git
cd race-proof

# Install Python package dependencies:
pip install -r requirements.txt
pip install -e .

# Compile native Rust acceleration core:
maturin build -m crates/race_proof_core/Cargo.toml
pip install crates/race_proof_core/target/wheels/*.whl
```

### Windows PowerShell Launcher

```powershell
.\Run_Race_Proof.ps1
```

---

## 5. Usage

### 1. Verify Attack Logs

```bash
# Auto-detect tool format and generate evidence bundle:
race-proof verify -i capture.json -o ./findings

# Verify an HTTP Archive (.har) with custom YAML invariant rules:
race-proof verify -i traffic.har -r invariants.yaml

# Silent JSON output for CI/CD gating (returns non-zero exit code on CONFIRMED):
race-proof verify -i results.json --json-output
```

### 2. Formal Verification (`race-proof prove`)

Mathematically prove whether an observed concurrency pattern can breach safety invariants across all possible interleavings:

```bash
# Explore interleaving state space:
race-proof prove -i race_proof_bench/fintech/bench_fin_001.json

# Export formal TLA+ specification:
race-proof prove -i race_proof_bench/fintech/bench_fin_001.json --tla-out WebApiRaceModel.tla

# Verify safety under atomic / serializable isolation guarantees:
race-proof prove -i race_proof_bench/fintech/bench_fin_001.json --isolated
```

### 3. PoC Synthesis (`race-proof hunt`)

Generate asynchronous Python reproduction scripts with microsecond barrier synchronization:

```bash
race-proof hunt --target "https://api.target.com/v1/coupon/redeem" \
                --method POST \
                --concurrency 20 \
                --protocol h2 \
                -o reproduce_race.py
```

### 4. Interactive Terminal User Interface (TUI)

Launch the interactive Terminal UI with full mouse clickability and keyboard navigation:

```bash
race-proof tui
```

Hotkeys:
- `d`: System Dashboard (engine telemetry and quick launchpad)
- `v`: Attack Verification (presets, custom logs, Wilson CIs, SARIF export)
- `b`: Benchmark Suite (31 scenarios, live progress, scorecard export)
- `p`: Formal Proof (interleaving state explorer and TLA+ model viewer)
- `h`: PoC Synthesizer (async barrier script generator)
- `a`: AI Agent (autonomous ReAct reasoning stream)
- `l`: Real-time Event Logs
- `q`: Quit

---

## 6. GitHub Actions Integration

Use the official RaceProof GitHub Action directly in any workflow:

```yaml
- name: Verify Concurrency Findings
  uses: Destroyer-official/race-proof@v0.2.0
  with:
    input: ./test_results/turbo_intruder.json
    fail-on: CONFIRMED
    sarif-out: findings.sarif

- name: Upload SARIF to GitHub Security Tab
  uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: findings.sarif
```

---

## 7. Testing

The test suite covers all analysis dimensions, native Rust kernels, ingestion adapters, formal verification, property-based fuzzing (Hypothesis), adversarial prompt injection, and the interactive TUI:

```bash
pytest -v
```

**71 passed tests (100% pass rate)**.

---

## 8. License

This project is licensed under the [MIT License](LICENSE).
