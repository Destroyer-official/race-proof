"""SARIF 2.1.0 Concurrency Exporter — generates GitHub/GitLab compliant reports.

Represents race conditions using SARIF's codeFlows and threadFlows structures,
mapping concurrent HTTP requests to interleaved thread execution locations.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from race_proof.models import RaceSession, Verdict, VerdictLevel

SARIF_SCHEMA = "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json"


class SarifExporter:
    """Exports RaceProof findings to standard SARIF 2.1.0 format."""

    RULE_DEFINITIONS = {
        "CONC001": {
            "id": "CONC001",
            "name": "LimitOverrunRaceCondition",
            "shortDescription": {"text": "Concurrency Limit Overrun (CWE-799)"},
            "fullDescription": {"text": "Multiple concurrent mutating requests succeeded beyond the allowed business threshold."},
            "defaultConfiguration": {"level": "error"},
            "properties": {"tags": ["security", "concurrency", "CWE-799"]},
        },
        "CONC002": {
            "id": "CONC002",
            "name": "LostUpdateRaceCondition",
            "shortDescription": {"text": "Lost Update Concurrency Defect (CWE-362)"},
            "fullDescription": {"text": "Concurrent read-modify-write cycles overwrote uncommitted state without transactional isolation."},
            "defaultConfiguration": {"level": "error"},
            "properties": {"tags": ["security", "concurrency", "CWE-362"]},
        },
        "CONC003": {
            "id": "CONC003",
            "name": "TOCTOURaceCondition",
            "shortDescription": {"text": "Time-of-Check to Time-of-Use Race (CWE-367)"},
            "fullDescription": {"text": "State validation was executed non-atomically prior to state mutation."},
            "defaultConfiguration": {"level": "error"},
            "properties": {"tags": ["security", "concurrency", "CWE-367"]},
        },
        "CONC004": {
            "id": "CONC004",
            "name": "StateStallRaceCondition",
            "shortDescription": {"text": "State Stalling Invariant Violation (CWE-820)"},
            "fullDescription": {"text": "Multiple concurrent mutating requests resulted in identical state snapshots."},
            "defaultConfiguration": {"level": "warning"},
            "properties": {"tags": ["security", "concurrency", "CWE-820"]},
        },
        "CONC005": {
            "id": "CONC005",
            "name": "WriteSkewRaceCondition",
            "shortDescription": {"text": "Write Skew Non-Serializable Anomaly (CWE-841)"},
            "fullDescription": {"text": "Concurrent transactions satisfied disjoint premises that combined to violate a global safety invariant."},
            "defaultConfiguration": {"level": "error"},
            "properties": {"tags": ["security", "concurrency", "CWE-841"]},
        },
    }

    @classmethod
    def to_sarif_dict(cls, session: RaceSession, verdict: Verdict) -> dict[str, Any]:
        """Convert a RaceSession and Verdict into a SARIF 2.1.0 document."""
        defect_class = (verdict.concurrency_defect_class or "").upper()
        if "LIMIT" in defect_class or "OVERRUN" in defect_class:
            rule_id = "CONC001"
        elif "LOST" in defect_class or "P4" in defect_class:
            rule_id = "CONC002"
        elif "TOCTOU" in defect_class:
            rule_id = "CONC003"
        elif "STALL" in defect_class:
            rule_id = "CONC004"
        elif "SKEW" in defect_class or "A5B" in defect_class:
            rule_id = "CONC005"
        else:
            rule_id = "CONC002"

        level = "error" if verdict.is_confirmed else "warning" if verdict.verdict == VerdictLevel.UNCERTAIN else "note"

        # Build threadFlows: one per concurrent request
        thread_flows = []
        exec_counter = 1
        for i, resp in enumerate(session.race_responses):
            thread_id = f"request-thread-{i+1:02d}"
            locs = [
                {
                    "location": {
                        "physicalLocation": {
                            "artifactLocation": {"uri": f"requests/race_{i:02d}.http"},
                            "region": {"startLine": 1},
                        },
                        "message": {
                            "text": f"Request {i+1} dispatched (TTFB: {resp.ttfb_ms or 0.0:.1f}ms, Elapsed: {resp.elapsed_ms:.1f}ms)"
                        },
                    },
                    "executionOrder": exec_counter,
                }
            ]
            exec_counter += 1

            if resp.status_code < 300:
                locs.append({
                    "location": {
                        "physicalLocation": {
                            "artifactLocation": {"uri": f"responses/race_{i:02d}.txt"},
                            "region": {"startLine": 1},
                        },
                        "message": {
                            "text": f"Request {i+1} committed transaction (HTTP {resp.status_code})"
                        },
                    },
                    "executionOrder": exec_counter,
                })
                exec_counter += 1

            thread_flows.append({
                "id": thread_id,
                "locations": locs,
            })

        message_text = (
            f"Race Condition Verified ({defect_class}): Confidence={verdict.confidence:.1%}, "
            f"p-value={verdict.p_value:.4f}, Invariant violated: {verdict.invariant_violated or 'N/A'}"
        )

        sarif_run = {
            "tool": {
                "driver": {
                    "name": "RaceProof",
                    "version": "0.2.0",
                    "informationUri": "https://github.com/race-proof/race-proof",
                    "rules": list(cls.RULE_DEFINITIONS.values()),
                }
            },
            "results": [
                {
                    "ruleId": rule_id,
                    "level": level,
                    "message": {"text": message_text},
                    "locations": [
                        {
                            "physicalLocation": {
                                "artifactLocation": {"uri": "requests/baseline.http"},
                                "region": {"startLine": 1},
                            },
                            "message": {"text": "Non-raced reference baseline transaction"},
                        }
                    ],
                    "codeFlows": [
                        {
                            "message": {"text": "Concurrent interleaving trace"},
                            "threadFlows": thread_flows,
                        }
                    ],
                    "properties": {
                        "finding_id": verdict.finding_id,
                        "verdict": verdict.verdict.value,
                        "confidence": verdict.confidence,
                        "p_value": verdict.p_value,
                        "success_rate": verdict.success_rate,
                        "ci_95_lower": verdict.ci_95_lower,
                        "ci_95_upper": verdict.ci_95_upper,
                        "concurrency_defect_class": verdict.concurrency_defect_class,
                        "remediation_guidance": verdict.remediation_guidance,
                    },
                }
            ],
        }

        return {
            "$schema": SARIF_SCHEMA,
            "version": "2.1.0",
            "runs": [sarif_run],
        }

    @classmethod
    def write_sarif(cls, session: RaceSession, verdict: Verdict, output_file: Path) -> Path:
        """Serialize SARIF report to file."""
        data = cls.to_sarif_dict(session, verdict)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return output_file

