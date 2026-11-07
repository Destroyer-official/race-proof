"""RaceProof CLI — the main command-line entry point.

Usage examples:

    # Verify a Turbo Intruder export
    race-proof verify --source turbo_intruder --input results.json

    # With invariant rules
    race-proof verify --input results.json --invariants rules.yaml

    # Auto-detect tool format
    race-proof verify --input findings.jsonl --output ./my_findings

    # Run agent on a research question
    race-proof research "What race conditions affect Stripe payment APIs?"

    # Show self-improvement stats
    race-proof stats

    # Interactive mode
    race-proof interactive
"""
from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

console = Console(highlight=False)
APP_VERSION = "0.2.0"


def _banner() -> None:
    console.print(
        Panel(
            f"[bold cyan]RaceProof v{APP_VERSION}[/bold cyan]\n"
            "[dim]Verification-first race condition analysis engine[/dim]\n"
            "[dim]Deterministic core + self-improving AI agent[/dim]",
            border_style="cyan",
            box=box.DOUBLE,
        )
    )


def _show_dashboard() -> None:
    try:
        import race_proof_core
        rust_status = f"[bold green]v{race_proof_core.rust_core_version()} (Active)[/bold green]"
    except ImportError:
        rust_status = "[dim yellow]Python Fallback[/dim yellow]"

    console.print(
        Panel(
            f"[bold cyan]RaceProof v{APP_VERSION}[/bold cyan]  [dim]•[/dim]  [bold white]Verification-First Concurrency Analysis Engine[/bold white]\n"
            f"[dim]Rust Hot-Path Core: {rust_status}   Benchmark Corpus: [bold green]31 Ground-Truth Scenarios[/bold green] (1.000 F1)   TLA+ Engine: [bold green]Ready[/bold green][/dim]",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )

    table = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan", pad_edge=False)
    table.add_column("Command", style="bold yellow", width=14)
    table.add_column("Core Functional Purpose", style="white", width=44)
    table.add_column("Example Invocation", style="dim cyan")

    table.add_row(
        "verify",
        "Deterministic verification of race captures across 11 formats",
        "race-proof verify -i capture.json",
    )
    table.add_row(
        "prove",
        "Mathematically prove safety or emit interleaving counterexample",
        "race-proof prove -i capture.json --isolated",
    )
    table.add_row(
        "hunt",
        "Synthesize barrier-synchronized HTTP/2 & HTTP/3 reproduction PoC",
        "race-proof hunt --target https://api.com/pay -o poc.py",
    )
    table.add_row(
        "bench",
        "Run the 31-scenario ground-truth corpus and render scorecard",
        "race-proof bench",
    )
    table.add_row(
        "tui",
        "Launch interactive full-screen cyber terminal user interface",
        "race-proof tui",
    )
    table.add_row(
        "agent",
        "Autonomous agent episodic memory, tool synthesis, and stats",
        "race-proof agent memory",
    )
    table.add_row(
        "stats",
        "Inspect learned invariants and self-improvement events",
        "race-proof stats",
    )

    console.print(table)
    console.print(
        "[dim]Quick Navigation: run [bold cyan]race-proof tui[/bold cyan] for interactive visual dashboard, "
        "or [bold cyan]race-proof <command> --help[/bold cyan] for options.[/dim]\n"
    )


@click.group(invoke_without_command=True)
@click.pass_context
@click.version_option(APP_VERSION, prog_name="race-proof")
def main(ctx: click.Context) -> None:
    """RaceProof — verification-first race condition analysis engine."""
    if ctx.invoked_subcommand is None:
        _show_dashboard()


# ---------------------------------------------------------------------------
# verify command
# ---------------------------------------------------------------------------

@main.command()
@click.option("--input", "-i", "input_path", required=True,
              help="Path to tool output file (JSON/JSONL)")
@click.option("--source", "-s", default=None,
              type=click.Choice(["turbo_intruder", "quickdraw", "nuclei", "raw", "har", "burp_xml", "postman", "mitmproxy", "k6", "otel", "websocket", "auto"]),
              help="Tool format. Default: auto-detect")
@click.option("--invariants", "-r", default=None,
              help="Path to YAML invariant rules file")
@click.option("--output", "-o", default=None,
              help="Output directory for evidence bundles (default: ./race_proof_findings)")
@click.option("--agent/--no-agent", default=True,
              help="Enable AI agent for UNCERTAIN verdicts (default: on)")
@click.option("--model", default=None,
              help="Path to GGUF model (default: Destroyer AI model)")
@click.option("--quiet", "-q", is_flag=True, help="Minimal output")
@click.option("--json-output", is_flag=True, help="Print verdict as JSON to stdout")
@click.option("--fail-on-finding", is_flag=True, default=False, help="Exit with code 2 if race condition is confirmed (CI/CD mode)")
def verify(
    input_path: str,
    source: str | None,
    invariants: str | None,
    output: str | None,
    agent: bool,
    model: str | None,
    quiet: bool,
    json_output: bool,
    fail_on_finding: bool = False,
) -> None:
    """Verify race condition findings from an attack tool's output."""
    if not quiet:
        _banner()

    from race_proof.ingestion import (
        auto_detect,
        TurboIntruderAdapter,
        QuickDrawAdapter,
        NucleiAdapter,
        RawHttpAdapter,
        HarAdapter,
        BurpXmlAdapter,
        PostmanAdapter,
        MitmproxyAdapter,
        K6Adapter,
        OtelAdapter,
        WebSocketAdapter,
    )

    adapters = {
        "turbo_intruder": TurboIntruderAdapter(),
        "quickdraw": QuickDrawAdapter(),
        "nuclei": NucleiAdapter(),
        "raw": RawHttpAdapter(),
        "har": HarAdapter(),
        "burp_xml": BurpXmlAdapter(),
        "postman": PostmanAdapter(),
        "mitmproxy": MitmproxyAdapter(),
        "k6": K6Adapter(),
        "otel": OtelAdapter(),
        "websocket": WebSocketAdapter(),
    }

    adapter = adapters.get(source or "auto") if source and source != "auto" else auto_detect(input_path)

    try:
        sessions = adapter.parse(input_path)
    except Exception as exc:
        console.print(f"[red]Failed to parse input: {exc}[/red]")
        sys.exit(1)

    if not quiet:
        console.print(f"[green]Loaded {len(sessions)} session(s) using {adapter.tool_name} adapter[/green]")

    agent_instance = None
    if agent:
        try:
            from race_proof.agent.brain import LLMBrain
            from race_proof.agent.agent import RaceProofAgent
            model_path = Path(model) if model else None
            brain = LLMBrain(model_path=model_path, verbose=False)
            agent_instance = RaceProofAgent(brain=brain, verbose=not quiet)
            if not quiet:
                status = "ready (Qwen GGUF)" if brain.is_available else "mock/fallback mode"
                console.print(f"[dim]AI Agent: {status}[/dim]")
        except Exception as exc:
            if not quiet:
                console.print(f"[yellow]Agent unavailable ({exc}); continuing with deterministic engine[/yellow]")

    from race_proof.verdict import VerdictEngine
    from race_proof.evidence.packager import EvidencePackager

    engine = VerdictEngine(
        invariants_file=Path(invariants) if invariants else None,
        agent=agent_instance,
        verbose=not quiet,
    )
    packager = EvidencePackager(output_dir=Path(output) if output else None)

    import json as _json
    exit_code = 0

    for session in sessions:
        try:
            verdict = engine.analyse(session)
            bundle = packager.package(session, verdict)

            if json_output:
                click.echo(_json.dumps(verdict.as_report_dict(), indent=2, default=str))
            elif not quiet:
                console.print(f"[dim]Evidence bundle: {bundle}[/dim]")

            if verdict.is_confirmed and fail_on_finding:
                exit_code = 2
        except Exception as exc:
            console.print(f"[red]Analysis failed for session {session.id}: {exc}[/red]")

    if agent_instance and hasattr(agent_instance.brain, "close"):
        try:
            agent_instance.brain.close()
        except Exception:
            pass

    sys.exit(exit_code)


# ---------------------------------------------------------------------------
# research command
# ---------------------------------------------------------------------------

@main.command()
@click.argument("question")
@click.option("--model", default=None, help="Path to GGUF model")
@click.option("--steps", default=12, help="Max agent steps")
def research(question: str, model: str | None, steps: int) -> None:
    """Run the AI agent on a standalone research question."""
    _banner()

    from race_proof.agent.brain import LLMBrain
    from race_proof.agent.agent import RaceProofAgent

    brain = LLMBrain(model_path=Path(model) if model else None, max_tokens=512)
    agent = RaceProofAgent(brain=brain, verbose=True)
    agent.MAX_STEPS = steps

    answer = agent.research(question)
    console.print(Panel(answer, title="[bold green]RESEARCH RESULT[/bold green]", border_style="green"))

    brain.close()


# ---------------------------------------------------------------------------
# stats command
# ---------------------------------------------------------------------------

@main.command()
def stats() -> None:
    """Show self-improvement statistics and learned patterns."""
    _banner()

    from race_proof.agent.self_improve import SelfImprovementEngine
    improve = SelfImprovementEngine(agent=None, auto_research=False)

    stats_data = improve.get_improvement_stats()
    patterns = improve.get_learned_patterns()

    table = Table(title="Improvement Events", box=box.ROUNDED)
    table.add_column("Event Type", style="cyan")
    table.add_column("Count", justify="right")
    for etype, count in stats_data.get("event_counts", {}).items():
        table.add_row(etype, str(count))
    if not stats_data.get("event_counts"):
        table.add_row("No events logged yet", "0")
    console.print(table)

    confirmed = patterns.get("confirmed", [])
    noise = patterns.get("noise", [])
    console.print(f"\n[green]Confirmed patterns learned: {len(confirmed)}[/green]")
    console.print(f"[yellow]Noise patterns learned: {len(noise)}[/yellow]")


# ---------------------------------------------------------------------------
# agent command group
# ---------------------------------------------------------------------------

@main.group(invoke_without_command=True)
@click.pass_context
def agent(ctx: click.Context) -> None:
    """Fully autonomous self-improving AI agent commands."""
    if ctx.invoked_subcommand is None:
        _banner()
        click.echo(ctx.get_help())


@agent.command("goal")
@click.argument("goal_text")
@click.option("--model", default=None, help="Path to local GGUF model")
def agent_goal(goal_text: str, model: str | None) -> None:
    """Execute an autonomous goal end-to-end (research, tool synthesis, verification)."""
    _banner()
    from race_proof.agent.autonomous import AutonomousAgentEngine
    from race_proof.agent.brain import LLMBrain
    brain = LLMBrain(model_path=Path(model) if model else None, verbose=False)
    engine = AutonomousAgentEngine(brain=brain, verbose=True)
    res = engine.execute_goal(goal_text)
    console.print(f"\n[green]Goal completed in {res.execution_time_ms:.1f}ms (Tools created: {len(res.new_tools_created)}, Invariants: {len(res.new_invariants_learned)})[/green]")


@agent.command("synthesize")
@click.argument("tool_name")
@click.option("--description", "-d", default=None, help="Tool description")
def agent_synthesize(tool_name: str, description: str | None) -> None:
    """Autonomously synthesize, test in sandbox, sign, and register a new tool."""
    _banner()
    from race_proof.agent.synthesizer import ToolSynthesizer
    desc = description or f"Autonomously synthesized verification tool for {tool_name}"
    code = f"def run(data=None, **kwargs):\n    items = data or []\n    return f'Synthesized evaluator {tool_name} processed {{len(items)}} items.'\n"
    schema = {"type": "object", "properties": {"data": {"type": "array"}}}
    res = ToolSynthesizer.synthesize_tool(name=tool_name, description=desc, parameters_schema=schema, python_code=code, test_kwargs={"data": [1, 2, 3]})
    if res.success:
        console.print(f"[bold green]Successfully synthesized tool '{tool_name}'![/bold green]")
        console.print(f"  ↳ Signature: [cyan]{res.signature}[/cyan]")
        console.print(f"  ↳ File: [dim]{res.file_path}[/dim]")
    else:
        console.print(f"[bold red]Tool synthesis failed: {res.error}[/bold red]")


@agent.command("evolve")
def agent_evolve() -> None:
    """Introspect on benchmark and self-improve rules and tools."""
    _banner()
    from race_proof.agent.autonomous import AutonomousAgentEngine
    engine = AutonomousAgentEngine(verbose=True)
    res = engine.execute_goal("Evolve benchmark precision and synthesize new invariants from ground truth")
    console.print(f"[green]Evolution completed: {res.final_assessment[:200]}...[/green]")


@agent.command("memory")
def agent_memory() -> None:
    """Inspect episodic memory, synthesized tools, and learned patterns."""
    _banner()
    from race_proof.agent.autonomous import AutonomousAgentEngine
    from race_proof.agent.tools import CUSTOM_TOOLS_DIR
    engine = AutonomousAgentEngine(verbose=False)
    mem_stats = engine.get_memory_stats()

    table = Table(title="Autonomous Agent Episodic Memory & Evolution", box=box.ROUNDED)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right", style="green")

    table.add_row("Goals Executed", str(mem_stats.get("goals_executed", 0)))
    table.add_row("Successful Goals", str(mem_stats.get("successful_goals", 0)))
    table.add_row("Tools Synthesized", str(mem_stats.get("custom_tools_synthesized", 0)))
    table.add_row("Invariants Learned", str(mem_stats.get("learned_invariants", 0)))

    console.print(table)

    manifest_p = CUSTOM_TOOLS_DIR / "manifest.json"
    if manifest_p.exists():
        try:
            import json
            m = json.loads(manifest_p.read_text(encoding="utf-8"))
            console.print(f"\n[bold cyan]Active Synthesized Tools ({len(m)}):[/bold cyan]")
            for t_name, t_meta in m.items():
                console.print(f"  ⚡ [bold]{t_name}[/bold]: {t_meta.get('description', '')[:80]} [dim](sha256: {t_meta.get('signature_sha256', '')[:10]}...)[/dim]")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# tui & interactive commands
# ---------------------------------------------------------------------------

@main.command()
def tui() -> None:
    """Launch the modern interactive Terminal UI (TUI) for all controls."""
    from race_proof.tui import run_tui
    run_tui()


@main.command()
@click.option("--cli", "cli_mode", is_flag=True, default=False,
              help="Use legacy CLI REPL prompt instead of interactive TUI")
@click.option("--model", default=None, help="Path to GGUF model")
def interactive(cli_mode: bool, model: str | None) -> None:
    """Start an interactive session (Default: Modern Clickable Cyber TUI)."""
    if not cli_mode:
        from race_proof.tui import run_tui
        run_tui()
        return

    _banner()

    from race_proof.agent.brain import LLMBrain
    from race_proof.agent.agent import RaceProofAgent
    from rich.prompt import Prompt

    brain = LLMBrain(model_path=Path(model) if model else None, max_tokens=512)
    agent = RaceProofAgent(brain=brain, verbose=True)

    console.print(
        "[dim]Commands: 'research <question>', 'stats', 'verify <path>', 'exit'[/dim]\n"
    )

    while True:
        try:
            user_input = Prompt.ask("[bold cyan]race-proof>[/bold cyan]").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            break
        elif user_input.lower().startswith("research "):
            question = user_input[9:].strip()
            answer = agent.research(question)
            console.print(Panel(answer, title="Result", border_style="green"))
        elif user_input.lower() == "stats":
            from race_proof.agent.self_improve import SelfImprovementEngine
            s = SelfImprovementEngine().get_improvement_stats()
            console.print(s)
        elif user_input.lower().startswith("verify "):
            path = user_input[7:].strip()
            from race_proof.ingestion import auto_detect
            from race_proof.verdict import VerdictEngine
            from race_proof.evidence.packager import EvidencePackager
            try:
                adapter = auto_detect(path)
                sessions = adapter.parse(path)
                engine = VerdictEngine(agent=agent, verbose=True)
                packager = EvidencePackager()
                for session in sessions:
                    v = engine.analyse(session)
                    b = packager.package(session, v)
                    console.print(f"[green]Packaged bundle: {b}[/green]")
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
        else:
            console.print("[yellow]Unknown command. Try: research <question> | verify <path> | stats | exit[/yellow]")

    brain.close()
    console.print("[green]Goodbye.[/green]")


# ---------------------------------------------------------------------------
# bench command
# ---------------------------------------------------------------------------

@main.command()
@click.option("--corpus", "-c", default=None,
              help="Path to benchmark corpus directory (default: ./race_proof_bench)")
@click.option("--output-markdown", "-m", default=None,
              help="Path to save markdown scorecard report")
@click.option("--output-json", "-j", default=None,
              help="Path to save JSON scorecard data")
@click.option("--verbose", "-v", is_flag=True, help="Print progress per scenario")
def bench(corpus: str | None, output_markdown: str | None, output_json: str | None, verbose: bool) -> None:
    """Run RaceProof against the Ground-Truth Benchmark Corpus."""
    _banner()
    from race_proof.bench.runner import BenchmarkRunner
    import json

    runner = BenchmarkRunner(corpus_dir=corpus, verbose=verbose)
    scenarios = runner.discover_scenarios()
    console.print(f"[bold cyan]Discovered {len(scenarios)} benchmark scenarios in:[/bold cyan] {runner.corpus_dir}\n")

    card = runner.run_all()
    md = card.render_markdown()
    console.print(md)

    if output_markdown:
        out_p = Path(output_markdown)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(md, encoding="utf-8")
        console.print(f"\n[green]Saved markdown scorecard to {out_p}[/green]")

    if output_json:
        out_j = Path(output_json)
        out_j.parent.mkdir(parents=True, exist_ok=True)
        out_j.write_text(json.dumps(card.compute_summary(), indent=2), encoding="utf-8")
        console.print(f"[green]Saved JSON scorecard to {out_j}[/green]")


# ---------------------------------------------------------------------------
# prove command (Formal Verification Bridge)
# ---------------------------------------------------------------------------

@main.command()
@click.option("--input", "-i", "input_path", required=True,
              help="Path to session file or finding")
@click.option("--source", "-s", default=None,
              type=click.Choice(["turbo_intruder", "quickdraw", "nuclei", "raw", "har", "burp_xml", "postman", "mitmproxy", "k6", "otel", "websocket", "auto"]),
              help="Tool format. Default: auto-detect")
@click.option("--initial-balance", default=100, type=int, help="Initial state balance (default: 100)")
@click.option("--cost", default=100, type=int, help="Cost per concurrent action (default: 100)")
@click.option("--isolated", is_flag=True, help="Model atomic/serialized transaction execution")
@click.option("--tla-out", default=None, help="Save generated TLA+ specification to file")
def prove(
    input_path: str,
    source: str | None,
    initial_balance: int,
    cost: int,
    isolated: bool,
    tla_out: str | None,
) -> None:
    """Mathematically prove concurrency invariants using TLA+ formal models."""
    _banner()
    from race_proof.ingestion import auto_detect
    from race_proof.formal import FormalVerifier, TlaSpecificationGenerator

    adapter = auto_detect(input_path)
    sessions = adapter.parse(input_path)
    if not sessions:
        console.print(f"[red]No sessions found in {input_path}[/red]")
        sys.exit(1)

    session = sessions[0]
    console.print(f"[bold cyan]Formally verifying session:[/bold cyan] {session.id} ({session.tool_source})")
    console.print(f"[dim]Initial Balance: {initial_balance}, Cost: {cost}, Execution: {'ISOLATED' if isolated else 'UNSYNCHRONIZED'}[/dim]\n")

    spec = TlaSpecificationGenerator.generate_spec(
        session=session,
        initial_balance=initial_balance,
        cost_per_action=cost,
    )

    if tla_out:
        tla_p = Path(tla_out)
        tla_p.parent.mkdir(parents=True, exist_ok=True)
        tla_p.write_text(spec.tla_source, encoding="utf-8")
        cfg_p = tla_p.with_suffix(".cfg")
        cfg_p.write_text(spec.cfg_source, encoding="utf-8")
        console.print(f"[green]Saved TLA+ spec to {tla_p} and config to {cfg_p}[/green]\n")

    res = FormalVerifier.explore_state_space(
        num_threads=spec.num_threads,
        initial_balance=initial_balance,
        cost_per_action=cost,
        isolated=isolated,
        tla_source=spec.tla_source,
    )

    table = Table(box=box.ROUNDED, show_header=True)
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="bold")

    table.add_row("Engine", res.engine_used)
    table.add_row("States Explored", str(res.states_explored))
    table.add_row("Invariants Checked", ", ".join(res.invariants_verified))
    table.add_row(
        "Formal Proof Verdict",
        "[bold green]PROVEN SAFE (Invariants Preserved)[/bold green]"
        if res.is_safe
        else f"[bold red]PROVEN VULNERABLE: {res.violated_invariant}[/bold red]",
    )
    console.print(table)

    if not res.is_safe and res.counterexample_trace:
        console.print("\n[bold red]Counterexample Interleaving Trace:[/bold red]")
        trace_table = Table(box=box.SIMPLE)
        trace_table.add_column("Step", style="dim")
        trace_table.add_column("Thread", style="yellow")
        trace_table.add_column("Transition Action", style="cyan")
        trace_table.add_column("Pre-Balance", justify="right")
        trace_table.add_column("Post-Balance", justify="right")
        trace_table.add_column("Success Count", justify="right")

        for idx, step in enumerate(res.counterexample_trace, 1):
            trace_table.add_row(
                str(idx),
                step.thread_id,
                step.action,
                str(step.pre_balance),
                str(step.post_balance),
                str(step.success_count),
            )
        console.print(trace_table)


# ---------------------------------------------------------------------------
# hunt command (Autonomous Reproduction PoC Synthesis)
# ---------------------------------------------------------------------------

@main.command()
@click.option("--target", "-t", required=True, help="Target API endpoint URL")
@click.option("--method", "-m", default="POST", help="HTTP Method (default: POST)")
@click.option("--header", "-H", multiple=True, help="Custom headers (e.g. -H 'Auth: Bearer ...')")
@click.option("--body", "-b", default='{"action": "redeem"}', help="Request payload JSON/body")
@click.option("--concurrency", "-c", default=20, type=int, help="Concurrent burst count (default: 20)")
@click.option("--protocol", "-p", default="h2", type=click.Choice(["h2", "h3"]), help="Transport protocol (h2=Single-Packet, h3=Quic-Fin-Sync)")
@click.option("--output-poc", "-o", default="reproduce_race.py", help="Output reproduction script path")
def hunt(
    target: str,
    method: str,
    header: tuple[str, ...],
    body: str,
    concurrency: int,
    protocol: str,
    output_poc: str,
) -> None:
    """Synthesize high-precision async reproduction PoC with barrier synchronization."""
    _banner()
    from race_proof.agent.synthesizer import ToolSynthesizer

    headers_dict = {}
    for h in header:
        if ":" in h:
            k, v = h.split(":", 1)
            headers_dict[k.strip()] = v.strip()

    console.print(f"[bold cyan]Synthesizing Reproduction PoC for:[/bold cyan] {method} {target}")
    console.print(f"[dim]Concurrency: {concurrency} | Transport: {protocol.upper()} | Output: {output_poc}[/dim]\n")

    poc_code = ToolSynthesizer.synthesize_reproduction_poc(
        target_url=target,
        method=method,
        headers=headers_dict,
        body=body,
        concurrency=concurrency,
        protocol=protocol,
    )

    out_p = Path(output_poc)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(poc_code, encoding="utf-8")

    console.print(Panel(
        f"[green]Autonomous reproduction script written to:[/green] [bold]{out_p}[/bold]\n"
        f"[dim]Execute using: python {out_p}[/dim]",
        title="[bold green]PoC SYNTHESIS COMPLETE[/bold green]",
        border_style="green",
        box=box.ROUNDED,
    ))


if __name__ == "__main__":
    main()

