"""Raw HTTP pair adapter.

Accepts raw HTTP request/response pairs in a simple JSON format.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from race_proof.ingestion.base import BaseAdapter
from race_proof.models import RaceRequest, RaceResponse, RaceSession


class RawHttpAdapter(BaseAdapter):

    @property
    def tool_name(self) -> str:
        return "raw"

    def parse(self, source: str | Path) -> list[RaceSession]:
        content = Path(source).read_text(encoding="utf-8") if Path(str(source)).exists() else str(source)
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Raw HTTP: invalid JSON: {exc}") from exc

        if isinstance(data, list):
            sessions = []
            for item in data:
                s = self._parse_single(item)
                if s:
                    sessions.append(s)
            if not sessions:
                raise ValueError("Raw HTTP: no valid sessions in list")
            return sessions
        elif isinstance(data, dict):
            s = self._parse_single(data)
            if not s:
                raise ValueError("Raw HTTP: session requires baseline and at least 2 race responses")
            return [s]
        raise ValueError("Raw HTTP: expected a JSON object or array")

    def _parse_single(self, data: dict) -> RaceSession | None:
        baseline_data = data.get("baseline", {})
        race_data = data.get("race", data.get("race_responses", []))

        if not race_data or len(race_data) < 2:
            return None

        baseline_req_raw = baseline_data.get("request", {})
        baseline_resp_raw = baseline_data.get("response", baseline_data)

        baseline_request = RaceRequest(
            method=baseline_req_raw.get("method", "POST"),
            url=baseline_req_raw.get("url", ""),
            headers=baseline_req_raw.get("headers", {}),
            body=baseline_req_raw.get("body"),
        ) if baseline_req_raw else None

        baseline = RaceResponse(
            status_code=int(baseline_resp_raw.get("status", baseline_resp_raw.get("status_code", 200))),
            headers=baseline_resp_raw.get("headers", {}),
            body=str(baseline_resp_raw.get("body", "")),
            elapsed_ms=float(baseline_resp_raw.get("elapsed_ms", 0.0)),
            ttfb_ms=baseline_resp_raw.get("ttfb_ms"),
            request=baseline_request,
            sequence_index=-1,
        )

        race_responses: list[RaceResponse] = []
        for i, item in enumerate(race_data):
            req_raw = item.get("request", {})
            resp_raw = item.get("response", item)
            req = RaceRequest(
                method=req_raw.get("method", "POST"),
                url=req_raw.get("url", ""),
                headers=req_raw.get("headers", {}),
                body=req_raw.get("body"),
                sequence_index=i,
            ) if req_raw else None

            race_responses.append(RaceResponse(
                status_code=int(resp_raw.get("status", resp_raw.get("status_code", 200))),
                headers=resp_raw.get("headers", {}),
                body=str(resp_raw.get("body", "")),
                elapsed_ms=float(resp_raw.get("elapsed_ms", 0.0)),
                ttfb_ms=resp_raw.get("ttfb_ms"),
                request=req,
                sequence_index=i,
            ))

        return RaceSession(
            id=data.get("id", str(uuid.uuid4())[:8]),
            tool_source="raw",
            baseline=baseline,
            race_responses=race_responses,
            metadata=data.get("metadata", {}),
        )

