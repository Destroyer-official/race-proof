"""Self-improvement engine.

After each verification run, this module examines the verdict and decides
whether to trigger an agent research session to improve future results.

Self-improvement lifecycle:
1. After a CONFIRMED verdict: save the successful invariant pattern to KB
2. After an UNCERTAIN verdict: trigger agent research to generate better rules
3. After NOISE verdict: log the false-positive pattern to avoid future misfire
4. Periodically: search for new CVEs and update the built-in pattern library
"""
from __future__ import annotations

import json
from datetime import datetime, timezone


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
from pathlib import Path
from typing import Any

import yaml

from race_proof.models import Verdict, VerdictLevel


KB_DIR = Path.home() / ".race-proof"
IMPROVEMENT_LOG = KB_DIR / "improvement_log.jsonl"
PATTERN_LIBRARY = KB_DIR / "learned_patterns.yaml"


class SelfImprovementEngine:
    """
    Coordinates the self-improvement loop.

    After each verdict, decides whether to run the agent for research,
    updates the pattern library, and logs improvement events.
    """

    def __init__(self, agent: Any = None, auto_research: bool = True):
        """
        Parameters
        ----------
        agent:
            RaceProofAgent instance. If None, self-improvement that
            requires LLM research is skipped (deterministic learning only).
        auto_research:
            If True, automatically trigger agent research on UNCERTAIN verdicts.
        """
        self.agent = agent
        self.auto_research = auto_research
        KB_DIR.mkdir(exist_ok=True)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def process_verdict(self, verdict: Verdict, context: str = "") -> dict[str, Any]:
        """
        Process a verdict and perform self-improvement actions.

        Returns a dict describing what actions were taken.
        """
        actions_taken: list[str] = []

        if verdict.verdict == VerdictLevel.CONFIRMED:
            self._learn_from_confirmed(verdict)
            actions_taken.append("Learned confirmed pattern to KB")

        elif verdict.verdict == VerdictLevel.UNCERTAIN:
            if self.auto_research and self.agent is not None:
                enhancement = self.agent.enhance_verdict(verdict, context)
                self._log_improvement(verdict, enhancement)
                actions_taken.append(
                    f"Agent research triggered; "
                    f"{len(enhancement.get('agent_new_rules', []))} new rules written"
                )
            else:
                self._log_uncertain(verdict)
                actions_taken.append("Logged uncertain verdict (agent not available)")

        elif verdict.verdict == VerdictLevel.NOISE:
            self._learn_from_noise(verdict)
            actions_taken.append("Logged false-positive pattern to avoid future misfires")

        return {"actions": actions_taken, "verdict_id": verdict.finding_id}

    # ------------------------------------------------------------------
    # Learning methods
    # ------------------------------------------------------------------

    def _learn_from_confirmed(self, verdict: Verdict) -> None:
        """Save a confirmed pattern to the persistent pattern library."""
        pattern = {
            "finding_id": verdict.finding_id,
            "verdict": verdict.verdict.value,
            "confidence": verdict.confidence,
            "success_rate": verdict.success_rate,
            "invariant_violated": verdict.invariant_violated,
            "severity": verdict.severity_hint,
            "tool_source": verdict.tool_source,
            "confirmed_at": _utc_now_iso(),
        }
        self._append_to_pattern_library("confirmed", pattern)
        self._log_event("CONFIRMED_LEARNED", verdict.finding_id, pattern)

    def _learn_from_noise(self, verdict: Verdict) -> None:
        """Log a noise pattern to reduce future false positives."""
        pattern = {
            "finding_id": verdict.finding_id,
            "success_rate": verdict.success_rate,
            "tool_source": verdict.tool_source,
            "noise_logged_at": _utc_now_iso(),
        }
        self._append_to_pattern_library("noise", pattern)
        self._log_event("NOISE_LEARNED", verdict.finding_id, pattern)

    def _log_uncertain(self, verdict: Verdict) -> None:
        self._log_event("UNCERTAIN_NO_RESEARCH", verdict.finding_id, {
            "confidence": verdict.confidence,
            "success_rate": verdict.success_rate,
        })

    def _log_improvement(self, verdict: Verdict, enhancement: dict[str, Any]) -> None:
        self._log_event("AGENT_RESEARCH_COMPLETE", verdict.finding_id, {
            "new_rules": enhancement.get("agent_new_rules", []),
            "steps": enhancement.get("agent_steps", 0),
            "conclusion": (enhancement.get("agent_conclusion") or "")[:200],
        })

    # ------------------------------------------------------------------
    # Statistics and reporting
    # ------------------------------------------------------------------

    def get_improvement_stats(self) -> dict[str, Any]:
        """Return statistics about the self-improvement history."""
        if not IMPROVEMENT_LOG.exists():
            return {"total_events": 0, "verdicts": {}}

        events: list[dict] = []
        try:
            for line in IMPROVEMENT_LOG.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    events.append(json.loads(line))
        except Exception:
            return {"total_events": 0, "error": "Could not read log"}

        counts: dict[str, int] = {}
        for ev in events:
            etype = ev.get("event_type", "UNKNOWN")
            counts[etype] = counts.get(etype, 0) + 1

        return {
            "total_events": len(events),
            "event_counts": counts,
            "last_event": events[-1] if events else None,
        }

    def get_learned_patterns(self) -> dict[str, list]:
        """Return all patterns learned by the system."""
        if not PATTERN_LIBRARY.exists():
            return {"confirmed": [], "noise": []}
        try:
            return yaml.safe_load(PATTERN_LIBRARY.read_text(encoding="utf-8")) or {}
        except Exception:
            return {"confirmed": [], "noise": []}

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _append_to_pattern_library(self, category: str, pattern: dict) -> None:
        library: dict[str, list] = {}
        if PATTERN_LIBRARY.exists():
            try:
                library = yaml.safe_load(PATTERN_LIBRARY.read_text(encoding="utf-8")) or {}
            except Exception:
                library = {}
        if category not in library:
            library[category] = []
        library[category].append(pattern)
        PATTERN_LIBRARY.write_text(yaml.dump(library, default_flow_style=False), encoding="utf-8")

    def _log_event(self, event_type: str, finding_id: str, data: dict) -> None:
        entry = {
            "event_type": event_type,
            "finding_id": finding_id,
            "timestamp": _utc_now_iso(),
            **data,
        }
        with IMPROVEMENT_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

