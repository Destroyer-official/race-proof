# Contributing to RaceProof

Thank you for your interest in contributing to RaceProof!
Our goal is to make RaceProof the **definitive 2027+ concurrency verification standard**—grounded in formal database theory, native performance, and mathematically verified evidence.

---

## 🛠️ Development Setup

### Prerequisites
- **Python 3.11+** (tested and optimized on Python 3.15)
- **Rust Toolchain 1.80+** (`rustc`, `cargo`)
- **Maturin** (`pip install maturin`)

### Quickstart

1. **Clone the repository:**
   ```bash
   git clone https://github.com/race-proof/race-proof.git
   cd race-proof
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\Activate.ps1
   ```

3. **Install dependencies and editable package:**
   ```bash
   pip install -r requirements.txt
   pip install -e .
   ```

4. **Build the Native Rust Core (`race_proof_core`):**
   ```bash
   maturin develop -m crates/race_proof_core/Cargo.toml
   ```

5. **Run test suite:**
   ```bash
   pytest -v
   ```

---

## 🏛️ Code Architecture & Standards

- **`race_proof/`**: Main Python package.
  - `analysis/`: Deterministic differential analysis, semantic diffing, interval sweep-line, and happens-before DAGs.
  - `formal/`: TLA+ formal specification generator and state-space interleaving explorer.
  - `agent/`: Local offline Qwen AI brain, WASI-hardened sandbox, tool synthesizer, and consensus swarm.
  - `ingestion/`: Universal tool adapters (Turbo Intruder, QuickDraw, Burp, HAR, Postman, mitmproxy, k6).
  - `evidence/`: SARIF 2.1.0 exporter, Ed25519 in-toto attestations, and standalone HTML audit dashboards.
  - `bench/`: Ground-truth benchmark runner and scorecard generator.
  - `tui/`: Interactive Terminal UI built with Textual.
- **`crates/race_proof_core`**: Native Rust SIMD kernels exposed to Python via PyO3.
- **`race_proof_bench/`**: Versioned corpus of labeled ground-truth scenarios.

---

## 🔌 Adding a New Ingestion Adapter

To add support for a new tool format (e.g., custom proxy or cloud trace):
1. Create a new module in `race_proof/ingestion/<tool_name>.py`.
2. Inherit from `BaseAdapter` and implement `parse(file_path: Path) -> list[RaceSession]`.
3. Register your adapter in `race_proof/ingestion/__init__.py` and in `auto_detect()`.
4. Add unit tests in `tests/test_adapters_and_standards.py`.

---

## 🏆 Adding a Benchmark Scenario

All benchmark scenarios live under `race_proof_bench/<domain>/bench_<domain>_<num>.json`.
Every scenario must conform to the JSON schema in `race_proof_bench/schemas/bench-scenario.v1.json`:
- `scenario_id`: Unique identifier (e.g., `bench_fin_006`).
- `domain`: One of `fintech`, `ecommerce`, `auth_identity`, `distributed_queues`, `graphql_mutations`, `grpc_microservices`.
- `ground_truth_verdict`: `CONFIRMED` or `BENIGN`.
- `baseline`: Baseline single-request response.
- `race_responses`: Concurrent response burst.
- `invariants`: Formal assertions evaluated over the responses.

Run the scorecard after adding:
```bash
race-proof bench -v
```

---

## 🧪 Quality Checklist

Before submitting a Pull Request, verify:
- [ ] All tests pass: `pytest -q`
- [ ] Type hints are complete and clean (`py.typed` compliant).
- [ ] Rust core compiles without warnings: `cargo check --manifest-path crates/race_proof_core/Cargo.toml`
- [ ] Benchmark precision and recall remain at 100% on the ground-truth corpus.

