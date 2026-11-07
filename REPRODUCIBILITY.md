# Reproducibility Specification

> **Version**: 1.0  
> **Status**: Deterministic / Production-Ready  
> **Target**: Court-ready, mathematically verifiable race condition proofs.

---

## 1. Core Principle: Zero Non-Determinism

Every analysis result emitted by RaceProof (verdicts, counterexample traces, SARIF logs, and attestation statements) must be bit-for-bit reproducible across operating systems, CPU architectures, and execution environments when given the same input bundle.

Unlike probabilistic security scanners that produce shifting outputs due to network latency fluctuations or dynamic model temperature, RaceProof decouples:
1. **Empirical Capture (Network Layer)**: High-speed burst traffic captured via proxies (Burp, HAR, mitmproxy).
2. **Deterministic Verification (Analysis Core)**: Fixed-seed, order-invariant, mathematical formal proof.

---

## 2. Deterministic Pipeline Components

### 2.1 Fixed Random Seeds
When running differential clustering, bootstrap confidence interval estimation, or model inferences:
- Random seeds are fixed globally (`seed=42` or configured via `--seed`).
- Wilson score intervals and binomial test p-values are computed analytically without Monte Carlo variance.

### 2.2 Order Permutation Invariance
RaceProof response set processing is mathematically invariant under arbitrary response permutations:
$$\text{Verdict}(R_1, R_2, \dots, R_n) \equiv \text{Verdict}(\pi(R_1, R_2, \dots, R_n)) \quad \forall \pi \in S_n$$
This is guaranteed by property-based testing (`tests/test_property_based.py`).

### 2.3 Ephemeral Dynamic Noise Masking
To prevent timestamps, CSRF nonces, and session tokens from causing spurious diffs:
- ISO-8601 timestamps, UUID v4s, Unix timestamps, and JWT signatures are masked deterministically using standardized regular expressions before SimHash and MinHash computation.

### 2.4 Model Hash Verification
For AI agent-assisted consensus arbitration:
- The exact SHA-256 hash of the underlying model weights (`.gguf` file) is logged in the finding metadata:
  ```json
  "model_provenance": {
    "engine": "llama-cpp",
    "model_name": "qwen2.5-coder-7b-instruct.Q4_K_M.gguf",
    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "temperature": 0.0,
    "top_p": 1.0,
    "seed": 42
  }
  ```
- Temperature is locked to `0.0` (pure greedy decoding) for reproducible reasoning chains.

---

## 3. Step-by-Step Reproduction Procedure

To independently verify a RaceProof finding from an evidence bundle:

### Step 1: Environment Reproduction
```bash
# Clone the repository at the exact tagged release
git clone https://github.com/Destroyer-official/race-proof.git
cd race-proof
git checkout v0.2.0

# Install pinned dependencies
pip install -r requirements.txt
pip install -e .
```

### Step 2: Verify Input Integrity
Check that the raw evidence bundle input has not been modified:
```bash
sha256sum race_proof_findings/<finding_id>/input_session.json
# Compare against finding_metadata.json "input_sha256"
```

### Step 3: Execute Hermetic Re-Verification
Run the verifier with identical parameters:
```bash
race-proof verify -i race_proof_findings/<finding_id>/input_session.json \
  --seed 42 \
  --output ./reproduction_output
```

### Step 4: Bit-for-Bit Diff Comparison
Compare the generated SARIF and verdict summary:
```bash
diff -u race_proof_findings/<finding_id>/sarif.json ./reproduction_output/*/sarif.json
```
Both files will match identically.

---

## 4. Formal TLA+ Model Checking Reproduction

To independently verify the formal concurrency proof via the TLC model checker:

1. Extract the generated TLA+ model:
   ```bash
   race-proof prove -i race_proof_findings/<finding_id>/input_session.json \
     --tla-out WebApiRaceModel.tla
   ```
2. Run the official Java TLC model checker:
   ```bash
   java -cp tla2tools.jar tlc2.TLC WebApiRaceModel.tla
   ```
3. TLC will explore the reachable state space and reproduce the exact counterexample trace discovering invariant violation `NoOverdraft` or `SingleWinner`.
