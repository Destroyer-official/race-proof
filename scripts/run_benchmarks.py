"""Standalone CLI runner for the Ground-Truth Benchmark Corpus."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from race_proof.bench.runner import BenchmarkRunner


def main() -> None:
    parser = argparse.ArgumentParser(description="RaceProof Ground-Truth Benchmark Evaluator")
    parser.add_argument("--corpus", "-c", default=None, help="Path to benchmark scenarios directory")
    parser.add_argument("--markdown", "-m", default="BENCHMARK_SCORECARD.md", help="Output markdown path")
    parser.add_argument("--json", "-j", default=None, help="Output JSON path")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose scenario logging")
    args = parser.parse_args()

    print(f"\n[+] Executing RaceProof Benchmark Suite...")
    runner = BenchmarkRunner(corpus_dir=args.corpus, verbose=args.verbose)
    card = runner.run_all()
    summary = card.compute_summary()

    print(f"\n[+] Results:")
    print(f"    • Total Scenarios : {summary['total_scenarios']}")
    print(f"    • Precision       : {summary['precision']*100:.1f}%")
    print(f"    • Recall          : {summary['recall']*100:.1f}%")
    print(f"    • F1 Score        : {summary['f1_score']:.4f}")
    print(f"    • Matthews Corr   : {summary['mcc']:.4f}")

    if args.markdown:
        out_md = Path(args.markdown)
        out_md.write_text(card.render_markdown(), encoding="utf-8")
        print(f"[+] Saved Markdown Scorecard to: {out_md}")

    if args.json:
        out_json = Path(args.json)
        out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"[+] Saved JSON Scorecard to: {out_json}")


if __name__ == "__main__":
    main()

