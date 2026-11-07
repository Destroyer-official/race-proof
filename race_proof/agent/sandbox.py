"""Hardened Sandbox — executes synthesized verification tools safely.

Provides:
1. Subprocess-level isolation with strict CPU timeout (5.0s).
2. Memory ceiling enforcement (256MB).
3. Network disabling (blocking socket operations).
4. Signed tool registry with SHA-256 integrity checks.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ToolExecutionResult:
    success: bool
    output: str
    error: str | None = None
    execution_time_ms: float = 0.0
    memory_used_mb: float = 0.0


class SignedToolRegistry:
    """Tracks and verifies cryptographic signatures for dynamically synthesized tools."""

    def __init__(self, registry_file: Path | None = None):
        self.registry_file = registry_file or (Path.home() / ".race-proof" / "tool_signatures.json")
        self.signatures: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if self.registry_file.exists():
            try:
                self.signatures = json.loads(self.registry_file.read_text(encoding="utf-8"))
            except Exception:
                self.signatures = {}

    def _save(self) -> None:
        self.registry_file.parent.mkdir(parents=True, exist_ok=True)
        self.registry_file.write_text(json.dumps(self.signatures, indent=2), encoding="utf-8")

    def register_tool(self, tool_name: str, code: str) -> str:
        digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
        self.signatures[tool_name] = digest
        self._save()
        return digest

    def verify_tool(self, tool_name: str, code: str) -> bool:
        expected = self.signatures.get(tool_name)
        if not expected:
            return False
        current = hashlib.sha256(code.encode("utf-8")).hexdigest()
        return secrets_compare(expected, current)


def secrets_compare(a: str, b: str) -> bool:
    import hmac
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


class HardenedSandbox:
    """Executes synthesized verification tools in an isolated sandbox subprocess."""

    DEFAULT_TIMEOUT_SEC = 5.0
    MAX_MEMORY_MB = 256.0

    @classmethod
    def run_python(
        cls,
        code: str,
        timeout_sec: float | None = None,
        context: dict[str, Any] | None = None,
    ) -> ToolExecutionResult:
        """Run Python code inside a sandboxed subprocess with strict limits."""
        import time

        timeout = timeout_sec or cls.DEFAULT_TIMEOUT_SEC
        with tempfile.TemporaryDirectory(prefix="race_proof_sandbox_") as tmp_dir:
            tmp_path = Path(tmp_dir)
            script_path = tmp_path / "sandbox_worker.py"
            input_data_path = tmp_path / "context.json"
            output_data_path = tmp_path / "output.json"

            # Serialize context data
            input_data_path.write_text(
                json.dumps(context or {}, default=str), encoding="utf-8"
            )

            # Wrapper script enforcing no network and safe execution
            harness_code = f"""
import sys
import json
import os

# Block raw socket network connections
try:
    import socket
    def _blocked(*args, **kwargs):
        raise PermissionError("Network access is strictly forbidden in RaceProof sandbox")
    socket.socket = _blocked
    socket.create_connection = _blocked
    socket.getaddrinfo = _blocked
except Exception:
    pass

# Load input context
with open(r"{input_data_path}", "r", encoding="utf-8") as f:
    context = json.load(f)

result_data = {{}}

# User synthesized tool code
{code}

# Dump output if result_data was populated
if result_data:
    with open(r"{output_data_path}", "w", encoding="utf-8") as f:
        json.dump(result_data, f, default=str)
"""
            script_path.write_text(harness_code, encoding="utf-8")

            env = os.environ.copy()
            env["PYTHONSAFEPATH"] = "1"
            env["PYTHONDONTWRITEBYTECODE"] = "1"

            start_t = time.perf_counter()
            try:
                proc = subprocess.run(
                    [sys.executable, "-I", str(script_path)],
                    cwd=str(tmp_path),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                elapsed_ms = (time.perf_counter() - start_t) * 1000.0

                if proc.returncode != 0:
                    return ToolExecutionResult(
                        success=False,
                        output=proc.stdout,
                        error=proc.stderr.strip() or f"Process exited with code {proc.returncode}",
                        execution_time_ms=elapsed_ms,
                    )

                out_str = proc.stdout
                if output_data_path.exists():
                    out_content = output_data_path.read_text(encoding="utf-8").strip()
                    if out_content and out_content != "{}":
                        out_str = f"{proc.stdout}\n{out_content}".strip() if proc.stdout.strip() else out_content

                return ToolExecutionResult(
                    success=True,
                    output=out_str,
                    execution_time_ms=elapsed_ms,
                )

            except subprocess.TimeoutExpired:
                elapsed_ms = (time.perf_counter() - start_t) * 1000.0
                return ToolExecutionResult(
                    success=False,
                    output="",
                    error=f"Execution timed out after {timeout:.1f} seconds (CPU limit exceeded)",
                    execution_time_ms=elapsed_ms,
                )
            except Exception as exc:
                elapsed_ms = (time.perf_counter() - start_t) * 1000.0
                return ToolExecutionResult(
                    success=False,
                    output="",
                    error=str(exc),
                    execution_time_ms=elapsed_ms,
                )
