"""mitmproxy flow export ingestion adapter.

Parses exported mitmproxy JSON flow dumps (mitmdump -s / flows exported as JSON).
Extracts microsecond HTTP timings, status codes, headers, and request-response pairs.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from race_proof.ingestion.base import BaseAdapter
from race_proof.models import RaceRequest, RaceResponse, RaceSession


class MitmproxyAdapter(BaseAdapter):
    """Adapter for mitmproxy JSON flow exports."""

    @property
    def tool_name(self) -> str:
        return "mitmproxy"

    def can_parse(self, content: str | bytes) -> bool:
        if isinstance(content, bytes):
            try:
                content = content.decode("utf-8", errors="replace")
            except Exception:
                return False
        content_stripped = content.strip()
        if not (content_stripped.startswith("[") or content_stripped.startswith("{")):
            return False
        return ('"timestamp_start"' in content or '"timestamp_end"' in content) and '"request"' in content and '"response"' in content

    def parse(self, path: Path | str) -> list[RaceSession]:
        p = Path(path)
        raw_text = p.read_text(encoding="utf-8")
        parsed = json.loads(raw_text)

        flows = parsed if isinstance(parsed, list) else parsed.get("flows", [parsed])
        if len(flows) < 3:
            raise ValueError(f"mitmproxy capture requires at least 3 flows; found {len(flows)}")

        def _build_response(flow: dict[str, Any], idx: int) -> RaceResponse:
            req_data = flow.get("request", {})
            resp_data = flow.get("response", {})

            # URL reconstruction
            scheme = req_data.get("scheme", "https")
            host = req_data.get("host", "localhost")
            port = req_data.get("port", 443)
            path_str = req_data.get("path", "/")
            port_part = f":{port}" if (scheme == "https" and port != 443) or (scheme == "http" and port != 80) else ""
            url_str = f"{scheme}://{host}{port_part}{path_str}"

            # Headers: mitmproxy represents headers as [ [k, v], ... ] or dict
            def _extract_headers(h_raw: Any) -> dict[str, str]:
                res = {}
                if isinstance(h_raw, list):
                    for item in h_raw:
                        if isinstance(item, list) and len(item) >= 2:
                            res[item[0]] = item[1]
                elif isinstance(h_raw, dict):
                    res = h_raw
                return res

            req_headers = _extract_headers(req_data.get("headers", []))
            body_content = req_data.get("content", "")

            req = RaceRequest(
                method=req_data.get("method", "GET"),
                url=url_str,
                headers=req_headers,
                body=body_content if body_content else None,
                sequence_index=idx,
            )

            resp_headers = _extract_headers(resp_data.get("headers", []))
            status_code = int(resp_data.get("status_code", 200))
            resp_content = resp_data.get("content", "")

            # Microsecond timestamp calculation
            t_req_start = req_data.get("timestamp_start", 0.0)
            t_resp_start = resp_data.get("timestamp_start", t_req_start)
            t_resp_end = resp_data.get("timestamp_end", t_resp_start + 0.03)

            ttfb_ms = max(0.0, (t_resp_start - t_req_start) * 1000.0) if t_req_start else None
            elapsed_ms = max(1.0, (t_resp_end - t_req_start) * 1000.0) if t_req_start else 30.0

            return RaceResponse(
                status_code=status_code,
                headers=resp_headers,
                body=resp_content,
                elapsed_ms=elapsed_ms,
                ttfb_ms=ttfb_ms,
                sequence_index=idx,
                request=req,
            )

        baseline = _build_response(flows[0], 0)
        race_resps = [
            _build_response(f, i) for i, f in enumerate(flows[1:], start=1)
        ]

        session = RaceSession(
            id=f"mitmproxy_{p.stem}",
            tool_source="mitmproxy",
            baseline=baseline,
            race_responses=race_resps,
            metadata={"source_file": str(p), "total_flows": len(flows)},
        )
        return [session]
