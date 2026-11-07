"""QuicDraw output adapter.

QuicDraw is an HTTP/3 race condition testing tool. It outputs results
in JSONL format or as a findings.jsonl file.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from race_proof.ingestion.base import BaseAdapter
from race_proof.models import RaceResponse, RaceSession


class QuickDrawAdapter(BaseAdapter):
    """Parses QuicDraw findings.jsonl output."""

    @property
    def tool_name(self) -> str:
        return "quickdraw"

    def parse(self, source: str | Path) -> list[RaceSession]:
        content = Path(source).read_text(encoding="utf-8") if Path(str(source)).exists() else str(source)
        sessions: list[RaceSession] = []

        # Try as single JSON first
        try:
            data = json.loads(content)
            if isinstance(data, dict) and "findings" in data:
                for finding in data["findings"]:
                    s = self._parse_finding(finding)
                    if s:
                        sessions.append(s)
                return sessions
            elif isinstance(data, list):
                for item in data:
                    s = self._parse_finding(item)
                    if s:
                        sessions.append(s)
                if sessions:
                    return sessions
        except json.JSONDecodeError:
            pass

        # Parse JSONL
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                finding = json.loads(line)
                s = self._parse_finding(finding)
                if s:
                    sessions.append(s)
            except Exception as exc:
                import warnings
                warnings.warn(f"QuicDraw: skipping line: {exc}")

        if not sessions:
            raise ValueError("QuicDraw: no valid sessions found in input")
        return sessions

    def _parse_finding(self, finding: dict) -> RaceSession | None:
        session_id = finding.get("finding_id") or finding.get("id") or str(uuid.uuid4())[:8]

        baseline_raw = finding.get("baseline", {})
        concurrent_raw = finding.get("concurrent", finding.get("race_responses", []))

        if not concurrent_raw or len(concurrent_raw) < 2:
            return None

        baseline = RaceResponse(
            status_code=int(baseline_raw.get("status", baseline_raw.get("status_code", 200))),
            body=str(baseline_raw.get("body", "")),
            elapsed_ms=float(baseline_raw.get("elapsed_ms", 0.0)),
            headers=baseline_raw.get("headers", {}),
            sequence_index=-1,
        )

        race_responses = [
            RaceResponse(
                status_code=int(r.get("status", r.get("status_code", 200))),
                body=str(r.get("body", "")),
                elapsed_ms=float(r.get("elapsed_ms", 0.0)),
                ttfb_ms=r.get("ttfb_ms"),
                headers=r.get("headers", {}),
                sequence_index=i,
            )
            for i, r in enumerate(concurrent_raw)
        ]

        return RaceSession(
            id=session_id,
            tool_source="quickdraw",
            baseline=baseline,
            race_responses=race_responses,
            metadata={
                "race_window_ms": finding.get("race_window_ms"),
                "protocol": finding.get("protocol", "HTTP/3"),
            },
        )

