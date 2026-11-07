"""Unit tests for Formal Verification & TLA+ Generator."""
from __future__ import annotations

import pytest
from race_proof.formal import FormalVerifier, TlaSpecificationGenerator
from race_proof.models import RaceResponse, RaceSession


def test_tla_spec_generation():
    session = RaceSession(
        id="test_session_001",
        tool_source="unit_test",
        metadata={"target_url": "https://api.bank.test/transfer"},
        baseline=RaceResponse(
            sequence_index=0,
            status_code=200,
            elapsed_ms=10.0,
            body='{"balance": 100}',
            headers={},
            is_json=True,
        ),
        race_responses=[
            RaceResponse(sequence_index=1, status_code=200, elapsed_ms=12.0, body='{"balance": 0}', headers={}, is_json=True),
            RaceResponse(sequence_index=2, status_code=200, elapsed_ms=12.5, body='{"balance": 0}', headers={}, is_json=True),
        ],
    )

    spec = TlaSpecificationGenerator.generate_spec(session)
    assert "MODULE WebApiRaceModel" in spec.tla_source
    assert "SPECIFICATION Spec" in spec.cfg_source
    assert "NoOverdraft" in spec.invariants
    assert "SingleWinner" in spec.invariants
    assert spec.num_threads == 2


def test_formal_verifier_proves_race_condition():
    # Model 3 threads with initial balance 100, cost 100 per action.
    # Under unsynchronized execution, multiple threads can read balance=100 concurrently,
    # leading to overdraft (balance < 0) or multiple winners.
    res = FormalVerifier.explore_state_space(
        num_threads=3,
        initial_balance=100,
        cost_per_action=100,
        isolated=False,
    )

    assert res.is_safe is False
    assert res.violated_invariant is not None
    assert len(res.counterexample_trace) > 0
    # Trace must show concurrent reads before commit
    actions = [step.action for step in res.counterexample_trace]
    assert any("ReadAndCheck" in a for a in actions)
    assert any("CommitMutate" in a for a in actions)


def test_formal_verifier_proves_isolated_safety():
    # Under serialized/isolated execution (e.g. database locks or atomic decrement),
    # the invariant balance >= 0 must hold for all interleavings.
    res = FormalVerifier.explore_state_space(
        num_threads=3,
        initial_balance=100,
        cost_per_action=100,
        isolated=True,
    )

    assert res.is_safe is True
    assert res.violated_invariant is None
    assert len(res.counterexample_trace) == 0
    assert res.states_explored > 0
