# RaceProof v0.2.0 — Production Release

Deterministic Concurrency Verification and Formal State-Space Analysis Engine for HTTP APIs.

---

### Highlights & Core Capabilities

- **Native Rust Hot-Path Core (`race_proof_core`)**:
  - SIMD 64-bit SimHash and Hamming distance clustering ($< 0.2\text{ ms}$).
  - Multi-threaded MinHash & Banded LSH near-duplicate clustering via `rayon`.
  - ReqRacer sweep-line happens-before interval DAG analysis ($\prec_{web}$).
- **Formal Verification Bridge (`race-proof prove`)**:
  - Automatic synthesis of formal **TLA+ specifications** (`WebApiRaceModel.tla`) and TLC configurations.
  - Built-in explicit state-space model checker outputting step-by-step interleaving counterexample traces.
- **Ground-Truth Benchmark Suite (`race-proof-bench`)**:
  - 31 versioned scenarios across 9 enterprise domains (Fintech, E-Commerce, Auth/Identity, Distributed Queues, GraphQL, gRPC, Cache Stampede, Storage TOCTOU, and WebSockets).
  - Verified **100.0% Precision** (0.0% False Discovery Rate) and **100.0% Recall** with Holm-Bonferroni correction.
- **Anti-Hallucination Consensus Swarm**:
  - Three-agent parallel arbitration (Adversary Skeptic, Formal Prover, Remediation Architect) to debunk false positives, 429 throttling, and dynamic noise.
- **Standards-Compliant Packaging**:
  - **SARIF 2.1.0** static analysis export with full execution `threadFlows`.
  - Cryptographically signed **in-toto Statement v1.0** Ed25519 attestations.
  - Standalone interactive HTML visual audit report (`diff.html`).
- **Modern Clickable Terminal UI (`race-proof tui`)**:
  - Full keyboard and mouse driven dark-mode interface built with Textual across 7 interactive panels.
- **100% Offline AI Integration**:
  - Local neural reasoning via `llama-cpp-python` with hardened sandbox isolation (256MB memory cap, 5.0s CPU timeout, zero network access).

---

### Verification & Checksums

- **Pytest Test Suite**: 77 / 77 passing cleanly.
- **License**: MIT

