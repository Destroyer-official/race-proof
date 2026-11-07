"""Automated Invariant Miner — 2027-ready dynamic specification inference.

Inspired by academic invariant synthesis literature (Daikon, ATUSA, ClassInvGen):
Automatically infers latent business invariants directly from baseline and race
response schemas without requiring manual rules file creation.
"""
from __future__ import annotations

import json
import re
from typing import Any

from race_proof.models import (
    InvariantOperator,
    InvariantRule,
    RaceResponse,
    RaceSession,
)


class InvariantMiner:
    """
    Mines latent business invariants from HTTP response bodies.

    Extracts:
    1. Numeric bounds (balance >= 0, remaining_slots >= 0)
    2. Idempotency / token uniqueness (unique order IDs, nonces, receipts)
    3. State mutation cardinality (at most 1 success transition per concurrent batch)
    4. Monotonic decrement / conservation laws
    """

    NUMERIC_KEYWORDS = {
        "balance", "credit", "credits", "point", "points", "stock", "inventory",
        "remaining", "remaining_redemptions", "slots", "quota", "allowance",
        "attempts", "attempts_left", "coins", "wallet", "amount", "budget"
    }

    ID_KEYWORDS = {
        "order_id", "transaction_id", "receipt", "receipt_id", "created_token",
        "confirmation_code", "claim_id", "ticket_id", "serial", "generated_uuid"
    }

    SUCCESS_KEYWORDS = {
        "success", "applied", "redeemed", "claimed", "transferred",
        "completed", "discount_applied", "coupon_applied", "processed"
    }

    def mine_rules(self, session: RaceSession) -> list[InvariantRule]:
        """Synthesize candidate invariant rules for the given session."""
        rules: list[InvariantRule] = []

        all_resps = [session.baseline] + session.race_responses
        json_bodies: list[dict[str, Any]] = []

        for r in all_resps:
            if r.body:
                try:
                    data = json.loads(r.body)
                    if isinstance(data, dict):
                        json_bodies.append(data)
                except Exception:
                    pass

        if not json_bodies:
            # Fallback: general HTTP 200 winner rule
            rules.append(
                InvariantRule(
                    id="mined_single_200_winner",
                    description="Auto-Mined: Mutating endpoint allows at most 1 HTTP 200 in concurrent burst",
                    operator=InvariantOperator.COUNT_GT,
                    threshold=1.0,
                    severity="HIGH",
                    applies_to="race_responses",
                )
            )
            return rules

        # 1. Mine numeric non-negativity bounds
        numeric_paths = self._find_paths_matching_keywords(json_bodies[0], self.NUMERIC_KEYWORDS)
        for path in numeric_paths:
            rule_id = f"mined_non_negative_{path.replace('.', '_')}"
            rules.append(
                InvariantRule(
                    id=rule_id,
                    description=f"Auto-Mined Invariant: Field '{path}' must not be negative",
                    jmespath=path,
                    operator=InvariantOperator.ANY_NEGATIVE,
                    threshold=0.0,
                    severity="HIGH",
                    applies_to="race_responses",
                )
            )

        # 2. Mine uniqueness / idempotency rules for resource IDs
        id_paths = self._find_paths_matching_keywords(json_bodies[0], self.ID_KEYWORDS)
        for path in id_paths:
            rule_id = f"mined_unique_{path.replace('.', '_')}"
            rules.append(
                InvariantRule(
                    id=rule_id,
                    description=f"Auto-Mined Invariant: Generated resource '{path}' must be strictly unique across parallel creations",
                    jmespath=path,
                    operator=InvariantOperator.UNIQUE_VALUES,
                    threshold=1.0,
                    severity="MEDIUM",
                    applies_to="race_responses",
                )
            )

        # 3. Mine single-success mutation cardinality
        success_paths = self._find_paths_matching_keywords(json_bodies[0], self.SUCCESS_KEYWORDS)
        for path in success_paths:
            rule_id = f"mined_single_success_{path.replace('.', '_')}"
            rules.append(
                InvariantRule(
                    id=rule_id,
                    description=f"Auto-Mined Invariant: Mutating flag '{path}' can only transition to true at most once",
                    jmespath=path,
                    expected_value=True,
                    operator=InvariantOperator.COUNT_GT,
                    threshold=1.0,
                    severity="HIGH",
                    applies_to="race_responses",
                )
            )

        # 4. Standard mutating winner cardinality
        if not any(r.id.startswith("mined_single_success_") for r in rules):
            rules.append(
                InvariantRule(
                    id="mined_single_200_winner",
                    description="Auto-Mined: Concurrent state transition permits at most 1 HTTP 200 response",
                    operator=InvariantOperator.COUNT_GT,
                    threshold=1.0,
                    severity="HIGH",
                    applies_to="race_responses",
                )
            )

        return rules

    def _find_paths_matching_keywords(
        self, data: dict[str, Any], keywords: set[str], prefix: str = ""
    ) -> list[str]:
        matched: list[str] = []
        for k, v in data.items():
            current_path = f"{prefix}.{k}" if prefix else k
            k_lower = k.lower()

            if any(kw in k_lower for kw in keywords):
                matched.append(current_path)

            if isinstance(v, dict):
                matched.extend(self._find_paths_matching_keywords(v, keywords, prefix=current_path))

        return matched

