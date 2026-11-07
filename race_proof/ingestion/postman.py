"""Postman / Newman JSON ingestion adapter.

Parses exported Newman test execution reports generated via:
    newman run collection.json -n 20 --reporters json --reporter-json-export report.json

Maps iteration 0 to the baseline reference and subsequent iterations to concurrent race responses.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from race_proof.ingestion.base import BaseAdapter
from race_proof.models import RaceRequest, RaceResponse, RaceSession


class PostmanAdapter(BaseAdapter):
    """Adapter for Postman / Newman JSON reports."""

    @property
    def tool_name(self) -> str:
        return "postman"

    def can_parse(self, content: str | bytes) -> bool:
        if isinstance(content, bytes):
            try:
                content = content.decode("utf-8", errors="replace")
            except Exception:
                return False
        content_stripped = content.strip()
        if not content_stripped.startswith("{"):
            return False
        return ('"executions"' in content and ('"run"' in content or '"collection"' in content or '"item"' in content)) or ('"collection"' in content and '"item"' in content)

    def parse(self, path: Path | str) -> list[RaceSession]:
        p = Path(path)
        data = json.loads(p.read_text(encoding="utf-8"))

        run_data = data.get("run", data)
        executions = run_data.get("executions", [])
        if len(executions) < 3:
            raise ValueError(f"Postman report requires at least 3 executions (1 baseline + 2 race); found {len(executions)}")

        def _build_response(exec_item: dict[str, Any], idx: int) -> RaceResponse:
            req_data = exec_item.get("item", {}).get("request", {})
            resp_data = exec_item.get("response", {})

            url_raw = req_data.get("url", {})
            if isinstance(url_raw, dict):
                url_str = url_raw.get("raw", "https://localhost/api")
            else:
                url_str = str(url_raw)

            req_headers = {}
            for h in req_data.get("header", []):
                req_headers[h.get("key", "")] = h.get("value", "")

            body_raw = req_data.get("body", {}).get("raw", "")

            req = RaceRequest(
                method=req_data.get("method", "GET"),
                url=url_str,
                headers=req_headers,
                body=body_raw if body_raw else None,
                sequence_index=idx,
            )

            resp_headers = {}
            for h in resp_data.get("header", []):
                resp_headers[h.get("key", "")] = h.get("value", "")

            elapsed = float(resp_data.get("responseTime", 30.0))
            status_code = int(resp_data.get("code", 200))
            resp_body = resp_data.get("stream", {}).get("data", "")
            if isinstance(resp_body, list):
                # Byte array representation
                try:
                    resp_body = bytes(resp_body).decode("utf-8", errors="replace")
                except Exception:
                    resp_body = ""
            elif not isinstance(resp_body, str):
                resp_body = str(resp_body)

            return RaceResponse(
                status_code=status_code,
                headers=resp_headers,
                body=resp_body,
                elapsed_ms=elapsed,
                ttfb_ms=round(elapsed * 0.6, 2),
                sequence_index=idx,
                request=req,
            )

        baseline = _build_response(executions[0], 0)
        race_responses = [
            _build_response(ex, i) for i, ex in enumerate(executions[1:], start=1)
        ]

        session = RaceSession(
            id=f"postman_{p.stem}",
            tool_source="postman",
            baseline=baseline,
            race_responses=race_responses,
            metadata={"source_file": str(p), "total_executions": len(executions)},
        )
        return [session]
