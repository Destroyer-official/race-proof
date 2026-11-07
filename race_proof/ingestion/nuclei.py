"""Nuclei race condition results adapter.

Nuclei's race condition templates output JSONL results with matched-at,
templateID, and extracted request/response pairs.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from race_proof.ingestion.base import BaseAdapter
from race_proof.models import RaceResponse, RaceSession


class NucleiAdapter(BaseAdapter):

    @property
    def tool_name(self) -> str:
        return "nuclei"

    def parse(self, source: str | Path) -> list[RaceSession]:
        content = Path(source).read_text(encoding="utf-8") if Path(str(source)).exists() else str(source)
        sessions: list[RaceSession] = []
        groups: dict[str, list[dict]] = {}

        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                key = entry.get("matched-at", entry.get("host", str(uuid.uuid4())[:8]))
                groups.setdefault(key, []).append(entry)
            except json.JSONDecodeError:
                continue

        for key, entries in groups.items():
            try:
                session = self._entries_to_session(key, entries)
                if session:
                    sessions.append(session)
            except Exception as exc:
                import warnings
                warnings.warn(f"Nuclei: skipping group {key}: {exc}")

        if not sessions:
            raise ValueError("Nuclei: no valid sessions extracted from input")
        return sessions

    def _entries_to_session(self, key: str, entries: list[dict]) -> RaceSession | None:
        if len(entries) < 3: # Need 1 baseline + at least 2 race responses
            return None

        def entry_to_response(entry: dict, idx: int) -> RaceResponse:
            resp_data = entry.get("response", {})
            if isinstance(resp_data, str):
                lines = resp_data.splitlines()
                status = 200
                if lines and lines[0].startswith("HTTP"):
                    try:
                        status = int(lines[0].split()[1])
                    except (IndexError, ValueError):
                        pass
                body = "\n".join(lines[lines.index("") + 1:]) if "" in lines else resp_data
                return RaceResponse(status_code=status, body=body, elapsed_ms=0.0, sequence_index=idx)

            return RaceResponse(
                status_code=int(resp_data.get("status-code", resp_data.get("status", 200))),
                body=str(resp_data.get("body", entry.get("extracted-results", [""])[0] if entry.get("extracted-results") else "")),
                elapsed_ms=float(resp_data.get("time", 0.0)),
                headers=resp_data.get("headers", {}),
                sequence_index=idx,
            )

        baseline = entry_to_response(entries[0], -1)
        race_responses = [entry_to_response(e, i) for i, e in enumerate(entries[1:])]

        if len(race_responses) < 2:
            return None

        return RaceSession(
            id=str(uuid.uuid4())[:8],
            tool_source="nuclei",
            baseline=baseline,
            race_responses=race_responses,
            metadata={
                "matched_at": key,
                "template_id": entries[0].get("templateID", ""),
            },
        )

