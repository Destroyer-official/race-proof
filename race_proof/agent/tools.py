"""Tool definitions for the RaceProof agent.

Each tool is a callable with a name, description, and JSON schema for
its arguments. The agent's ReAct loop selects tools by name and passes
structured JSON arguments.

All tools are SAFE BY DEFAULT:
- Web search uses only DuckDuckGo (no API key, no credentials)
- Code execution runs in a restricted namespace with a timeout
- File writes are limited to the RaceProof data directory
"""
from __future__ import annotations

import json
import textwrap
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Tool:
    """A single callable tool available to the agent."""
    name: str
    description: str
    parameters: dict[str, Any]           # JSON Schema of args
    fn: Callable[..., str]               # Always returns a string (agent observes strings)
    examples: list[str] = field(default_factory=list)

    def call(self, **kwargs: Any) -> str:
        import inspect
        try:
            sig = inspect.signature(self.fn)
            has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
            if has_var_kw:
                return self.fn(**kwargs)
            valid_args = {k: v for k, v in kwargs.items() if k in sig.parameters}
            if not valid_args and len(sig.parameters) == 1 and kwargs:
                param_name = next(iter(sig.parameters.keys()))
                valid_args = {param_name: next(iter(kwargs.values()))}
            return self.fn(**valid_args)
        except Exception as exc:
            return f"ERROR in tool '{self.name}': {type(exc).__name__}: {exc}"

    def schema_str(self) -> str:
        """Return a compact schema string for the agent's system prompt."""
        params = ", ".join(
            f"{k}: {v.get('type', 'any')}"
            for k, v in self.parameters.get("properties", {}).items()
        )
        return f"  {self.name}({params})\n    {self.description}"


class ToolRegistry:
    """Container for all tools available to the agent."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def schema_block(self) -> str:
        lines = ["Available tools:"]
        for t in self._tools.values():
            lines.append(t.schema_str())
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _web_search(query: str, max_results: int = 5) -> str:
    """Search the web using DuckDuckGo (via ddgs). No API key required."""
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS

        results = []
        ddgs_client = DDGS()
        try:
            raw_results = list(ddgs_client.text(query, max_results=max_results))
        except TypeError:
            raw_results = list(ddgs_client.text(keywords=query, max_results=max_results))

        for r in raw_results:
            results.append(
                f"Title: {r.get('title', '')}\n"
                f"URL: {r.get('href', '')}\n"
                f"Snippet: {r.get('body', '')[:300]}\n"
            )
        if not results:
            return "No results found."
        return "\n---\n".join(results)
    except ImportError:
        return (
            "ERROR: 'ddgs' is not installed. "
            "Run: pip install ddgs"
        )
    except Exception as exc:
        return f"Search failed: {exc}"


def _fetch_url(url: str, max_chars: int = 3000) -> str:
    """Fetch and extract text from a URL using httpx, requests, or urllib fallback."""
    import re
    text = ""
    content_type = ""
    headers = {"User-Agent": "RaceProof/2.0 (Security Concurrency Research)"}

    # Try httpx
    try:
        import httpx
        with httpx.Client(timeout=15, follow_redirects=True, headers=headers) as client:
            resp = client.get(url)
            content_type = resp.headers.get("content-type", "")
            text = resp.text
    except Exception:
        # Fallback to requests
        try:
            import requests
            resp = requests.get(url, timeout=15, headers=headers)
            content_type = resp.headers.get("content-type", "")
            text = resp.text
        except Exception:
            # Fallback to urllib.request
            try:
                import urllib.request
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=15) as u_resp:
                    content_type = u_resp.headers.get("content-type", "")
                    text = u_resp.read().decode("utf-8", errors="replace")
            except Exception as exc:
                return f"Fetch failed for {url}: {exc}"

    if "json" in content_type:
        return text[:max_chars]

    # Clean HTML markup to plain text
    try:
        from lxml import etree
        tree = etree.fromstring(text.encode("utf-8", errors="replace"), etree.HTMLParser())
        plain = " ".join(tree.itertext())
        return re.sub(r'\s+', ' ', plain).strip()[:max_chars]
    except Exception:
        plain = re.sub(r'<[^>]+>', ' ', text)
        return re.sub(r'\s+', ' ', plain).strip()[:max_chars]


def _run_python(code: str, timeout: int = 5) -> str:
    """
    Execute a Python code snippet in a hardened subprocess sandbox.
    Enforces CPU timeout (5s default), memory limits, and blocks network socket connections.
    """
    from race_proof.agent.sandbox import HardenedSandbox
    result = HardenedSandbox.run_python(code, timeout_sec=float(timeout))
    if not result.success:
        return f"ERROR: {result.error}\nOutput:\n{result.output}"
    return result.output.strip() if result.output.strip() else "(no output)"


def _write_invariant_rule(
    rule_id: str,
    description: str,
    jmespath: str,
    operator: str,
    threshold: float,
    severity: str = "HIGH",
    applies_to: str = "race_responses",
) -> str:
    """
    Write a new invariant rule to the learned rules file.

    Rules are appended to ~/.race-proof/learned_invariants.yaml and
    automatically loaded on next run.
    """
    import yaml
    from pathlib import Path

    rules_dir = Path.home() / ".race-proof"
    rules_dir.mkdir(exist_ok=True)
    rules_file = rules_dir / "learned_invariants.yaml"

    new_rule = {
        "id": rule_id,
        "description": description,
        "jmespath": jmespath,
        "operator": operator,
        "threshold": threshold,
        "severity": severity,
        "applies_to": applies_to,
    }

    # Load existing rules
    existing: list[dict] = []
    if rules_file.exists():
        try:
            data = yaml.safe_load(rules_file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                existing = data
        except Exception:
            existing = []

    # Avoid duplicates
    ids = {r.get("id") for r in existing}
    if rule_id in ids:
        return f"Rule '{rule_id}' already exists. Skipping."

    existing.append(new_rule)
    rules_file.write_text(yaml.dump(existing, default_flow_style=False), encoding="utf-8")
    return f"Rule '{rule_id}' written to {rules_file}"


def _research_cve(cve_id: str) -> str:
    """Research a specific CVE via web search and NVD."""
    query = f"{cve_id} race condition vulnerability technical details"
    search_results = _web_search(query, max_results=3)
    # Also try to fetch NVD
    nvd_url = f"https://services.nvd.nist.gov/rest/json/cves/2.0?cveId={cve_id}"
    try:
        nvd_data = _fetch_url(nvd_url, max_chars=2000)
    except Exception as exc:
        nvd_data = f"NVD fetch failed: {exc}"
    return f"=== Web Search ===\n{search_results}\n\n=== NVD Data ===\n{nvd_data}"


def _list_known_patterns() -> str:
    """List all known race condition patterns from the knowledge base."""
    patterns = {
        "double_spend": "Payment/wallet APIs where concurrent requests both debit the same funds",
        "coupon_replay": "Discount/coupon systems where concurrent redemptions both succeed",
        "rate_limit_bypass": "API rate limiters bypassed by concurrent requests hitting before counter increments",
        "account_creation": "Registration endpoints where concurrent requests create duplicate accounts",
        "file_toctou": "Time-of-check/time-of-use: file permission checks before operations",
        "session_fixation": "Session token reuse when concurrent requests invalidate/create simultaneously",
        "inventory_oversell": "Stock/inventory systems where concurrent purchases exceed available quantity",
        "privilege_escalation": "Role assignment endpoints where concurrent requests elevate privileges",
        "otp_bypass": "OTP/2FA validation where concurrent requests exhaust retry windows",
        "withdrawal_bypass": "Banking: concurrent withdrawal requests both pass balance checks",
    }
    lines = ["Known race condition patterns:"]
    for name, desc in patterns.items():
        lines.append(f"  {name}: {desc}")
    return "\n".join(lines)


def _save_to_knowledge_base(key: str, content: str) -> str:
    """Save researched knowledge to the persistent knowledge base."""
    import yaml
    from pathlib import Path

    kb_dir = Path.home() / ".race-proof"
    kb_dir.mkdir(exist_ok=True)
    kb_file = kb_dir / "knowledge_base.yaml"

    kb: dict = {}
    if kb_file.exists():
        try:
            kb = yaml.safe_load(kb_file.read_text(encoding="utf-8")) or {}
        except Exception:
            kb = {}

    kb[key] = {"content": content, "saved_at": _utc_now_iso()}
    kb_file.write_text(yaml.dump(kb, default_flow_style=False), encoding="utf-8")
    return f"Saved to knowledge base under key '{key}' ({len(content)} chars)"


def _load_from_knowledge_base(key: str) -> str:
    """Load previously researched knowledge from the persistent knowledge base."""
    from pathlib import Path
    import yaml

    kb_file = Path.home() / ".race-proof" / "knowledge_base.yaml"
    if not kb_file.exists():
        return "Knowledge base is empty."
    try:
        kb = yaml.safe_load(kb_file.read_text(encoding="utf-8")) or {}
        entry = kb.get(key)
        if entry is None:
            keys = list(kb.keys())
            return f"Key '{key}' not found. Available keys: {keys}"
        if isinstance(entry, dict):
            return f"[saved at {entry.get('saved_at', 'unknown')}]\n{entry.get('content', '')}"
        return str(entry)
    except Exception as exc:
        return f"Knowledge base read error: {exc}"


def _verify_rule_syntax(rule_yaml: str, sample_json: str = "{}") -> str:
    """Validate that a rule parses and runs against a sample JSON body."""
    import yaml
    from race_proof.models import InvariantRule, RaceResponse, RaceSession
    from race_proof.analysis.invariants import InvariantChecker
    try:
        data = yaml.safe_load(rule_yaml)
        if isinstance(data, list):
            data = data[0]
        rule = InvariantRule(**data)
        resp = RaceResponse(status_code=200, headers={"Content-Type": "application/json"}, body=sample_json)
        checker = InvariantChecker(rules=[rule], load_builtins=False)
        dummy_session = RaceSession(id="test", tool_source="test", baseline=resp, race_responses=[resp, resp])
        checker.analyse(dummy_session)
        return f"SUCCESS: Rule '{rule.id}' is syntactically valid and executable."
    except Exception as exc:
        return f"SYNTAX ERROR in rule: {exc}"


def _generate_poc_script(url: str, method: str = "POST", headers_json: str = "{}", payload: str = "", count: int = 10) -> str:
    """Generate an asynchronous Python reproduction PoC script."""
    import json
    try:
        h = json.loads(headers_json) if headers_json else {}
    except Exception:
        h = {}
    from race_proof.models import RaceRequest, RaceResponse, RaceSession, Verdict, VerdictLevel
    from race_proof.evidence.poc_generator import PocGenerator
    req = RaceRequest(method=method, url=url, headers=h, body=payload)
    resp = RaceResponse(status_code=200, request=req)
    session = RaceSession(id="poc", tool_source="poc", baseline=resp, race_responses=[resp]*count)
    verdict = Verdict(finding_id="poc_gen", verdict=VerdictLevel.CONFIRMED, confidence=0.9, trial_count=count, success_rate=1.0, ci_95_lower=0.5, ci_95_upper=1.0, p_value=0.001)
    return PocGenerator.generate(session, verdict)


# ---------------------------------------------------------------------------
# Dynamic Tool Synthesis & Persistence
# ---------------------------------------------------------------------------

_CURRENT_REGISTRY: ToolRegistry | None = None
CUSTOM_TOOLS_DIR = Path.home() / ".race-proof" / "custom_tools"


def _compile_and_build_callable(name: str, python_code: str) -> Callable[..., str]:
    allowed_modules = {
        "json", "re", "math", "statistics", "datetime", "collections",
        "itertools", "heapq", "difflib", "hashlib", "urllib", "base64"
    }
    real_import = __import__

    def _safe_import(mod_name: str, *args: Any, **kwargs: Any) -> Any:
        root = mod_name.split(".")[0]
        if root not in allowed_modules:
            raise ImportError(f"Importing '{mod_name}' is restricted in sandbox")
        return real_import(mod_name, *args, **kwargs)

    allowed_builtins = {
        "print": print,
        "len": len, "range": range, "enumerate": enumerate,
        "zip": zip, "map": map, "filter": filter,
        "list": list, "dict": dict, "set": set, "tuple": tuple,
        "str": str, "int": int, "float": float, "bool": bool,
        "min": min, "max": max, "sum": sum, "abs": abs, "round": round,
        "sorted": sorted, "reversed": reversed,
        "isinstance": isinstance, "issubclass": issubclass,
        "hasattr": hasattr, "getattr": getattr,
        "repr": repr, "type": type,
        "True": True, "False": False, "None": None,
        "__import__": _safe_import,
    }

    safe_globals: dict[str, Any] = {
        "__builtins__": allowed_builtins,
        "json": __import__("json"),
        "re": __import__("re"),
        "math": __import__("math"),
        "statistics": __import__("statistics"),
        "base64": __import__("base64"),
        "hashlib": __import__("hashlib"),
    }
    execution_env: dict[str, Any] = dict(safe_globals)
    compiled = compile(python_code, f"<custom_tool_{name}>", "exec")
    exec(compiled, execution_env, execution_env)

    if "run" not in execution_env or not callable(execution_env["run"]):
        raise ValueError("Custom tool python_code must define a callable 'def run(**kwargs)'")

    def _tool_runner(**kwargs: Any) -> str:
        res = execution_env["run"](**kwargs)
        if isinstance(res, (dict, list)):
            return json.dumps(res, indent=2, default=str)
        return str(res)

    return _tool_runner


def _register_custom_tool(
    name: str,
    description: str,
    parameters_json: str,
    python_code: str,
    test_kwargs_json: str = "{}",
) -> str:
    """Register and persist a new custom tool created by the agent."""
    if not name.isidentifier():
        return f"ERROR: '{name}' is not a valid Python identifier."

    try:
        if isinstance(parameters_json, str):
            raw_params = json.loads(parameters_json)
        else:
            raw_params = parameters_json

        if "type" not in raw_params:
            props = {}
            for k, v in raw_params.items():
                props[k] = {"type": v if isinstance(v, str) else "string"}
            schema = {"type": "object", "properties": props}
        else:
            schema = raw_params
    except Exception as exc:
        return f"ERROR parsing parameters_json: {exc}"

    try:
        runner = _compile_and_build_callable(name, python_code)
    except Exception as exc:
        return f"ERROR compiling custom tool code: {exc}"

    try:
        test_kwargs = json.loads(test_kwargs_json) if test_kwargs_json else {}
        test_output = runner(**test_kwargs)
    except Exception as exc:
        return f"ERROR during test execution with test_kwargs: {exc}"

    CUSTOM_TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    code_path = CUSTOM_TOOLS_DIR / f"{name}.py"
    code_path.write_text(python_code, encoding="utf-8")

    from race_proof.agent.sandbox import SignedToolRegistry
    sig_reg = SignedToolRegistry()
    digest = sig_reg.register_tool(name, python_code)

    manifest_path = CUSTOM_TOOLS_DIR / "manifest.json"
    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}

    manifest[name] = {
        "name": name,
        "description": description,
        "parameters": schema,
        "created_at": _utc_now_iso(),
        "code_file": f"{name}.py",
        "sha256": digest,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    new_tool = Tool(
        name=name,
        description=description,
        parameters=schema,
        fn=runner,
    )
    if _CURRENT_REGISTRY is not None:
        _CURRENT_REGISTRY.register(new_tool)

    return (
        f"SUCCESS: Custom tool '{name}' successfully compiled, tested, persisted, and registered into active registry!\n"
        f"Test output: {str(test_output)[:200]}"
    )


def _load_persisted_custom_tools(registry: ToolRegistry) -> int:
    manifest_path = CUSTOM_TOOLS_DIR / "manifest.json"
    if not manifest_path.exists():
        return 0
    from race_proof.agent.sandbox import SignedToolRegistry
    sig_reg = SignedToolRegistry()
    loaded = 0
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for name, meta in manifest.items():
            code_file = CUSTOM_TOOLS_DIR / meta.get("code_file", f"{name}.py")
            if code_file.exists():
                code = code_file.read_text(encoding="utf-8")
                # Integrity check: verify signature
                if not sig_reg.verify_tool(name, code):
                    continue
                runner = _compile_and_build_callable(name, code)
                tool = Tool(
                    name=name,
                    description=meta.get("description", ""),
                    parameters=meta.get("parameters", {"type": "object", "properties": {}}),
                    fn=runner,
                )
                registry.register(tool)
                loaded += 1
    except Exception:
        pass
    return loaded


# ---------------------------------------------------------------------------
# Default tool registry factory
# ---------------------------------------------------------------------------

def get_default_tools() -> ToolRegistry:
    """Build and return the default tool registry."""
    global _CURRENT_REGISTRY
    registry = ToolRegistry()
    _CURRENT_REGISTRY = registry

    registry.register(Tool(
        name="web_search",
        description="Search the web via DuckDuckGo. Free, no API key. Use for CVE research, technique lookups, vulnerability patterns.",
        parameters={"type": "object", "properties": {
            "query": {"type": "string", "description": "Search query"},
            "max_results": {"type": "integer", "description": "Max results (1-10)", "default": 5},
        }, "required": ["query"]},
        fn=_web_search,
        examples=["web_search(query='race condition payment API CVE 2024')"],
    ))

    registry.register(Tool(
        name="fetch_url",
        description="Fetch and extract text from a URL. Use to read CVE details, blog posts, writeups.",
        parameters={"type": "object", "properties": {
            "url": {"type": "string"},
            "max_chars": {"type": "integer", "default": 3000},
        }, "required": ["url"]},
        fn=_fetch_url,
    ))

    registry.register(Tool(
        name="run_python",
        description="Execute a Python code snippet in a safe sandbox. Use for data analysis, pattern matching, stats.",
        parameters={"type": "object", "properties": {
            "code": {"type": "string", "description": "Python code to execute"},
        }, "required": ["code"]},
        fn=_run_python,
    ))

    registry.register(Tool(
        name="write_invariant_rule",
        description="Write a new learned invariant rule to the persistent rules file. Use this to encode a vulnerability pattern you just researched.",
        parameters={"type": "object", "properties": {
            "rule_id": {"type": "string"},
            "description": {"type": "string"},
            "jmespath": {"type": "string"},
            "operator": {"type": "string", "enum": ["count_gt", "count_eq", "any_negative", "lt", "lte", "gt", "gte", "eq", "neq", "contains", "not_contains"]},
            "threshold": {"type": "number"},
            "severity": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"], "default": "HIGH"},
            "applies_to": {"type": "string", "default": "race_responses"},
        }, "required": ["rule_id", "description", "jmespath", "operator", "threshold"]},
        fn=_write_invariant_rule,
    ))

    registry.register(Tool(
        name="research_cve",
        description="Research a specific CVE identifier — fetches web results and NVD data.",
        parameters={"type": "object", "properties": {
            "cve_id": {"type": "string", "description": "e.g. CVE-2024-12345"},
        }, "required": ["cve_id"]},
        fn=_research_cve,
    ))

    registry.register(Tool(
        name="list_known_patterns",
        description="List all built-in known race condition vulnerability patterns.",
        parameters={"type": "object", "properties": {}},
        fn=lambda: _list_known_patterns(),
    ))

    registry.register(Tool(
        name="save_knowledge",
        description="Save researched knowledge to the persistent knowledge base for future use.",
        parameters={"type": "object", "properties": {
            "key": {"type": "string", "description": "Unique key for the knowledge entry"},
            "content": {"type": "string", "description": "Knowledge content to save"},
        }, "required": ["key", "content"]},
        fn=_save_to_knowledge_base,
    ))

    registry.register(Tool(
        name="load_knowledge",
        description="Load previously saved knowledge from the persistent knowledge base.",
        parameters={"type": "object", "properties": {
            "key": {"type": "string"},
        }, "required": ["key"]},
        fn=_load_from_knowledge_base,
    ))

    registry.register(Tool(
        name="verify_rule_syntax",
        description="Validate a candidate YAML invariant rule against dummy JSON data before committing.",
        parameters={"type": "object", "properties": {
            "rule_yaml": {"type": "string", "description": "YAML rule definition"},
            "sample_json": {"type": "string", "description": "Sample JSON string to test against", "default": "{}"},
        }, "required": ["rule_yaml"]},
        fn=_verify_rule_syntax,
    ))

    registry.register(Tool(
        name="generate_poc_script",
        description="Generate an asynchronous Python reproduction PoC script for a verified race endpoint.",
        parameters={"type": "object", "properties": {
            "url": {"type": "string", "description": "Target endpoint URL"},
            "method": {"type": "string", "description": "HTTP method", "default": "POST"},
            "headers_json": {"type": "string", "description": "JSON string of headers", "default": "{}"},
            "payload": {"type": "string", "description": "Request body payload", "default": ""},
            "count": {"type": "integer", "description": "Concurrent request count", "default": 10},
        }, "required": ["url"]},
        fn=_generate_poc_script,
    ))

    registry.register(Tool(
        name="register_custom_tool",
        description="Autonomously synthesize, test, persist, and register a brand new tool into the agent runtime. The tool python_code must define 'def run(**kwargs) -> str'.",
        parameters={"type": "object", "properties": {
            "name": {"type": "string", "description": "Valid Python identifier for the tool name"},
            "description": {"type": "string", "description": "Clear explanation of what the tool does"},
            "parameters_json": {"type": "string", "description": "JSON Schema object string describing arguments, e.g. '{\"type\":\"object\",\"properties\":{\"token\":{\"type\":\"string\"}}}'"},
            "python_code": {"type": "string", "description": "Python source code defining 'def run(**kwargs) -> str'"},
            "test_kwargs_json": {"type": "string", "description": "JSON string of test kwargs to test execution in sandbox before registering", "default": "{}"},
        }, "required": ["name", "description", "parameters_json", "python_code"]},
        fn=_register_custom_tool,
    ))

    # Restore any previously synthesized custom tools
    _load_persisted_custom_tools(registry)

    return registry

    return registry

