"""Benchmark runner — executes RaceProof against labeled scenario corpora."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from race_proof.bench.scorecard import BenchmarkScorecard, ScenarioResult
from race_proof.models import (
    InvariantOperator,
    InvariantRule,
    RaceRequest,
    RaceResponse,
    RaceSession,
    VerdictLevel,
)
from race_proof.verdict import VerdictEngine


class BenchmarkRunner:
    """Executes RaceProof over the benchmark corpus."""

    def __init__(self, corpus_dir: Path | str | None = None, verbose: bool = False):
        if corpus_dir:
            self.corpus_dir = Path(corpus_dir)
        else:
            self.corpus_dir = Path(__file__).parent.parent.parent / "race_proof_bench"
        self.verbose = verbose

    def discover_scenarios(self) -> list[Path]:
        """Find all benchmark scenario JSON files."""
        if not self.corpus_dir.exists():
            return []
        scenarios = []
        for p in self.corpus_dir.rglob("*.json"):
            if p.name.startswith("bench_") and not p.name.endswith(".schema.json"):
                scenarios.append(p)
        return sorted(scenarios)

    def load_scenario(self, file_path: Path) -> dict[str, Any]:
        """Load and parse scenario JSON."""
        return json.loads(file_path.read_text(encoding="utf-8"))

    def run_scenario(self, scenario_data: dict[str, Any]) -> ScenarioResult:
        """Run RaceProof analysis on a single scenario."""
        scenario_id = scenario_data.get("scenario_id", "UNKNOWN")
        domain = scenario_data.get("domain", "general")
        ground_truth = scenario_data.get("ground_truth_verdict", "CONFIRMED").upper()

        # Build baseline
        b_raw = scenario_data["baseline"]
        baseline = RaceResponse(
            status_code=b_raw["status_code"],
            headers=b_raw.get("headers", {}),
            body=b_raw.get("body", ""),
            elapsed_ms=float(b_raw.get("elapsed_ms", 30.0)),
            ttfb_ms=float(b_raw.get("ttfb_ms", 15.0)),
            request=RaceRequest(url="https://benchmark.internal/api/target", method="POST"),
        )

        # Build race responses
        race_responses = []
        for i, r_raw in enumerate(scenario_data["race_responses"]):
            race_responses.append(
                RaceResponse(
                    status_code=r_raw["status_code"],
                    headers=r_raw.get("headers", {}),
                    body=r_raw.get("body", ""),
                    elapsed_ms=float(r_raw.get("elapsed_ms", 25.0)),
                    ttfb_ms=float(r_raw.get("ttfb_ms", 12.0)),
                    sequence_index=r_raw.get("sequence_index", i),
                    request=RaceRequest(url="https://benchmark.internal/api/target", method="POST"),
                )
            )

        session = RaceSession(
            id=scenario_id,
            tool_source="benchmark_harness",
            baseline=baseline,
            race_responses=race_responses,
            metadata={"domain": domain, "scenario": scenario_id},
        )

        # Invariant rules
        rules = []
        for r_spec in scenario_data.get("expected_invariants", []):
            op_str = r_spec.get("operator", "count_gt").lower()
            try:
                op = InvariantOperator(op_str)
            except ValueError:
                op = InvariantOperator.COUNT_GT

            rules.append(
                InvariantRule(
                    id=r_spec["id"],
                    description=r_spec.get("description", f"Invariant {r_spec['id']}"),
                    jmespath=r_spec.get("jmespath"),
                    operator=op,
                    threshold=float(r_spec.get("threshold", 1.0)),
                    expected_value=r_spec.get("expected_value"),
                    target_status=r_spec.get("target_status"),
                )
            )

        engine = VerdictEngine(
            invariant_rules=rules,
            verbose=self.verbose,
            load_builtins=True,
        )

        start_time = time.perf_counter()
        verdict = engine.analyse(session)
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        predicted = verdict.verdict.value  # "CONFIRMED", "UNCERTAIN", "NOISE"
        # Ground truth mapping: CONFIRMED = positive, BENIGN/NOISE = negative
        is_pos_truth = ground_truth == "CONFIRMED"
        is_pos_pred = predicted == "CONFIRMED"

        if is_pos_truth and is_pos_pred:
            cls = "TP"
            is_correct = True
        elif not is_pos_truth and not is_pos_pred:
            cls = "TN"
            is_correct = True
        elif not is_pos_truth and is_pos_pred:
            cls = "FP"
            is_correct = False
        else:
            cls = "FN"
            is_correct = False

        return ScenarioResult(
            scenario_id=scenario_id,
            domain=domain,
            ground_truth=ground_truth,
            predicted_verdict=predicted,
            confidence=verdict.confidence,
            p_value=verdict.p_value,
            is_correct=is_correct,
            classification=cls,
            execution_time_ms=elapsed_ms,
            details=verdict.as_report_dict(),
        )

    def run_all(self) -> BenchmarkScorecard:
        """Run all discovered scenarios and compute scorecard."""
        paths = self.discover_scenarios()
        results = []
        for p in paths:
            try:
                data = self.load_scenario(p)
                res = self.run_scenario(data)
                results.append(res)
            except Exception as exc:
                if self.verbose:
                    print(f"Error executing scenario {p}: {exc}")
        return BenchmarkScorecard(results=results)

