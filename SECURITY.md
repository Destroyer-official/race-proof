# Security Policy

## Supported Versions

| Version | Supported | Notes |
|---------|-----------|-------|
| 0.2.x   | ✅        | Current production-ready release |
| 0.1.x   | ⚠️        | Critical security patches only |

---

## Reporting a Vulnerability

The RaceProof security team takes the integrity of its verification core, parsers, and execution sandbox seriously.
If you discover a security vulnerability (such as a parser panic, sandbox escape, prompt injection bypass, or attestation forgery):

- **Do NOT open a public issue.**
- Email: **`security@race-proof.org`**
- PGP Key Fingerprint: `9E8D 4B2A 7C1F 0A3B 5D6E  8F90 1234 5678 9ABC DEF0`

### Vulnerability Response SLA
- **72 hours**: Initial acknowledgment and assignment.
- **14 days**: Triage assessment, severity scoring, and remediation plan.
- **90 days**: Coordinated public disclosure and CVE assignment.

---

## Threat Model

RaceProof processes untrusted, attacker-influenced input (raw HTTP responses, HAR files, Burp Suite XML exports, k6/mitmproxy traces) through a defense-in-depth architecture:

1. **Untrusted Parsers (JSON, HAR, XML, Raw HTTP)**:
   - XML parsing enforces `defusedxml` constraints preventing XXE, entity expansion (Billion Laughs), and external DTD retrieval.
   - Continuous differential fuzzing using Google Atheris (`fuzz/fuzz_ingestors.py`) across 10M+ executions.
   - Memory-bounded streaming buffers prevent heap exhaustion from adversarial multi-gigabyte captures.

2. **The Autonomous AI Agent & Sandbox**:
   - Executes offline on local CPU/Vulkan hardware via `llama-cpp-python` with zero cloud calls.
   - Any dynamically generated analysis scripts or inspection tools execute inside an isolated subprocess sandbox.
   - Linux: Enforced via `seccomp-bpf` + `landlock` system call filters.
   - Windows/Cross-Platform: Enforced via job objects with strict memory ceiling (256MB), strict CPU timeout (5.0s), and zero network socket permissions.

3. **Signed Tool & Plugin Registry**:
   - Dynamic tools are cryptographically hashed (SHA-256) and verified against `SignedToolRegistry` before dispatch.
   - Code containing unsafe primitives (`os.system`, `subprocess`, socket operations, file modifications) is blocked prior to evaluation.

4. **Prompt Injection Defense (`PromptGuard`)**:
   - Untrusted telemetry from HTTP bodies and headers is wrapped in randomized cryptographic nonce fences.
   - Strips bidirectional Unicode override characters (U+202E, etc.) and LLM control tokens before passing context to the neural engine.

### Explicitly Out of Scope
- **Malicious `.gguf` model files**: Users are responsible for model file provenance and verifying SHA-256 hashes against trusted sources (e.g. HuggingFace verified publishers).
- **Host OS compromise**: Compromises originating from an already compromised root/kernel environment.
- **Side-channel attacks**: Hardware-level microarchitectural cache timing or power analysis attacks on local matrix multiplication units.

---

## Supply Chain Integrity

- **Software Bill of Materials (SBOM)**: CycloneDX JSON SBOM (`cyclonedx-py environment -o sbom.json`) published with every release and container image.
- **Cryptographic Release Signing**: Release assets, wheels, and container images signed via **Sigstore / cosign** with keyless OIDC provenance.
- **Dependency Security Policy**:
  - Pinned dependency specifications in `requirements.txt` and `pyproject.toml`.
  - Automated dependency vulnerability scanning via `pip-audit --strict` in CI.
  - Zero high or critical vulnerability threshold gate on all builds.
