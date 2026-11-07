"""Timing distribution analysis.

A genuine race condition produces responses that cluster tightly in
wall-clock time or display a bimodal latency distribution indicative
of server-side lock contention.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

from race_proof.models import AnalysisDimension, DimensionResult, RaceSession


@dataclass
class TimingCluster:
    centroid_ms: float
    spread_ms: float          # std deviation / range
    member_indices: list[int]
    is_tight: bool            # spread < threshold → consistent with race window


class TimingAnalyser:
    """
    Analyses the timing distribution of race responses to determine
    whether anomalous responses cluster in a way consistent with
    concurrent server-side processing within the same transaction window.
    """

    TIGHT_WINDOW_MS = 10.0
    ANOMALY_DELTA_MS = 5.0

    def __init__(
        self,
        tight_window_ms: float = TIGHT_WINDOW_MS,
        anomaly_delta_ms: float = ANOMALY_DELTA_MS,
    ):
        self.tight_window_ms = tight_window_ms
        self.anomaly_delta_ms = anomaly_delta_ms

    def analyse(self, session: RaceSession) -> DimensionResult:
        """Run timing analysis on a RaceSession."""
        elapsed_times = [r.elapsed_ms for r in session.race_responses]
        ttfb_times = [r.ttfb_ms for r in session.race_responses if r.ttfb_ms is not None]
        server_proc_times = [r.server_processing_ms for r in session.race_responses if r.server_processing_ms is not None]

        baseline_elapsed = session.baseline.elapsed_ms
        baseline_ttfb = session.baseline.ttfb_ms

        evidence: list[str] = []
        details: dict[str, Any] = {}

        # Basic statistics on elapsed times
        if elapsed_times:
            mean_elapsed = statistics.mean(elapsed_times)
            stdev_elapsed = statistics.stdev(elapsed_times) if len(elapsed_times) > 1 else 0.0
            details["elapsed_ms"] = {
                "mean": round(mean_elapsed, 2),
                "stdev": round(stdev_elapsed, 2),
                "min": round(min(elapsed_times), 2),
                "max": round(max(elapsed_times), 2),
                "baseline": round(baseline_elapsed, 2),
            }

        # Cluster analysis
        clusters = self._cluster_times(elapsed_times)
        tight_clusters = [c for c in clusters if c.is_tight and len(c.member_indices) >= 2]

        details["clusters"] = [
            {
                "centroid_ms": round(c.centroid_ms, 2),
                "spread_ms": round(c.spread_ms, 2),
                "members": c.member_indices,
                "tight": c.is_tight,
            }
            for c in clusters
        ]

        if tight_clusters:
            best = min(tight_clusters, key=lambda c: c.spread_ms)
            evidence.append(
                f"Tight timing cluster: {len(best.member_indices)} responses within "
                f"{best.spread_ms:.1f} ms of each other (centroid={best.centroid_ms:.1f} ms)"
            )

        # KDE-based bimodality / multimodality check
        bimodal, bimodal_detail, num_modes = self._check_bimodality(elapsed_times)
        if bimodal:
            evidence.append(f"Multimodal latency distribution detected: {bimodal_detail}")
        details["bimodal"] = bimodal
        details["detected_latency_modes"] = num_modes

        # TTFB analysis: winners hitting same upstream lock
        ttfb_tight = False
        if len(ttfb_times) >= 2:
            ttfb_spread = max(ttfb_times) - min(ttfb_times)
            ttfb_tight = ttfb_spread < self.tight_window_ms
            details["ttfb_spread_ms"] = round(ttfb_spread, 2)
            if ttfb_tight:
                evidence.append(
                    f"TTFB spread across race responses: {ttfb_spread:.1f} ms "
                    f"(< {self.tight_window_ms} ms threshold → consistent with synchronized arrival)"
                )

        # Server processing time analysis (elapsed - TTFB)
        if len(server_proc_times) >= 2:
            proc_spread = max(server_proc_times) - min(server_proc_times)
            details["server_processing_spread_ms"] = round(proc_spread, 2)
            if proc_spread < self.tight_window_ms:
                evidence.append(
                    f"Server processing window spread: {proc_spread:.1f} ms "
                    "(backend completed requests in lockstep)"
                )

        # Anomaly detection relative to baseline
        anomalous_indices: list[int] = []
        if baseline_elapsed > 0:
            for i, t in enumerate(elapsed_times):
                delta = abs(t - baseline_elapsed)
                if delta > self.anomaly_delta_ms * 3:
                    anomalous_indices.append(i)
                    evidence.append(
                        f"Response[{i}] timing anomaly: {t:.1f} ms "
                        f"vs baseline {baseline_elapsed:.1f} ms (Δ={delta:.1f} ms)"
                    )
        details["anomalous_response_indices"] = anomalous_indices

        # Concurrency overlap & serialization index
        overlap_ratio, peak_concurrent, overlap_evidence = self._compute_concurrency_overlap(session)
        evidence.extend(overlap_evidence)
        ser_score, is_serialized = self._compute_serialization_index(elapsed_times)
        if is_serialized:
            evidence.append(
                f"Server-side lock contention detected: sequential FIFO stepping (score={ser_score})"
            )
        details["concurrency_overlap_ratio"] = round(overlap_ratio, 3)
        details["peak_concurrent_in_flight"] = peak_concurrent
        details["serialization_score"] = ser_score
        details["is_serialized_queue"] = is_serialized

        anomaly_detected = bool(tight_clusters) or bimodal or ttfb_tight or (peak_concurrent >= 2 and overlap_ratio > 0.5)
        confidence = self._compute_confidence(tight_clusters, bimodal, ttfb_tight, len(elapsed_times))

        return DimensionResult(
            dimension=AnalysisDimension.TIMING,
            anomaly_detected=anomaly_detected,
            confidence=round(confidence, 3),
            summary=self._build_summary(tight_clusters, bimodal, ttfb_tight, elapsed_times),
            details=details,
            evidence_lines=evidence[:8],
        )

    # ------------------------------------------------------------------
    # Concurrency Overlap & Serialization
    # ------------------------------------------------------------------

    def _compute_concurrency_overlap(self, session: RaceSession) -> tuple[float, int, list[str]]:
        windows = []
        for r in session.race_responses:
            start = r.ttfb_ms if r.ttfb_ms is not None else 0.0
            end = r.elapsed_ms if r.elapsed_ms > start else start + 1.0
            windows.append((start, end, r.sequence_index))

        if len(windows) < 2:
            return 0.0, 1, []

        events = []
        for start, end, idx in windows:
            events.append((start, 1, idx))
            events.append((end, -1, idx))
        events.sort(key=lambda x: (x[0], -x[1]))

        current_concurrent = 0
        peak_concurrent = 0
        for _, delta, _ in events:
            current_concurrent += delta
            if current_concurrent > peak_concurrent:
                peak_concurrent = current_concurrent

        overlap_ratios = []
        for i in range(len(windows)):
            for j in range(i + 1, len(windows)):
                s1, e1, _ = windows[i]
                s2, e2, _ = windows[j]
                overlap = max(0.0, min(e1, e2) - max(s1, s2))
                duration = min(e1 - s1, e2 - s2)
                if duration > 0:
                    overlap_ratios.append(overlap / duration)

        max_ratio = max(overlap_ratios) if overlap_ratios else 0.0
        avg_ratio = statistics.mean(overlap_ratios) if overlap_ratios else 0.0

        evidence = []
        if peak_concurrent >= 2 and max_ratio > 0.3:
            evidence.append(
                f"Concurrent server execution: {peak_concurrent} requests overlapping in flight "
                f"(max window overlap={max_ratio:.1%}, avg={avg_ratio:.1%})"
            )
        return max_ratio, peak_concurrent, evidence

    def _compute_serialization_index(self, elapsed_times: list[float]) -> tuple[float, bool]:
        if len(elapsed_times) < 3:
            return 0.0, False
        sorted_times = sorted(elapsed_times)
        diffs = [sorted_times[i+1] - sorted_times[i] for i in range(len(sorted_times)-1)]
        mean_diff = statistics.mean(diffs)
        if mean_diff < 0.5:
            return 0.0, False
        stdev_diff = statistics.stdev(diffs) if len(diffs) > 1 else 0.0
        cv = stdev_diff / mean_diff if mean_diff > 0 else 1.0
        is_serialized = cv < 0.25 and mean_diff > 2.0
        return round(1.0 - min(cv, 1.0), 3), is_serialized

    # ------------------------------------------------------------------
    # Clustering
    # ------------------------------------------------------------------

    def _cluster_times(self, times: list[float]) -> list[TimingCluster]:
        if not times:
            return []
        sorted_indexed = sorted(enumerate(times), key=lambda x: x[1])
        clusters: list[TimingCluster] = []
        current_group: list[tuple[int, float]] = [sorted_indexed[0]]

        for idx, t in sorted_indexed[1:]:
            if t - current_group[-1][1] <= self.tight_window_ms:
                current_group.append((idx, t))
            else:
                clusters.append(self._make_cluster(current_group))
                current_group = [(idx, t)]
        clusters.append(self._make_cluster(current_group))
        return clusters

    def _make_cluster(self, group: list[tuple[int, float]]) -> TimingCluster:
        indices = [i for i, _ in group]
        vals = [t for _, t in group]
        centroid = statistics.mean(vals)
        spread = (max(vals) - min(vals)) if len(vals) > 1 else 0.0
        return TimingCluster(
            centroid_ms=centroid,
            spread_ms=spread,
            member_indices=indices,
            is_tight=spread < self.tight_window_ms,
        )

    # ------------------------------------------------------------------
    # Bimodality / KDE Peak Detection
    # ------------------------------------------------------------------

    def _check_bimodality(self, times: list[float]) -> tuple[bool, str, int]:
        if len(times) < 4:
            return False, "", 1
        try:
            import numpy as np
            from scipy.stats import gaussian_kde

            arr = np.array(times, dtype=float)
            if arr.std() < 1e-6:
                return False, "all times identical", 1

            kde = gaussian_kde(arr, bw_method="silverman")
            xs = np.linspace(arr.min(), arr.max(), 200)
            density = kde(xs)

            peaks: list[float] = []
            max_d = density.max()
            for i in range(1, len(density) - 1):
                # Detect peaks with relative prominence (>10% of max density)
                if density[i] > density[i-1] and density[i] > density[i+1] and density[i] > 0.10 * max_d:
                    peaks.append(float(xs[i]))

            if len(peaks) >= 2:
                peak_str = ", ".join(f"{p:.1f} ms" for p in peaks[:3])
                return True, f"{len(peaks)} timing peaks at {peak_str}", len(peaks)
            return False, f"single timing mode at {peaks[0]:.1f} ms" if peaks else "", len(peaks)
        except Exception:
            if len(times) < 2:
                return False, "", 1
            rng = max(times) - min(times)
            std = statistics.stdev(times)
            if std > 0 and rng / std > 4:
                return True, f"high dispersion (range={rng:.1f} ms, std={std:.1f} ms)", 2
            return False, "", 1

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _compute_confidence(
        self,
        tight_clusters: list[TimingCluster],
        bimodal: bool,
        ttfb_tight: bool,
        n: int,
    ) -> float:
        score = 0.0
        if tight_clusters:
            tightest = min(tight_clusters, key=lambda c: c.spread_ms)
            score += max(0.15, 0.65 - tightest.spread_ms / 100.0)
        if bimodal:
            score += 0.25
        if ttfb_tight:
            score += 0.15
        score *= min(1.0, 0.5 + n / 20.0)
        return min(0.95, score)

    def _build_summary(
        self,
        tight_clusters: list[TimingCluster],
        bimodal: bool,
        ttfb_tight: bool,
        times: list[float],
    ) -> str:
        parts: list[str] = []
        if tight_clusters:
            best = min(tight_clusters, key=lambda c: c.spread_ms)
            parts.append(
                f"tight cluster: {len(best.member_indices)} responses "
                f"within {best.spread_ms:.1f} ms"
            )
        if bimodal:
            parts.append("multimodal latency distribution (lock contention)")
        if ttfb_tight:
            parts.append("TTFB synchronized")
        if not parts:
            spread = max(times) - min(times) if times else 0
            parts.append(f"no timing anomaly detected (spread={spread:.1f} ms)")
        return "; ".join(parts)
