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
    return Llama(
        model_path=str(MODEL_PATH),
        n_ctx=N_CTX,
        n_batch=N_BATCH,
        n_ubatch=N_UBATCH,
        n_threads=N_THREADS,
        n_threads_batch=N_THREADS_BATCH,
        n_gpu_layers=gpu_layers,
        use_mmap=True,
        use_mlock=False,
        offload_kqv=True,
        flash_attn=False,  # Keep disabled until this Vulkan build is benchmarked.
        verbose=VERBOSE_BACKEND,
    )


def initialize_model() -> tuple[Llama, str]:
    if not MODEL_PATH.is_file():
        raise FileNotFoundError(f"GGUF model not found: {MODEL_PATH}")

    console.print(
        Panel(
            "[bold cyan]DESTROYER AI[/bold cyan]\n"
            "[dim]Qwen3.5 4B • llama.cpp • Vulkan requested[/dim]\n"
            f"[dim]Context: {N_CTX:,} | Batch: {N_BATCH}/{N_UBATCH} | "
            f"CPU threads: {N_THREADS}/{N_THREADS_BATCH} | GPU layers: {N_GPU_LAYERS}[/dim]",
            title="[bold white]INITIALIZING[/bold white]",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )

    try:
        with console.status("[bold cyan]Loading model with Vulkan GPU offload...", spinner="dots"):
            model = make_llama(gpu_layers=N_GPU_LAYERS)
        console.print(
            "[green]Model loaded. Vulkan offload was requested; check the backend log "
            "for the actual device and offloaded-layer count.[/green]"
        )
        return model, "Vulkan requested"
    except Exception as gpu_error:
        console.print(
            Panel(
                f"[yellow]GPU/Vulkan initialization failed:[/yellow]\n{gpu_error}",
                title="GPU INITIALIZATION FAILURE",
                border_style="yellow",
            )
        )
        retry = Prompt.ask(
            "Retry with CPU-only inference?",
            choices=["y", "n"],
            default="n",
        )
        if retry.lower() != "y":
            raise RuntimeError("Model initialization stopped; GPU initialization failed.") from gpu_error

    with console.status("[bold yellow]Loading CPU-only fallback...", spinner="dots"):
        model = make_llama(gpu_layers=0)
    console.print("[yellow]CPU-only fallback loaded. Expect lower generation speed.[/yellow]")
    return model, "CPU fallback"


# ---------------------------------------------------------------------------
# Chat template and context management
# ---------------------------------------------------------------------------
def build_prompt(messages: list[dict[str, str]], *, thinking: bool) -> str:
    """Render the text-only structure used by the model's published Jinja template.

    The published template uses <think> for reasoning and an empty, closed
    <think> block to disable reasoning. The GGUF should contain a compatible
    Qwen3.5 chat template; this renderer implements its text-only message path.
    """
    parts: list[str] = []
    for message in messages:
        role = message["role"]
        content = message["content"]
        if role == "system":
            parts.append(f"{IM_START}system\n{content}{IM_END}\n")
        elif role in {"user", "assistant"}:
            parts.append(f"{IM_START}{role}\n{content}{IM_END}\n")
        else:
            raise ValueError(f"Unsupported message role in local history: {role}")

    parts.append(f"{IM_START}assistant\n")
    if thinking:
        parts.append("<think>\n")
    else:
        parts.append("<think>\n\n</think>\n\n")
    return "".join(parts)


def count_prompt_tokens(llm: Llama, prompt: str) -> int:
    return len(llm.tokenize(prompt.encode("utf-8"), add_bos=True, special=True))


def fit_history(
    llm: Llama,
    history: list[dict[str, str]],
    *,
    thinking: bool,
    max_new_tokens: int,
) -> str:
    """Drop oldest complete user/assistant turns until the prompt fits."""
    prompt = build_prompt(history, thinking=thinking)
    prompt_budget = N_CTX - max_new_tokens - 64

    while count_prompt_tokens(llm, prompt) > prompt_budget and len(history) > 3:
        # history = [system, user_old, assistant_old, ..., user_current]
        del history[1:3]
        prompt = build_prompt(history, thinking=thinking)

    used = count_prompt_tokens(llm, prompt)
    if used + max_new_tokens + 32 > N_CTX:
        raise ValueError(
            f"The current prompt needs about {used} tokens and the requested "
            f"generation budget is {max_new_tokens}, exceeding n_ctx={N_CTX}. "
            "Shorten the question or increase DESTROYER_N_CTX if RAM permits."
        )
    return prompt


# ---------------------------------------------------------------------------
# Streaming generation and Rich terminal display
# ---------------------------------------------------------------------------
def generation_settings(mode: str) -> dict[str, float | int]:
    if mode == "think":
        # Qwen-family reasoning-style sampling starting point.
        return {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "repeat_penalty": 1.05}
    return {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "repeat_penalty": 1.05}


def generate_stream(
    llm: Llama,
    prompt: str,
    *,
    mode: str,
    max_tokens: int,
) -> tuple[str, dict[str, float | int]]:
    settings = generation_settings("think" if mode in {"think", "research"} else "fast")
    stream = llm(
        prompt,
        max_tokens=max_tokens,
        temperature=float(settings["temperature"]),
        top_p=float(settings["top_p"]),
        top_k=int(settings["top_k"]),
        repeat_penalty=float(settings["repeat_penalty"]),
        stop=[IM_END],
        stream=True,
    )

    thinking_enabled = mode in {"think", "research"}
    answer_started = not thinking_enabled
    pending_thought = ""
    raw_generated: list[str] = []
    visible_parts: list[str] = []
    first_token_at: float | None = None
    started_at = time.perf_counter()
    update_counter = 0

    title = {
        "fast": "[bold green]DESTROYER AI • FAST CHAT[/bold green]",
        "think": "[bold cyan]DESTROYER AI • THINKING[/bold cyan]",
        "research": "[bold magenta]DESTROYER AI • OFFLINE RESEARCH[/bold magenta]",
    }[mode]

    initial_status = (
        "[dim]Reasoning... the final answer will appear after the thinking block.[/dim]"
        if thinking_enabled
        else "[dim]Waiting for the first response token...[/dim]"
    )
    with Live(
        Panel(initial_status, title=title, border_style="green", box=box.ROUNDED),
        console=console,
        refresh_per_second=12,
        transient=False,
    ) as live:
        for event in stream:
            piece = event["choices"][0].get("text", "")
            if not piece:
                continue

            if first_token_at is None:
                first_token_at = time.perf_counter()
            raw_generated.append(piece)

            if not answer_started:
                pending_thought += piece
                marker_position = pending_thought.find(THINK_END)
                if marker_position < 0:
                    continue
                piece = pending_thought[marker_position + len(THINK_END):]
                pending_thought = ""
                answer_started = True
                piece = piece.lstrip("\r\n")

            if piece:
                visible_parts.append(piece)
                update_counter += 1
                if update_counter % 3 == 0:
                    live.update(
                        Panel(
                            Markdown("".join(visible_parts) or "[dim]Generating...[/dim]"),
                            title=title,
                            border_style="green",
                            box=box.ROUNDED,
                        )
                    )

        # If this fine-tune does not emit a closing think marker, preserve its
        # generated text rather than silently returning an empty answer.
        if thinking_enabled and not answer_started and pending_thought:
            console.print(
                "[yellow]The model did not emit </think>; displaying its generated text as-is.[/yellow]"
            )
            visible_parts.append(pending_thought)

        final_text = "".join(visible_parts).strip()
        live.update(
            Panel(
                Markdown(final_text or "[yellow]No visible response was generated.[/yellow]"),
                title=title,
                border_style="green",
                box=box.ROUNDED,
            )
        )

    finished_at = time.perf_counter()
    elapsed = max(finished_at - started_at, 1e-9)
    ttft = (first_token_at - started_at) if first_token_at is not None else elapsed
    decode_time = max(elapsed - ttft, 1e-9)

    try:
        generated_tokens = len(
            llm.tokenize("".join(raw_generated).encode("utf-8"), add_bos=False, special=True)
        )
    except Exception:
        generated_tokens = len(raw_generated)  # Approximation if tokenization fails.

    metrics: dict[str, float | int] = {
        "generated_tokens_including_thought": generated_tokens,
        "time_to_first_token_s": ttft,
        "total_time_s": elapsed,
        "decode_tokens_per_s_approx": generated_tokens / decode_time,
    }
    return final_text, metrics


# ---------------------------------------------------------------------------
# Interactive application
# ---------------------------------------------------------------------------
def print_help() -> None:
    console.print(
        Panel(
            "[bold]Commands[/bold]\n"
            "[cyan]/fast[/cyan]       Fast mode; thinking OFF\n"
            "[cyan]/think[/cyan]      Thinking mode ON for subsequent messages\n"
            "[cyan]/mode[/cyan]       Show current mode\n"
            "[magenta]research <q>[/magenta] One-turn, longer offline analysis\n"
            "[cyan]/clear[/cyan]      Clear conversation history\n"
            "[cyan]/help[/cyan]       Show this help\n"
            "[red]/exit[/red]       Exit",
            title="DESTROYER AI HELP",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )


def run_chat() -> None:
    llm, backend_mode = initialize_model()
    history: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    current_mode = "fast"

    console.print(
        Panel(
            f"[bold cyan]DESTROYER AI READY[/bold cyan]\n"
            f"Backend: [bold]{backend_mode}[/bold]\n"
            f"Default mode: [green]FAST / THINKING OFF[/green]\n"
            "Type [magenta]research <question>[/magenta] for longer offline analysis.\n"
            "Type [dim]/help[/dim] for commands.",
            border_style="cyan",
            box=box.DOUBLE,
        )
    )

    try:
        while True:
            try:
                user_input = Prompt.ask(
                    f"[bold blue]You[/bold blue] [dim]({current_mode.upper()})[/dim]"
                ).strip()
            except EOFError:
                break

            if not user_input:
                continue

            lowered = user_input.lower()
            if lowered in {"/exit", "exit", "quit"}:
                break
            if lowered == "/help":
                print_help()
                continue
            if lowered == "/clear":
                history = [{"role": "system", "content": SYSTEM_PROMPT}]
                console.print("[green]Conversation history cleared.[/green]")
                continue
            if lowered == "/fast":
                current_mode = "fast"
                console.print("[green]Fast mode enabled. Thinking is OFF.[/green]")
                continue
            if lowered == "/think":
                current_mode = "think"
                console.print("[cyan]Thinking mode enabled.[/cyan]")
                continue
            if lowered == "/mode":
                console.print(f"Current mode: [bold]{current_mode.upper()}[/bold]")
                continue

            one_turn_research = lowered.startswith("research ")
            if one_turn_research:
                question = user_input[len("research "):].strip()
                if not question:
                    console.print("[yellow]Usage: research <question>[/yellow]")
                    continue
                turn_mode = "research"
                user_content = RESEARCH_INSTRUCTION + question
                max_tokens = RESEARCH_MAX_TOKENS
            else:
                turn_mode = current_mode
                user_content = user_input
                max_tokens = THINK_MAX_TOKENS if turn_mode == "think" else FAST_MAX_TOKENS

            history.append({"role": "user", "content": user_content})
            try:
                prompt = fit_history(
                    llm,
                    history,
                    thinking=turn_mode in {"think", "research"},
                    max_new_tokens=max_tokens,
                )
                answer, metrics = generate_stream(
                    llm,
                    prompt,
                    mode=turn_mode,
                    max_tokens=max_tokens,
                )
                if answer:
                    history.append({"role": "assistant", "content": answer})
                else:
                    # Remove the unanswered user turn so it is not replayed as
                    # if the assistant had completed it.
                    history.pop()

                console.print(
                    "[dim]Generated: {tokens} tokens (including hidden reasoning) | "
                    "TTFT: {ttft:.2f}s | Total: {total:.2f}s | "
                    "Approx. decode: {tps:.2f} tok/s[/dim]".format(
                        tokens=metrics["generated_tokens_including_thought"],
                        ttft=metrics["time_to_first_token_s"],
                        total=metrics["total_time_s"],
                        tps=metrics["decode_tokens_per_s_approx"],
                    )
                )
            except KeyboardInterrupt:
                if history and history[-1]["role"] == "user":
                    history.pop()
                console.print("\n[yellow]Generation interrupted.[/yellow]")
            except Exception as exc:
                if history and history[-1]["role"] == "user":
                    history.pop()
                console.print(Panel(f"[red]{type(exc).__name__}: {exc}[/red]", title="GENERATION ERROR", border_style="red"))

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
    finally:
        console.print("[dim]Releasing model resources...[/dim]")
        del llm
        gc.collect()
        console.print("[green]Destroyer AI shut down.[/green]")


if __name__ == "__main__":
    try:
        run_chat()
    except Exception as exc:
        console.print(Panel(f"[bold red]{type(exc).__name__}: {exc}[/bold red]", title="FATAL ERROR", border_style="red"))
        sys.exit(1)
