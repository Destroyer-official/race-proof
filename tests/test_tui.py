"""Unit and Integration tests for RaceProof Interactive Terminal UI (TUI)."""
from __future__ import annotations

import asyncio
from pathlib import Path
import pytest

from textual.widgets import Button, DataTable, Input, RichLog, Select, Static, TabbedContent
from race_proof.tui.app import RaceProofTUI


def test_tui_mount_and_default_state():
    """Verify TUI initializes cleanly with all tabs, tables, and headers."""
    async def _test():
        app = RaceProofTUI()
        async with app.run_test(size=(140, 50)) as pilot:
            assert "RaceProof" in app.TITLE

            # Main tabs container
            tabs = app.query_one("#main-tabs", TabbedContent)
            assert tabs.active == "tab-dashboard"

            # Check Benchmark DataTable column initialization
            bench_table = app.query_one("#bench-datatable", DataTable)
            assert len(bench_table.columns) == 8

            # Check Formal Proof trace table initialization
            trace_table = app.query_one("#prove-trace-table", DataTable)
            assert len(trace_table.columns) == 6

    asyncio.run(_test())


def test_tui_tab_navigation():
    """Verify switching between tabs via action_switch_tab."""
    async def _test():
        app = RaceProofTUI()
        async with app.run_test(size=(140, 50)) as pilot:
            tabs = app.query_one("#main-tabs", TabbedContent)

            app.action_switch_tab("tab-verify")
            assert tabs.active == "tab-verify"

            app.action_switch_tab("tab-bench")
            assert tabs.active == "tab-bench"

            app.action_switch_tab("tab-prove")
            assert tabs.active == "tab-prove"

            app.action_switch_tab("tab-hunt")
            assert tabs.active == "tab-hunt"

            app.action_switch_tab("tab-agent")
            assert tabs.active == "tab-agent"

            app.action_switch_tab("tab-logs")
            assert tabs.active == "tab-logs"

            app.action_switch_tab("tab-dashboard")
            assert tabs.active == "tab-dashboard"

    asyncio.run(_test())


def test_tui_dashboard_navigation_buttons():
    """Verify clicking quick-action buttons on Dashboard switches tabs."""
    async def _test():
        app = RaceProofTUI()
        async with app.run_test(size=(140, 50)) as pilot:
            tabs = app.query_one("#main-tabs", TabbedContent)

            btn_verify = app.query_one("#btn-dash-verify", Button)
            btn_verify.press()
            await pilot.pause()
            assert tabs.active == "tab-verify"

            app.action_switch_tab("tab-dashboard")
            await pilot.pause()
            btn_bench = app.query_one("#btn-dash-bench", Button)
            btn_bench.press()
            await pilot.pause()
            assert tabs.active == "tab-bench"

            app.action_switch_tab("tab-dashboard")
            await pilot.pause()
            btn_prove = app.query_one("#btn-dash-prove", Button)
            btn_prove.press()
            await pilot.pause()
            assert tabs.active == "tab-prove"

            app.action_switch_tab("tab-dashboard")
            await pilot.pause()
            btn_hunt = app.query_one("#btn-dash-hunt", Button)
            btn_hunt.press()
            await pilot.pause()
            assert tabs.active == "tab-hunt"

            app.action_switch_tab("tab-dashboard")
            await pilot.pause()
            btn_agent = app.query_one("#btn-dash-agent", Button)
            btn_agent.press()
            await pilot.pause()
            assert tabs.active == "tab-agent"

    asyncio.run(_test())


def test_tui_verify_preset_and_execution():
    """Verify loading a scenario preset and running verification."""
    async def _test():
        app = RaceProofTUI()
        async with app.run_test(size=(140, 50)) as pilot:
            app.action_switch_tab("tab-verify")

            # Manually set input path to fintech scenario
            bench_root = Path(__file__).resolve().parent.parent / "race_proof_bench"
            target_scenario = bench_root / "fintech" / "bench_fin_001.json"
            assert target_scenario.exists()

            inp = app.query_one("#verify-path-input", Input)
            inp.value = str(target_scenario)

            # Trigger verification button
            btn_run = app.query_one("#btn-run-verify", Button)
            btn_run.press()
            await pilot.pause()

            # Wait for thread worker to finish
            await app.workers.wait_for_complete()
            await pilot.pause()

            banner = app.query_one("#verify-banner", Static)
            assert "CONFIRMED" in str(banner.render())

            # Test export SARIF
            btn_sarif = app.query_one("#btn-export-sarif", Button)
            btn_sarif.press()
            await pilot.pause()
            sarif_p = Path.cwd() / "race_proof_findings.sarif"
            assert sarif_p.exists()
            sarif_p.unlink(missing_ok=True)

            # Test clear
            btn_clear = app.query_one("#btn-clear-verify", Button)
            btn_clear.press()
            await pilot.pause()
            assert inp.value == ""

    asyncio.run(_test())


def test_tui_formal_proof_execution():
    """Verify running mathematical TLA+ state exploration from TUI."""
    async def _test():
        app = RaceProofTUI()
        async with app.run_test(size=(140, 50)) as pilot:
            app.action_switch_tab("tab-prove")

            btn_proof = app.query_one("#btn-run-proof", Button)
            btn_proof.press()
            await pilot.pause()

            await app.workers.wait_for_complete()
            await pilot.pause()

            banner = app.query_one("#prove-banner", Static)
            banner_text = str(banner.render())
            assert "PROVEN VULNERABLE" in banner_text

            trace_table = app.query_one("#prove-trace-table", DataTable)
            assert trace_table.row_count > 0

            # Test isolated mode (what user tested in screenshot)
            iso_select = app.query_one("#prove-select-isolation", Select)
            iso_select.value = "isolated"
            btn_proof.press()
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

            banner_text = str(banner.render())
            assert "PROVEN SAFE" in banner_text

            # Test generate TLA+ spec button
            btn_tla = app.query_one("#btn-gen-tla", Button)
            btn_tla.press()
            await pilot.pause()
            assert app.last_tla_spec != ""

    asyncio.run(_test())


def test_tui_poc_hunt_synthesis():
    """Verify generating async reproduction PoC script."""
    async def _test():
        app = RaceProofTUI()
        async with app.run_test(size=(140, 50)) as pilot:
            app.action_switch_tab("tab-hunt")

            btn_hunt = app.query_one("#btn-run-hunt", Button)
            btn_hunt.press()

            await pilot.pause()

            assert "asyncio.Barrier" in app.last_poc_code
            assert "https://api.target.com/v1/coupon/redeem" in app.last_poc_code

            btn_save = app.query_one("#btn-save-hunt", Button)
            btn_save.press()
            await pilot.pause()
            saved_p = Path.cwd() / "reproduce_race_poc.py"
            assert saved_p.exists()
            saved_p.unlink(missing_ok=True)

    asyncio.run(_test())


def test_tui_benchmark_execution():
    """Verify running benchmark suite and updating KPI tiles."""
    async def _test():
        app = RaceProofTUI()
        async with app.run_test(size=(140, 50)) as pilot:
            app.action_switch_tab("tab-bench")

            btn_bench = app.query_one("#btn-run-bench", Button)
            btn_bench.press()
            await pilot.pause()

            # Allow background benchmark worker to process scenarios
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert app.last_benchmark_scorecard is not None
            assert len(app.last_benchmark_scorecard.results) >= 25
            summary = app.last_benchmark_scorecard.compute_summary()
            assert summary["precision"] >= 0.95
            assert summary["recall"] == 1.0

            btn_export = app.query_one("#btn-export-scorecard", Button)
            btn_export.press()
            await pilot.pause()
            card_p = Path.cwd() / "BENCHMARK_SCORECARD.md"
            assert card_p.exists()
            card_p.unlink(missing_ok=True)

    asyncio.run(_test())


def test_tui_benchmark_domain_filter():
    """Verify changing domain filter filters the DataTable rows."""
    async def _test():
        app = RaceProofTUI()
        async with app.run_test(size=(140, 50)) as pilot:
            app.action_switch_tab("tab-bench")
            table = app.query_one("#bench-datatable", DataTable)
            assert table.row_count == 31

            filter_sel = app.query_one("#bench-domain-filter", Select)
            filter_sel.value = "fintech"
            await pilot.pause()

            # Filtered rows should now only be fintech (5 scenarios)
            assert table.row_count == 5

            # Inspect scenario detail
            app._display_bench_scenario_detail("BENCH-FIN-001")
            pane = app.query_one("#bench-detail-pane", Static)
            assert "BENCH-FIN-001" in str(pane.render())

    asyncio.run(_test())


def test_tui_agent_and_logs_tab_interactions():
    """Verify interacting with agent presets and logging telemetry."""
    async def _test():
        app = RaceProofTUI()
        async with app.run_test(size=(140, 50)) as pilot:
            # 1. Agent Tab
            app.action_switch_tab("tab-agent")
            btn_token = app.query_one("#btn-agent-token-tool", Button)
            btn_token.press()
            await pilot.pause()
            goal_inp = app.query_one("#agent-goal-input", Input)
            assert "OAuth refresh" in goal_inp.value

            btn_run_agent = app.query_one("#btn-run-agent", Button)
            btn_run_agent.press()
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            agent_log = app.query_one("#agent-stream-log", RichLog)
            assert len(agent_log.lines) > 0

            # 2. Logs Tab
            app.action_switch_tab("tab-logs")
            btn_tel = app.query_one("#btn-log-telemetry", Button)
            btn_tel.press()
            await pilot.pause()
            sys_log = app.query_one("#system-log-view", RichLog)
            assert len(sys_log.lines) > 0

            btn_clear_logs = app.query_one("#btn-clear-logs", Button)
            btn_clear_logs.press()
            await pilot.pause()
            assert len(sys_log.lines) == 0

    asyncio.run(_test())


