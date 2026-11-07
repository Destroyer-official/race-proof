# Benchmark Suite (`bench/`)

This directory provides the canonical command-line interface and schema definitions for the **RaceProof Ground-Truth Concurrency Benchmark Suite**.

## Corpus Overview

The complete corpus is maintained in [`race_proof_bench/`](../race_proof_bench/), containing 31 rigorously verified scenarios across 9 architectural domains:

1. **`fintech`**: Multi-account balance overdrafts, simultaneous credit deductions.
2. **`ecommerce`**: Flash sale coupon double-spend, inventory oversell.
3. **`auth_identity`**: Password reset token collisions, OTP multi-use.
4. **`distributed_queues`**: Message deduplication and consumer lock collisions.
5. **`graphql_mutations`**: Concurrent GraphQL mutation batches.
6. **`grpc_microservices`**: Un-fenced inter-service gRPC writes.
7. **`cache_stampede`**: Redis/Memcached cache invalidation races.
8. **`storage_toctou`**: Cloud storage object overwrite races.
9. **`websocket_frames`**: Bidirectional real-time message sequencing races.

## Running the Benchmark

```bash
# Run via python bench runner:
python bench/run_bench.py

# Run via CLI:
race-proof bench

# Export scorecard to Markdown and JSON:
race-proof bench -m scorecard.md -j scorecard.json
```

## Contributing Scenarios

See [`CONTRIBUTING.md`](../CONTRIBUTING.md#adding-a-benchmark-scenario) and [`schema.json`](schema.json) for scenario formatting rules.

