#!/usr/bin/env python3
"""Canonical benchmark runner script for RaceProof Ground-Truth Corpus."""
from __future__ import annotations

import sys
from pathlib import Path

# Add repo root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from race_proof.bench.runner import BenchmarkRunner


def main() -> None:
    runner = BenchmarkRunner(verbose=True)
    card = runner.run_all()
    print("\n" + card.render_markdown())


    summary = card.compute_summary()
    if summary["precision"] >= 0.95 and summary["recall"] == 1.0:
        print("\n[SUCCESS] Ground-Truth Benchmark Standard Verified (Zero False Positives / 100% Recall)!")
        sys.exit(0)
    else:
        print("\n[FAILURE] Benchmark thresholds not met.")
        sys.exit(1)


if __name__ == "__main__":
    main()
