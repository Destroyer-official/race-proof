"""Semantic body diffing — not just length/status, but meaning.

Advanced features
-----------------
* Dynamic Ephemeral Noise Filtering: Automatically masks nonces, timestamps,
  CSRF tokens, UUIDs, JWTs, and request IDs before comparison to eliminate false-positive diffs.
* State Stalling / Stale-Read Detection: Identifies concurrent mutating requests
  that read and commit from identical snapshots (the hallmark of lost-update race bugs).
* SimHash-based fuzzy hash distance for rapid approximate comparison.
* Structural JSON key-by-key tree diffing.
* HTML DOM text comparison via lxml.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from race_proof.models import AnalysisDimension, DimensionResult, RaceResponse, RaceSession


# Common patterns for dynamic noise that changes on every request
EPHEMERAL_PATTERNS = [
    # ISO-8601 Timestamps
    (re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?'), '<TIMESTAMP>'),
    # Standard Date Strings (e.g. "Sat, 07 Nov 2026 11:20:00 GMT")
    (re.compile(r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}\s+\d{2}:\d{2}:\d{2}\s+(?:GMT|UTC|[A-Z]{3})'), '<DATE>'),
    # UUIDs v4 / v1
    (re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'), '<UUID>'),
    # JWT tokens
    (re.compile(r'eyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}'), '<JWT>'),
    # Unix timestamp (milliseconds or seconds, roughly years 2020-2035)
    (re.compile(r'\b1[6-9]\d{8,11}\b'), '<UNIX_TIME>'),
]

EPHEMERAL_FIELD_NAMES = {
    "timestamp", "time", "date", "created_at", "updated_at", "ts",
    "nonce", "csrf", "_csrf", "csrf_token", "authenticity_token", "xsrf_token",
    "request_id", "req_id", "trace_id", "correlation_id", "x-request-id",
    "etag", "session_id", "jwt",
}


@dataclass
class DiffSummary:
    simhash_distance: float          # 0.0 = identical, 1.0 = completely different
    structure_changed: bool          # JSON key set or HTML DOM changed
    value_changes: list[str]         # human-readable field-level changes
    text_similarity: float           # 0.0–1.0 SequenceMatcher ratio
    anomalous_fields: list[str]      # fields that changed between race responses
    raw_diff_lines: list[str] = field(default_factory=list)


class SemanticDiffer:
    """
    Compares baseline against race responses and analyzes internal
    cross-response divergence to discover business-logic anomalies.
    """

    def __init__(self, min_body_len_for_diff: int = 4, filter_ephemeral_noise: bool = True):
        self.min_body_len = min_body_len_for_diff
        self.filter_ephemeral_noise = filter_ephemeral_noise

    def analyse(self, session: RaceSession) -> DimensionResult:
        """Run advanced semantic diff analysis on a RaceSession."""
        anomalies: list[str] = []
        evidence: list[str] = []
        all_summaries: list[DiffSummary] = []

        # Sanitize bodies if ephemeral filtering enabled
        cleaned_baseline_body = self._clean_noise(session.baseline.body) if self.filter_ephemeral_noise else session.baseline.body

        for resp in session.race_responses:
            cleaned_resp_body = self._clean_noise(resp.body) if self.filter_ephemeral_noise else resp.body
            summary = self._diff_pair(session.baseline, resp, cleaned_baseline_body, cleaned_resp_body)
            all_summaries.append(summary)
            if summary.simhash_distance > 0.15 or summary.structure_changed or summary.value_changes:
                anomalies.append(
                    f"Response[{resp.sequence_index}]: "
                    f"hash_dist={summary.simhash_distance:.3f}, "
                    f"changes={summary.value_changes[:3]}"
                )
                evidence.extend(summary.value_changes[:5])

        different_count = sum(
            1 for s in all_summaries
            if s.simhash_distance > 0.15 or s.structure_changed or s.value_changes
        )
        anomaly_rate = different_count / max(len(all_summaries), 1)

        # Detect cross-race divergence: race responses differ from each other
        cross_divergence = self._cross_divergence(session.race_responses)
        if cross_divergence:
            evidence.append(f"Cross-race divergence detected: {cross_divergence}")

        # Detect State Stalling / Stale Reads
        state_stalling = self._detect_state_stalling(session)
        if state_stalling:
            evidence.append(f"State Stalling detected: {state_stalling}")

        anomaly_detected = different_count >= 2 or cross_divergence is not None or state_stalling is not None
        confidence = min(0.98, anomaly_rate * 0.6 + (0.25 if cross_divergence else 0.0) + (0.25 if state_stalling else 0.0))

        summary_parts = [f"{different_count}/{len(all_summaries)} race responses differ semantically from baseline"]
        if cross_divergence:
            summary_parts.append(f"cross-race divergence: {cross_divergence}")
        if state_stalling:
            summary_parts.append(f"state stalling: {state_stalling}")

        return DimensionResult(
            dimension=AnalysisDimension.SEMANTIC_DIFF,
            anomaly_detected=anomaly_detected,
            confidence=round(confidence, 3),
            summary="; ".join(summary_parts),
            details={
                "different_count": different_count,
                "total_race_responses": len(all_summaries),
                "anomaly_rate": round(anomaly_rate, 3),
                "cross_divergence": cross_divergence,
                "state_stalling": state_stalling,
                "per_response": [
                    {
                        "index": i,
                        "simhash_distance": round(s.simhash_distance, 4),
                        "structure_changed": s.structure_changed,
                        "value_changes": s.value_changes[:5],
                        "text_similarity": round(s.text_similarity, 4),
                    }
                    for i, s in enumerate(all_summaries)
                ],
            },
            evidence_lines=evidence[:10],
        )

    # ------------------------------------------------------------------
    # Noise Filtering
    # ------------------------------------------------------------------

    def _clean_noise(self, text: str) -> str:
        """Strip or mask dynamic noise like CSRF tokens and timestamps."""
        if not text:
            return ""
        result = text
        for pattern, replacement in EPHEMERAL_PATTERNS:
            result = pattern.sub(replacement, result)
        return result

    def _sanitize_dict(self, data: Any) -> Any:
        """Recursively mask dynamic noise in JSON objects."""
        if isinstance(data, dict):
            clean = {}
            for k, v in data.items():
                if k.lower() in EPHEMERAL_FIELD_NAMES:
                    clean[k] = "<EPHEMERAL_MASKED>"
                else:
                    clean[k] = self._sanitize_dict(v)
            return clean
        elif isinstance(data, list):
            return [self._sanitize_dict(item) for item in data]
        elif isinstance(data, str):
            return self._clean_noise(data)
        return data

    # ------------------------------------------------------------------
    # Stale Read & State Stalling Detection
    # ------------------------------------------------------------------

    def _detect_state_stalling(self, session: RaceSession) -> str | None:
        """
        Detects if multiple concurrent mutating requests produced identical state snapshot
        (the signature of a lost-update / uncommitted snapshot race condition).
        """
        success_mutations = [
            r for r in session.race_responses
            if 200 <= r.status_code < 300 and len(r.body) >= self.min_body_len
        ]
        if len(success_mutations) < 2:
            return None

        # Check for identical clean bodies among 200 responses
        cleaned_bodies = [self._clean_noise(r.body) for r in success_mutations]
        if len(cleaned_bodies) >= 2 and len(set(cleaned_bodies)) == 1:
            return (
                f"{len(success_mutations)} concurrent mutating requests returned identical response bodies "
                "(consistent with stale read/lost update)"
            )
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _diff_pair(
        self,
        baseline: RaceResponse,
        race: RaceResponse,
        clean_base_body: str,
        clean_race_body: str,
    ) -> DiffSummary:
        """Diff one baseline/race response pair."""
        if baseline.is_json and race.is_json:
            return self._diff_json(clean_base_body, clean_race_body)
        if baseline.is_html and race.is_html:
            return self._diff_html(clean_base_body, clean_race_body)
        return self._diff_text(clean_base_body, clean_race_body)

    def _simhash_distance(self, a: str, b: str) -> float:
        """Fast approximate string similarity using bit-population of XOR."""
        try:
            import race_proof_core
            ha = race_proof_core.fast_simhash(a)
            hb = race_proof_core.fast_simhash(b)
            return min(1.0, race_proof_core.fast_hamming_distance(ha, hb) / 64.0)
        except Exception:
            pass
        try:
            from simhash import Simhash
            ha = Simhash(a)
            hb = Simhash(b)
            distance = ha.distance(hb)
            return min(1.0, distance / 64.0)
        except Exception:
            def shingles(s: str, k: int = 3) -> set[str]:
                return {s[i:i+k] for i in range(max(0, len(s)-k+1))}
            sa, sb = shingles(a), shingles(b)
            if not sa and not sb:
                return 0.0
            return 1.0 - len(sa & sb) / max(len(sa | sb), 1)

    def _diff_json(self, a_body: str, b_body: str) -> DiffSummary:
        try:
            a = json.loads(a_body)
            b = json.loads(b_body)
        except (json.JSONDecodeError, ValueError):
            return self._diff_text(a_body, b_body)

        if self.filter_ephemeral_noise:
            a = self._sanitize_dict(a)
            b = self._sanitize_dict(b)

        changes: list[str] = []
        try:
            from jsondiff import diff as jdiff
            delta = jdiff(a, b, syntax="symmetric")
            changes = self._flatten_json_delta(delta)
        except Exception:
            changes = self._naive_json_diff(a, b)

        hash_dist = self._simhash_distance(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        structure_changed = self._json_keys_changed(a, b)

        return DiffSummary(
            simhash_distance=hash_dist,
            structure_changed=structure_changed,
            value_changes=changes,
            text_similarity=1.0 - hash_dist,
            anomalous_fields=[c.split(":")[0].strip() for c in changes],
        )

    def _diff_html(self, a_body: str, b_body: str) -> DiffSummary:
        try:
            from lxml import etree
            def text_content(html: str) -> str:
                tree = etree.fromstring(html, etree.HTMLParser())
                return " ".join(tree.itertext())
            a_text = text_content(a_body)
            b_text = text_content(b_body)
        except Exception:
            a_text, b_text = a_body, b_body

        ratio = SequenceMatcher(None, a_text, b_text).ratio()
        hash_dist = self._simhash_distance(a_text, b_text)

        changes: list[str] = []
        if ratio < 0.95:
            matcher = SequenceMatcher(None, a_text.split(), b_text.split())
            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                if tag in ("replace", "insert", "delete"):
                    before = " ".join(a_text.split()[i1:i2])[:60]
                    after = " ".join(b_text.split()[j1:j2])[:60]
                    changes.append(f"[{tag}] '{before}' → '{after}'")
                    if len(changes) >= 5:
                        break

        return DiffSummary(
            simhash_distance=hash_dist,
            structure_changed=hash_dist > 0.3,
            value_changes=changes,
            text_similarity=ratio,
            anomalous_fields=[],
        )

    def _diff_text(self, a_body: str, b_body: str) -> DiffSummary:
        ratio = SequenceMatcher(None, a_body, b_body).ratio()
        hash_dist = self._simhash_distance(a_body, b_body)
        changes: list[str] = []

        nums_a = re.findall(r'[-+]?\d+(?:\.\d+)?', a_body)
        nums_b = re.findall(r'[-+]?\d+(?:\.\d+)?', b_body)
        if nums_a != nums_b:
            pairs = list(zip(nums_a, nums_b))
            for na, nb in pairs[:5]:
                if na != nb:
                    changes.append(f"numeric change: {na} → {nb}")

        return DiffSummary(
            simhash_distance=hash_dist,
            structure_changed=False,
            value_changes=changes,
            text_similarity=ratio,
            anomalous_fields=[],
        )

    def _cross_divergence(self, responses: list[RaceResponse]) -> str | None:
        """Detect if race responses differ significantly from each other."""
        if len(responses) < 2:
            return None
        statuses = {r.status_code for r in responses}
        if len(statuses) > 1:
            return f"status codes diverged across race responses: {sorted(statuses)}"

        cleaned_bodies = [
            self._clean_noise(r.body) if self.filter_ephemeral_noise else r.body
            for r in responses
        ]

        # Try native Rust MinHash LSH clustering
        try:
            import race_proof_core
            clusters = race_proof_core.minhash_lsh_cluster(cleaned_bodies)
            distinct_clusters = len(set(clusters))
            if distinct_clusters > 1:
                return f"race responses split into {distinct_clusters} distinct clusters via MinHash LSH"
        except Exception:
            pass

        unique_bodies = set(cleaned_bodies)
        if len(unique_bodies) > 1:
            dist = self._simhash_distance(cleaned_bodies[0], cleaned_bodies[1])
            if dist > 0.15:
                return f"body hash divergence between race responses (dist={dist:.3f})"
        return None

    def _flatten_json_delta(self, delta: Any, prefix: str = "") -> list[str]:
        results: list[str] = []
        if isinstance(delta, dict):
            for key, value in delta.items():
                full_key = f"{prefix}.{key}" if prefix else str(key)
                if isinstance(value, dict):
                    results.extend(self._flatten_json_delta(value, full_key))
                else:
                    results.append(f"{full_key}: {value}")
        return results[:10]

    def _naive_json_diff(self, a: Any, b: Any, prefix: str = "") -> list[str]:
        changes: list[str] = []
        if isinstance(a, dict) and isinstance(b, dict):
            all_keys = set(a) | set(b)
            for k in all_keys:
                path = f"{prefix}.{k}" if prefix else str(k)
                if k not in a:
                    changes.append(f"{path}: ADDED = {b[k]!r}")
                elif k not in b:
                    changes.append(f"{path}: REMOVED (was {a[k]!r})")
                elif a[k] != b[k]:
                    changes.append(f"{path}: {a[k]!r} → {b[k]!r}")
        elif a != b:
            changes.append(f"{prefix}: {a!r} → {b!r}")
        return changes[:10]

    def _json_keys_changed(self, a: Any, b: Any) -> bool:
        if isinstance(a, dict) and isinstance(b, dict):
            return set(a.keys()) != set(b.keys())
        return False
