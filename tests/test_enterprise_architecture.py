"""Tests for Enterprise Architecture, Registries, Logging, and Swarm Consensus."""
from __future__ import annotations

import io
import json
import pytest

from race_proof.config import OracleConfig
from race_proof.exceptions import (
    CorruptPayloadError,
    IngestionError,
    RaceProofError,
    VerificationError,
)
from race_proof.logging import setup_logging
from race_proof.models import (
    RaceRequest,
    RaceResponse,
    RaceSession,
    Verdict,
    VerdictLevel,
)
from race_proof.registry import (
    AdapterRegistry,
    EngineRegistry,
    ExporterRegistry,
)
from race_proof.agent.consensus_swarm import (
    AdversaryAgent,
    FormalProverAgent,
    MultiAgentConsensusSwarm,
    RootCauseRemediationAgent,
)


def test_exception_hierarchy():
    err = CorruptPayloadError("Truncated JSON buffer", context={"bytes": 42})
    assert isinstance(err, IngestionError)
    assert isinstance(err, RaceProofError)
    assert "Truncated JSON buffer" in str(err)
    assert "bytes=42" in str(err)


def test_configuration_defaults():
    cfg = OracleConfig()
    assert cfg.log_level in ("INFO", "DEBUG", "WARNING", "ERROR")
    assert cfg.sandbox_timeout_seconds > 0.0
    assert cfg.sandbox_memory_mb >= 128
    assert cfg.sarif_version == "2.1.0"


def test_structured_logging():
    stream = io.StringIO()
    logger = setup_logging(level="DEBUG", json_format=True, stream=stream)
    logger.info("Enterprise audit verification started")

    output = stream.getvalue().strip()
    data = json.loads(output)
    assert data["level"] == "INFO"
    assert "Enterprise audit verification started" in data["message"]


def test_registry_extensibility():
    @AdapterRegistry.register("mock_cloud_adapter")
    class MockAdapter:
        pass

    assert AdapterRegistry.get("mock_cloud_adapter") is MockAdapter
    assert "mock_cloud_adapter" in AdapterRegistry.list_all()

    @EngineRegistry.register("mock_engine")
    class MockEngine:
        pass

    assert EngineRegistry.get("mock_engine") is MockEngine

    @ExporterRegistry.register("mock_exporter")
    class MockExporter:
        pass

    assert ExporterRegistry.get("mock_exporter") is MockExporter


def test_consensus_swarm_prevents_hallucination_on_rate_limit():
    # Construct a session where server returned HTTP 429 rate limit
    session = RaceSession(
        id="rate_limit_session",
        tool_source="turbo_intruder",
        baseline=RaceResponse(status_code=200, elapsed_ms=20.0, body="OK", headers={}),
        race_responses=[
            RaceResponse(status_code=200, elapsed_ms=22.0, body="OK", headers={}),
            RaceResponse(status_code=429, elapsed_ms=25.0, body="Too Many Requests", headers={}),
            RaceResponse(status_code=429, elapsed_ms=26.0, body="Too Many Requests", headers={}),
        ],
    )

    # Suppose a crude heuristic marked it CONFIRMED
    heuristic_verdict = Verdict(
        finding_id="finding_mock_429",
        verdict=VerdictLevel.CONFIRMED,
        confidence=0.85,
        trial_count=3,
        success_rate=0.33,
        ci_95_lower=0.1,
        ci_95_upper=0.9,
        p_value=0.01,
        invariant_violated=None,
        dimensions=[],
        tool_source="test",
    )

    swarm = MultiAgentConsensusSwarm(max_workers=3)
    consensus = swarm.arbitrate(session, heuristic_verdict)

    # Swarm must debunk the false positive!
    assert consensus.consensus_level == "DEBUNKED_FALSE_POSITIVE"
    assert consensus.final_verdict == VerdictLevel.NOISE
    assert any("429" in r for r in consensus.adversary_reasons)
