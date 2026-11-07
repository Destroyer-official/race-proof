"""Repeated-trial statistical engine.

A genuine race condition is reproducible at a measurable rate across N trials.
This module calculates binomial success rates, Wilson confidence intervals,
and p-values to distinguish signal from noise.
"""
from __future__ import annotations

import math
from typing import Any

from race_proof.models import AnalysisDimension, DimensionResult, RaceSession


class StatisticsEngine:
    """
    Analyses repeated race trial results to compute a statistically
    defensible success rate with confidence bounds.

    Can operate in two modes:
    1. Single-session mode: estimate success rate from status code diversity
       within one captured session.
    2. Multi-trial mode: given N pre-run trial sessions, compute binomial stats.
    """

    def __init__(self, min_success_rate: float = 0.05, alpha: float = 0.05):
        """
        Parameters
        ----------
        min_success_rate:
            Minimum observed success rate to consider a finding non-noise.
            Default 5% (1-in-20 reproducibility is a defensible bar).
        alpha:
            Significance level for the binomial test. Default 0.05.
        """
        self.min_success_rate = min_success_rate
        self.alpha = alpha

    # ------------------------------------------------------------------
    # Single session estimation
    # ------------------------------------------------------------------

    def analyse(self, session: RaceSession) -> DimensionResult:
        """
        Estimate statistical significance from a single captured session.
        
        In a single session, 'successes' are race responses that deviate
        from the baseline (different status code, or anomalous body marker).
        """
        n = len(session.race_responses)
        baseline_code = session.baseline.status_code

        # Count responses that differ from baseline
        successes = sum(
            1 for r in session.race_responses
            if r.status_code != baseline_code
        )

        return self._compute_result(n=n, successes=successes, evidence_prefix="single-session")

    def analyse_trials(
        self, sessions: list[RaceSession], success_fn: Any = None
    ) -> DimensionResult:
        """
        Compute stats across multiple trial sessions.

        Parameters
        ----------
        sessions:
            List of RaceSession objects, each representing one trial run.
        success_fn:
            Optional callable(session) -> bool. If None, a session is a
            success if any race response has a different status than baseline.
        """
        n = len(sessions)
        if success_fn is None:
            def success_fn(s: RaceSession) -> bool:
                return any(r.status_code != s.baseline.status_code for r in s.race_responses)

        successes = sum(1 for s in sessions if success_fn(s))
        return self._compute_result(n=n, successes=successes, evidence_prefix="multi-trial")

    # ------------------------------------------------------------------
    # Core statistics
    # ------------------------------------------------------------------

    def _compute_result(self, n: int, successes: int, evidence_prefix: str) -> DimensionResult:
        if n == 0:
            return DimensionResult(
                dimension=AnalysisDimension.STATISTICS,
                anomaly_detected=False,
                confidence=0.0,
                summary="No trials available for statistical analysis.",
                details={},
                evidence_lines=[],
            )

        rate = successes / n
        ci_lo, ci_hi = self._wilson_ci(n=n, k=successes, alpha=self.alpha)
        p_value = self._binomial_p_value(n=n, k=successes)

        anomaly_detected = bool(
            rate >= self.min_success_rate
            and p_value < self.alpha
            and ci_lo > 0.0
        )

        confidence = 0.0
        if anomaly_detected:
            # Confidence scales with rate and inversely with CI width
            ci_width = ci_hi - ci_lo
            confidence = min(0.95, rate * (1.0 - ci_width))

        evidence: list[str] = [
            f"{evidence_prefix}: {successes}/{n} trials succeeded "
            f"(rate={rate:.1%}, 95% CI [{ci_lo:.1%}–{ci_hi:.1%}], p={p_value:.4f})"
        ]
        if p_value < 0.001:
            evidence.append("p < 0.001: extremely unlikely to be random noise")
        elif p_value < 0.01:
            evidence.append("p < 0.01: strong evidence against null hypothesis")

        return DimensionResult(
            dimension=AnalysisDimension.STATISTICS,
            anomaly_detected=anomaly_detected,
            confidence=round(confidence, 3),
            summary=(
                f"{'Statistically significant' if anomaly_detected else 'Not significant'}: "
                f"{successes}/{n} successes (rate={rate:.1%}, p={p_value:.4f})"
            ),
            details={
                "n_trials": n,
                "successes": successes,
                "success_rate": round(rate, 4),
                "ci_95_lower": round(ci_lo, 4),
                "ci_95_upper": round(ci_hi, 4),
                "p_value": round(p_value, 6),
                "significant": anomaly_detected,
                "min_success_rate_threshold": self.min_success_rate,
                "alpha": self.alpha,
            },
            evidence_lines=evidence,
        )

    # ------------------------------------------------------------------
    # Statistical helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _wilson_ci(n: int, k: int, alpha: float = 0.05) -> tuple[float, float]:
        """Wilson score confidence interval for a binomial proportion."""
        if n == 0:
            return 0.0, 1.0
        try:
            from scipy.stats import norm
            z = float(norm.ppf(1 - alpha / 2))
        except ImportError:
            z = 1.96  # 95% CI fallback

        p_hat = k / n
        centre = p_hat + z**2 / (2 * n)
        margin = z * math.sqrt((p_hat * (1 - p_hat) + z**2 / (4 * n)) / n)
        denominator = 1 + z**2 / n

        lo = max(0.0, (centre - margin) / denominator)
        hi = min(1.0, (centre + margin) / denominator)
        return float(lo), float(hi)

    @staticmethod
    def _binomial_p_value(n: int, k: int, p0: float = 0.01) -> float:
        """
        One-sided binomial test p-value.

        H0: the true success rate is p0 (default 1% — attributable to noise).
        H1: the true rate is higher than p0.
        """
        try:
            from scipy.stats import binomtest
            result = binomtest(k, n, p0, alternative="greater")
            return float(result.pvalue)
        except ImportError:
            # Manual calculation using the binomial CDF complement
            p_val = 0.0
            log_p0 = math.log(p0) if p0 > 0 else float("-inf")
            log_q0 = math.log(1 - p0) if p0 < 1 else float("-inf")
            log_binom_coeff = 0.0
            # Build up P(X >= k) = sum_{i=k}^{n} C(n,i) p0^i (1-p0)^(n-i)
            for i in range(k, n + 1):
                if i == k:
                    log_binom_coeff = sum(
                        math.log(n - j) - math.log(j + 1) for j in range(i)
                    )
                else:
                    log_binom_coeff += math.log(n - i + 1) - math.log(i)
                log_prob = log_binom_coeff + i * log_p0 + (n - i) * log_q0
                p_val += math.exp(log_prob)
            return min(1.0, p_val)
