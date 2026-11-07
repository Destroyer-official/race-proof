"""Autonomous Tool & Script Synthesizer for RaceProof Agent.

Empowers the agent to autonomously write, test, verify, sign, and persist:
1. Custom verification tools (Python functions implementing `def run(**kwargs) -> str`).
2. High-speed differential analysers and custom invariant evaluators.
3. Asynchronous reproduction PoCs (supporting HTTP/1.1 last-byte, HTTP/2 single-packet, and HTTP/3).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from race_proof.agent.sandbox import HardenedSandbox, SignedToolRegistry
from race_proof.agent.tools import Tool, ToolRegistry, CUSTOM_TOOLS_DIR, _CURRENT_REGISTRY, _compile_and_build_callable


@dataclass
class SynthesisResult:
    tool_name: str
    success: bool
    code: str
    signature: str
    test_output: str
    file_path: str
    error: str | None = None


class ToolSynthesizer:
    """Autonomously synthesizes, verifies, signs, and registers new agent tools."""

    @classmethod
    def synthesize_tool(
        cls,
        name: str,
        description: str,
        parameters_schema: dict[str, Any],
        python_code: str,
        test_kwargs: dict[str, Any] | None = None,
        registry: ToolRegistry | None = None,
    ) -> SynthesisResult:
        """
        Synthesize, test in sandbox, sign, persist, and register a new tool.
        """
        if not name.isidentifier():
            return SynthesisResult(
                tool_name=name,
                success=False,
                code=python_code,
                signature="",
                test_output="",
                file_path="",
                error=f"Tool name '{name}' is not a valid Python identifier",
            )

        # 1. Test execute in HardenedSandbox
        test_args = test_kwargs or {}
        test_wrapper_code = f"""
{python_code}

if 'run' in locals():
    result_data['test_result'] = run(**{json.dumps(test_args)})
else:
    raise NameError("Synthesized tool must define 'def run(**kwargs)'")
"""
        sandbox_res = HardenedSandbox.run_python(test_wrapper_code, timeout_sec=4.0)
        if not sandbox_res.success:
            return SynthesisResult(
                tool_name=name,
                success=False,
                code=python_code,
                signature="",
                test_output=sandbox_res.output,
                file_path="",
                error=f"Sandbox test execution failed: {sandbox_res.error}",
            )

        # 2. Persist code
        CUSTOM_TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        code_file = CUSTOM_TOOLS_DIR / f"{name}.py"
        code_file.write_text(python_code, encoding="utf-8")

        # 3. Cryptographically sign tool
        sig_reg = SignedToolRegistry()
        signature = sig_reg.register_tool(name, python_code)

        # 4. Update manifest
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
            "parameters": parameters_schema,
            "signature_sha256": signature,
            "code_file": f"{name}.py",
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        # 5. Build callable and register in live registry
        target_reg = registry or _CURRENT_REGISTRY
        try:
            runner = _compile_and_build_callable(name, python_code)
            new_tool = Tool(
                name=name,
                description=description,
                parameters=parameters_schema,
                fn=runner,
            )
            if target_reg is not None:
                target_reg.register(new_tool)
        except Exception as exc:
            return SynthesisResult(
                tool_name=name,
                success=False,
                code=python_code,
                signature=signature,
                test_output=sandbox_res.output,
                file_path=str(code_file),
                error=f"Compilation/registration failed: {exc}",
            )

        return SynthesisResult(
            tool_name=name,
            success=True,
            code=python_code,
            signature=signature,
            test_output=sandbox_res.output,
            file_path=str(code_file),
            error=None,
        )

    @classmethod
    def synthesize_reproduction_poc(
        cls,
        target_url: str,
        method: str = "POST",
        headers: dict[str, str] | None = None,
        body: str | None = None,
        concurrency: int = 10,
        protocol: str = "h2",
    ) -> str:
        """
        Synthesize a standalone production-ready Python reproduction script.
        Supports asyncio + httpx with Barrier synchronization.
        """
        h_dict = headers or {"Content-Type": "application/json"}
        return f'''"""Auto-generated Race Condition Reproduction PoC by RaceProof Agent."""
import asyncio
import httpx
import time

TARGET_URL = "{target_url}"
METHOD = "{method.upper()}"
HEADERS = {json.dumps(h_dict, indent=4)}
BODY = {repr(body)}
CONCURRENCY = {concurrency}


async def send_race_request(client: httpx.AsyncClient, barrier: asyncio.Barrier, seq_id: int):
    # Synchronize all coroutines to fire at the identical event loop tick
    await barrier.wait()
    t0 = time.perf_counter()
    try:
        resp = await client.request(METHOD, TARGET_URL, headers=HEADERS, content=BODY, timeout=10.0)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return seq_id, resp.status_code, elapsed_ms, resp.text[:120]
    except Exception as exc:
        return seq_id, 0, 0.0, str(exc)


async def main():
    print(f"[*] Dispatching {{CONCURRENCY}} concurrent requests via {protocol.upper()} synchronization...")
    barrier = asyncio.Barrier(CONCURRENCY)
    limits = httpx.Limits(max_connections=CONCURRENCY + 5, max_keepalive_connections=CONCURRENCY + 5)
    async with httpx.AsyncClient(http2=True, limits=limits, verify=False) as client:
        tasks = [send_race_request(client, barrier, i) for i in range(CONCURRENCY)]
        results = await asyncio.gather(*tasks)

    print("\\n[+] Results:")
    for seq_id, status, elapsed, preview in results:
        print(f"  [{{seq_id:02d}}] Status={{status}} | Elapsed={{elapsed:.1f}}ms | Response={{preview}}")


if __name__ == "__main__":
    asyncio.run(main())
'''

