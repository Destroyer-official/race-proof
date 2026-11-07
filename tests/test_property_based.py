"""Property-based testing with Hypothesis for RaceProof core verification invariants."""
from __future__ import annotations

import copy
import random
from hypothesis import given, strategies as st, settings

from race_proof.models import (
    RaceRequest,
    RaceResponse,
    RaceSession,
    VerdictLevel,
)
from race_proof.verdict import VerdictEngine


@st.composite
def race_session_strategy(draw):
    """Generates valid synthetic RaceSessions with random responses and statuses."""
    session_id = draw(st.text(min_size=1, max_size=10, alphabet="abcdefghijklmnopqrstuvwxyz0123456789"))
    base_code = draw(st.sampled_from([200, 400, 403, 404, 409, 500]))
    base_body = draw(st.sampled_from([
        '{"status": "error", "balance": 0}',
        '{"error": "insufficient_funds"}',
        '{"result": "denied"}',
        '<html><body>Error</body></html>',
    ]))

    baseline = RaceResponse(
        status_code=base_code,
        headers={"content-type": "application/json"},
        body=base_body,
        elapsed_ms=draw(st.floats(min_value=10.0, max_value=100.0)),
        ttfb_ms=draw(st.floats(min_value=5.0, max_value=50.0)),
        request=RaceRequest(url="https://api.test/resource", method="POST"),
    )

    n_responses = draw(st.integers(min_value=2, max_value=10))
    race_resps = []
    for i in range(n_responses):
        code = draw(st.sampled_from([200, 400, 403, 409, 500]))
        body = draw(st.sampled_from([
            '{"status": "success", "balance": 0}',
            '{"status": "error", "balance": 0}',
            '{"debited": 100, "balance": -50}',
            '{"order_id": 12345, "status": "applied"}',
        ]))
        race_resps.append(
            RaceResponse(
                status_code=code,
                headers={"content-type": "application/json"},
                body=body,
                elapsed_ms=draw(st.floats(min_value=10.0, max_value=100.0)),
                ttfb_ms=draw(st.floats(min_value=5.0, max_value=50.0)),
                sequence_index=i,
                request=RaceRequest(url="https://api.test/resource", method="POST"),
            )
        )

    return RaceSession(
        id=session_id,
        tool_source="hypothesis",
        baseline=baseline,
        race_responses=race_resps,
    )


@settings(max_examples=25, deadline=None)
@given(session=race_session_strategy())
def test_property_verdict_idempotence(session: RaceSession):
    """Property 1: Analyzing the exact same session twice yields an identical verdict and confidence."""
    engine = VerdictEngine(verbose=False, load_builtins=True)
    v1 = engine.analyse(session)
    v2 = engine.analyse(session)

    assert v1.verdict == v2.verdict
    assert v1.confidence == v2.confidence
    assert v1.success_rate == v2.success_rate
    assert v1.p_value == v2.p_value
    assert v1.invariant_violated == v2.invariant_violated


@settings(max_examples=25, deadline=None)
@given(session=race_session_strategy())
def test_property_permutation_invariance(session: RaceSession):
    """Property 2: Permuting the order of race responses preserves verdict classification."""
    engine = VerdictEngine(verbose=False, load_builtins=True)
    v_orig = engine.analyse(session)

    # Permute the race responses
    shuffled_resps = list(session.race_responses)
    random.shuffle(shuffled_resps)

    permuted_session = RaceSession(
        id=session.id + "_shuffled",
        tool_source=session.tool_source,
        baseline=session.baseline,
        race_responses=shuffled_resps,
        metadata=session.metadata,
    )

    v_perm = engine.analyse(permuted_session)
    assert v_orig.verdict == v_perm.verdict

