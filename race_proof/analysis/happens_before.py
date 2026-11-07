"""Request-Level Happens-Before DAG & Concurrency Graph Engine.

Directly implements the formal concurrency model from ACM ESEC/FSE (ReqRacer):
Constructs a happens-before directed acyclic graph (DAG) across concurrent HTTP
requests and determines the maximal overlapping concurrency clique.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from race_proof.models import RaceSession, RaceResponse


@dataclass
class HappensBeforeDAG:
    total_requests: int
    happens_before_edges: list[tuple[int, int]]       # (Ra, Rb) where Ra finished before Rb started
    concurrent_pairs: list[tuple[int, int]]           # (Ra, Rb) with no happens-before relation
    concurrency_density: float                        # Ratio of concurrent pairs to all pairs
    max_concurrent_clique: int                        # Maximum requests actively running simultaneously
    is_true_concurrent_burst: bool                    # Density > 0.5 and clique >= 2


class HappensBeforeEngine:
    """
    Constructs the request-level happens-before graph:
    Ra ≺ Rb  <=>  Ra.elapsed_ms < Rb.ttfb_ms
    """

    def analyse(self, session: RaceSession) -> HappensBeforeDAG:
        resps = session.race_responses
        n = len(resps)
        if n < 2:
            return HappensBeforeDAG(
                total_requests=n,
                happens_before_edges=[],
                concurrent_pairs=[],
                concurrency_density=0.0,
                max_concurrent_clique=n,
                is_true_concurrent_burst=False,
            )

        # Build intervals [start, end]
        intervals: list[tuple[float, float, int]] = []
        for r in resps:
            start = r.ttfb_ms if r.ttfb_ms is not None else 0.0
            end = r.elapsed_ms if r.elapsed_ms > start else start + 1.0
            intervals.append((start, end, r.sequence_index))

        # 1. Compute happens-before and concurrent pairs
        hb_edges: list[tuple[int, int]] = []
        concurrent_pairs: list[tuple[int, int]] = []

        for i in range(n):
            for j in range(i + 1, n):
                s1, e1, idx1 = intervals[i]
                s2, e2, idx2 = intervals[j]

                if e1 < s2:
                    hb_edges.append((idx1, idx2))
                elif e2 < s1:
                    hb_edges.append((idx2, idx1))
                else:
                    concurrent_pairs.append((idx1, idx2))

        total_possible_pairs = (n * (n - 1)) // 2
        density = len(concurrent_pairs) / total_possible_pairs if total_possible_pairs > 0 else 0.0

        # 2. Compute max concurrent clique
        max_clique = 0
        try:
            import race_proof_core
            starts = [it[0] for it in intervals]
            ends = [it[1] for it in intervals]
            max_clique = race_proof_core.compute_peak_concurrency(starts, ends)
        except Exception:
            events: list[tuple[float, int]] = []
            for s, e, _ in intervals:
                events.append((s, 1))
                events.append((e, -1))
            events.sort(key=lambda x: (x[0], -x[1]))

            current_active = 0
            for _, delta in events:
                current_active += delta
                if current_active > max_clique:
                    max_clique = current_active

        is_burst = (density >= 0.5) and (max_clique >= 2)

        return HappensBeforeDAG(
            total_requests=n,
            happens_before_edges=hb_edges,
            concurrent_pairs=concurrent_pairs,
            concurrency_density=round(density, 3),
            max_concurrent_clique=max_clique,
            is_true_concurrent_burst=is_burst,
        )

