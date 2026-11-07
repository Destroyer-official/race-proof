"""RaceProof — ingestion adapters for all supported tool formats."""
from race_proof.ingestion.base import BaseAdapter
from race_proof.ingestion.turbo_intruder import TurboIntruderAdapter
from race_proof.ingestion.quickdraw import QuickDrawAdapter
from race_proof.ingestion.nuclei import NucleiAdapter
from race_proof.ingestion.raw_http import RawHttpAdapter
from race_proof.ingestion.har import HarAdapter
from race_proof.ingestion.burp_xml import BurpXmlAdapter
from race_proof.ingestion.postman import PostmanAdapter
from race_proof.ingestion.mitmproxy import MitmproxyAdapter
from race_proof.ingestion.k6 import K6Adapter
from race_proof.ingestion.otel import OtelAdapter
from race_proof.ingestion.websocket import WebSocketAdapter

__all__ = [
    "BaseAdapter",
    "TurboIntruderAdapter",
    "QuickDrawAdapter",
    "NucleiAdapter",
    "RawHttpAdapter",
    "HarAdapter",
    "BurpXmlAdapter",
    "PostmanAdapter",
    "MitmproxyAdapter",
    "K6Adapter",
    "OtelAdapter",
    "WebSocketAdapter",
    "auto_detect",
]


def auto_detect(source_path: str) -> BaseAdapter:
    """Auto-detect the tool format and return the right adapter."""
    import json
    from pathlib import Path
    p = Path(source_path)
    if not p.exists():
        raise FileNotFoundError(f"Input file not found: {source_path}")
    
    text = p.read_text(encoding="utf-8", errors="replace").strip()

    # XML check (Burp Suite exported items)
    if text.startswith("<?xml") or "<items" in text or "<item>" in text:
        return BurpXmlAdapter()

    # Postman check
    if '"collection"' in text and ('"executions"' in text or '"run"' in text):
        return PostmanAdapter()

    # mitmproxy flow export check
    if ('"timestamp_start"' in text or '"timestamp_end"' in text) and '"request"' in text and '"response"' in text:
        return MitmproxyAdapter()

    # OpenTelemetry trace check
    if '"resourceSpans"' in text or ('"scopeSpans"' in text and '"spans"' in text):
        return OtelAdapter()

    # WebSocket frame check
    if '"frames"' in text and ('"opcode"' in text or '"direction"' in text or '"payload"' in text):
        return WebSocketAdapter()
    
    # Try to parse as JSON/JSONL
    if text.startswith("[") or text.startswith("{"):
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                if "log" in data and "entries" in data["log"]:
                    return HarAdapter()
                if "findings" in data or "race_window_ms" in data:
                    return QuickDrawAdapter()
                if "baseline" in data and ("race" in data or "race_responses" in data):
                    return RawHttpAdapter()
            elif isinstance(data, list) and data:
                first = data[0]
                if isinstance(first, dict):
                    if "race_responses" in first or "baseline" in first:
                        return TurboIntruderAdapter()
                    if "request" in first and "response" in first:
                        return RawHttpAdapter()
        except json.JSONDecodeError:
            pass

    # Try JSONL
    first_line = text.splitlines()[0] if text.splitlines() else ""
    try:
        first = json.loads(first_line)
        if "metric" in first and "http_req" in str(first):
            return K6Adapter()
        if "type" in first and first["type"] == "Point" and "http_req" in str(first):
            return K6Adapter()
        if "templateID" in first or "matched-at" in first or "template-id" in first:
            return NucleiAdapter()
        if "race_window_ms" in first or "finding_id" in first:
            return QuickDrawAdapter()
    except json.JSONDecodeError:
        pass
    
    # Fallback: raw HTTP
    return RawHttpAdapter()
