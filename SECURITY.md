# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.2.x   | :white_check_mark: |
| 0.1.x   | :x:                |

---

## Reporting a Vulnerability

The RaceProof team takes the security of its verification core and analysis sandbox extremely seriously.
If you discover a security vulnerability—especially concerning **agent sandbox escapes**, **arbitrary code execution**, **prompt injection evasion**, or **cryptographic bypasses** in attestations:

1. **Do NOT open a public GitHub issue.**
2. Email your detailed advisory and reproduction PoC to **`security@race-proof.io`**.
3. We will acknowledge receipt within **24 hours** and provide a triaged assessment and remediation plan within **72 hours**.

---

## The RaceProof Trust Model

Because RaceProof is designed to analyze potentially hostile, untrusted HTTP traffic logs exported from security tools (Burp Suite, Turbo Intruder, etc.) and run AI synthesis scripts:

### 1. Ingestion Boundary
- Ingestion parsers (HAR, Burp XML, JSONL, mitmproxy flows) run under strict resource bounds and length caps.
- XML parsing uses `defusedxml` semantics to prevent Billion Laughs / XXE attacks.
- JSON parsing uses memory-capped streaming parsers.

### 2. Autonomous Agent Sandbox
- Dynamically synthesized tools are restricted to a locked-down subprocess sandbox:
  - Strict wall-clock execution limits (default: 5.0 seconds).
  - Strict virtual memory ceiling (default: 256MB).
  - Zero outbound or inbound network access.
  - No host filesystem access outside an ephemeral temporary working directory.
- Tools are cryptographically hashed and verified against `SignedToolRegistry` before execution.

### 3. Prompt Injection Defense (`PromptGuard`)
- All untrusted text from HTTP headers, response bodies, and error logs is sanitised using bidirectional override stripping, control token neutralisation, and cryptographic isolation fences before being processed by local LLMs.

