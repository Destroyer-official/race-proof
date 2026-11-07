"""Database Isolation & Concurrency Anomaly Classifier.

Grounding in IEEE S&P 2025 (Racedb) and ANSI SQL isolation anomaly theory
(Berenson et al., Fekete et al.). Classifies empirical findings into formal
concurrency defect categories.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

from race_proof.models import RaceSession, Verdict, VerdictLevel


class ConcurrencyAnomalyType(str, Enum):
    LIMIT_OVERRUN = "LIMIT_OVERRUN"                     # Single-use quota exceeded (double spend, multi coupon)
    LOST_UPDATE = "LOST_UPDATE"                         # Parallel read-modify-write overwrite (identical stale reads)
    WRITE_SKEW = "WRITE_SKEW"                           # Concurrent checks passed locally but broke global invariant
    TOCTOU_DIRTY_READ = "TOCTOU_DIRTY_READ"             # Check succeeded before concurrent commit invalidated state
    REORDERING_DESYNC = "REORDERING_DESYNC"             # Asynchronous out-of-order execution across multi-endpoint flow
    BENIGN_CONCURRENCY = "BENIGN_CONCURRENCY"           # Clean serialized or properly handled lock contention


@dataclass
class AnomalyClassification:
    anomaly_type: ConcurrencyAnomalyType
    isolation_level_implication: str                    # e.g. "READ COMMITTED lacks row-level locks (SELECT ... FOR UPDATE)"
    remediation_guidance: str                           # concrete architectural defense
    confidence: float
    evidence: list[str]


class ConcurrencyAnomalyClassifier:
    """Classifies race findings into theoretical concurrency defect classes."""

    def classify(self, session: RaceSession, verdict: Verdict) -> AnomalyClassification:
        if not verdict.is_confirmed:
            return AnomalyClassification(
                anomaly_type=ConcurrencyAnomalyType.BENIGN_CONCURRENCY,
                isolation_level_implication="Adequate isolation or synchronized handling observed.",
                remediation_guidance="No concurrency vulnerability detected.",
                confidence=1.0 - verdict.confidence,
                evidence=["No invariant breaches found."],
            )

        evidence: list[str] = []
        resps = session.race_responses

        # 1. Check for State Stalling / Lost Update
        # Stalling occurs when multiple concurrent responses return identical mutated snapshots
        bodies = [r.body.strip() for r in resps if r.body and r.status_code in (200, 201)]
        has_identical_mutations = len(bodies) >= 2 and len(set(bodies)) < len(bodies)

        negative_violation = any(
            v.rule_id for v in verdict.invariant_violations if "negative" in v.rule_id.lower() or "overdraft" in v.rule_id.lower()
        )
        single_winner_violation = any(
            v.rule_id for v in verdict.invariant_violations if "200_winner" in v.rule_id.lower() or "single" in v.rule_id.lower()
        )

        if has_identical_mutations and not negative_violation:
            evidence.append(
                "Multiple mutating requests returned identical state snapshots, indicating a classic lost-update read-modify-write overwrite."
            )
            return AnomalyClassification(
                anomaly_type=ConcurrencyAnomalyType.LOST_UPDATE,
                isolation_level_implication="Backend runs at READ COMMITTED without atomic UPDATE or pessimistic locks.",
                remediation_guidance="Use atomic database expressions (UPDATE table SET balance = balance - 1) or SELECT ... FOR UPDATE.",
                confidence=0.92,
                evidence=evidence,
            )

        if negative_violation:
            evidence.append(
                "Durable balance or quota decreased below zero, proving check-then-act was not isolated from concurrent modification."
            )
            return AnomalyClassification(
                anomaly_type=ConcurrencyAnomalyType.TOCTOU_DIRTY_READ,
                isolation_level_implication="Application performed application-tier IF (balance >= amount) before issuing non-locked UPDATE.",
                remediation_guidance="Enforce CHECK constraints at the database level (CHECK (balance >= 0)) and wrap in SERIALIZABLE transactions.",
                confidence=0.95,
                evidence=evidence,
            )

        if single_winner_violation:
            evidence.append(
                "Multiple concurrent requests successfully claimed a single-use quota or redemption action."
            )
            return AnomalyClassification(
                anomaly_type=ConcurrencyAnomalyType.LIMIT_OVERRUN,
                isolation_level_implication="Lack of unique database constraints or distributed idempotency locks.",
                remediation_guidance="Add a UNIQUE constraint on the redemption record or acquire a distributed Redis/database mutex.",
                confidence=0.90,
                evidence=evidence,
            )

        # Default classification for multi-endpoint or complex skew
        evidence.append("Concurrent execution produced anomalous cross-response divergence.")
        return AnomalyClassification(
            anomaly_type=ConcurrencyAnomalyType.WRITE_SKEW,
            isolation_level_implication="Snapshot Isolation or weak read committed allows concurrent conflicting writes.",
            remediation_guidance="Use SERIALIZABLE isolation level or explicit advisory locks on the parent entity.",
            confidence=0.85,
            evidence=evidence,
        )

