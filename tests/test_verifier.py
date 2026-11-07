"""Unit tests for RaceProof core components."""
import json
import pytest
from race_proof.models import (
    RaceRequest,
    RaceResponse,
    RaceSession,
    InvariantRule,
    InvariantOperator,
    VerdictLevel,
)
from race_proof.analysis.semantic_diff import SemanticDiffer
from race_proof.analysis.timing import TimingAnalyser
from race_proof.analysis.invariants import InvariantChecker
from race_proof.analysis.statistics import StatisticsEngine
from race_proof.verdict import VerdictEngine
from race_proof.ingestion.turbo_intruder import TurboIntruderAdapter
from race_proof.ingestion.raw_http import RawHttpAdapter
from race_proof.agent.brain import ToolCallParser
from race_proof.agent.tools import ToolRegistry, get_default_tools


def create_sample_session(is_vulnerable: bool = True) -> RaceSession:
    baseline = RaceResponse(
        status_code=200,
        headers={"Content-Type": "application/json"},
        body='{"balance": 100, "remaining": 1}',
        elapsed_ms=145.0,
        sequence_index=-1,
    )
    if is_vulnerable:
        race_responses = [
            RaceResponse(
                status_code=200,
                headers={"Content-Type": "application/json"},
                body='{"balance": 80, "remaining": 0}',
                elapsed_ms=140.0,
                ttfb_ms=138.0,
                sequence_index=0,
            ),
            RaceResponse(
                status_code=200,
                headers={"Content-Type": "application/json"},
                body='{"balance": 60, "remaining": -1}',
                elapsed_ms=140.5,
                ttfb_ms=138.2,
                sequence_index=1,
            ),
            RaceResponse(
                status_code=400,
                headers={"Content-Type": "application/json"},
                body='{"error": "already redeemed"}',
                elapsed_ms=155.0,
                sequence_index=2,
            ),
        ]
    else:
        race_responses = [
            RaceResponse(
                status_code=200,
                headers={"Content-Type": "application/json"},
                body='{"balance": 80, "remaining": 0}',
                elapsed_ms=140.0,
                sequence_index=0,
            ),
            RaceResponse(
                status_code=429,
                headers={"Content-Type": "application/json"},
                body='{"error": "rate limited"}',
                elapsed_ms=141.0,
                sequence_index=1,
            ),
        ]
    return RaceSession(
        id="test_session_1",
        tool_source="unit_test",
        baseline=baseline,
        race_responses=race_responses,
    )


def test_semantic_diff_anomaly():
    differ = SemanticDiffer()
    session = create_sample_session(is_vulnerable=True)
    res = differ.analyse(session)
    assert res.anomaly_detected is True
    assert res.confidence > 0.0


def test_timing_analyser_clustering():
    timer = TimingAnalyser(tight_window_ms=5.0)
    session = create_sample_session(is_vulnerable=True)
    res = timer.analyse(session)
    assert res.anomaly_detected is True
    assert len(res.details.get("clusters", [])) > 0


def test_invariant_checker_violation():
    rule = InvariantRule(
        id="remaining_non_negative",
        description="Remaining count cannot drop below 0",
        jmespath="remaining",
        operator=InvariantOperator.ANY_NEGATIVE,
        threshold=0,
        severity="HIGH",
    )
    checker = InvariantChecker(rules=[rule], load_builtins=False)
    session = create_sample_session(is_vulnerable=True)
    res = checker.analyse(session)
    assert res.anomaly_detected is True
    assert len(res.details.get("violations", [])) == 1


def test_invariant_checker_passed():
    rule = InvariantRule(
        id="balance_positive",
        description="Balance must stay positive",
        jmespath="balance",
        operator=InvariantOperator.ANY_NEGATIVE,
        threshold=0,
    )
    checker = InvariantChecker(rules=[rule])
    session = create_sample_session(is_vulnerable=False)
    res = checker.analyse(session)
    assert res.anomaly_detected is False


def test_statistics_engine():
    stats = StatisticsEngine()
    session = create_sample_session(is_vulnerable=True)
    res = stats.analyse(session)
    assert "success_rate" in res.details
    assert res.details["n_trials"] == 3


def test_verdict_engine_confirmed():
    rule = InvariantRule(
        id="remaining_non_negative",
        description="Remaining count cannot drop below 0",
        jmespath="remaining",
        operator=InvariantOperator.ANY_NEGATIVE,
        threshold=0,
        severity="HIGH",
    )
    engine = VerdictEngine(invariant_rules=[rule], agent=None, verbose=False, load_builtins=False)
    session = create_sample_session(is_vulnerable=True)
    verdict = engine.analyse(session)
    assert verdict.verdict == VerdictLevel.CONFIRMED
    assert verdict.invariant_violated == "remaining_non_negative"


def test_tool_call_parser():
    raw_action = """Thought: Need to search for CVEs.
Action: web_search
Action Input: {"query": "CVE-2024-1234"}
"""
    p = ToolCallParser.parse(raw_action)
    assert p["thought"] == "Need to search for CVEs."
    assert p["action"] == "web_search"
    assert p["action_input"]["query"] == "CVE-2024-1234"
    assert p["is_final"] is False

    raw_final = """Thought: Analysis complete.
Final Answer: This is a verified vulnerability.
"""
    pf = ToolCallParser.parse(raw_final)
    assert pf["is_final"] is True
    assert "verified vulnerability" in pf["final_answer"]
