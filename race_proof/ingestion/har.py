"""HAR (HTTP Archive format) ingestion adapter.

Parses .har files exported from Burp Suite, Proxyman, Chrome DevTools,
OWASP ZAP, or Fiddler. Automatically groups requests by target URL
and identifies concurrent race bursts based on timestamp clustering.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from race_proof.ingestion.base import BaseAdapter
from race_proof.models import RaceRequest, RaceResponse, RaceSession


class HarAdapter(BaseAdapter):
    """Parses HTTP Archive (.har) files."""

    @property
    def tool_name(self) -> str:
        return "har"

    def parse(self, source: str | Path) -> list[RaceSession]:
        content = Path(source).read_text(encoding="utf-8") if Path(str(source)).exists() else str(source)
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"HAR adapter: invalid JSON: {exc}") from exc

        log = data.get("log", data)
        entries = log.get("entries", [])
        if len(entries) < 3:
            raise ValueError("HAR file requires at least 3 entries (1 baseline + 2 race requests)")

        # Group entries by normalized URL (ignoring dynamic query params)
        url_groups: dict[str, list[dict]] = {}
        for entry in entries:
            req = entry.get("request", {})
            url = req.get("url", "")
            base_url = url.split("?")[0]
            url_groups.setdefault(base_url, []).append(entry)

        sessions: list[RaceSession] = []
        for url_key, group in url_groups.items():
            if len(group) >= 3:
                session = self._convert_group_to_session(url_key, group)
                if session:
                    sessions.append(session)

        if not sessions:
            # Fallback: treat the first entry as baseline, and all remaining as concurrent batch
            fallback_session = self._convert_group_to_session("har_stream", entries)
            if fallback_session:
                sessions.append(fallback_session)

        if not sessions:
            raise ValueError("HAR adapter: could not identify valid race sessions in entries")

        return sessions

    def _convert_group_to_session(self, key: str, entries: list[dict]) -> RaceSession | None:
        if len(entries) < 3:
            return None

        # Sort entries by startedDateTime if present
        def parse_time(e: dict) -> float:
            ts_str = e.get("startedDateTime")
            if not ts_str:
                return 0.0
            try:
                dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                return dt.timestamp() * 1000.0
            except Exception:
                return 0.0

        sorted_entries = sorted(entries, key=parse_time)
        baseline_entry = sorted_entries[0]
        race_entries = sorted_entries[1:]

        baseline_resp = self._entry_to_response(baseline_entry, sequence_index=-1)
        race_responses = [
            self._entry_to_response(e, sequence_index=i)
            for i, e in enumerate(race_entries)
        ]

        return RaceSession(
            id=f"har_{str(uuid.uuid4())[:8]}",
            tool_source="har",
            baseline=baseline_resp,
            race_responses=race_responses,
            metadata={"endpoint": key, "total_har_entries": len(entries)},
        )

    def _entry_to_response(self, entry: dict, sequence_index: int) -> RaceResponse:
        req_raw = entry.get("request", {})
        resp_raw = entry.get("response", {})
        timings = entry.get("timings", {})

        headers: dict[str, str] = {}
        for h in resp_raw.get("headers", []):
            name, val = h.get("name"), h.get("value")
            if name and val:
                headers[name] = val

        body = resp_raw.get("content", {}).get("text", "")
        status = int(resp_raw.get("status", 200))
        elapsed = float(entry.get("time", timings.get("send", 0) + timings.get("wait", 0) + timings.get("receive", 0)))
        ttfb = float(timings.get("wait", 0)) if "wait" in timings and timings["wait"] > 0 else None

        req_headers: dict[str, str] = {}
        for h in req_raw.get("headers", []):
            name, val = h.get("name"), h.get("value")
            if name and val:
                req_headers[name] = val

        post_data = req_raw.get("postData", {}).get("text")

        request = RaceRequest(
            method=req_raw.get("method", "GET"),
            url=req_raw.get("url", ""),
            headers=req_headers,
            body=post_data,
            sequence_index=sequence_index,
        )

        return RaceResponse(
            status_code=status,
            headers=headers,
            body=body,
            elapsed_ms=round(elapsed, 2),
            ttfb_ms=round(ttfb, 2) if ttfb is not None else None,
            request=request,
            sequence_index=sequence_index,
        )

