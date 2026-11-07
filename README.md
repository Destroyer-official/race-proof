# RaceProof

Deterministic concurrency verification and formal state-space analysis engine for HTTP APIs.

[![Release](https://img.shields.io/github/v/release/Destroyer-official/race-proof?color=blue)](https://github.com/Destroyer-official/race-proof/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.15-blue)](https://www.python.org/)
[![Rust 1.80+](https://img.shields.io/badge/Rust-1.80%2B-orange)](https://www.rust-lang.org/)
[![SARIF 2.1.0](https://img.shields.io/badge/SARIF-2.1.0-green)](https://sarifweb.azurewebsites.net/)
[![in-toto v1.0](https://img.shields.io/badge/in--toto-v1.0%20Ed25519-purple)](https://in-toto.io/)

---

## Table of Contents

1. [Overview](#1-overview)
2. [The Concurrency Verification Problem](#2-the-concurrency-verification-problem)
3. [Architecture and Analysis Pipeline](#3-architecture-and-analysis-pipeline)
4. [Supported Ingestion Formats](#4-supported-ingestion-formats)
5. [Installation](#5-installation)
6. [Command-Line Reference](#6-command-line-reference)
7. [Writing Invariant Rules](#7-writing-invariant-rules)
8. [Evidence Bundle Output](#8-evidence-bundle-output)
9. [Benchmark Corpus and Results](#9-benchmark-corpus-and-results)
10. [Backward Compatibility with `race_oracle`](#10-backward-compatibility-with-race_oracle)
11. [Documentation Links](#11-documentation-links)
12. [License](#12-license)

---

## 1. Overview

**RaceProof** is an offline, verification-first analysis engine that assesses whether concurrent HTTP request bursts caused unintended state corruption in a target web application.

Most security testing tools (e.g. Burp Suite Turbo Intruder, Nuclei, k6, mitmproxy) focus on **burst transmission**—dispatching multiple HTTP requests as close together in time as possible. However, analyzing the resulting response sets is typically left to simplistic string-matching or status-code heuristics. 

RaceProof operates **downstream** of transmission tools. It takes the recorded HTTP traffic logs, parses the concurrent responses, removes dynamic non-deterministic noise (timestamps, CSRF nonces, session cookies), and evaluates whether business invariants were violated. When an invariant violation is identified, RaceProof:

1. Maps the failure to a database concurrency defect class (`LOST_UPDATE`, `TOCTOU_DIRTY_READ`, `WRITE_SKEW`, `LIMIT_OVERRUN`).
2. Calculates exact server-side concurrency overlap using time-to-first-byte (TTFB) delta calculations.
3. Formally models the execution in TLA+ and explores the reachability of the invalid state across possible thread interleavings.
4. Generates a standalone, deterministic Python reproduction script using `asyncio.Barrier` synchronization.
5. Emits a structured evidence bundle containing **SARIF 2.1.0** reports, an interactive visual HTML dashboard, and an **in-toto Statement v1.0** cryptographic attestation.

RaceProof is 100% offline. It contains no external tracking, requires no cloud accounts, and makes no remote network calls during analysis.

---

## 2. The Concurrency Verification Problem

In HTTP-based services, evaluating race condition vulnerabilities presents several technical challenges:

### 2.1 Status Codes Are Ambiguous
Receiving multiple `HTTP 200 OK` responses across concurrent requests does not prove a race condition exists:
- Read-only endpoints (`GET /api/v1/profile`) naturally return `200 OK` to all concurrent callers.
- Idempotent updates (`PUT /api/v1/settings` with identical payloads) safely return `200 OK`.
- Endpoints with application-level queuing may return `200 OK` while processing requests serially.

### 2.2 Ephemeral Token Differences Induce Spurious Variance
Comparing raw response bodies byte-by-byte produces false positives because modern web frameworks inject dynamic values on every response:
- CSRF nonces and form tokens
- UUIDs and request tracking IDs
- ISO-8601 timestamps and Unix epochs
- Ephemeral JWT signatures and cache headers

### 2.3 Network Jitter Distorts Arrival Order
Requests sent concurrently across the public Internet do not arrive at the backend database simultaneously. Load balancers, reverse proxies, and TLS termination points introduce latency jitter. An analysis tool must measure the **server-side processing window** ($\Delta = \text{Elapsed} - \text{TTFB}$) to determine whether two requests actually executed concurrently within the same database transaction window.

---

## 3. Architecture and Analysis Pipeline

The RaceProof pipeline processes concurrent HTTP captures through seven deterministic stages:

```
[ Ingestion Log ] (Burp XML, HAR, k6, mitmproxy, Postman, OTel, WebSocket)
       │
       ▼
[ Normalization ] ──► Uniform RaceSession (Baseline + Concurrent Responses)
       │
       ▼
[ Ephemeral Masking ] ──► Regex DFA masking of UUIDs, Nonces, Dates, JWTs
       │
       ▼
[ Deterministic Analysis Core ]
       ├── 1. Semantic Token Differ (Myers / Patience diffing)
       ├── 2. Timing Sweep-Line Analysis (ReqRacer happens-before DAG: ≺_web)
       ├── 3. SimHash & MinHash LSH (Near-duplicate clustering)
       ├── 4. Business Invariant Engine (relational & numeric assertions)
       └── 5. Hypothesis Testing (Wilson score 95% CI + binomial p-values)
       │
       ▼
[ Formal Verification Engine ] ──► TLA+ Model Generator & BFS State-Space Explorer
       │
       ▼
[ Multi-Agent Consensus Swarm ] ──► Parallel Adversary & Prover validation
       │
       ▼
[ Evidence Output ] ──► SARIF 2.1.0, in-toto Attestation, diff.html, PoC script
```

### 3.1 Ephemeral Field Masking
Before text comparison, the response body is passed through deterministic regular expression automata that normalize volatile fields without modifying the underlying data structure:
- **UUIDs**: `[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}` $\to$ `<UUID_MASK>`
- **Timestamps**: ISO-8601 (`2026-11-07T12:00:00Z`) and Unix timestamps $\to$ `<TIMESTAMP_MASK>`
- **Tokens**: JWT strings (`ey...`) and hexadecimal tokens ($>16$ chars) $\to$ `<NONCE_MASK>`

### 3.2 Temporal Analysis (ReqRacer Concurrency DAG)
RaceProof calculates the exact flight window for each response:
$$\text{Server Window} = \left[ t_{\text{sent}} + \text{TTFB},\; t_{\text{sent}} + t_{\text{elapsed}} \right]$$
Using an interval sweep-line algorithm implemented in Rust (`crates/race_proof_core`), RaceProof computes the pairwise interval overlap across all responses. If interval overlap is zero, requests were serialized by the web tier and cannot represent a database race condition.

### 3.3 Semantic Diffing and Clustering
- **64-bit SIMD SimHash**: Fast Hamming distance calculation ($k \le 3$) to identify identical clusters.
- **MinHash with Banded LSH ($B=32, R=4$)**: Parallel near-duplicate clustering implemented via `rayon` to scale across tens of thousands of concurrent responses.
- **State Stalling Detection**: Flags instances where concurrent requests observe an identical pre-commit state value (e.g. identical balance) prior to committing independent mutations.

### 3.4 Invariant Engine
The invariant engine applies formal predicates across responses:
- `single_winner`: Exactly one response may match a given condition (e.g. `status_code == 200` or `body.status == "SUCCESS"`).
- `any_negative`: No numeric field (e.g. `balance`, `remaining_stock`) may drop below zero.
- `state_stall`: Multiple mutating responses must not reflect the same snapshot value.
- `unique`: Identifiers returned in responses (e.g. voucher IDs, coupon tokens) must be mutually distinct.
- `numeric_lte`: A numeric field must not exceed a specified threshold.

### 3.5 Formal TLA+ Verification (`race-proof prove`)
RaceProof automatically translates observed API transactions into formal TLA+ mathematical models:
- Generates `WebApiRaceModel.tla` and `WebApiRaceModel.cfg`.
- Executes an internal breadth-first state-space model checker exploring all reachable execution interleavings.
- Emits the exact step-by-step interleaving trace showing the thread scheduling order that triggers the invariant breach.

---

## 4. Supported Ingestion Formats

RaceProof includes dedicated parsers for 11 log and proxy capture formats:

| Format / Tool | Source Extension | Description |
| :--- | :--- | :--- |
| **HTTP Archive (`.har`)** | `.har` | Chrome DevTools, Burp Suite, OWASP ZAP, Proxyman export |
| **Burp Suite Turbo Intruder** | `.json` | Turbo Intruder JSON table export containing request/response logs |
| **Burp Suite XML** | `.xml` | Native Burp Suite "Save items" XML export with Base64 payload decoding |
| **mitmproxy** | `.json` / `.flow` | Flows exported via `mitmproxy2json` or Python flow dump scripts |
| **Postman / Newman** | `.json` | Collection run summary logs exported via `newman -r json` |
| **k6 Load Testing** | `.json` / `.ndjson` | Metrics and response streams exported via `k6 run --out json` |
| **Nuclei (Race Templates)** | `.jsonl` | Nuclei race-condition template output lines |
| **OpenTelemetry (OTel)** | `.json` | OTel distributed trace JSON containing concurrent `resourceSpans` |
| **WebSocket Message Frames** | `.json` | Structured JSON log of bidirectional WebSocket frames |
| **Raw HTTP Transcripts** | `.txt` / `.json` | Plain text RFC-7230 request and response pairs |
| **QuickDraw HTTP/3** | `.jsonl` | High-concurrency QUIC/HTTP-3 burst output logs |

The tool format is automatically detected from file contents, or can be specified explicitly via `--source`.

---

## 5. Installation

### 5.1 Prerequisites
- **Python**: Version 3.11, 3.12, 3.13, or 3.15.
- **Rust Toolchain (Optional)**: Version 1.80+ required only if compiling the native acceleration core from source. If Rust is not installed, RaceProof runs on pure Python fallbacks.

### 5.2 From Source (Standard Installation)

```bash
# 1. Clone the repository
git clone https://github.com/Destroyer-official/race-proof.git
cd race-proof

# 2. Install dependencies and the package in editable mode
pip install -r requirements.txt
pip install -e .
```

### 5.3 Building the Native Rust Core (Optional Speedup)

```bash
# Build and install the PyO3 native extension
pip install maturin
maturin develop -m crates/race_proof_core/Cargo.toml
```

### 5.4 Docker Deployment

```bash
# Build the container image
docker build -t race-proof .

# Run verification on a local capture file
docker run --rm -v $(pwd):/data race-proof verify -i /data/capture.har
```

---

## 6. Command-Line Reference

RaceProof provides seven subcommands through the `race-proof` executable:

```text
Usage: race-proof [OPTIONS] COMMAND [ARGS]...

Commands:
  verify       Verify race condition findings from an attack tool's output.
  prove        Mathematically prove concurrency invariants using TLA+ formal models.
  bench        Run RaceProof against the Ground-Truth Benchmark Corpus.
  hunt         Synthesize high-precision async reproduction PoC with microsecond barrier.
  tui          Launch the modern interactive Terminal UI (TUI).
  agent        Run autonomous AI agent goal execution and memory commands.
  stats        Show self-improvement statistics and learned pattern database.
```

### 6.1 `race-proof verify`

Verifies a captured response set from a proxy or attack tool log.

```bash
race-proof verify -i <input-file> [OPTIONS]
```

**Options:**
- `-i, --input PATH`: Path to log file (`.har`, `.json`, `.xml`, `.ndjson`). **[Required]**
- `-s, --source TEXT`: Source format (`har`, `turbo_intruder`, `burp_xml`, `mitmproxy`, `k6`, `postman`, `nuclei`, `otel`, `websocket`, `raw`, `auto`). Default: `auto`.
- `-r, --rules PATH`: Optional YAML file containing custom business invariant rules.
- `-o, --output PATH`: Directory to save the evidence bundle. Default: `./race_proof_findings`.
- `--seed INTEGER`: Fixed random seed for deterministic Wilson score calculations. Default: `42`.
- `--json`: Output raw verdict JSON to stdout instead of formatted terminal tables.

**Example:**
```bash
race-proof verify -i examples/sample_input/har_race_confirmed.har -o ./findings
```

**Exit Codes:**
- `0`: Invariant violation confirmed (`CONFIRMED`).
- `1`: Error encountered during execution.
- `2`: No invariant violation found (`BENIGN` or `NOISE`).

---

### 6.2 `race-proof prove`

Translates an API session into a formal TLA+ model and runs the BFS explicit state-space model checker.

```bash
race-proof prove -i <input-file> [OPTIONS]
```

**Options:**
- `-i, --input PATH`: Path to session log or JSON finding. **[Required]**
- `--initial-balance INTEGER`: Initial numerical state balance (e.g. `100`). Default: `100`.
- `--cost INTEGER`: Cost per concurrent mutating action (e.g. `100`). Default: `100`.
- `--isolated`: Model atomic/serialized transaction execution (proves safety baseline).
- `--tla-out PATH`: Save the generated TLA+ specification to a `.tla` file.

**Example:**
```bash
race-proof prove -i examples/sample_input/har_race_confirmed.har \
  --initial-balance 100 \
  --cost 100 \
  --tla-out WebApiRaceModel.tla
```

---

### 6.3 `race-proof bench`

Runs the verification engine against the versioned 31-scenario Ground-Truth Benchmark Corpus.

```bash
race-proof bench [OPTIONS]
```

**Options:**
- `-d, --domain TEXT`: Filter execution to a single domain (e.g. `fintech`, `ecommerce`, `auth_identity`).
- `-m, --markdown PATH`: Path to write the rendered Markdown scorecard.
- `-j, --json PATH`: Path to write the machine-readable JSON scorecard.
- `-v, --verbose`: Print detailed per-scenario diagnostic logs.

**Example:**
```bash
race-proof bench -m scorecard.md -j scorecard.json
```

---

### 6.4 `race-proof hunt`

Synthesizes a high-precision Python reproduction script utilizing `asyncio.Barrier` synchronization to reproduce confirmed race conditions against an authorized endpoint.

```bash
race-proof hunt -u <target-url> -n <num-requests> [OPTIONS]
```

**Options:**
- `-u, --url TEXT`: Target URL to evaluate. **[Required]**
- `-n, --num-requests INTEGER`: Number of concurrent requests to align. Default: `5`.
- `-m, --method TEXT`: HTTP method (`POST`, `PUT`, `GET`). Default: `POST`.
- `-H, --header TEXT`: Custom header in `"Header: Value"` format. Can be specified multiple times.
- `-d, --data TEXT`: Request payload body.
- `-o, --output PATH`: Output path for the synthesized Python script. Default: `reproduce_race.py`.

---

### 6.5 `race-proof tui`

Launches the interactive dark-mode Terminal User Interface.

```bash
race-proof tui
```

**Navigation Shortcuts:**
- `q`: Quit application.
- `d`: Navigate to **Dashboard** tab.
- `v`: Navigate to **Verify** tab.
- `b`: Navigate to **Benchmark** tab.
- `p`: Navigate to **Formal Proof** tab.
- `h`: Navigate to **PoC Hunt** tab.
- `a`: Navigate to **AI Agent** tab.
- `l`: Navigate to **Event Logs** tab.

---

## 7. Writing Invariant Rules

While RaceProof automatically mines latent invariants from status codes and response bodies, you can define explicit domain-specific invariants in a YAML file:

```yaml
invariants:
  - id: single_coupon_winner
    description: "At most one coupon application may succeed"
    severity: HIGH
    operator: single_winner
    field: status_code
    threshold: 1.0

  - id: balance_non_negative
    description: "Account balance must never drop below zero"
    severity: CRITICAL
    operator: any_negative
    field: account.balance
    threshold: 0.0

  - id: unique_transaction_ids
    description: "All minted transaction identifiers must be distinct"
    severity: HIGH
    operator: unique
    field: data.transaction_id

  - id: no_stale_balance_reads
    description: "Concurrent threads must not read identical pre-commit balance"
    severity: HIGH
    operator: state_stall
    field: balance
```

Pass the file to `verify`:
```bash
race-proof verify -i capture.har -r custom_rules.yaml
```

---

## 8. Evidence Bundle Output

When RaceProof confirms a vulnerability, it creates an evidence directory (`./race_proof_findings/<finding_id>/`) containing:

```text
race_proof_findings/finding_HAR-FIN-001_8a12c4/
├── sarif.json                # SARIF 2.1.0 report with threadFlow traces
├── attestation.sigstore.json # in-toto Statement v1.0 signed with Ed25519
├── diff.html                 # Standalone interactive visual diff & waterfall SVG
├── WebApiRaceModel.tla       # Synthesized TLA+ formal specification
├── WebApiRaceModel.cfg       # TLC model checker configuration file
├── input_session.json        # Normalized capture session log
└── reproduce_race.py         # Standalone asyncio barrier reproduction script
```

### 8.1 SARIF 2.1.0 Integration
The `sarif.json` output is compatible with GitHub Advanced Security, GitLab SAST, DefectDojo, and any standard SARIF consumer:
```json
{
  "version": "2.1.0",
  "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
  "runs": [
    {
      "tool": {
        "driver": {
          "name": "RaceProof",
          "version": "0.2.0",
          "rules": [
            {
              "id": "RP-LOST-UPDATE",
              "name": "LostUpdateConcurrencyDefect",
              "shortDescription": { "text": "Unsynchronized concurrent read-modify-write cycle" }
            }
          ]
        }
      }
    }
  ]
}
```

---

## 9. Benchmark Corpus and Results

RaceProof is continuously evaluated against a versioned Ground-Truth Corpus located in [`race_proof_bench/`](race_proof_bench/):

### Summary Metrics Across 31 Scenarios

| Domain | Scenarios | True Positives | False Positives | True Negatives | False Negatives | Precision | Recall |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `fintech` | 5 | 3 | 0 | 2 | 0 | **100.0%** | **100.0%** |
| `ecommerce` | 5 | 3 | 0 | 2 | 0 | **100.0%** | **100.0%** |
| `auth_identity` | 5 | 4 | 0 | 1 | 0 | **100.0%** | **100.0%** |
| `distributed_queues` | 4 | 2 | 0 | 2 | 0 | **100.0%** | **100.0%** |
| `graphql_mutations` | 3 | 2 | 0 | 1 | 0 | **100.0%** | **100.0%** |
| `grpc_microservices` | 3 | 2 | 0 | 1 | 0 | **100.0%** | **100.0%** |
| `cache_stampede` | 2 | 1 | 0 | 1 | 0 | **100.0%** | **100.0%** |
| `storage_toctou` | 2 | 1 | 0 | 1 | 0 | **100.0%** | **100.0%** |
| `websocket_frames` | 2 | 1 | 0 | 1 | 0 | **100.0%** | **100.0%** |
| **Total** | **31** | **19** | **0** | **12** | **0** | **100.0%** | **100.0%** |

- **Precision**: $100.0\%$ (Zero false positives recorded across all benign control scenarios).
- **Recall**: $100.0\%$ (All 19 true concurrent vulnerabilities correctly detected).
- **Matthews Correlation Coefficient (MCC)**: $1.0000$.

To reproduce the benchmark scorecard locally:
```bash
python bench/run_bench.py
```

---

## 10. Backward Compatibility with `race_oracle`

To preserve compatibility with legacy installations and existing automated scripts, RaceProof includes a complete 1:1 dual compatibility mirror in the `race_oracle` namespace:

- Both CLI commands (`race-proof` and `race-oracle`) are installed and function identically.
- All Python imports from `race_oracle.*` (e.g. `race_oracle.analysis.invariants`, `race_oracle.evidence.sarif`) re-export all symbols from `race_proof.*`.
- Both Windows PowerShell (`.\Run_Race_Proof.ps1`, `.\Run_Race_Oracle.ps1`) and Unix bash runners (`./run_race_proof.sh`, `./run_race_oracle.sh`) are maintained in the repository root.

---

## 11. Documentation Links

- [System Architecture](docs/architecture.md) — Detailed specifications of all internal analysis engines.
- [Writing Invariants](docs/invariants.md) — Reference guide for rule authoring with 10 real-world examples.
- [Benchmark Corpus Standard](docs/benchmark.md) — Methodology, scenario schemas, and statistical verification.
- [Threat Model and Security](docs/threat-model.md) — Ingestion boundary protections and sandbox limits.
- [Offline AI and Sandbox Architecture](docs/ai.md) — Local model inference, temperature calibration, and sandbox execution.
- [Reproducibility Specification](REPRODUCIBILITY.md) — Deterministic seeds and bit-for-bit output reproduction.
- [Cryptographic Attestation](ATTESTATION.md) — Verification of in-toto Statement v1.0 signatures via OpenSSL and cosign.
- [Contributing Guidelines](CONTRIBUTING.md) — Development setup, PR requirements, and adapter guidelines.
- [Security Policy](SECURITY.md) — Vulnerability reporting, response SLAs, and supply chain integrity.

---

## 12. License

RaceProof is licensed under the [MIT License](LICENSE).
