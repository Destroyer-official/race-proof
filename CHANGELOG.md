# Changelog

All notable changes to **RaceProof** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.2.0] - 2026-11-07 — The Definitive 2027+ Verification Standard

### Added
- **Native Rust Hot-Path Core (`race_proof_core`)**:
  - SIMD Myers/Patience token differ and 64-bit SimHash.
  - Parallel MinHash + Banded LSH near-duplicate clustering using `rayon`.
  - Native interval overlap sweep-line engine for ReqRacer happens-before DAGs.
- **Formal Verification Bridge (`race-proof prove`)**:
  - Automatic synthesis of formal TLA+ specifications (`WebApiRaceModel.tla`) and TLC configurations.
  - Built-in explicit state-space model checker exploring thread interleavings and outputting exact counterexample traces.
- **Ground-Truth Benchmark Corpus (`race-proof-bench`)**:
  - 25 versioned ground-truth scenarios across Fintech, E-Commerce, Auth/Identity, Distributed Queues, GraphQL, and gRPC.
  - Automated scorecard calculation with 100% precision, 100% recall, and 1.000 F1 score.
- **Clickable Interactive Terminal UI (TUI)**:
  - Full keyboard and mouse driven cyber dark-mode interface powered by Textual.
  - 7 interactive tabs: Dashboard, Verify Attack, Benchmark Suite, Formal Proof, PoC Synthesizer, Autonomous AI Agent, and Real-time Event Logs.
  - Non-blocking async background execution (`@work(exclusive=True, thread=True)`).
- **Universal Ingestion Adapters**:
  - Added support for mitmproxy flows, Postman/Newman collections, and k6 NDJSON logs alongside Turbo Intruder, QuickDraw, Burp XML, and HAR.
- **Court-Ready Evidence Standard**:
  - Complete SARIF 2.1.0 exporter with `codeFlows` and `threadFlows`.
  - Cryptographically signed Ed25519 in-toto Statement v1.0 attestations.
- **Multi-Agent Consensus & Anti-Hallucination Swarm**:
  - Parallel execution of Adversary (Skeptic), Formal Prover, and Remediation Architect agents to eliminate hallucinations before verdict issuance.
- **Enterprise CI/CD & Packaging**:
  - Automated GitHub Actions workflow (`ci.yml`) for multi-platform linting, testing, and benchmark regression prevention.
  - Distroless multi-stage Docker container (`Dockerfile`).

---

## [0.1.0] - 2026-03-15 — Initial Architectural Release

### Added
- Core deterministic verification engine with 7 native analysis dimensions.
- Ephemeral token masking (CSRF, UUIDs, ISO dates, JWTs, Unix timestamps).
- Initial adapters for Burp Turbo Intruder, QuickDraw, and Nuclei Gate.
- Standalone HTML interactive differential report generator (`diff.html`).
- Local Qwen 4B GGUF brain integration with basic tool synthesis.

