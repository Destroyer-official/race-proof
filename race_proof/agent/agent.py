"""RaceProofAgent — the main autonomous ReAct agent loop.

The agent is invoked after the deterministic engine produces an UNCERTAIN
verdict. It researches the finding, generates new invariant rules, and
produces an enhanced verdict with supporting evidence.

It is also invocable directly for standalone web research tasks.
"""
from __future__ import annotations

import time
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich import box

from race_proof.agent.brain import LLMBrain, ToolCallParser
from race_proof.agent.tools import ToolRegistry, get_default_tools
from race_proof.models import Verdict, VerdictLevel

console = Console(highlight=False)


class RaceProofAgent:
    """
    Autonomous ReAct agent that improves race condition verdicts through
    web research, code execution, and self-generated invariant rules.
    """

    MAX_STEPS = 12          # Hard cap on ReAct iterations
    STEP_TIMEOUT_S = 60     # Max seconds per tool call

    def __init__(
        self,
        brain: LLMBrain | None = None,
        tools: ToolRegistry | None = None,
        verbose: bool = True,
    ):
        self.brain = brain or LLMBrain()
        self.tools = tools or get_default_tools()
        self.verbose = verbose
        self._trajectory: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enhance_verdict(self, verdict: Verdict, context: str = "") -> dict[str, Any]:
        """
        Given an existing oracle verdict, run the agent to:
        1. Research known patterns matching the endpoint/context
        2. Generate new invariant rules
        3. Return an enhanced verdict dict with agent findings appended

        This is the primary entry-point from the main oracle pipeline.
        """
        task = self._build_verdict_task(verdict, context)
        result = self.run(task)

        enhancement = {
            "agent_invoked": True,
            "agent_conclusion": result.get("final_answer", ""),
            "agent_steps": len(result.get("trajectory", [])),
            "agent_new_rules": result.get("new_rules_written", []),
            "agent_research": result.get("research_summary", ""),
        }
        return enhancement

    def research(self, question: str) -> str:
        """
        Run the agent on an arbitrary research question.
        Returns the final answer string.
        """
        result = self.run(question)
        return result.get("final_answer", "No answer produced.")

    def run(self, task: str) -> dict[str, Any]:
        """
        Execute the full ReAct loop for a given task.

        Returns a dict with:
            final_answer: str
            trajectory: list of step dicts
            new_rules_written: list of rule IDs
            research_summary: str
        """
        self._trajectory = []
        new_rules_written: list[str] = []
        research_lines: list[str] = []

        if self.verbose:
            console.print(
                Panel(
                    f"[dim]{task[:200]}...[/dim]" if len(task) > 200 else f"[dim]{task}[/dim]",
                    title="[bold cyan]RACE ORACLE AGENT — TASK[/bold cyan]",
                    border_style="cyan",
                    box=box.ROUNDED,
                )
            )

        # Build the initial prompt
        system_block = self._build_system_prompt()
        conversation = f"{system_block}\n\nTask: {task}\n\n"

        for step in range(self.MAX_STEPS):
            if self.verbose:
                console.print(f"[dim cyan]Agent step {step + 1}/{self.MAX_STEPS}...[/dim cyan]")

            # Generate next step
            start = time.perf_counter()
            raw_output = self.brain.complete(conversation)
            elapsed = time.perf_counter() - start

            parsed = ToolCallParser.parse(raw_output)
            self._trajectory.append({
                "step": step + 1,
                "thought": parsed["thought"],
                "action": parsed["action"],
                "action_input": parsed["action_input"],
                "elapsed_s": round(elapsed, 2),
            })

            if self.verbose and parsed["thought"]:
                console.print(f"  [yellow]Thought:[/yellow] {parsed['thought'][:150]}")

            # Final answer?
            if parsed["is_final"]:
                answer = parsed["final_answer"] or ""
                if self.verbose:
                    console.print(
                        Panel(
                            answer,
                            title="[bold green]AGENT FINAL ANSWER[/bold green]",
                            border_style="green",
                            box=box.ROUNDED,
                        )
                    )
                return {
                    "final_answer": answer,
                    "trajectory": self._trajectory,
                    "new_rules_written": new_rules_written,
                    "research_summary": "\n".join(research_lines),
                }

            # Execute the action
            action_name = parsed.get("action")
            action_input = parsed.get("action_input") or {}

            if not action_name:
                observation = "ERROR: No action specified. Please specify an Action."
            else:
                tool = self.tools.get(action_name)
                if tool is None:
                    observation = (
                        f"ERROR: Unknown tool '{action_name}'. "
                        f"Available: {[t.name for t in self.tools.all_tools()]}"
                    )
                else:
                    if self.verbose:
                        console.print(f"  [cyan]Action:[/cyan] {action_name}({action_input})")
                    try:
                        observation = tool.call(**action_input)
                        # Track side effects
                        if action_name == "write_invariant_rule":
                            rule_id = action_input.get("rule_id", "unknown")
                            new_rules_written.append(rule_id)
                        if action_name in ("web_search", "fetch_url", "research_cve"):
                            research_lines.append(f"[{action_name}] {observation[:100]}...")
                    except Exception as exc:
                        observation = f"Tool error: {type(exc).__name__}: {exc}"

            if self.verbose:
                console.print(
                    f"  [green]Observation:[/green] {str(observation)[:200]}"
                    + ("..." if len(str(observation)) > 200 else "")
                )

            # Append to conversation
            conversation += (
                f"Thought: {parsed['thought']}\n"
                f"Action: {action_name}\n"
                f"Action Input: {parsed.get('action_input', {})}\n"
                f"Observation: {str(observation)[:1500]}\n\n"
            )

            self._trajectory[-1]["observation"] = str(observation)[:500]

        # Exceeded max steps
        fallback = (
            "Agent reached maximum steps without a conclusive answer. "
            "Review the trajectory for partial findings."
        )
        if self.verbose:
            console.print("[yellow]Agent reached max steps.[/yellow]")

        return {
            "final_answer": fallback,
            "trajectory": self._trajectory,
            "new_rules_written": new_rules_written,
            "research_summary": "\n".join(research_lines),
        }

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        from race_proof.agent.brain import AGENT_SYSTEM_PROMPT
        tool_block = self.tools.schema_block()
        return f"{AGENT_SYSTEM_PROMPT}\n\n{tool_block}"

    def _build_verdict_task(self, verdict: Verdict, context: str) -> str:
        lines = [
            f"I have an UNCERTAIN race condition verdict that needs deeper investigation.",
            f"",
            f"Verdict details:",
            f"  - Finding ID: {verdict.finding_id}",
            f"  - Verdict: {verdict.verdict.value}",
            f"  - Confidence: {verdict.confidence:.1%}",
            f"  - Trial count: {verdict.trial_count}",
            f"  - Success rate: {verdict.success_rate:.1%}",
            f"  - Tool source: {verdict.tool_source}",
            f"  - Invariant violated: {verdict.invariant_violated or 'None detected'}",
            f"",
        ]
        if context:
            lines.extend([f"Additional context:", f"  {context}", ""])
        lines.extend([
            "Please:",
            "1. Research web for known race condition patterns matching this context",
            "2. If you find relevant CVEs or patterns, write new invariant rules",
            "3. Provide a final assessment: is this likely a real vulnerability or noise?",
            "4. Explain what additional invariant rules would confirm it next time",
        ])
        return "\n".join(lines)

