"""RaceProof — core data models.

All data flowing through the engine is typed here. Every adapter,
analyser and reporter operates on these primitives — no raw dicts.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# HTTP primitives
# ---------------------------------------------------------------------------

class RaceRequest(BaseModel):
    """A single HTTP request captured during a race attack."""

    method: str = "GET"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    body: str | None = None
    sequence_index: int = 0          # position in the concurrent batch
    timestamp_ms: float | None = None

    def get_header(self, name: str, default: str = "") -> str:
        """Case-insensitive header retrieval."""
        target = name.lower()
        for k, v in self.headers.items():
            if k.lower() == target:
                return v
        return default

    @property
    def raw(self) -> str:
        """Reconstruct a minimal RFC-compliant raw HTTP representation."""
        from urllib.parse import urlparse
        parsed = urlparse(self.url)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        lines = [f"{self.method.upper()} {path} HTTP/1.1"]
        host = self.get_header("host", parsed.netloc or "localhost")
        lines.append(f"Host: {host}")
        for k, v in self.headers.items():
            if k.lower() != "host":
                lines.append(f"{k}: {v}")
        if self.body is not None:
            body_bytes = self.body.encode("utf-8", errors="replace")
            if not self.get_header("content-length"):
                lines.append(f"Content-Length: {len(body_bytes)}")
            lines.append("")
            lines.append(self.body)
        else:
            lines.append("")
        return "\r\n".join(lines)


class RaceResponse(BaseModel):
    """A single HTTP response received during a race attack."""

    status_code: int
    headers: dict[str, str] = Field(default_factory=dict)
    body: str = ""
    elapsed_ms: float = 0.0          # total wall time from send to body-complete
    ttfb_ms: float | None = None     # time-to-first-byte
    request: RaceRequest | None = None
    sequence_index: int = 0          # matches the request's index

    def get_header(self, name: str, default: str = "") -> str:
        """Case-insensitive header lookup."""
        target = name.lower()
        for k, v in self.headers.items():
            if k.lower() == target:
                return v
        return default

    @property
    def content_type(self) -> str:
        return self.get_header("content-type").lower()

    @property
    def is_json(self) -> bool:
        return "application/json" in self.content_type or self.body.strip().startswith(("{", "["))

    @property
    def is_html(self) -> bool:
        return "text/html" in self.content_type or self.body.strip().lower().startswith(("<html", "<!doctype"))

    @property
    def body_hash(self) -> str:
        return hashlib.sha256(self.body.encode("utf-8", errors="replace")).hexdigest()[:16]

    @property
    def server_processing_ms(self) -> float | None:
        """
        Server transaction processing window: (elapsed - TTFB).
        Isolates backend execution time from network RTT.
        """
        if self.ttfb_ms is not None and self.elapsed_ms >= self.ttfb_ms:
            return round(self.elapsed_ms - self.ttfb_ms, 2)
        return None


class RaceSession(BaseModel):
    """
    One complete race-attack session: a baseline response and N concurrent
    race responses captured from the same attack window.
    """

    id: str
    tool_source: str                            # "turbo_intruder" | "quickdraw" | "nuclei" | "har" | "raw"
    baseline: RaceResponse                      # a non-raced reference response
    race_responses: list[RaceResponse]          # the concurrent batch
    metadata: dict[str, Any] = Field(default_factory=dict)
    captured_at: datetime = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def _require_at_least_two_race(self) -> "RaceSession":
        if len(self.race_responses) < 2:
            raise ValueError(
                f"RaceSession requires at least 2 race responses; got {len(self.race_responses)}"
            )
        return self

    @property
    def winner_candidates(self) -> list[RaceResponse]:
        """Race responses whose status_code differs from the baseline or are HTTP 2xx."""
        base_code = self.baseline.status_code
        return [r for r in self.race_responses if r.status_code != base_code or 200 <= r.status_code < 300]

    @property
    def status_distribution(self) -> dict[int, int]:
        dist: dict[int, int] = {}
        for r in self.race_responses:
            dist[r.status_code] = dist.get(r.status_code, 0) + 1
        return dist

    @property
    def has_divergent_status(self) -> bool:
        return len(self.status_distribution) > 1


# ---------------------------------------------------------------------------
# Invariant rules
# ---------------------------------------------------------------------------

class InvariantOperator(str, Enum):
    """Supported comparison operators in invariant expressions."""
    EQ = "eq"
    NEQ = "neq"
    LT = "lt"
    LTE = "lte"
    GT = "gt"
    GTE = "gte"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    COUNT_GT = "count_gt"       # count of responses matching condition > threshold
    COUNT_EQ = "count_eq"
    ANY_NEGATIVE = "any_negative"
    STATE_STALL = "state_stall" # multiple concurrent mutating requests produced identical state snapshot
    UNIQUE_VALUES = "unique"    # all extracted values must be strictly distinct
    SUM_GT = "sum_gt"           # sum of extracted values > threshold
    SUM_EQ = "sum_eq"


class InvariantRule(BaseModel):
    """A business invariant rule evaluated across responses."""

    id: str
    description: str
    jmespath: str | None = None         # path into JSON response body
    expected_value: Any = None          # value to match for count operators
    target_status: int | None = None    # optional HTTP status filter (e.g. 200)
    operator: InvariantOperator = InvariantOperator.COUNT_GT
    threshold: float = 1.0
    applies_to: str = "race_responses"  # "race_responses" | "baseline" | "any"
    severity: str = "HIGH"              # HIGH | MEDIUM | LOW


class InvariantViolation(BaseModel):
    rule_id: str
    description: str
    evidence: str
    severity: str = "HIGH"


# ---------------------------------------------------------------------------
# Analysis dimension results
# ---------------------------------------------------------------------------

class AnalysisDimension(str, Enum):
    SEMANTIC_DIFF = "semantic_diff"
    TIMING = "timing"
    INVARIANT = "invariant"
    STATISTICS = "statistics"


class DimensionResult(BaseModel):
    """Result from one analysis dimension."""

    dimension: AnalysisDimension
    anomaly_detected: bool      # True = this dimension sees something race-like
    confidence: float           # 0.0 – 1.0
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)
    evidence_lines: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

class VerdictLevel(str, Enum):
    CONFIRMED = "CONFIRMED"
    UNCERTAIN = "UNCERTAIN"
    NOISE = "NOISE"


class Verdict(BaseModel):
    """The oracle's final verdict on a RaceSession."""

    finding_id: str
    verdict: VerdictLevel
    confidence: float                   # weighted composite 0.0 – 1.0
    trial_count: int
    success_rate: float
    ci_95_lower: float
    ci_95_upper: float
    p_value: float
    invariant_violated: str | None = None
    invariant_violations: list[InvariantViolation] = Field(default_factory=list)
    dimensions: list[DimensionResult] = Field(default_factory=list)
    severity_hint: str = "UNKNOWN"
    tool_source: str = "unknown"
    concurrency_defect_class: str | None = None
    isolation_level_implication: str | None = None
    remediation_guidance: str | None = None
    is_multi_endpoint: bool = False
    timestamp: datetime = Field(default_factory=_utc_now)
    evidence_bundle_path: str | None = None

    @property
    def is_confirmed(self) -> bool:
        return self.verdict == VerdictLevel.CONFIRMED

    @property
    def dimension_map(self) -> dict[AnalysisDimension, DimensionResult]:
        return {d.dimension: d for d in self.dimensions}

    def as_report_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
