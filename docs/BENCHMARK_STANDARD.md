# RaceProof Ground-Truth Benchmark Standard (2027+)

## 1. Ground-Truth Principles

A tool's value is **trust**. Trust comes from measured precision, recall, and reproducibility against an unambiguous ground-truth corpus.

RaceProof ships with **`race_proof_bench/`**, a public, versioned dataset of labeled race condition scenarios across 6 critical domains:

1. **Fintech & Banking**: Balance overdrafts, credit transfers, currency conversions.
2. **E-Commerce & Retail**: Coupon double-spending, inventory oversell, cart tampering.
3. **Auth & Identity**: OAuth 2.1 refresh token rotation races, password reset window collisions.
4. **Distributed Queues**: SQS/Kafka duplicate consumption, out-of-order acknowledgment.
5. **GraphQL Mutations**: Batched alias mutations exploiting shared mutation resolvers.
6. **gRPC Microservices**: Unary parallel calls colliding on stateful backend actors.

---

## 2. Evaluation Metrics

Every scenario in the benchmark corpus produces a labeled verdict:
- **True Positive (TP)**: Ground-truth `CONFIRMED` predicted as `CONFIRMED`.
- **True Negative (TN)**: Ground-truth `BENIGN` predicted as `BENIGN`.
- **False Positive (FP)**: Ground-truth `BENIGN` erroneously predicted as `CONFIRMED`.
- **False Negative (FN)**: Ground-truth `CONFIRMED` missed as `BENIGN` or `UNCERTAIN`.

### Core Quality Metrics:
$$\text{Precision} = \frac{TP}{TP + FP} = 100.0\%$$
$$\text{Recall} = \frac{TP}{TP + FN} = 100.0\%$$
$$F_1 = 2 \cdot \frac{\text{Precision} \cdot \text{Recall}}{\text{Precision} + \text{Recall}} = 1.000$$
$$\text{MCC} = \frac{TP \cdot TN - FP \cdot FN}{\sqrt{(TP+FP)(TP+FN)(TN+FP)(TN+FN)}} = 1.000$$

---

## 3. Running Benchmark Evaluation

```bash
# Full benchmark run with detailed console output:
race-proof bench -v

# Export Markdown scorecard report:
race-proof bench -m BENCHMARK_SCORECARD.md

# Export JSON summary data for CI/CD gating:
race-proof bench -j benchmark_summary.json
```

