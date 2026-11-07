"""Advanced tests for enterprise capabilities: HAR, Burp XML, Noise Filtering, State Stalling, and PoC generator."""
import json
import pytest
from race_proof.models import (
    RaceRequest,
    RaceResponse,
    RaceSession,
    InvariantRule,
    InvariantOperator,
    Verdict,
    VerdictLevel,
)
from race_proof.analysis.semantic_diff import SemanticDiffer
from race_proof.analysis.invariants import InvariantChecker
from race_proof.evidence.poc_generator import PocGenerator
from race_proof.ingestion.har import HarAdapter
from race_proof.ingestion.burp_xml import BurpXmlAdapter
from race_proof.agent.tools import get_default_tools


def test_ephemeral_noise_filtering():
    """Verify that dynamic CSRF tokens and timestamps do NOT cause false positive diffs."""
    differ = SemanticDiffer(filter_ephemeral_noise=True)

    base = RaceResponse(
        status_code=200,
        headers={"Content-Type": "application/json"},
        body='{"balance": 100, "csrf_token": "nonce-aaa-111", "timestamp": "2026-11-07T11:00:00Z"}',
    )
    # Same business balance, but different dynamic nonce and timestamp
    race1 = RaceResponse(
        status_code=200,
        headers={"Content-Type": "application/json"},
        body='{"balance": 100, "csrf_token": "nonce-bbb-222", "timestamp": "2026-11-07T11:00:01Z"}',
        sequence_index=0,
    )
    race2 = RaceResponse(
        status_code=200,
        headers={"Content-Type": "application/json"},
        body='{"balance": 100, "csrf_token": "nonce-ccc-333", "timestamp": "2026-11-07T11:00:02Z"}',
        sequence_index=1,
    )
    session = RaceSession(id="noise_test", tool_source="test", baseline=base, race_responses=[race1, race2])
    res = differ.analyse(session)
    # Since only ephemeral fields changed, different_count should be 0
    assert res.details["different_count"] == 0
    assert res.anomaly_detected is False


def test_state_stalling_detection():
    """Verify that multiple concurrent mutating requests returning identical snapshots are flagged."""
    differ = SemanticDiffer()

    base = RaceResponse(
        status_code=200,
        headers={"Content-Type": "application/json"},
        body='{"status": "success", "remaining_slots": 5}',
    )
    # Two requests both read and returned the exact same snapshot (lost update)
    race1 = RaceResponse(
        status_code=200,
        headers={"Content-Type": "application/json"},
        body='{"status": "success", "remaining_slots": 4}',
        sequence_index=0,
    )
    race2 = RaceResponse(
        status_code=200,
        headers={"Content-Type": "application/json"},
        body='{"status": "success", "remaining_slots": 4}',
        sequence_index=1,
    )
    session = RaceSession(id="stall_test", tool_source="test", baseline=base, race_responses=[race1, race2])
    res = differ.analyse(session)
    assert res.details.get("state_stalling") is not None
    assert res.anomaly_detected is True


def test_unique_invariant_operator():
    """Test that duplicate values violate the UNIQUE_VALUES operator."""
    rule = InvariantRule(
        id="unique_orders",
        description="Order IDs must be distinct",
        jmespath="order_id",
        operator=InvariantOperator.UNIQUE_VALUES,
    )
    checker = InvariantChecker(rules=[rule], load_builtins=False)

    base = RaceResponse(status_code=200, body='{"order_id": "ORD-000"}', headers={"Content-Type": "application/json"})
    r1 = RaceResponse(status_code=200, body='{"order_id": "ORD-111"}', headers={"Content-Type": "application/json"})
    r2 = RaceResponse(status_code=200, body='{"order_id": "ORD-111"}', headers={"Content-Type": "application/json"}) # Collision!

    session = RaceSession(id="uniq_test", tool_source="test", baseline=base, race_responses=[r1, r2])
    res = checker.analyse(session)
    assert res.anomaly_detected is True
    assert "Uniqueness violation" in res.details["violations"][0]["evidence"]


def test_har_adapter_parsing():
    """Test parsing of HAR (HTTP Archive) data."""
    har_json = {
        "log": {
            "entries": [
                {
                    "request": {"method": "POST", "url": "https://api.shop.local/checkout"},
                    "response": {"status": 200, "content": {"text": '{"balance": 100}'}},
                    "time": 150.0,
                    "startedDateTime": "2026-11-07T11:00:00.000Z",
                },
                {
                    "request": {"method": "POST", "url": "https://api.shop.local/checkout"},
                    "response": {"status": 200, "content": {"text": '{"balance": 80}'}},
                    "time": 140.0,
                    "startedDateTime": "2026-11-07T11:00:00.050Z",
                },
                {
                    "request": {"method": "POST", "url": "https://api.shop.local/checkout"},
                    "response": {"status": 200, "content": {"text": '{"balance": 60}'}},
                    "time": 140.2,
                    "startedDateTime": "2026-11-07T11:00:00.051Z",
                },
            ]
        }
    }
    adapter = HarAdapter()
    sessions = adapter.parse_string(json.dumps(har_json))
    assert len(sessions) == 1
    assert len(sessions[0].race_responses) == 2
    assert sessions[0].baseline.status_code == 200


def test_poc_generator_script():
    """Test automated asynchronous Python reproduction script generator."""
    base = RaceResponse(
        status_code=200,
        request=RaceRequest(method="POST", url="https://api.test/redeem", headers={"Authorization": "Bearer test1234"}, body='{"code":"GIFT10"}'),
    )
    r1 = RaceResponse(status_code=200, request=base.request)
    r2 = RaceResponse(status_code=200, request=base.request)
    session = RaceSession(id="poc_test", tool_source="test", baseline=base, race_responses=[r1, r2])
    verdict = Verdict(
        finding_id="finding_123",
        verdict=VerdictLevel.CONFIRMED,
        confidence=0.95,
        trial_count=2,
        success_rate=1.0,
        ci_95_lower=0.5,
        ci_95_upper=1.0,
        p_value=0.001,
        invariant_violated="single_200_winner",
    )

    code = PocGenerator.generate(session, verdict)
    assert "CONCURRENT_REQUESTS = 2" in code
    assert "asyncio.Barrier(CONCURRENT_REQUESTS)" in code
    assert "https://api.test/redeem" in code
    assert "Bearer test1234" in code
    assert "async def send_worker" in code


def test_agent_new_tools():
    """Test the agent's new verify_rule_syntax and generate_poc_script tools."""
    tools = get_default_tools()
    verifier = tools.get("verify_rule_syntax")
    assert verifier is not None

    rule_yaml = """
id: custom_test_rule
description: Test balance
jmespath: balance
operator: any_negative
threshold: 0
"""
    res = verifier.call(rule_yaml=rule_yaml, sample_json='{"balance": 50}')
    assert "SUCCESS" in res

    poc_tool = tools.get("generate_poc_script")
    assert poc_tool is not None
    poc_res = poc_tool.call(url="https://bank.local/transfer", count=5)
    assert "CONCURRENT_REQUESTS = 5" in poc_res
    assert "asyncio.Barrier(CONCURRENT_REQUESTS)" in poc_res


def test_sample_inputs_parse_and_verify():
    """Verify that all sample files in examples/sample_input auto-detect and verify."""
    from pathlib import Path
    from race_proof.ingestion import auto_detect
    from race_proof.verdict import VerdictEngine

    samples_dir = Path("examples/sample_input")
    assert samples_dir.exists()

    engine = VerdictEngine(load_builtins=True, verbose=False)

    for sample_file in samples_dir.glob("*"):
        if sample_file.suffix in (".json", ".jsonl", ".xml", ".har"):
            adapter = auto_detect(sample_file)
            assert adapter is not None, f"Failed to auto-detect {sample_file.name}"
            sessions = adapter.parse(sample_file)
            assert len(sessions) >= 1, f"No sessions in {sample_file.name}"
            for session in sessions:
                verdict = engine.analyse(session)
                assert verdict.finding_id is not None
                assert verdict.confidence >= 0.0
                assert len(verdict.dimensions) == 4
