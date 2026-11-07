"""WebSocket Frame Log Ingestion Adapter.

Parses WebSocket frame capture logs (JSON records with direction, opcode, payload,
and timestamps) and maps real-time interleaved messages into a `RaceSession`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from race_proof.exceptions import CorruptPayloadError, IngestionError
from race_proof.ingestion.base import BaseAdapter
from race_proof.models import RaceRequest, RaceResponse, RaceSession
from race_proof.registry import AdapterRegistry


@AdapterRegistry.register("websocket")
@AdapterRegistry.register("ws")
class WebSocketAdapter(BaseAdapter):
    """Adapter for WebSocket message frame log captures."""

    @property
    def tool_name(self) -> str:
        return "websocket"

    def parse(self, file_path: Path | str) -> list[RaceSession]:
        p = Path(file_path)
        if not p.exists():
            raise IngestionError(f"File not found: {p}")

        try:
            content = p.read_text(encoding="utf-8")
            data = json.loads(content)
        except Exception as e:
            raise CorruptPayloadError(f"Failed to parse WebSocket JSON: {e}")

        frames_raw: list[dict[str, Any]] = []
        if isinstance(data, dict):
            frames_raw = data.get("frames", data.get("messages", []))
        elif isinstance(data, list):
            frames_raw = data
        else:
            raise IngestionError("Unrecognized WebSocket frame log structure")

        if len(frames_raw) < 2:
            return []

        # Find initial handshake or first message as baseline
        b_frame = frames_raw[0]
        baseline = self._frame_to_response(b_frame, 0)

        race_responses: list[RaceResponse] = []
        for idx, fr in enumerate(frames_raw[1:], 1):
            race_responses.append(self._frame_to_response(fr, idx))

        session = RaceSession(
            id=f"ws_session_{p.stem}",
            tool_source="websocket",
            baseline=baseline,
            race_responses=race_responses,
            metadata={"protocol": "wss", "total_frames": len(frames_raw)},
        )
        return [session]

    def _frame_to_response(self, frame: dict[str, Any], seq: int) -> RaceResponse:
        payload = frame.get("payload", frame.get("data", ""))
        if isinstance(payload, dict):
            body_str = json.dumps(payload)
            is_json = True
        else:
            body_str = str(payload)
            is_json = body_str.startswith("{") or body_str.startswith("[")

        elapsed_ms = float(frame.get("elapsed_ms", frame.get("duration_ms", 15.0)))
        status_code = int(frame.get("status_code", 101 if seq == 0 else 200))

        return RaceResponse(
            sequence_index=seq,
            status_code=status_code,
            headers={"upgrade": "websocket", "connection": "Upgrade"},
            body=body_str,
            elapsed_ms=elapsed_ms,
            ttfb_ms=elapsed_ms * 0.3,
            is_json=is_json,
            request=RaceRequest(
                url=frame.get("url", "wss://api.internal/ws/v1"),
                method="GET" if seq == 0 else "SEND",
                headers={},
                body=str(frame.get("send_payload", "")),
            ),
        )
