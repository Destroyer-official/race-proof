"""Unit tests for Postman, mitmproxy, and k6 adapters, SARIF 2.1.0, and signed attestation."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from race_proof.ingestion.postman import PostmanAdapter
from race_proof.ingestion.mitmproxy import MitmproxyAdapter
from race_proof.ingestion.k6 import K6Adapter
from race_proof.ingestion.otel import OtelAdapter
from race_proof.ingestion.websocket import WebSocketAdapter
from race_proof.evidence.sarif import SarifExporter
from race_proof.evidence.attestation import AttestationSigner
from race_proof.evidence.packager import EvidencePackager
from race_proof.models import RaceRequest, RaceResponse, RaceSession, Verdict, VerdictLevel


@pytest.fixture
def sample_race_session():
    base_req = RaceRequest(method="POST", url="https://api.test/checkout", headers={"content-type": "application/json"})
    base_resp = RaceResponse(status_code=400, headers={"content-type": "application/json"}, body='{"error": "already_used"}', elapsed_ms=40.0, ttfb_ms=20.0, request=base_req)

    race_resps = []
    for i in range(3):
        r_req = RaceRequest(method="POST", url="https://api.test/checkout", headers={"content-type": "application/json"}, sequence_index=i)
        r_resp = RaceResponse(status_code=200, headers={"content-type": "application/json"}, body=f'{{"status": "applied", "id": {i}}}', elapsed_ms=30.0, ttfb_ms=15.0, sequence_index=i, request=r_req)
        race_resps.append(r_resp)

    return RaceSession(
        id="session_test_99",
        tool_source="unit_test",
        baseline=base_resp,
        race_responses=race_resps,
    )


def test_postman_adapter_parsing(tmp_path):
    postman_data = {
        "run": {
            "executions": [
                {
                    "item": {"request": {"method": "POST", "url": {"raw": "https://api.test/transfer"}, "header": [{"key": "Content-Type", "value": "application/json"}]}},
                    "response": {"code": 409, "responseTime": 45, "stream": {"data": "{\"error\": \"exhausted\"}"}},
                },
                {
                    "item": {"request": {"method": "POST", "url": {"raw": "https://api.test/transfer"}}},
                    "response": {"code": 200, "responseTime": 32, "stream": {"data": "{\"success\": true}"}},
                },
                {
                    "item": {"request": {"method": "POST", "url": {"raw": "https://api.test/transfer"}}},
                    "response": {"code": 200, "responseTime": 33, "stream": {"data": "{\"success\": true}"}},
                },
            ]
        }
    }
    file_p = tmp_path / "postman_run.json"
    file_p.write_text(json.dumps(postman_data), encoding="utf-8")

    adapter = PostmanAdapter()
    assert adapter.can_parse(file_p.read_text(encoding="utf-8"))
    sessions = adapter.parse(file_p)
    assert len(sessions) == 1
    s = sessions[0]
    assert s.baseline.status_code == 409
    assert len(s.race_responses) == 2
    assert s.race_responses[0].status_code == 200


def test_mitmproxy_adapter_parsing(tmp_path):
    mitm_data = [
        {
            "request": {"method": "POST", "scheme": "https", "host": "bank.test", "port": 443, "path": "/api/withdraw", "timestamp_start": 100.0, "headers": [["User-Agent", "curl/8.0"]]},
            "response": {"status_code": 400, "content": "{\"error\": \"limit\"}", "timestamp_start": 100.02, "timestamp_end": 100.05, "headers": [["Content-Type", "application/json"]]},
        },
        {
            "request": {"method": "POST", "scheme": "https", "host": "bank.test", "port": 443, "path": "/api/withdraw", "timestamp_start": 100.0, "headers": []},
            "response": {"status_code": 200, "content": "{\"debited\": 100}", "timestamp_start": 100.015, "timestamp_end": 100.035, "headers": []},
        },
        {
            "request": {"method": "POST", "scheme": "https", "host": "bank.test", "port": 443, "path": "/api/withdraw", "timestamp_start": 100.0, "headers": []},
            "response": {"status_code": 200, "content": "{\"debited\": 100}", "timestamp_start": 100.016, "timestamp_end": 100.036, "headers": []},
        },
    ]
    file_p = tmp_path / "mitmproxy_dump.json"
    file_p.write_text(json.dumps(mitm_data), encoding="utf-8")

    adapter = MitmproxyAdapter()
    assert adapter.can_parse(file_p.read_text(encoding="utf-8"))
    sessions = adapter.parse(file_p)
    assert len(sessions) == 1
    s = sessions[0]
    assert s.baseline.status_code == 400
    assert len(s.race_responses) == 2
    assert s.race_responses[0].ttfb_ms is not None


def test_k6_adapter_parsing(tmp_path):
    k6_lines = [
        json.dumps({"type": "Point", "metric": "http_req_duration", "data": {"value": 25.4, "tags": {"status": "429", "url": "https://api.test/redeem"}}}),
        json.dumps({"type": "Point", "metric": "http_req_duration", "data": {"value": 18.2, "tags": {"status": "200", "url": "https://api.test/redeem"}}}),
        json.dumps({"type": "Point", "metric": "http_req_duration", "data": {"value": 18.5, "tags": {"status": "200", "url": "https://api.test/redeem"}}}),
    ]
    file_p = tmp_path / "k6_output.ndjson"
    file_p.write_text("\n".join(k6_lines), encoding="utf-8")

    adapter = K6Adapter()
    assert adapter.can_parse(file_p.read_text(encoding="utf-8"))
    sessions = adapter.parse(file_p)
    assert len(sessions) == 1
    s = sessions[0]
    assert s.baseline.status_code == 429
    assert len(s.race_responses) == 2


def test_sarif_export(sample_race_session, tmp_path):
    verdict = Verdict(
        finding_id="finding_sarif_01",
        verdict=VerdictLevel.CONFIRMED,
        confidence=0.92,
        trial_count=3,
        success_rate=1.0,
        ci_95_lower=0.6,
        ci_95_upper=1.0,
        p_value=0.0001,
        concurrency_defect_class="LIMIT_OVERRUN",
        invariant_violated="single_coupon_use",
    )
    sarif_p = tmp_path / "sarif.json"
    SarifExporter.write_sarif(sample_race_session, verdict, sarif_p)

    assert sarif_p.exists()
    doc = json.loads(sarif_p.read_text(encoding="utf-8"))
    assert doc["version"] == "2.1.0"
    assert len(doc["runs"]) == 1
    results = doc["runs"][0]["results"]
    assert len(results) == 1
    assert results[0]["ruleId"] == "CONC001"
    assert "codeFlows" in results[0]
    thread_flows = results[0]["codeFlows"][0]["threadFlows"]
    assert len(thread_flows) == 3


def test_attestation_signing(sample_race_session, tmp_path):
    bundle_dir = tmp_path / "evidence_bundle"
    bundle_dir.mkdir()
    (bundle_dir / "verdict.json").write_text('{"verdict": "CONFIRMED"}', encoding="utf-8")
    (bundle_dir / "diff.html").write_text('<html>Diff</html>', encoding="utf-8")

    verdict = Verdict(
        finding_id="finding_attest_01",
        verdict=VerdictLevel.CONFIRMED,
        confidence=0.88,
        trial_count=3,
        success_rate=1.0,
        ci_95_lower=0.5,
        ci_95_upper=1.0,
        p_value=0.001,
    )

    out_file = AttestationSigner.write_attestation(bundle_dir, sample_race_session, verdict)
    assert out_file.exists()
    envelope = json.loads(out_file.read_text(encoding="utf-8"))

    assert envelope["payloadType"] == "application/vnd.in-toto+json"
    assert "signature" in envelope
    assert len(envelope["signature"]) == 64
    statement = envelope["statement"]
    assert statement["_type"] == "https://in-toto.io/Statement/v1"
    assert len(statement["subject"]) >= 2


def test_otel_adapter_parsing(tmp_path):
    otel_payload = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "4bf92f3577b34da6a3ce929d0e0e4736",
                                "spanId": "00f067aa0ba902b7",
                                "name": "/api/v1/checkout",
                                "startTimeUnixNano": "1700000000000000000",
                                "endTimeUnixNano": "1700000000030000000",
                                "attributes": [
                                    {"key": "http.route", "value": {"stringValue": "/api/v1/checkout"}},
                                    {"key": "http.status_code", "value": {"intValue": 409}},
                                ],
                            },
                            {
                                "traceId": "4bf92f3577b34da6a3ce929d0e0e4736",
                                "spanId": "5fb397be34d23b0f",
                                "name": "/api/v1/checkout",
                                "startTimeUnixNano": "1700000000005000000",
                                "endTimeUnixNano": "1700000000032000000",
                                "attributes": [
                                    {"key": "http.route", "value": {"stringValue": "/api/v1/checkout"}},
                                    {"key": "http.status_code", "value": {"intValue": 200}},
                                ],
                            },
                            {
                                "traceId": "4bf92f3577b34da6a3ce929d0e0e4736",
                                "spanId": "8a329de4b12389ab",
                                "name": "/api/v1/checkout",
                                "startTimeUnixNano": "1700000000006000000",
                                "endTimeUnixNano": "1700000000033000000",
                                "attributes": [
                                    {"key": "http.route", "value": {"stringValue": "/api/v1/checkout"}},
                                    {"key": "http.status_code", "value": {"intValue": 200}},
                                ],
                            },
                        ]
                    }
                ]
            }
        ]
    }
    file_p = tmp_path / "otel_trace.json"
    file_p.write_text(json.dumps(otel_payload), encoding="utf-8")

    adapter = OtelAdapter()
    sessions = adapter.parse(file_p)
    assert len(sessions) == 1
    s = sessions[0]
    assert s.tool_source == "opentelemetry"
    assert s.baseline.status_code == 409
    assert len(s.race_responses) == 2
    assert s.race_responses[0].status_code == 200


def test_websocket_adapter_parsing(tmp_path):
    ws_payload = {
        "frames": [
            {
                "opcode": 1,
                "direction": "receive",
                "status_code": 101,
                "elapsed_ms": 12.0,
                "payload": {"event": "connected", "session_id": "ws_123"},
            },
            {
                "opcode": 1,
                "direction": "receive",
                "status_code": 200,
                "elapsed_ms": 8.5,
                "payload": {"event": "balance_updated", "balance": 0},
            },
            {
                "opcode": 1,
                "direction": "receive",
                "status_code": 200,
                "elapsed_ms": 8.7,
                "payload": {"event": "balance_updated", "balance": 0},
            },
        ]
    }
    file_p = tmp_path / "ws_capture.json"
    file_p.write_text(json.dumps(ws_payload), encoding="utf-8")

    adapter = WebSocketAdapter()
    sessions = adapter.parse(file_p)
    assert len(sessions) == 1
    s = sessions[0]
    assert s.tool_source == "websocket"
    assert s.baseline.status_code == 101
    assert len(s.race_responses) == 2
    assert s.race_responses[0].status_code == 200


def test_auto_detect_otel_and_websocket(tmp_path):
    from race_proof.ingestion import auto_detect

    otel_f = tmp_path / "otel.json"
    otel_f.write_text('{"resourceSpans": [{"scopeSpans": [{"spans": []}]}]}', encoding="utf-8")
    assert isinstance(auto_detect(str(otel_f)), OtelAdapter)

    ws_f = tmp_path / "ws.json"
    ws_f.write_text('{"frames": [{"direction": "send", "payload": {}}]}', encoding="utf-8")
    assert isinstance(auto_detect(str(ws_f)), WebSocketAdapter)

