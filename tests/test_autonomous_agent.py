"""Unit and integration tests for Autonomous Agent Engine & Tool Synthesizer."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from race_proof.agent.autonomous import AutonomousAgentEngine
from race_proof.agent.synthesizer import ToolSynthesizer
from race_proof.agent.tools import ToolRegistry, get_default_tools, CUSTOM_TOOLS_DIR
from race_proof.agent.sandbox import SignedToolRegistry


def test_tool_synthesizer_success(tmp_path):
    tool_name = "test_credit_delta_checker"
    desc = "Calculates delta between pre and post credits"
    code = """
def run(pre=0, post=0, **kwargs):
    delta = post - pre
    return f"DELTA={delta}"
"""
    schema = {
        "type": "object",
        "properties": {
            "pre": {"type": "number"},
            "post": {"type": "number"},
        },
    }
    test_kwargs = {"pre": 100, "post": 50}

    registry = ToolRegistry()
    res = ToolSynthesizer.synthesize_tool(
        name=tool_name,
        description=desc,
        parameters_schema=schema,
        python_code=code,
        test_kwargs=test_kwargs,
        registry=registry,
    )

    assert res.success is True
    assert len(res.signature) == 64
    assert "DELTA=-50" in res.test_output

    # Verify registered tool works in registry
    tool = registry.get(tool_name)
    assert tool is not None
    out = tool.call(pre=500, post=200)
    assert "DELTA=-300" in out


def test_tool_synthesizer_rejects_insecure_code():
    tool_name = "malicious_network_tool"
    desc = "Attempts network egress"
    code = """
import socket
def run(**kwargs):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(("8.8.8.8", 53))
    return "PWNED"
"""
    schema = {"type": "object", "properties": {}}
    res = ToolSynthesizer.synthesize_tool(
        name=tool_name,
        description=desc,
        parameters_schema=schema,
        python_code=code,
    )

    assert res.success is False
    assert "error" in (res.error or "").lower()


def test_autonomous_agent_goal_execution():
    from race_proof.agent.brain import LLMBrain
    mock_brain = LLMBrain(model_path=Path("mock_test.gguf"))
    engine = AutonomousAgentEngine(brain=mock_brain, verbose=False)
    goal = "Synthesize and test a custom token validator tool"
    context = {"tool_name": "validate_session_nonce"}

    res = engine.execute_goal(goal, context=context)

    assert res.goal == goal
    assert res.success is True
    assert len(res.steps_executed) >= 2
    assert len(res.new_tools_created) >= 1
    assert "validate_session_nonce" in res.new_tools_created
    assert len(res.final_assessment) > 0


def test_autonomous_agent_memory_persistence():
    from race_proof.agent.brain import LLMBrain
    mock_brain = LLMBrain(model_path=Path("mock_test.gguf"))
    engine = AutonomousAgentEngine(brain=mock_brain, verbose=False)
    stats = engine.get_memory_stats()

    assert "goals_executed" in stats
    assert stats["goals_executed"] >= 1
    assert stats["successful_goals"] >= 1


def test_synthesize_reproduction_poc():
    poc_script = ToolSynthesizer.synthesize_reproduction_poc(
        target_url="https://api.test/redeem",
        method="POST",
        headers={"Authorization": "Bearer test_tok"},
        body='{"coupon": "SAVE50"}',
        concurrency=15,
        protocol="h2",
    )

    assert "asyncio.Barrier(CONCURRENCY)" in poc_script
    assert "https://api.test/redeem" in poc_script
    assert "SAVE50" in poc_script
    assert "CONCURRENCY = 15" in poc_script

