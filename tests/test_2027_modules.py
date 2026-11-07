"""Unit & integration tests for 2027 research modules:
- Automated Invariant Mining (ATUSA / ClassInvGen)
- Request-Level Happens-Before DAG (ACM ESEC/FSE ReqRacer)
- Database Concurrency Defect Classification (IEEE S&P 2025 Racedb / ANSI SQL)
- Multi-Endpoint Collision & Workflow Analysis (PortSwigger State Machine)
"""
import json
import pytest

from race_proof.models import (
    RaceRequest,
    RaceResponse,
    RaceSession,
    Verdict,
    VerdictLevel,
    InvariantViolation,
)
from race_proof.analysis.invariant_miner import InvariantMiner
from race_proof.analysis.happens_before import HappensBeforeEngine
from race_proof.analysis.anomaly_classifier import (
    ConcurrencyAnomalyClassifier,
    ConcurrencyAnomalyType,
)
from race_proof.analysis.multi_endpoint import MultiEndpointAnalyser
from race_proof.verdict import VerdictEngine


def test_automated_invariant_mining_numeric_and_id():
    """Verify that InvariantMiner infers bounds and uniqueness from payload schemas."""
    base_body = json.dumps({
        "account_id": "ACC-101",
        "balance": 500,
        "remaining_redemptions": 1,
        "applied": True,
        "order_id": "ORD-999"
    })
    base = RaceResponse(status_code=200, body=base_body)
    r1 = RaceResponse(status_code=200, body=base_body, sequence_index=0)
    r2 = RaceResponse(status_code=200, body=base_body, sequence_index=1)
    session = RaceSession(id="miner_test", tool_source="test", baseline=base, race_responses=[r1, r2])

    miner = InvariantMiner()
    rules = miner.mine_rules(session)
    rule_ids = [r.id for r in rules]

    # Check that balance and remaining_redemptions were mined as non-negative invariants
    assert any("balance" in rid for rid in rule_ids)
    assert any("remaining_redemptions" in rid for rid in rule_ids)
    # Check that order_id was mined as uniqueness invariant
    assert any("order_id" in rid for rid in rule_ids)
    # Check that applied was mined as single success mutation
    assert any("applied" in rid for rid in rule_ids)


def test_happens_before_dag_concurrency_intervals():
    """Verify ReqRacer-style happens-before DAG construction and concurrency density."""
    base = RaceResponse(status_code=200, elapsed_ms=30.0)
    
    # r0 and r1 overlap heavily: r0 [10, 30], r1 [12, 32]
    r0 = RaceResponse(status_code=200, ttfb_ms=10.0, elapsed_ms=30.0, sequence_index=0)
    r1 = RaceResponse(status_code=200, ttfb_ms=12.0, elapsed_ms=32.0, sequence_index=1)
    # r2 executes strictly after r0 and r1: [50, 70]
    r2 = RaceResponse(status_code=200, ttfb_ms=50.0, elapsed_ms=70.0, sequence_index=2)

    session = RaceSession(id="hb_test", tool_source="test", baseline=base, race_responses=[r0, r1, r2])

    engine = HappensBeforeEngine()
    dag = engine.analyse(session)

    assert dag.total_requests == 3
    # r0 and r1 are concurrent
    assert (0, 1) in dag.concurrent_pairs or (1, 0) in dag.concurrent_pairs
    # r0 happens before r2, r1 happens before r2
    assert (0, 2) in dag.happens_before_edges
    assert (1, 2) in dag.happens_before_edges
    assert dag.max_concurrent_clique == 2
    assert dag.concurrency_density > 0.0


def test_concurrency_anomaly_classifier_lost_update():
    """Verify classification of lost update (stale read overwrite)."""
    base = RaceResponse(status_code=200, body='{"balance": 100}')
    # Both concurrent requests returned the identical snapshot 80 (lost update)
    r0 = RaceResponse(status_code=200, body='{"balance": 80}', sequence_index=0)
    r1 = RaceResponse(status_code=200, body='{"balance": 80}', sequence_index=1)
    session = RaceSession(id="lost_up_test", tool_source="test", baseline=base, race_responses=[r0, r1])

    verdict = Verdict(
        finding_id="f_lost",
        verdict=VerdictLevel.CONFIRMED,
        confidence=0.85,
        trial_count=2,
        success_rate=1.0,
        ci_95_lower=0.5,
        ci_95_upper=1.0,
        p_value=0.01,
        invariant_violations=[InvariantViolation(rule_id="stall_check", description="State stalling", evidence="Identical snapshots", severity="HIGH")],
    )

    classifier = ConcurrencyAnomalyClassifier()
    classification = classifier.classify(session, verdict)
    assert classification.anomaly_type == ConcurrencyAnomalyType.LOST_UPDATE
    assert "READ COMMITTED" in classification.isolation_level_implication
    assert "UPDATE" in classification.remediation_guidance


def test_concurrency_anomaly_classifier_toctou_negative():
    """Verify classification of TOCTOU dirty read leading to negative balance."""
    base = RaceResponse(status_code=200, body='{"balance": 100}')
    r0 = RaceResponse(status_code=200, body='{"balance": 0}', sequence_index=0)
    r1 = RaceResponse(status_code=200, body='{"balance": -100}', sequence_index=1)
    session = RaceSession(id="toctou_test", tool_source="test", baseline=base, race_responses=[r0, r1])

    verdict = Verdict(
        finding_id="f_toctou",
        verdict=VerdictLevel.CONFIRMED,
        confidence=0.95,
        trial_count=2,
        success_rate=1.0,
        ci_95_lower=0.5,
        ci_95_upper=1.0,
        p_value=0.001,
        invariant_violations=[InvariantViolation(rule_id="non_negative_balance", description="No negative balance", evidence="Found [-100]", severity="HIGH")],
    )

    classifier = ConcurrencyAnomalyClassifier()
    classification = classifier.classify(session, verdict)
    assert classification.anomaly_type == ConcurrencyAnomalyType.TOCTOU_DIRTY_READ
    assert "CHECK constraints" in classification.remediation_guidance


def test_multi_endpoint_workflow_analysis():
    """Verify detection of cross-endpoint collisions (e.g. /cart vs /checkout)."""
    req_cart = RaceRequest(method="POST", url="https://shop.example/api/cart/apply_coupon")
    req_checkout = RaceRequest(method="POST", url="https://shop.example/api/cart/checkout")

    base = RaceResponse(status_code=200, request=req_cart, elapsed_ms=25.0)
    r0 = RaceResponse(status_code=200, request=req_cart, ttfb_ms=10.0, elapsed_ms=25.0, sequence_index=0)
    r1 = RaceResponse(status_code=200, request=req_checkout, ttfb_ms=11.0, elapsed_ms=26.0, sequence_index=1)

    session = RaceSession(id="me_test", tool_source="test", baseline=base, race_responses=[r0, r1])

    analyser = MultiEndpointAnalyser()
    res = analyser.analyse(session)

    assert res.is_multi_endpoint is True
    assert len(res.unique_endpoints) == 2
    assert res.sub_state_collision_detected is True
    assert len(res.cross_endpoint_pairs) >= 1


def test_full_pipeline_2027_integration():
    """End-to-end integration test verifying that VerdictEngine runs all 2027 modules."""
    sample_json = json.dumps({"balance": 100, "status": "ok"})
    base = RaceResponse(status_code=200, body=sample_json, elapsed_ms=20.0)
    # Both race responses succeed and one produces negative balance
    r0 = RaceResponse(status_code=200, body=json.dumps({"balance": 0, "status": "ok"}), ttfb_ms=10.0, elapsed_ms=20.0, sequence_index=0)
    r1 = RaceResponse(status_code=200, body=json.dumps({"balance": -100, "status": "ok"}), ttfb_ms=10.2, elapsed_ms=20.4, sequence_index=1)

    session = RaceSession(id="pipeline_2027", tool_source="test", baseline=base, race_responses=[r0, r1])

    # Instantiate engine with load_builtins=True (auto_mine enabled)
    engine = VerdictEngine(load_builtins=True, verbose=False)
    verdict = engine.analyse(session)

    # Invariant miner should have caught balance non-negativity
    assert verdict.is_confirmed is True
    assert verdict.concurrency_defect_class is not None
    assert verdict.isolation_level_implication is not None
    assert verdict.remediation_guidance is not None

