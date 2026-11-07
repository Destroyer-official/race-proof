"""Unit and Integration tests for RaceProof Interactive Terminal UI (TUI)."""
from __future__ import annotations

import asyncio
from pathlib import Path
import pytest

from textual.widgets import Button, DataTable, Input, RichLog, Static, TabbedContent
from race_proof.tui.app import RaceProofTUI


def test_tui_mount_and_default_state():
    """Verify TUI initializes cleanly with all tabs, tables, and headers."""
    async def _test():
        app = RaceProofTUI()
        async with app.run_test(size=(140, 50)) as pilot:
            assert "RACE ORACLE" in app.TITLE

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
            btn_bench = app.query_one("#btn-dash-bench", Button)
            btn_bench.press()
            await pilot.pause()
            assert tabs.active == "tab-bench"

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

            # Wait for thread worker to finish
            await app.workers.wait_for_complete()
            await pilot.pause()

            banner = app.query_one("#verify-banner", Static)
            assert "CONFIRMED" in str(banner.render())

    asyncio.run(_test())


def test_tui_formal_proof_execution():
    """Verify running mathematical TLA+ state exploration from TUI."""
    async def _test():
        app = RaceProofTUI()
        async with app.run_test(size=(140, 50)) as pilot:
            app.action_switch_tab("tab-prove")

            btn_proof = app.query_one("#btn-run-proof", Button)
            btn_proof.press()

            await app.workers.wait_for_complete()
            await pilot.pause()

            banner = app.query_one("#prove-banner", Static)
            banner_text = str(banner.render())
            assert "PROVEN VULNERABLE" in banner_text

            trace_table = app.query_one("#prove-trace-table", DataTable)
            assert trace_table.row_count > 0


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

    asyncio.run(_test())


def test_tui_benchmark_execution():
    """Verify running benchmark suite and updating KPI tiles."""
    async def _test():
        app = RaceProofTUI()
        async with app.run_test(size=(140, 50)) as pilot:
            app.action_switch_tab("tab-bench")

            btn_bench = app.query_one("#btn-run-bench", Button)
            btn_bench.press()

            # Allow background benchmark worker to process scenarios
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert app.last_benchmark_scorecard is not None
            assert len(app.last_benchmark_scorecard.results) >= 25
            summary = app.last_benchmark_scorecard.compute_summary()
            assert summary["precision"] >= 0.95
            assert summary["recall"] == 1.0

    asyncio.run(_test())
