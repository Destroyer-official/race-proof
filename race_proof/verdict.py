"""Verdict engine — orchestrates all analysis dimensions and produces a final verdict.

The engine runs all 4 deterministic analysis dimensions in order:
1. Semantic Body Diff
2. Timing Distribution
3. Invariant Violation
4. Repeated-Trial Statistics

Then combines their results into a weighted composite verdict.
If the verdict is UNCERTAIN and an agent is attached, the agent is
invoked for deeper research.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich import box

from race_proof.models import (
    AnalysisDimension,
    DimensionResult,
    InvariantRule,
    InvariantViolation,
    RaceSession,
    Verdict,
    VerdictLevel,
)

console = Console(highlight=False)

DIMENSION_WEIGHTS = {
    AnalysisDimension.INVARIANT: 0.45,
    AnalysisDimension.STATISTICS: 0.25,
    AnalysisDimension.SEMANTIC_DIFF: 0.20,
    AnalysisDimension.TIMING: 0.10,
}


class VerdictEngine:
    """Orchestrates all analysis dimensions and produces a final verdict."""

    def __init__(
        self,
        invariants_file: Path | None = None,
        invariant_rules: list[InvariantRule] | None = None,
        agent: Any | None = None,
        verbose: bool = True,
        load_builtins: bool = True,
    ):
        from race_proof.analysis.semantic_diff import SemanticDiffer
        from race_proof.analysis.timing import TimingAnalyser
        from race_proof.analysis.invariants import InvariantChecker
        from race_proof.analysis.statistics import StatisticsEngine

        self.differ = SemanticDiffer()
        self.timer = TimingAnalyser()
        self.invariant_checker = InvariantChecker(
            rules=invariant_rules,
            rules_file=invariants_file,
            load_builtins=load_builtins,
            auto_mine=load_builtins,
        )
        
        if load_builtins:
            learned = Path.home() / ".race-proof" / "learned_invariants.yaml"
            if learned.exists():
                self.invariant_checker._load_rules_file(learned)

        self.stats_engine = StatisticsEngine()
        self.agent = agent
        self.verbose = verbose

    def analyse(self, session: RaceSession) -> Verdict:
        """Run the full analysis pipeline on a RaceSession."""
        finding_id = f"finding_{session.id}_{str(uuid.uuid4())[:6]}"

        if self.verbose:
            console.print(
                Panel(
                    f"[dim]Session: {session.id} | Tool: {session.tool_source} | "
                    f"Race responses: {len(session.race_responses)}[/dim]",
                    title="[bold cyan]RACEPROOF — ANALYSING[/bold cyan]",
                    border_style="cyan",
                    box=box.ROUNDED,
                )
            )

        dimensions: list[DimensionResult] = []

        for name, analyser, label in [
            ("semantic_diff", self.differ.analyse, "Semantic diff"),
            ("timing", self.timer.analyse, "Timing analysis"),
            ("invariant", self.invariant_checker.analyse, "Invariant check"),
            ("statistics", self.stats_engine.analyse, "Statistics"),
        ]:
            if self.verbose:
                console.print(f"  [dim]Running {label}...[/dim]", end=" ")
            try:
                result = analyser(session)
                dimensions.append(result)
                if self.verbose:
                    icon = "✓" if result.anomaly_detected else "·"
                    color = "red" if result.anomaly_detected else "green"
                    console.print(f"[{color}]{icon}[/{color}] {result.summary[:80]}")
            except Exception as exc:
                if self.verbose:
                    console.print(f"[yellow]ERROR: {exc}[/yellow]")

        inv_dim = next((d for d in dimensions if d.dimension == AnalysisDimension.INVARIANT), None)
        violations: list[InvariantViolation] = []
        invariant_violated: str | None = None
        if inv_dim and inv_dim.details.get("violations"):
            for v in inv_dim.details["violations"]:
                violations.append(InvariantViolation(**v))
            if violations:
                invariant_violated = violations[0].rule_id

        composite_confidence = self._compute_composite_confidence(dimensions)
        anomaly_count = sum(1 for d in dimensions if d.anomaly_detected)

        stats_dim = next((d for d in dimensions if d.dimension == AnalysisDimension.STATISTICS), None)
        trial_count = stats_dim.details.get("n_trials", len(session.race_responses)) if stats_dim else len(session.race_responses)
        success_rate = stats_dim.details.get("success_rate", 0.0) if stats_dim else 0.0
        ci_lo = stats_dim.details.get("ci_95_lower", 0.0) if stats_dim else 0.0
        ci_hi = stats_dim.details.get("ci_95_upper", 1.0) if stats_dim else 1.0
        p_value = stats_dim.details.get("p_value", 1.0) if stats_dim else 1.0

        verdict_level = self._determine_verdict(
            anomaly_count=anomaly_count,
            composite_confidence=composite_confidence,
            has_invariant_violation=bool(violations),
            has_stats_significance=bool(stats_dim and stats_dim.anomaly_detected),
        )

        severity = self._determine_severity(violations, anomaly_count, composite_confidence)

        # 2027 Advanced Concurrency Diagnostics (ACM ReqRacer, PortSwigger, IEEE S&P 2025 Racedb)
        from race_proof.analysis.happens_before import HappensBeforeEngine
        from race_proof.analysis.multi_endpoint import MultiEndpointAnalyser
        from race_proof.analysis.anomaly_classifier import ConcurrencyAnomalyClassifier

        hb_dag = HappensBeforeEngine().analyse(session)
        me_res = MultiEndpointAnalyser().analyse(session)

        timing_dim = next((d for d in dimensions if d.dimension == AnalysisDimension.TIMING), None)
        if timing_dim:
            timing_dim.details["concurrency_density"] = hb_dag.concurrency_density
            timing_dim.details["max_concurrent_clique"] = hb_dag.max_concurrent_clique
            timing_dim.details["is_true_concurrent_burst"] = hb_dag.is_true_concurrent_burst
            if hb_dag.is_true_concurrent_burst:
                timing_dim.evidence_lines.append(
                    f"ReqRacer DAG: {hb_dag.max_concurrent_clique} requests overlapped simultaneously "
                    f"(concurrency density={hb_dag.concurrency_density:.1%})"
                )

        if me_res.is_multi_endpoint and timing_dim:
            timing_dim.details["is_multi_endpoint"] = True
            timing_dim.details["unique_endpoints"] = me_res.unique_endpoints
            timing_dim.evidence_lines.extend(me_res.evidence)

        verdict = Verdict(
            finding_id=finding_id,
            verdict=verdict_level,
            confidence=round(composite_confidence, 3),
            trial_count=trial_count,
            success_rate=round(success_rate, 4),
            ci_95_lower=round(ci_lo, 4),
            ci_95_upper=round(ci_hi, 4),
            p_value=round(p_value, 6),
            invariant_violated=invariant_violated,
            invariant_violations=violations,
            dimensions=dimensions,
            severity_hint=severity,
            tool_source=session.tool_source,
            is_multi_endpoint=me_res.is_multi_endpoint,
        )

        # Run IEEE S&P 2025 Concurrency Defect Classification
        classification = ConcurrencyAnomalyClassifier().classify(session, verdict)
        verdict.concurrency_defect_class = classification.anomaly_type.value
        verdict.isolation_level_implication = classification.isolation_level_implication
        verdict.remediation_guidance = classification.remediation_guidance

        if self.verbose:
            self._print_verdict(verdict)

        if verdict_level == VerdictLevel.UNCERTAIN and self.agent is not None:
            if self.verbose:
                console.print("[dim cyan]Invoking agent for deeper research...[/dim cyan]")
            try:
                from race_proof.agent.self_improve import SelfImprovementEngine
                improve = SelfImprovementEngine(agent=self.agent, auto_research=True)
                improve.process_verdict(verdict, context=str(session.metadata))
            except Exception as exc:
                if self.verbose:
                    console.print(f"[yellow]Agent enhancement failed: {exc}[/yellow]")

        return verdict

    def analyse_trials(self, sessions: list[RaceSession]) -> Verdict:
        """Run analysis across multiple trial sessions for multi-run statistics."""
        if not sessions:
            raise ValueError("No sessions provided for multi-trial analysis")

        representative = sessions[0]
        single_verdict = self.analyse(representative)

        from race_proof.analysis.statistics import StatisticsEngine
        multi_stats = StatisticsEngine().analyse_trials(sessions)

        updated_dims = [
            d for d in single_verdict.dimensions
            if d.dimension != AnalysisDimension.STATISTICS
        ]
        updated_dims.append(multi_stats)

        composite = self._compute_composite_confidence(updated_dims)
        verdict_level = self._determine_verdict(
            anomaly_count=sum(1 for d in updated_dims if d.anomaly_detected),
            composite_confidence=composite,
            has_invariant_violation=bool(single_verdict.invariant_violations),
            has_stats_significance=multi_stats.anomaly_detected,
        )

        return Verdict(
            finding_id=single_verdict.finding_id,
            verdict=verdict_level,
            confidence=round(composite, 3),
            trial_count=len(sessions),
            success_rate=round(multi_stats.details.get("success_rate", 0.0), 4),
            ci_95_lower=round(multi_stats.details.get("ci_95_lower", 0.0), 4),
            ci_95_upper=round(multi_stats.details.get("ci_95_upper", 1.0), 4),
            p_value=round(multi_stats.details.get("p_value", 1.0), 6),
            invariant_violated=single_verdict.invariant_violated,
            invariant_violations=single_verdict.invariant_violations,
            dimensions=updated_dims,
            severity_hint=single_verdict.severity_hint,
            tool_source=single_verdict.tool_source,
        )

    def _compute_composite_confidence(self, dimensions: list[DimensionResult]) -> float:
        total_weight = 0.0
        weighted_sum = 0.0
        for dim in dimensions:
            weight = DIMENSION_WEIGHTS.get(dim.dimension, 0.1)
            if dim.anomaly_detected:
                weighted_sum += weight * dim.confidence
            total_weight += weight
        if total_weight == 0:
            return 0.0
        return min(0.99, weighted_sum / total_weight)

    def _determine_verdict(
        self,
        anomaly_count: int,
        composite_confidence: float,
        has_invariant_violation: bool,
        has_stats_significance: bool,
    ) -> VerdictLevel:
        if has_invariant_violation and (anomaly_count >= 2 or composite_confidence >= 0.5):
            return VerdictLevel.CONFIRMED

        if anomaly_count >= 3 and composite_confidence >= 0.70:
            return VerdictLevel.CONFIRMED

        if anomaly_count == 0 or composite_confidence < 0.1:
            return VerdictLevel.NOISE

        return VerdictLevel.UNCERTAIN

    def _determine_severity(
        self,
        violations: list[InvariantViolation],
        anomaly_count: int,
        confidence: float,
    ) -> str:
        if violations:
            levels = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
            best = max(violations, key=lambda v: levels.get(v.severity, 0))
            return best.severity
        if confidence >= 0.7 and anomaly_count >= 3:
            return "MEDIUM"
        if confidence >= 0.5:
            return "LOW"
        return "UNKNOWN"

    def _print_verdict(self, verdict: Verdict) -> None:
        colors = {
            VerdictLevel.CONFIRMED: "bold red",
            VerdictLevel.UNCERTAIN: "bold yellow",
            VerdictLevel.NOISE: "bold green",
        }
        icons = {
            VerdictLevel.CONFIRMED: "🔴 CONFIRMED",
            VerdictLevel.UNCERTAIN: "🟡 UNCERTAIN",
            VerdictLevel.NOISE: "🟢 NOISE",
        }
        color = colors[verdict.verdict]
        icon = icons[verdict.verdict]

        lines = [
            f"[{color}]{icon}[/{color}]",
            f"Confidence: {verdict.confidence:.1%}  |  "
            f"Success rate: {verdict.success_rate:.1%}  |  "
            f"Severity: {verdict.severity_hint}",
        ]
        if verdict.invariant_violated:
            lines.append(f"Invariant violated: [red]{verdict.invariant_violated}[/red]")
        if verdict.invariant_violations:
            for v in verdict.invariant_violations[:2]:
                lines.append(f"  ↳ [{v.severity}] {v.evidence[:100]}")
        if verdict.concurrency_defect_class:
            lines.append(f"Defect Class: [bold cyan]{verdict.concurrency_defect_class}[/bold cyan] [dim]({verdict.isolation_level_implication})[/dim]")
        if verdict.remediation_guidance and verdict.is_confirmed:
            lines.append(f"Remediation: [green]{verdict.remediation_guidance}[/green]")

        console.print(
            Panel(
                "\n".join(lines),
                title=f"[bold]VERDICT — {verdict.finding_id}[/bold]",
                border_style="red" if verdict.is_confirmed else "yellow" if verdict.verdict == VerdictLevel.UNCERTAIN else "green",
                box=box.DOUBLE,
            )
        )
