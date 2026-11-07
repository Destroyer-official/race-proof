# Invariant Specification & Rule Authoring Guide

> **Version**: 1.0  
> **Status**: Production Standard  
> **Target**: Writing deterministic invariants to detect state corruption, double-spends, and limit overruns.

---

## 1. What is an Invariant?

An **invariant** is a logical predicate over a set of HTTP responses that must **always hold true** regardless of server load, network latency, or concurrent request interleaving.

If an attacker fires $N$ concurrent requests against an endpoint that should only allow a single successful execution, any state transition where $> 1$ request succeeds represents an **invariant violation**.

RaceProof evaluates invariants deterministically using:
- **HTTP status codes**
- **JSON response bodies via JMESPath expressions**
- **Headers and state diffs**
- **Statistical thresholds**

---

## 2. Invariant Rule Schema

Invariant rules can be declared via YAML or JSON:

```yaml
invariants:
  - id: rule_unique_identifier
    description: Human-readable description of the security invariant
    severity: CRITICAL | HIGH | MEDIUM | LOW
    operator: single_winner | any_negative | state_stall | unique | all_match | none_match | numeric_lte | custom
    field: status_code | jmespath.expression
    threshold: 1.0
    expected: null
```

---

## 3. Ten Real-World Invariant Examples

### Example 1: Single Winner on Coupon Redemption (Limit Overrun)
Ensures that across $N$ parallel coupon redemption attempts, at most one request receives an HTTP 200 success response.
```yaml
id: single_coupon_winner
description: At most one concurrent coupon application may succeed
severity: HIGH
operator: single_winner
field: status_code
threshold: 1.0
```

### Example 2: Negative Account Balance Prevention (Fintech TOCTOU)
Ensures that no concurrent withdrawal or transfer results in a negative account balance.
```yaml
id: no_negative_balance
description: Account balance must never fall below zero
severity: CRITICAL
operator: any_negative
field: account.balance
threshold: 0.0
```

### Example 3: Unique Gift Card Redemption ID
Ensures that the redeemed voucher code or authorization token is never granted more than once across parallel threads.
```yaml
id: unique_voucher_grant
description: Granted voucher authorizations must be globally distinct
severity: HIGH
operator: unique
field: data.authorization_token
```

### Example 4: State Stalling / Stale Read Detection (Lost Update)
Detects whether concurrent requests observe an identical initial balance snapshot despite one request having already committed a deduction.
```yaml
id: no_stale_balance_reads
description: Concurrent threads must not read identical pre-commit state
severity: HIGH
operator: state_stall
field: balance
```

### Example 5: One-Time Password (OTP) / Verification Code Single-Use
Ensures that an SMS or email OTP cannot be validated multiple times simultaneously to mint separate sessions.
```yaml
id: single_otp_validation
description: OTP code can only transition one session to authenticated state
severity: CRITICAL
operator: single_winner
field: status_code
threshold: 1.0
```

### Example 6: Reward Points Non-Overdraft (E-Commerce)
Ensures that loyalty reward points deducted across concurrent purchases do not exceed the user's total accrued points.
```yaml
id: reward_points_ceiling
description: Deducted points must not exceed initial balance
severity: HIGH
operator: numeric_lte
field: points.remaining
threshold: 0.0
```

### Example 7: Inventory Allocation Cap (Flash Sale Race)
Prevents an inventory SKU from being reserved by multiple shoppers when stock count is 1.
```yaml
id: single_inventory_reservation
description: Exactly one thread may successfully lock the inventory item
severity: CRITICAL
operator: single_winner
field: reservation.status
expected: "RESERVED"
threshold: 1.0
```

### Example 8: Password Reset Token Invalidation
Ensures that once a password reset token is used, concurrent requests return HTTP 400 or HTTP 401 instead of 200.
```yaml
id: password_reset_single_use
description: Password reset token must be invalidated upon first concurrent read
severity: HIGH
operator: single_winner
field: status_code
threshold: 1.0
```

### Example 9: Invitation Code Referral Bonus
Ensures that a single-use onboarding invite code does not pay out referral bonuses to multiple parallel signups.
```yaml
id: referral_bonus_single_claim
description: Referral credit must only be credited to one newly registered user
severity: MEDIUM
operator: single_winner
field: referral.bonus_applied
expected: true
threshold: 1.0
```

### Example 10: WebSocket Session Claim Collision
Ensures that claiming ownership of a real-time WebSocket channel from multiple browser tabs fails for all except the first caller.
```yaml
id: ws_channel_exclusive_claim
description: Channel ownership claim must be mutually exclusive
severity: HIGH
operator: single_winner
field: payload.action_result
expected: "CLAIM_GRANTED"
threshold: 1.0
```

---

## 4. Latent Invariant Auto-Mining

If you do not specify explicit invariant rules, RaceProof's **Invariant Miner** (`race_proof/analysis/invariant_miner.py`) inspects the response schema automatically:
1. **Identifies Numeric Decrements**: Finds numeric balance/counter fields and synthesizes `NoOverdraft` checks.
2. **Detects Resource Identifiers**: Mines UUIDs and transaction IDs and asserts `UniqueToken` invariants.
3. **Monitors Success Codes**: Asserts `SingleWinner` whenever the endpoint contains state-mutating verbs (`POST`, `PUT`, `PATCH`, `DELETE`).

