# Formal Concurrency Verification & TLA+ Specification

## 1. Why Formal Verification for Web APIs?

Empirical testing only proves the presence of defects under specific network timing conditions; it cannot prove their absence.
RaceProof bridges empirical security testing with **mathematical formal methods**:

- Translates empirical request/response traces into formal **TLA+ Specifications (`WebApiRaceModel.tla`)**.
- Uses an explicit state-space model checker (`Python-BFS-Explorer`) to explore **all possible thread interleavings**.
- Formally proves whether concurrent execution preserves transactional invariants.

---

## 2. Generated TLA+ Specification Structure

```tla
----------------------- MODULE WebApiRaceModel -----------------------
EXTENDS Naturals, Sequences, TLC

CONSTANTS Threads, InitialBalance, CostPerAction

VARIABLES balance, thread_state, success_count

TypeOK ==
    /\ balance \in Int
    /\ success_count \in 0..Cardinality(Threads)

NoOverdraft == balance >= 0

SingleWinner == success_count <= 1

Spec == Init /\ [][Next]_<<balance, thread_state, success_count>>
---------------------------------------------------------------------
```

---

## 3. Running Formal Proofs via CLI

```bash
# Explore interleaving state space for a session:
race-proof prove -i race_proof_bench/fintech/bench_fin_001.json

# Export generated TLA+ specification to disk:
race-proof prove -i race_proof_bench/fintech/bench_fin_001.json --tla-out WebApiRaceModel.tla

# Verify safety under atomic / isolated transaction guarantees:
race-proof prove -i race_proof_bench/fintech/bench_fin_001.json --isolated
```

When a vulnerability is proven, RaceProof prints the **Counterexample Interleaving Trace**, showing the exact execution schedule of thread reads and writes that violates safety.

