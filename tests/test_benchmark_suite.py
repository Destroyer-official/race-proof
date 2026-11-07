"""Unit and Integration tests for Benchmark Suite and Scorecard."""
from __future__ import annotations

from pathlib import Path
import pytest
from race_proof.bench.runner import BenchmarkRunner
from race_proof.bench.scorecard import BenchmarkScorecard, ScenarioResult


def test_benchmark_runner_discovers_scenarios():
    runner = BenchmarkRunner(verbose=False)
    scenarios = runner.discover_scenarios()
    assert len(scenarios) >= 25


def test_benchmark_runner_executes_suite():
    runner = BenchmarkRunner(verbose=False)
    card = runner.run_all()
    summ = card.compute_summary()

    assert summ["total_scenarios"] >= 25
    assert summ["precision"] >= 0.95
    assert summ["recall"] == 1.0
    assert summ["f1_score"] >= 0.95
    assert summ["mcc"] >= 0.90


def test_scorecard_markdown_generation():
    res = ScenarioResult(
        scenario_id="TEST-001",
        domain="fintech",
        ground_truth="CONFIRMED",
        predicted_verdict="CONFIRMED",
        confidence=0.9,
        p_value=0.0001,
        is_correct=True,
        classification="TP",
        execution_time_ms=5.0,
    )
    card = BenchmarkScorecard(results=[res])
    md = card.render_markdown()
    assert "# 🏆 RaceProof Benchmark Scorecard" in md
    assert "TEST-001" in md
    assert "fintech" in md
    assert "✅ `TP`" in md
