"""OpenTelemetry (OTel) Distributed Trace Ingestion Adapter.

Parses OTLP JSON trace exports (standard resourceSpans / scopeSpans format)
and maps concurrent overlapping server spans into a formal `RaceSession`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from race_proof.exceptions import CorruptPayloadError, IngestionError
from race_proof.ingestion.base import BaseAdapter
from race_proof.models import RaceRequest, RaceResponse, RaceSession
from race_proof.registry import AdapterRegistry


@AdapterRegistry.register("otel")
@AdapterRegistry.register("opentelemetry")
class OtelAdapter(BaseAdapter):
    """Adapter for OpenTelemetry JSON distributed trace exports."""

    @property
    def tool_name(self) -> str:
        return "opentelemetry"

    def parse(self, file_path: Path | str) -> list[RaceSession]:
        p = Path(file_path)
        if not p.exists():
            raise IngestionError(f"File not found: {p}")

        try:
            content = p.read_text(encoding="utf-8")
            data = json.loads(content)
        except Exception as e:
            raise CorruptPayloadError(f"Failed to parse OTel JSON: {e}")

        # OTLP format structure: {"resourceSpans": [...]} or list of spans
        spans_raw: list[dict[str, Any]] = []
        if isinstance(data, dict):
            if "resourceSpans" in data:
                for rs in data["resourceSpans"]:
                    for ss in rs.get("scopeSpans", []):
                        spans_raw.extend(ss.get("spans", []))
            elif "spans" in data:
                spans_raw = data["spans"]
            else:
                # May be a single trace bundle
                spans_raw = [data]
        elif isinstance(data, list):
            spans_raw = data
        else:
            raise IngestionError("Unrecognized OpenTelemetry JSON trace format")

        if not spans_raw:
            return []

        # Group spans by endpoint/target name
        grouped: dict[str, list[dict[str, Any]]] = {}
        for sp in spans_raw:
            target = sp.get("name", "span_operation")
            # Check attributes for http.route or http.target
            attrs = {a.get("key"): a.get("value", {}).get("stringValue") for a in sp.get("attributes", [])}
            route = attrs.get("http.route") or attrs.get("http.target") or target
            grouped.setdefault(route, []).append(sp)

        sessions: list[RaceSession] = []

        for route_name, group_spans in grouped.items():
            if len(group_spans) < 2:
                continue

            # Sort spans by startTimeUnixNano
            sorted_spans = sorted(
                group_spans,
                key=lambda s: int(s.get("startTimeUnixNano", 0))
            )

            # First span as baseline
            b_span = sorted_spans[0]
            b_resp = self._span_to_response(b_span, 0, route_name)

            # Remaining spans as concurrent race trials
            race_responses: list[RaceResponse] = []
            for idx, sp in enumerate(sorted_spans[1:], 1):
                race_responses.append(self._span_to_response(sp, idx, route_name))

            sessions.append(
                RaceSession(
                    id=f"otel_trace_{route_name.strip('/').replace('/', '_')}",
                    tool_source="opentelemetry",
                    baseline=b_resp,
                    race_responses=race_responses,
                    metadata={"route": route_name, "total_spans": len(group_spans)},
                )
            )

        return sessions

    def _span_to_response(self, span: dict[str, Any], seq: int, route: str) -> RaceResponse:
        start_nano = int(span.get("startTimeUnixNano", 0))
        end_nano = int(span.get("endTimeUnixNano", start_nano + 10_000_000))
        duration_ms = max(0.1, (end_nano - start_nano) / 1_000_000.0)

        # Extract attributes
        attrs: dict[str, Any] = {}
        for item in span.get("attributes", []):
            k = item.get("key")
            v_dict = item.get("value", {})
            val = (
                v_dict.get("stringValue")
                or v_dict.get("intValue")
                or v_dict.get("boolValue")
                or str(v_dict)
            )
            attrs[k] = val

        status_code = int(attrs.get("http.status_code", 200))
        status_msg = span.get("status", {}).get("message", "OK")

        # Fake a JSON body from span attributes and events
        body_dict = {
            "span_id": span.get("spanId"),
            "trace_id": span.get("traceId"),
            "status": status_msg,
            "attributes": attrs,
        }

        return RaceResponse(
            sequence_index=seq,
            status_code=status_code,
            headers={"content-type": "application/json", "x-trace-id": span.get("traceId", "")},
            body=json.dumps(body_dict),
            elapsed_ms=duration_ms,
            ttfb_ms=duration_ms * 0.4,
            is_json=True,
            request=RaceRequest(
                url=attrs.get("http.url", f"https://trace.internal{route}"),
                method=str(attrs.get("http.method", "POST")),
                headers={},
                body=str(attrs.get("http.request_body", "")),
            ),
        )
