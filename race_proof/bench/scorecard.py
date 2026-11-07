"""Benchmark scorecard calculation with Holm-Bonferroni multi-testing correction."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScenarioResult:
    scenario_id: str
    domain: str
    ground_truth: str
    predicted_verdict: str
    confidence: float
    p_value: float
    is_correct: bool
    classification: str  # TP, FP, TN, FN
    execution_time_ms: float
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class DomainMetrics:
    domain: str
    total: int = 0
    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) > 0 else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) > 0 else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return (2 * p * r) / (p + r) if (p + r) > 0 else 0.0

    @property
    def fdr(self) -> float:
        return self.fp / (self.tp + self.fp) if (self.tp + self.fp) > 0 else 0.0


class BenchmarkScorecard:
    """Computes precision, recall, F1, MCC and Holm-Bonferroni correction."""

    def __init__(self, results: list[ScenarioResult], alpha: float = 0.05):
        self.results = results
        self.alpha = alpha

    def compute_summary(self) -> dict[str, Any]:
        total = len(self.results)
        tp = sum(1 for r in self.results if r.classification == "TP")
        fp = sum(1 for r in self.results if r.classification == "FP")
        tn = sum(1 for r in self.results if r.classification == "TN")
        fn = sum(1 for r in self.results if r.classification == "FN")

        precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
        f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
        fdr = fp / (tp + fp) if (tp + fp) > 0 else 0.0

        # Matthew's Correlation Coefficient
        denom = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
        mcc = ((tp * tn) - (fp * fn)) / denom if denom > 0 else 0.0

        # Holm-Bonferroni correction over p-values
        sorted_by_p = sorted(self.results, key=lambda r: r.p_value)
        m = len(sorted_by_p)
        significant_count = 0
        for rank, r in enumerate(sorted_by_p, start=1):
            threshold = self.alpha / (m - rank + 1)
            if r.p_value <= threshold:
                significant_count += 1
            else:
                break

        # Per-domain breakdown
        domains: dict[str, DomainMetrics] = {}
        for r in self.results:
            if r.domain not in domains:
                domains[r.domain] = DomainMetrics(domain=r.domain)
            dm = domains[r.domain]
            dm.total += 1
            if r.classification == "TP":
                dm.tp += 1
            elif r.classification == "FP":
                dm.fp += 1
            elif r.classification == "TN":
                dm.tn += 1
            elif r.classification == "FN":
                dm.fn += 1

        return {
            "total_scenarios": total,
            "true_positives": tp,
            "false_positives": fp,
            "true_negatives": tn,
            "false_negatives": fn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1_score": round(f1, 4),
            "fdr": round(fdr, 4),
            "mcc": round(mcc, 4),
            "holm_bonferroni_significant": significant_count,
            "alpha": self.alpha,
            "domains": {
                name: {
                    "total": dm.total,
                    "tp": dm.tp,
                    "fp": dm.fp,
                    "tn": dm.tn,
                    "fn": dm.fn,
                    "precision": round(dm.precision, 4),
                    "recall": round(dm.recall, 4),
                    "f1": round(dm.f1, 4),
                    "fdr": round(dm.fdr, 4),
                }
                for name, dm in sorted(domains.items())
            },
        }

    def render_markdown(self) -> str:
        s = self.compute_summary()
        lines = [
            "# 🏆 RaceProof Benchmark Scorecard (`race-proof-bench`)",
            "",
            f"**Total Scenarios Tested:** {s['total_scenarios']}  ",
            f"**Overall Precision:** `{s['precision']:.1%}` (FDR: `{s['fdr']:.1%}`)  ",
            f"**Overall Recall:** `{s['recall']:.1%}`  ",
            f"**F1 Score:** `{s['f1_score']:.4f}`  ",
            f"**Matthews Correlation Coefficient (MCC):** `{s['mcc']:.4f}`  ",
            f"**Holm-Bonferroni Statistically Significant:** `{s['holm_bonferroni_significant']}/{s['total_scenarios']}` (α = {s['alpha']})  ",
            "",
            "## Domain Performance Breakdown",
            "",
            "| Domain | Total | TP | FP | TN | FN | Precision | Recall | F1 Score |",
            "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
        ]

        for d_name, dm in s["domains"].items():
            lines.append(
                f"| `{d_name}` | {dm['total']} | {dm['tp']} | {dm['fp']} | {dm['tn']} | {dm['fn']} | "
                f"**{dm['precision']:.1%}** | **{dm['recall']:.1%}** | **{dm['f1']:.4f}** |"
            )

        lines.extend([
            "",
            "## Scenario Execution Ledger",
            "",
            "| Scenario ID | Domain | Ground Truth | Prediction | Result | Conf | p-value | Time (ms) |",
            "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
        ])

        for r in self.results:
            icon = "✅" if r.is_correct else "❌"
            lines.append(
                f"| `{r.scenario_id}` | `{r.domain}` | `{r.ground_truth}` | `{r.predicted_verdict}` | "
                f"{icon} `{r.classification}` | {r.confidence:.2f} | {r.p_value:.4f} | {r.execution_time_ms:.1f} |"
            )

        return "\n".join(lines)

