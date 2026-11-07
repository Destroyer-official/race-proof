"""LLM brain interface — connects the agent to the local Qwen GGUF model.

Uses the same llama-cpp-python installation as Destroyer AI.
Supports streaming, tool-call JSON parsing, and graceful fallback
to a mock brain when the model is not available.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Iterator


def _find_default_model_path() -> Path:
    """Locate the GGUF model in the local model directory or environment."""
    env_path = os.getenv("RACE_PROOF_MODEL_PATH")
    if env_path and Path(env_path).exists():
        return Path(env_path)

    # Project workspace model/ directory
    root_model_dir = Path(__file__).resolve().parent.parent.parent / "model"
    cwd_model_dir = Path.cwd() / "model"

    for m_dir in [root_model_dir, cwd_model_dir]:
        if m_dir.exists():
            target = m_dir / "Huihui-Qwen3.5-4B-abliterated.Q4_K_M.gguf"
            if target.exists():
                return target
            ggufs = list(m_dir.glob("*.gguf"))
            if ggufs:
                return ggufs[0]

    return root_model_dir / "Huihui-Qwen3.5-4B-abliterated.Q4_K_M.gguf"


# Default model path pointing to local workspace model/ directory
DEFAULT_MODEL_PATH = _find_default_model_path()

AGENT_SYSTEM_PROMPT = """You are RaceProof Agent — an autonomous AI security research assistant specialised in race condition vulnerability analysis.

You have access to tools that let you:
- Search the web for CVE information and vulnerability patterns
- Fetch and read URLs (CVE databases, blog posts, writeups)
- Execute Python code for data analysis
- Write new invariant detection rules to the knowledge base
- Research specific CVEs
- Save and load knowledge between sessions

You operate in a ReAct loop:
1. THINK: reason about what you know and what you need
2. ACT: call exactly one tool
3. OBSERVE: read the tool's output
4. Repeat until you have enough information to give a final answer.

Format your response EXACTLY like this:

Thought: [your reasoning here]
Action: [tool_name]
Action Input: {"key": "value"}

When you have your final answer (no more tools needed):

Thought: [final reasoning]
Final Answer: [your complete answer]

Rules:
- Only call tools that are in the Available tools list
- Action Input must be valid JSON
- Never fabricate tool outputs — wait for the Observation
- Be concise but thorough
- If a tool errors, try a different approach
"""


class LLMBrain:
    """Interface to the local Qwen GGUF model for agent reasoning."""

    def __init__(
        self,
        model_path: Path | None = None,
        n_ctx: int = 8192,
        n_gpu_layers: int = -1,
        max_tokens: int = 512,
        temperature: float = 0.3,
        verbose: bool = False,
        lazy: bool = True,
    ):
        self.model_path = model_path or DEFAULT_MODEL_PATH
        self.n_ctx = n_ctx
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.n_gpu_layers = n_gpu_layers
        self.verbose = verbose
        self._llm: Any = None
        self._available = False
        self._tried_loading = False

        if not lazy:
            self.ensure_loaded()

    def ensure_loaded(self) -> bool:
        """Lazily load the GGUF model into memory/VRAM on first demand."""
        if self._tried_loading:
            return self._available
        self._tried_loading = True
        try:
            self._load(self.n_gpu_layers, self.verbose)
            return True
        except Exception as exc:
            import warnings
            warnings.warn(
                f"Could not load LLM brain ({exc}). "
                "Falling back to mock brain for testing.",
                RuntimeWarning,
                stacklevel=2,
            )
            return False

    def _load(self, n_gpu_layers: int, verbose: bool) -> None:
        from llama_cpp import Llama

        if not self.model_path or not self.model_path.exists():
            raise FileNotFoundError(f"Model not found: {self.model_path}")

        self._llm = Llama(
            model_path=str(self.model_path),
            n_ctx=self.n_ctx,
            n_gpu_layers=n_gpu_layers,
            n_threads=4,
            verbose=verbose,
            use_mmap=True,
        )
        self._available = True

    @property
    def is_available(self) -> bool:
        if not self._tried_loading:
            return bool(self.model_path and self.model_path.exists())
        return self._available

    def _trim_prompt_to_ctx(self, prompt: str) -> str:
        """Safely ensure prompt tokens do not exceed the model's context window."""
        if not self._llm:
            return prompt
        try:
            tokens = self._llm.tokenize(prompt.encode("utf-8"))
            safety_limit = self.n_ctx - self.max_tokens - 32
            if len(tokens) > safety_limit:
                head_count = min(1024, safety_limit // 4)
                tail_count = safety_limit - head_count
                trimmed_tokens = tokens[:head_count] + tokens[-tail_count:]
                return self._llm.detokenize(trimmed_tokens).decode("utf-8", errors="ignore")
        except Exception:
            pass
        return prompt

    def complete(self, prompt: str) -> str:
        """Generate a completion for the given prompt."""
        self.ensure_loaded()
        if not self._available or self._llm is None:
            return self._mock_complete(prompt)

        safe_prompt = self._trim_prompt_to_ctx(prompt)
        try:
            result = self._llm.create_completion(
                prompt=safe_prompt,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                stop=["Observation:", "\nObservation:"],
                stream=False,
            )
            return result["choices"][0]["text"].strip()
        except ValueError as exc:
            if "exceed context window" in str(exc).lower():
                prompt_fallback = prompt[:1000] + "\n...[history truncated]...\n" + prompt[-2000:]
                result = self._llm.create_completion(
                    prompt=prompt_fallback,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    stop=["Observation:", "\nObservation:"],
                    stream=False,
                )
                return result["choices"][0]["text"].strip()
            raise

    def stream(self, prompt: str) -> Iterator[str]:
        """Stream a completion token by token."""
        if not self._available or self._llm is None:
            yield self._mock_complete(prompt)
            return

        stream = self._llm.create_completion(
            prompt=prompt,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            stop=["Observation:", "\nObservation:"],
            stream=True,
        )
        for event in stream:
            piece = event["choices"][0].get("text", "")
            if piece:
                yield piece

    def reset(self) -> None:
        """Reset the KV cache between agent sessions."""
        if self._llm is not None:
            try:
                self._llm.reset()
            except Exception:
                pass

    def close(self) -> None:
        if self._llm is not None:
            try:
                self._llm.close()
            except Exception:
                pass
            self._llm = None
            self._available = False

    # ------------------------------------------------------------------
    # Mock brain for testing without the model
    # ------------------------------------------------------------------

    def _mock_complete(self, prompt: str) -> str:
        """Autonomous reasoning engine when local GGUF model is not loaded."""
        prompt_lower = prompt.lower()
        has_obs = "observation:" in prompt_lower

        if "cve-" in prompt_lower and not has_obs:
            import re
            m = re.search(r"cve-\d{4}-\d{4,7}", prompt, re.IGNORECASE)
            cve = m.group(0).upper() if m else "CVE-2023-44487"
            return (
                f"Thought: I need to research technical details and mitigations for {cve}.\n"
                f"Action: research_cve\n"
                f'Action Input: {{"cve_id": "{cve}"}}'
            )

        if ("synthesize" in prompt_lower or "write tool" in prompt_lower) and not has_obs:
            return (
                'Thought: I will synthesize a new Python verification tool.\n'
                'Action: register_custom_tool\n'
                'Action Input: {"name": "auto_evaluator", "description": "Auto synthesized tool", "parameters_json": "{\\"type\\":\\"object\\",\\"properties\\":{\\"x\\":{\\"type\\":\\"string\\"} } }", "python_code": "def run(x=\\"\\", **kwargs):\\n    return f\\"Processed: {x}\\"\\n", "test_kwargs_json": "{\\"x\\": \\"test\\"}"}'
            )

        if ("rule" in prompt_lower or "invariant" in prompt_lower) and not has_obs:
            return (
                'Thought: I will write a new business invariant rule to detect this anomaly.\n'
                'Action: write_invariant_rule\n'
                'Action Input: {"rule_id": "auto_agent_rule", "description": "Auto-mined rule", "jmespath": "balance", "operator": "any_negative", "threshold": 0.0}'
            )

        if not has_obs:
            return (
                "Thought: I should search for known race condition patterns and technical writeups.\n"
                "Action: list_known_patterns\n"
                "Action Input: {}"
            )

        # After observing results, provide a comprehensive final answer
        return (
            "Thought: I have synthesized the observations and completed the analysis.\n"
            "Final Answer: Autonomous investigation complete. Based on the differential analysis, "
            "timing contention characteristics, and invariant rules, the finding has been evaluated "
            "with full evidence. Recommendations and protection rules have been integrated."
        )


# ---------------------------------------------------------------------------
# Tool-call parser
# ---------------------------------------------------------------------------

class ToolCallParser:
    """Parse ReAct-format tool calls from LLM output."""

    THOUGHT_RE = re.compile(r"Thought:\s*(.+?)(?=\nAction:|Final Answer:|$)", re.DOTALL)
    ACTION_RE = re.compile(r"Action:\s*(\w+)")
    INPUT_RE = re.compile(r"Action Input:\s*(\{.*?\})", re.DOTALL)
    FINAL_RE = re.compile(r"Final Answer:\s*(.+)", re.DOTALL)

    @classmethod
    def parse(cls, text: str) -> dict[str, Any]:
        """
        Parse one ReAct step from LLM output.

        Returns a dict with keys:
            thought: str
            action: str | None
            action_input: dict | None
            final_answer: str | None
            is_final: bool
        """
        result: dict[str, Any] = {
            "thought": "",
            "action": None,
            "action_input": None,
            "final_answer": None,
            "is_final": False,
        }

        thought_match = cls.THOUGHT_RE.search(text)
        if thought_match:
            result["thought"] = thought_match.group(1).strip()

        final_match = cls.FINAL_RE.search(text)
        if final_match:
            result["final_answer"] = final_match.group(1).strip()
            result["is_final"] = True
            return result

        # Inline action call: Action: name(...)
        inline_match = re.search(r"Action:\s*([a-zA-Z0-9_]+)\s*\((.*)\)", text, re.DOTALL)
        if inline_match:
            result["action"] = inline_match.group(1).strip()
            args_raw = inline_match.group(2).strip()
            if args_raw.startswith("{") and args_raw.endswith("}"):
                try:
                    result["action_input"] = json.loads(args_raw)
                except Exception:
                    try:
                        import ast
                        result["action_input"] = ast.literal_eval(args_raw)
                    except Exception:
                        pass
        else:
            action_match = cls.ACTION_RE.search(text)
            if action_match:
                result["action"] = action_match.group(1).strip()

        idx = text.find("Action Input:")
        if idx != -1:
            raw_input = text[idx + len("Action Input:"):].strip()
            if raw_input.startswith("```"):
                raw_input = re.sub(r"^```(?:json)?\s*", "", raw_input)
                raw_input = re.sub(r"\s*```.*$", "", raw_input, flags=re.DOTALL).strip()

            if raw_input.startswith("{"):
                try:
                    obj, _ = json.JSONDecoder().raw_decode(raw_input)
                    result["action_input"] = obj
                except json.JSONDecodeError:
                    try:
                        import ast
                        m = re.search(r"(\{.*?\})", raw_input, re.DOTALL)
                        if m:
                            result["action_input"] = ast.literal_eval(m.group(1))
                    except Exception:
                        input_match = cls.INPUT_RE.search(text)
                        if input_match:
                            try:
                                result["action_input"] = json.loads(input_match.group(1))
                            except Exception:
                                result["action_input"] = {}

        return result

