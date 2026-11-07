"""Multi-Endpoint Collision & Workflow Graph Analyser.

Implements state-machine sub-state collision detection (PortSwigger / James Kettle).
Detects and models race conditions where distinct endpoints (e.g. /cart vs /checkout)
target shared underlying session or database records concurrently.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from race_proof.models import RaceSession, RaceResponse


@dataclass
class MultiEndpointResult:
    is_multi_endpoint: bool
    unique_endpoints: list[str]
    cross_endpoint_pairs: list[tuple[str, str]]
    sub_state_collision_detected: bool
    evidence: list[str]


class MultiEndpointAnalyser:
    """Analyses concurrent request sets targeting multiple disparate API endpoints."""

    def analyse(self, session: RaceSession) -> MultiEndpointResult:
        all_resps = [session.baseline] + session.race_responses
        endpoint_map: dict[int, str] = {}

        for r in all_resps:
            idx = r.sequence_index
            if r.request and r.request.url:
                parsed = urlparse(r.request.url)
                path = f"{r.request.method.upper()} {parsed.path or '/'}"
            else:
                path = f"METHOD {session.tool_source}"
            endpoint_map[idx] = path

        unique_routes = sorted(list(set(endpoint_map.values())))
        is_multi = len(unique_routes) >= 2

        if not is_multi:
            return MultiEndpointResult(
                is_multi_endpoint=False,
                unique_endpoints=unique_routes,
                cross_endpoint_pairs=[],
                sub_state_collision_detected=False,
                evidence=[],
            )

        # Detect cross-endpoint in-flight overlaps
        cross_pairs: list[tuple[str, str]] = []
        evidence: list[str] = [
            f"Multi-Endpoint workflow race detected across {len(unique_routes)} routes: {', '.join(unique_routes)}"
        ]

        resps = session.race_responses
        for i in range(len(resps)):
            for j in range(i + 1, len(resps)):
                r1, r2 = resps[i], resps[j]
                ep1, ep2 = endpoint_map.get(r1.sequence_index, ""), endpoint_map.get(r2.sequence_index, "")
                if ep1 != ep2:
                    # Check if their flight windows overlapped
                    s1 = r1.ttfb_ms or 0.0
                    e1 = r1.elapsed_ms
                    s2 = r2.ttfb_ms or 0.0
                    e2 = r2.elapsed_ms
                    overlap = max(0.0, min(e1, e2) - max(s1, s2))
                    if overlap > 0.5:
                        cross_pairs.append((ep1, ep2))
                        evidence.append(
                            f"Cross-endpoint collision between [{ep1}] and [{ep2}] "
                            f"(overlapped for {overlap:.1f} ms)"
                        )

        sub_state = len(cross_pairs) > 0 and any(r.status_code in (200, 201) for r in resps)

        return MultiEndpointResult(
            is_multi_endpoint=True,
            unique_endpoints=unique_routes,
            cross_endpoint_pairs=cross_pairs[:5],
            sub_state_collision_detected=sub_state,
            evidence=evidence[:6],
        )

