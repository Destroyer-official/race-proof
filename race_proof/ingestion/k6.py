"""k6 load testing NDJSON ingestion adapter.

Parses k6 NDJSON metric streams exported via:
    k6 run --out json=results.json test_race.js

Correlates Point records where metric == 'http_req_duration' into concurrent RaceSessions.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from race_proof.ingestion.base import BaseAdapter
from race_proof.models import RaceRequest, RaceResponse, RaceSession


class K6Adapter(BaseAdapter):
    """Adapter for k6 load testing NDJSON metric exports."""

    @property
    def tool_name(self) -> str:
        return "k6"

    def can_parse(self, content: str | bytes) -> bool:
        if isinstance(content, bytes):
            try:
                content = content.decode("utf-8", errors="replace")
            except Exception:
                return False
        first_line = content.strip().split("\n")[0] if content.strip() else ""
        return ('"metric"' in first_line and '"http_req' in first_line) or ('"type":"Point"' in first_line and '"data"' in first_line)

    def parse(self, path: Path | str) -> list[RaceSession]:
        p = Path(path)
        points: list[dict[str, Any]] = []

        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get("type") == "Point" and obj.get("metric") == "http_req_duration":
                        points.append(obj)
                except Exception:
                    pass

        if len(points) < 3:
            raise ValueError(f"k6 export requires at least 3 http_req_duration data points; found {len(points)}")

        def _point_to_response(pt: dict[str, Any], idx: int) -> RaceResponse:
            data = pt.get("data", {})
            tags = data.get("tags", {})
            val = float(data.get("value", 20.0))  # duration in ms

            url = tags.get("url", "https://localhost/api/k6_target")
            method = tags.get("method", "POST")
            status_code = int(tags.get("status", 200))

            req = RaceRequest(
                method=method,
                url=url,
                headers={"user-agent": "k6/0.50"},
                body=None,
                sequence_index=idx,
            )

            body_sample = f'{{"k6_sample": true, "status": {status_code}, "duration_ms": {val}}}'

            return RaceResponse(
                status_code=status_code,
                headers={"content-type": "application/json"},
                body=body_sample,
                elapsed_ms=val,
                ttfb_ms=round(val * 0.7, 2),
                sequence_index=idx,
                request=req,
            )

        baseline = _point_to_response(points[0], 0)
        race_resps = [
            _point_to_response(pt, i) for i, pt in enumerate(points[1:], start=1)
        ]

        session = RaceSession(
            id=f"k6_{p.stem}",
            tool_source="k6",
            baseline=baseline,
            race_responses=race_resps,
            metadata={"source_file": str(p), "points_analyzed": len(points)},
        )
        return [session]
