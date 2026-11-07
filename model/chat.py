"""Destroyer AI - Rich terminal chat for Qwen3.5 GGUF via llama.cpp/Vulkan.

Default mode is fast/non-thinking. Use /think for reasoning mode or
'research <question>' for a longer, offline research-style analysis.

This script is text-only. It does not browse the web or retrieve live sources.
"""

from __future__ import annotations

import gc
import os
import sys
import time
from pathlib import Path
from typing import Any

from rich import box
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

# Add the Vulkan SDK's Bin directory before importing llama_cpp so Windows can
# resolve SDK/runtime DLLs where necessary. The AMD driver remains responsible
# for providing the actual Vulkan physical device.
_DLL_DIRECTORY_HANDLES: list[Any] = []
if os.name == "nt":
    sdk_root = os.environ.get("VULKAN_SDK")
    if sdk_root:
        vulkan_bin = Path(sdk_root) / "Bin"
        if vulkan_bin.is_dir():
            os.environ["PATH"] = str(vulkan_bin) + os.pathsep + os.environ.get("PATH", "")
            try:
                _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(str(vulkan_bin)))
            except (AttributeError, OSError):
                pass

from llama_cpp import Llama  # noqa: E402  (must follow DLL path setup)


# ---------------------------------------------------------------------------
# Hardware/model configuration
# ---------------------------------------------------------------------------
MODEL_PATH = Path(
    r"C:\Users\des\OneDrive\Desktop\clint\Huihui-Qwen3.5-4B-abliterated.Q4_K_M.gguf"
)

# Sensible starting values for a Ryzen 3 3200G + Vega 8 + 16 GB shared RAM.
# Override them in PowerShell with $env:DESTROYER_N_CTX='3072', etc.
N_CTX = int(os.getenv("DESTROYER_N_CTX", "4096"))
N_BATCH = int(os.getenv("DESTROYER_N_BATCH", "256"))
N_UBATCH = int(os.getenv("DESTROYER_N_UBATCH", "128"))
N_THREADS = int(os.getenv("DESTROYER_THREADS", "4"))
N_THREADS_BATCH = int(os.getenv("DESTROYER_THREADS_BATCH", "4"))
N_GPU_LAYERS = int(os.getenv("DESTROYER_GPU_LAYERS", "-1"))
VERBOSE_BACKEND = os.getenv("DESTROYER_VERBOSE", "1").strip().lower() not in {
    "0", "false", "no", "off"
}

FAST_MAX_TOKENS = 320
THINK_MAX_TOKENS = 640
RESEARCH_MAX_TOKENS = 900

IM_START = "<|im_start|>"
IM_END = "<|im_end|>"
THINK_END = "</think>"

console = Console(highlight=False)

SYSTEM_PROMPT = (
    "You are Destroyer AI, a local technical assistant. Be direct, analytical, "
    "and precise. Distinguish established facts from assumptions and uncertainty. "
    "Do not fabricate citations, measurements, tool results, or claims of live "
    "verification. This runtime has no web access unless a separate retrieval "
    "system is explicitly connected. For code and security questions, prefer "
    "reproducible explanations and identify limitations."
)

RESEARCH_INSTRUCTION = (
    "[OFFLINE RESEARCH-STYLE ANALYSIS]\n"
    "Analyze the question carefully and methodically. Structure the final answer "
    "with: (1) objective and scope, (2) established facts, (3) analysis, "
    "(4) uncertainties and missing evidence, and (5) practical conclusions. "
    "Do not claim to have searched the internet, checked current sources, or "
    "verified information externally. Do not invent references. State explicitly "
    "when the available model knowledge may be stale.\n\n"
    "Question: "
)


# ---------------------------------------------------------------------------
# Model initialization
# ---------------------------------------------------------------------------
def make_llama(*, gpu_layers: int) -> Llama: