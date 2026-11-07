"""Burp Suite XML export adapter.

Parses items exported from Burp Suite (Save items in Intruder / Repeater / Proxy).
Decodes base64 request/response payloads if necessary.
"""
from __future__ import annotations

import base64
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from race_proof.ingestion.base import BaseAdapter
from race_proof.models import RaceRequest, RaceResponse, RaceSession


class BurpXmlAdapter(BaseAdapter):
    """Parses Burp Suite XML saved items."""

    @property
    def tool_name(self) -> str:
        return "burp_xml"

    def parse(self, source: str | Path) -> list[RaceSession]:
        content = Path(source).read_text(encoding="utf-8", errors="replace") if Path(str(source)).exists() else str(source)
        try:
            root = ET.fromstring(content)
        except Exception as exc:
            raise ValueError(f"Burp XML adapter: invalid XML content: {exc}") from exc

        items = root.findall(".//item")
        if len(items) < 3:
            raise ValueError("Burp XML requires at least 3 items (1 baseline + 2 race items)")

        responses: list[RaceResponse] = []
        for i, item in enumerate(items):
            resp = self._parse_item(item, sequence_index=i - 1)
            responses.append(resp)

        baseline = responses[0]
        race_responses = responses[1:]

        return [
            RaceSession(
                id=f"burp_{str(uuid.uuid4())[:8]}",
                tool_source="burp_xml",
                baseline=baseline,
                race_responses=race_responses,
                metadata={"total_items": len(items)},
            )
        ]

    def _parse_item(self, item: ET.Element, sequence_index: int) -> RaceResponse:
        url_elem = item.find("url")
        url = url_elem.text.strip() if url_elem is not None and url_elem.text else "https://target.local/"

        status_elem = item.find("status")
        status = int(status_elem.text.strip()) if status_elem is not None and status_elem.text else 200

        time_elem = item.find("time")
        elapsed = float(time_elem.text.strip()) if time_elem is not None and time_elem.text else 0.0

        # Decode response
        resp_elem = item.find("response")
        body = ""
        headers: dict[str, str] = {}
        if resp_elem is not None and resp_elem.text:
            raw_text = resp_elem.text
            if resp_elem.attrib.get("base64") == "true":
                try:
                    raw_text = base64.b64decode(raw_text).decode("utf-8", errors="replace")
                except Exception:
                    pass

            # Split HTTP response into headers & body
            parts = raw_text.split("\r\n\r\n", 1)
            if len(parts) == 1:
                parts = raw_text.split("\n\n", 1)

            if len(parts) == 2:
                header_part, body_part = parts
                body = body_part
                for line in header_part.splitlines()[1:]:
                    if ":" in line:
                        k, v = line.split(":", 1)
                        headers[k.strip()] = v.strip()
            else:
                body = raw_text

        # Decode request
        req_elem = item.find("request")
        method = "POST"
        post_body = None
        req_headers: dict[str, str] = {}
        if req_elem is not None and req_elem.text:
            raw_req = req_elem.text
            if req_elem.attrib.get("base64") == "true":
                try:
                    raw_req = base64.b64decode(raw_req).decode("utf-8", errors="replace")
                except Exception:
                    pass
            parts = raw_req.split("\r\n\r\n", 1)
            if len(parts) == 1:
                parts = raw_req.split("\n\n", 1)
            if parts:
                header_lines = parts[0].splitlines()
                if header_lines:
                    first_line = header_lines[0].split()
                    if first_line:
                        method = first_line[0]
                    for line in header_lines[1:]:
                        if ":" in line:
                            k, v = line.split(":", 1)
                            req_headers[k.strip()] = v.strip()
            if len(parts) == 2:
                post_body = parts[1]

        request = RaceRequest(
            method=method,
            url=url,
            headers=req_headers,
            body=post_body,
            sequence_index=sequence_index,
        )

        return RaceResponse(
            status_code=status,
            headers=headers,
            body=body,
            elapsed_ms=elapsed,
            request=request,
            sequence_index=sequence_index,
        )

