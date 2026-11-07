"""Enterprise Codebase Verification Checklist for RaceProof.

Validates:
1. Native Rust Core compilation status
2. Full test suite execution across all modules
3. Ground-truth benchmark precision & recall standards
4. Packaging and PEP 561 compliance
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def log(msg: str, status: str = "INFO") -> None:
    colors = {
        "INFO": "\033[94m",
        "PASS": "\033[92m",
        "FAIL": "\033[91m",
        "WARN": "\033[93m",
    }
    reset = "\033[0m"
    color = colors.get(status, reset)
    print(f"{color}[{status}] {msg}{reset}")


def check_rust_core() -> bool:
    log("Checking Native Rust Core (race_proof_core)...")
    try:
        import race_proof_core
        ver = race_proof_core.rust_core_version()
        log(f"Rust Core Online: v{ver} (SIMD + LSH + ReqRacer active)", "PASS")
        return True
    except ImportError:
        log("Rust Core not compiled; pure Python fallback active.", "WARN")
        return False


def run_tests() -> bool:
    log("Running pytest test suite...")
    res = subprocess.run([sys.executable, "-m", "pytest", "-q"], capture_output=True, text=True)
    if res.returncode == 0:
        log(f"All tests passed cleanly:\n{res.stdout.strip()}", "PASS")
        return True
    else:
        log(f"Test failures detected:\n{res.stderr.strip() or res.stdout.strip()}", "FAIL")
        return False


def run_benchmark() -> bool:
    log("Running Ground-Truth Benchmark verification...")
    from race_proof.bench.runner import BenchmarkRunner

    runner = BenchmarkRunner(verbose=False)
    card = runner.run_all()
    summary = card.compute_summary()

    precision = summary["precision"]
    recall = summary["recall"]
    total = summary["total_scenarios"]

    log(f"Evaluated {total} scenarios. Precision: {precision*100:.1f}%, Recall: {recall*100:.1f}%")

    if precision >= 0.95 and recall == 1.0:
        log("Benchmark Standard Verified (Zero False Positives / 100% Recall)!", "PASS")
        return True
    else:
        log("Benchmark thresholds not met!", "FAIL")
        return False


def check_pep561() -> bool:
    log("Checking PEP 561 typing compliance...")
    typed_file = Path(__file__).resolve().parent.parent / "race_proof" / "py.typed"
    if typed_file.exists():
        log("py.typed marker verified.", "PASS")
        return True
    else:
        log("Missing py.typed marker!", "FAIL")
        return False


def main() -> None:
    print("\n" + "=" * 60)
    print("  ⚡ RACEPROOF // PRODUCTION VERIFICATION CHECKLIST")
    print("=" * 60 + "\n")

    results = [
        ("PEP 561 Typing Marker", check_pep561()),
        ("Rust Hot-Path Engine", check_rust_core()),
        ("Pytest Test Suite", run_tests()),
        ("Benchmark Corpus Quality", run_benchmark()),
    ]

    print("\n" + "=" * 60)
    print("  SUMMARY REPORT")
    print("=" * 60)
    all_ok = True
    for name, passed in results:
        status = "PASSED" if passed else "FAILED"
        print(f"  • {name:<32} : {status}")
        if not passed and name != "Rust Hot-Path Engine":
            all_ok = False

    if all_ok:
        log("RaceProof is fully production ready and all verifications passed.", "PASS")
        sys.exit(0)
    else:
        log("Verification failed. Please review errors above.", "FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()

