"""Invariant violation checker.

Business invariants are defined in YAML and evaluated against the
response bodies of a RaceSession. This is the oracle's primary
truth-telling mechanism: a finding is only flagged CONFIRMED when
a verifiable invariant is demonstrably broken.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from race_proof.models import (
    AnalysisDimension,
    DimensionResult,
    InvariantOperator,
    InvariantRule,
    InvariantViolation,
    RaceResponse,
    RaceSession,
)


_BUILTIN_RULES_PATH = Path(__file__).parent.parent / "builtin_invariants.yaml"


class InvariantChecker:
    """
    Evaluates user-defined (and built-in) business invariants against
    race session responses. Each rule is evaluated independently;
    all violations are collected and reported.
    """

    def __init__(
        self,
        rules: list[InvariantRule] | None = None,
        rules_file: Path | None = None,
        load_builtins: bool = True,
        auto_mine: bool | None = None,
    ):
        self.rules: list[InvariantRule] = []
        self.has_user_rules = bool(rules or rules_file)
        self.auto_mine = load_builtins if auto_mine is None else auto_mine

        # Load built-in rules if requested and the file exists
        if load_builtins and _BUILTIN_RULES_PATH.exists():
            self._load_rules_file(_BUILTIN_RULES_PATH)

        # Load user-provided rules file
        if rules_file and rules_file.exists():
            self._load_rules_file(rules_file)

        # Append inline rules
        if rules:
            self.rules.extend(rules)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyse(self, session: RaceSession) -> DimensionResult:
        """Evaluate all loaded invariants against a RaceSession."""
        active_rules = list(self.rules)
        if self.auto_mine and not self.has_user_rules:
            try:
                from race_proof.analysis.invariant_miner import InvariantMiner
                mined = InvariantMiner().mine_rules(session)
                existing_ids = {r.id for r in active_rules}
                for mr in mined:
                    if mr.id not in existing_ids:
                        active_rules.append(mr)
            except Exception:
                pass

        if not active_rules:
            return DimensionResult(
                dimension=AnalysisDimension.INVARIANT,
                anomaly_detected=False,
                confidence=0.0,
                summary="No invariant rules loaded. Add rules via --invariants <file.yaml>.",
                details={"rules_checked": 0},
                evidence_lines=[],
            )

        violations: list[InvariantViolation] = []
        evidence: list[str] = []
        rules_checked = 0

        for rule in active_rules:
            try:
                violation = self._evaluate_rule(rule, session)
                rules_checked += 1
                if violation:
                    violations.append(violation)
                    evidence.append(f"[{rule.severity}] {rule.id}: {violation.evidence}")
            except Exception as exc:
                evidence.append(f"Rule '{rule.id}' evaluation error: {exc}")

        anomaly_detected = len(violations) > 0
        # Confidence is high when a concrete invariant is broken
        confidence = min(0.98, 0.5 * len(violations)) if violations else 0.0

        # Severity escalation
        severity = "UNKNOWN"
        if violations:
            levels = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "UNKNOWN": 0}
            best = max(violations, key=lambda v: levels.get(v.severity, 0))
            severity = best.severity

        return DimensionResult(
            dimension=AnalysisDimension.INVARIANT,
            anomaly_detected=anomaly_detected,
            confidence=round(confidence, 3),
            summary=(
                f"{len(violations)}/{rules_checked} invariants violated"
                if violations
                else f"All {rules_checked} invariants held"
            ),
            details={
                "rules_checked": rules_checked,
                "violations": [v.model_dump() for v in violations],
                "highest_severity": severity,
            },
            evidence_lines=evidence[:10],
        )

    # ------------------------------------------------------------------
    # Rule evaluation
    # ------------------------------------------------------------------

    def _evaluate_rule(
        self, rule: InvariantRule, session: RaceSession
    ) -> InvariantViolation | None:
        """Evaluate one rule. Returns a violation or None."""
        if rule.applies_to == "baseline":
            responses = [session.baseline]
        elif rule.applies_to == "any":
            responses = [session.baseline] + session.race_responses
        else:
            responses = session.race_responses

        # Extract values via JMESPath if specified
        values: list[Any] = []
        if rule.jmespath:
            for resp in responses:
                val = self._extract_jmespath(resp, rule.jmespath)
                if val is not None:
                    values.append(val)
        else:
            values = [r.status_code for r in responses]

        return self._apply_operator(rule, values, responses)

    def _apply_operator(
        self,
        rule: InvariantRule,
        values: list[Any],
        responses: list[RaceResponse],
    ) -> InvariantViolation | None:
        op = rule.operator
        threshold = rule.threshold

        def violation(evidence: str) -> InvariantViolation:
            return InvariantViolation(
                rule_id=rule.id,
                description=rule.description,
                evidence=evidence,
                severity=rule.severity,
            )

        def _is_effective_success(resp: RaceResponse) -> bool:
            """Determines if a 2xx response is a true application-level success."""
            if not (200 <= resp.status_code < 300):
                return False
            # Check gRPC status header
            grpc_stat = resp.get_header("grpc-status")
            if grpc_stat and grpc_stat.strip() not in ("0", ""):
                return False
            # Check GraphQL / REST JSON error or rejection payloads
            if resp.is_json:
                try:
                    payload = json.loads(resp.body)
                    if isinstance(payload, dict):
                        if payload.get("errors") or payload.get("error"):
                            return False
                        if payload.get("idempotent_replay") is True:
                            return False
                        for k, v in payload.items():
                            sval = str(v).lower()
                            if "duplicate" in sval or "already" in sval or "conflict" in sval or "replay" in sval:
                                return False
                except Exception:
                    pass
            return True

        if op == InvariantOperator.COUNT_GT:
            if getattr(rule, "expected_value", None) == 200 and not rule.jmespath:
                count = sum(1 for r in responses if _is_effective_success(r))
            elif getattr(rule, "expected_value", None) is not None:
                count = sum(1 for v in values if v == rule.expected_value)
            elif not rule.jmespath:
                count = sum(1 for r in responses if _is_effective_success(r))
            else:
                count = sum(1 for v in values if v)
            if count > threshold:
                return violation(f"{count} responses matched (threshold >{threshold}): {values[:5]}")

        elif op == InvariantOperator.COUNT_EQ:
            if getattr(rule, "expected_value", None) == 200 and not rule.jmespath:
                count = sum(1 for r in responses if _is_effective_success(r))
            elif getattr(rule, "expected_value", None) is not None:
                count = sum(1 for v in values if v == rule.expected_value)
            elif not rule.jmespath:
                count = sum(1 for r in responses if _is_effective_success(r))
            else:
                count = sum(1 for v in values if v)
            if count != threshold:
                return violation(f"{count} responses matched (expected exactly {int(threshold)})")

        elif op == InvariantOperator.ANY_NEGATIVE:
            negatives = [v for v in values if isinstance(v, (int, float)) and v < 0]
            if negatives:
                return violation(f"Negative values found: {negatives}")

        elif op in (InvariantOperator.LT, InvariantOperator.LTE,
                    InvariantOperator.GT, InvariantOperator.GTE):
            numeric = [v for v in values if isinstance(v, (int, float))]
            for val in numeric:
                triggered = (
                    (op == InvariantOperator.LT and val >= threshold)
                    or (op == InvariantOperator.LTE and val > threshold)
                    or (op == InvariantOperator.GT and val <= threshold)
                    or (op == InvariantOperator.GTE and val < threshold)
                )
                if triggered:
                    return violation(f"Value {val} violates {op.value} {threshold}")

        elif op == InvariantOperator.EQ:
            for val in values:
                if val != threshold:
                    return violation(f"Value {val!r} ≠ expected {threshold!r}")

        elif op == InvariantOperator.NEQ:
            for val in values:
                if val == threshold:
                    return violation(f"Value {val!r} should not equal {threshold!r}")

        elif op == InvariantOperator.STATE_STALL:
            # Detect identical state snapshot across 2 or more responses
            if len(values) >= 2:
                duplicates = [v for v in values if values.count(v) > 1]
                if duplicates:
                    return violation(f"State Stall: identical snapshot values returned across concurrent requests: {duplicates[:3]}")

        elif op == InvariantOperator.UNIQUE_VALUES:
            # All values must be distinct (e.g. generated coupon codes or IDs)
            if len(values) >= 2:
                unique_set = set(str(v) for v in values)
                if len(unique_set) < len(values):
                    return violation(f"Uniqueness violation: {len(values) - len(unique_set)} duplicate values detected in concurrent responses")

        elif op in (InvariantOperator.SUM_GT, InvariantOperator.SUM_EQ):
            numeric = [v for v in values if isinstance(v, (int, float))]
            total = sum(numeric)
            if op == InvariantOperator.SUM_GT and total > threshold:
                return violation(f"Sum of values {total} exceeds threshold >{threshold}")
            elif op == InvariantOperator.SUM_EQ and total != threshold:
                return violation(f"Sum of values {total} does not match expected {threshold}")

        elif op == InvariantOperator.CONTAINS:
            for val in values:
                if isinstance(val, str) and str(threshold) not in val:
                    return violation(f"Value {val!r} does not contain {threshold!r}")

        elif op == InvariantOperator.NOT_CONTAINS:
            for val in values:
                if isinstance(val, str) and str(threshold) in val:
                    return violation(f"Value {val!r} should not contain {threshold!r}")

        return None

    def _extract_jmespath(self, response: RaceResponse, path: str) -> Any:
        """Extract a value from a JSON response body using a JMESPath expression or fallback."""
        if not response.is_json:
            return None
        try:
            data = json.loads(response.body)
            try:
                import jmespath
                return jmespath.search(path, data)
            except ImportError:
                # Dot-lookup fallback
                cur = data
                for part in path.split("."):
                    if isinstance(cur, dict):
                        cur = cur.get(part)
                    else:
                        return None
                return cur
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Rule loading
    # ------------------------------------------------------------------

    def _load_rules_file(self, path: Path) -> None:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raw = raw.get("invariants", []) if isinstance(raw, dict) else []
            for item in raw:
                try:
                    self.rules.append(InvariantRule(**item))
                except Exception:
                    pass
        except Exception:
            pass

    @staticmethod
    def from_yaml_string(yaml_text: str) -> "InvariantChecker":
        """Create a checker from a YAML string."""
        raw = yaml.safe_load(yaml_text)
        if isinstance(raw, list):
            rules = [InvariantRule(**item) for item in raw]
        else:
            rules = [InvariantRule(**item) for item in raw.get("invariants", [])]
        return InvariantChecker(rules=rules)
