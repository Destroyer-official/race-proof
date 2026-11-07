"""Unit tests for agent tools: web search, sandbox execution, rules writer, knowledge base."""
import os
import pytest
from race_proof.agent.tools import get_default_tools


def test_agent_tools_registry():
    registry = get_default_tools()
    tool_names = [t.name for t in registry.all_tools()]
    assert "web_search" in tool_names
    assert "run_python" in tool_names
    assert "write_invariant_rule" in tool_names
    assert "research_cve" in tool_names
    assert "save_knowledge" in tool_names
    assert "load_knowledge" in tool_names


def test_agent_sandbox_run_python():
    registry = get_default_tools()
    tool = registry.get("run_python")
    assert tool is not None
    code = """
import math
vals = [10, 20, 30]
print(f"SUM={sum(vals)}, SQRT={math.sqrt(100)}")
"""
    output = tool.call(code=code)
    assert "SUM=60" in output
    assert "SQRT=10.0" in output


def test_agent_knowledge_base():
    registry = get_default_tools()
    save_tool = registry.get("save_knowledge")
    load_tool = registry.get("load_knowledge")
    assert save_tool is not None
    assert load_tool is not None

    res = save_tool.call(key="test_cve_pattern", content="TOCTOU race in balance transfer")
    assert "Saved to knowledge base" in res

    content = load_tool.call(key="test_cve_pattern")
    assert "TOCTOU race in balance transfer" in content


def test_agent_rule_writer():
    registry = get_default_tools()
    writer = registry.get("write_invariant_rule")
    assert writer is not None

    res = writer.call(
        rule_id="test_learned_rule_1",
        description="Prevent balance overdraft",
        jmespath="account.balance",
        operator="any_negative",
        threshold=0,
    )
    assert "written to" in res or "already exists" in res


def test_dynamic_tool_synthesis():
    registry = get_default_tools()
    reg_tool = registry.get("register_custom_tool")
    assert reg_tool is not None

    code = """
import math
from collections import Counter

def run(text: str = "") -> str:
    if not text:
        return "0.0"
    counts = Counter(text)
    total = len(text)
    entropy = -sum((c / total) * math.log2(c / total) for c in counts.values())
    return f"{entropy:.4f}"
"""
    res = reg_tool.call(
        name="calculate_entropy",
        description="Calculates Shannon entropy of a response text.",
        parameters_json='{"type":"object","properties":{"text":{"type":"string"}},"required":["text"]}',
        python_code=code,
        test_kwargs_json='{"text":"hello world"}',
    )
    assert "SUCCESS" in res
    assert "registered into active registry" in res

    # Check that it's now in registry and callable
    custom_tool = registry.get("calculate_entropy")
    assert custom_tool is not None
    output = custom_tool.call(text="aaaa")
    assert float(output) == 0.0

    # Check persistence reload
    fresh_registry = get_default_tools()
    assert fresh_registry.get("calculate_entropy") is not None

    # Cleanup test files
    from pathlib import Path
    custom_dir = Path.home() / ".race-proof" / "custom_tools"
    tool_file = custom_dir / "calculate_entropy.py"
    if tool_file.exists():
        tool_file.unlink()
    manifest_file = custom_dir / "manifest.json"
    if manifest_file.exists():
        try:
            import json
            m = json.loads(manifest_file.read_text(encoding="utf-8"))
            m.pop("calculate_entropy", None)
            manifest_file.write_text(json.dumps(m, indent=2), encoding="utf-8")
        except Exception:
            pass

