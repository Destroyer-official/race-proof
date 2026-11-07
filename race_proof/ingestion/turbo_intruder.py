"""Turbo Intruder output adapter.

Turbo Intruder (Burp Suite extension) can export results as a table or JSON.
This adapter accepts the JSON export format where each entry represents
a race attempt with baseline and race responses.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from race_proof.ingestion.base import BaseAdapter
from race_proof.models import RaceRequest, RaceResponse, RaceSession


class TurboIntruderAdapter(BaseAdapter):
    """Parses Turbo Intruder JSON race results export."""

    @property
    def tool_name(self) -> str:
        return "turbo_intruder"

    def parse(self, source: str | Path) -> list[RaceSession]:
        content = Path(source).read_text(encoding="utf-8") if Path(str(source)).exists() else str(source)
        
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"TurboIntruder: invalid JSON input: {exc}") from exc

        if isinstance(data, dict):
            data = [data]

        sessions: list[RaceSession] = []
        for entry in data:
            try:
                session = self._parse_entry(entry)
                sessions.append(session)
            except Exception as exc:
                import warnings
                warnings.warn(f"Skipping TurboIntruder entry: {exc}")

        if not sessions:
            raise ValueError("TurboIntruder: no valid sessions found in input")
        return sessions

    def _parse_entry(self, entry: dict) -> RaceSession:
        session_id = entry.get("id") or str(uuid.uuid4())[:8]
        
        # Parse baseline
        baseline_raw = entry.get("baseline", {})
        baseline = self._parse_response(baseline_raw, sequence_index=-1)

        # Parse race responses
        race_raw = entry.get("race_responses", entry.get("responses", []))
        if not race_raw or len(race_raw) < 2:
            raise ValueError(f"Session {session_id}: requires at least 2 race responses")
        
        race_responses = [
            self._parse_response(r, sequence_index=i)
            for i, r in enumerate(race_raw)
        ]

        # Parse optional request info
        target_url = entry.get("metadata", {}).get("target_url", "")
        method = entry.get("metadata", {}).get("method", "POST")
        
        if target_url:
            request = RaceRequest(method=method, url=target_url)
            baseline.request = request
            for r in race_responses:
                r.request = RaceRequest(method=method, url=target_url, sequence_index=r.sequence_index)

        return RaceSession(
            id=session_id,
            tool_source="turbo_intruder",
            baseline=baseline,
            race_responses=race_responses,
            metadata=entry.get("metadata", {}),
        )

    def _parse_response(self, raw: dict, sequence_index: int = 0) -> RaceResponse:
        return RaceResponse(
            status_code=int(raw.get("status", raw.get("status_code", 200))),
            headers=raw.get("headers", {}),
            body=str(raw.get("body", "")),
            elapsed_ms=float(raw.get("elapsed_ms", raw.get("time", 0.0))),
            ttfb_ms=raw.get("ttfb_ms"),
            sequence_index=sequence_index,
        )

