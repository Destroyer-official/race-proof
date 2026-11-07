"""RaceProof — autonomous self-improving AI agent layer.

The agent uses the local Qwen GGUF (via llama-cpp-python, same binary
already installed for Destroyer AI) as its reasoning brain. It can:

- Research the web (DuckDuckGo, free, no API key)
- Execute sandboxed Python scripts
- Write new invariant detection rules based on research
- Update its own knowledge base with learned patterns
- Self-improve: after uncertain verdicts it researches similar CVEs and
  generates better detection rules for next time
"""
from race_proof.agent.tools import ToolRegistry, get_default_tools
from race_proof.agent.agent import RaceProofAgent
from race_proof.agent.autonomous import AutonomousAgentEngine
from race_proof.agent.synthesizer import ToolSynthesizer
from race_proof.agent.sandbox import HardenedSandbox, SignedToolRegistry
from race_proof.agent.guard import PromptGuard

__all__ = [
    "RaceProofAgent",
    "AutonomousAgentEngine",
    "ToolSynthesizer",
    "HardenedSandbox",
    "SignedToolRegistry",
    "PromptGuard",
    "ToolRegistry",
    "get_default_tools",
]

