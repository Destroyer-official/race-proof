"""DESTROYER AI - adaptive local Qwen GGUF assistant for Windows/Linux.

Features
--------
- Detects RAM, CPU thread count, Vulkan SDK/runtime and Vulkan physical devices.
- Selects a conservative context/batch profile for available system memory.
- Requests full Vulkan offload when a Vulkan GPU is detected; falls back through
  partial GPU offload to CPU if model initialization fails.
- Logs the actual llama.cpp backend initialization output to destroyer_backend.log.
- Uses the GGUF-embedded Jinja chat template, HF tokenizer_config.json, or the
  model-author's adjacent chat_template.jinja; never guesses a prompt format.
- Passes enable_thinking to the Jinja template, rather than manually fabricating
  ChatML or <think> blocks.
- Streams a lightweight Rich terminal display; renders Markdown once at completion.
- Hides model <think> traces while retaining only the final answer in history.
- Keeps context bounded using token counts from the actual rendered template.
- Separates app wall-throughput from llama.cpp's internal prompt/decode metrics.
- Offers /bench and /autotune. Autotuning takes three measurements per backend,
  selects by median end-to-end response throughput (prefill + decode), and saves
  the winning layer count for this hardware/model.

This is offline inference. The `research` command does not browse the web.
"""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import gc
import json
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any

try:
    from rich import box
    from rich.console import Console
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.prompt import Prompt
    from rich.text import Text
except ImportError as exc:  # pragma: no cover - exercised on user's machine
    raise SystemExit(
        "Missing dependency 'rich'. Install it with: "
        f'"{sys.executable}" -m pip install rich'
    ) from exc

# Add Vulkan SDK DLL directory before importing llama_cpp. This does not install
# a Vulkan driver; the AMD display driver supplies the actual physical device.
_DLL_DIRECTORY_HANDLES: list[Any] = []
if os.name == "nt":
    _sdk_root = os.environ.get("VULKAN_SDK")
    if _sdk_root:
        _vulkan_bin = Path(_sdk_root) / "Bin"
        if _vulkan_bin.is_dir():
            os.environ["PATH"] = str(_vulkan_bin) + os.pathsep + os.environ.get("PATH", "")
            try:
                _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(str(_vulkan_bin)))
            except (AttributeError, OSError):
                pass

try:
    import llama_cpp
    from llama_cpp import Llama
    from llama_cpp.llama_chat_format import Jinja2ChatFormatter
except ImportError as exc:  # pragma: no cover - exercised on user's machine
    raise SystemExit(
        "llama-cpp-python is not importable in this Python environment. "
        "Install/build the Vulkan-enabled package in the same interpreter used "
        f"to run this script. Python: {sys.executable}\nDetails: {exc}"
    ) from exc


# ---------------------------------------------------------------------------
# User configuration and sensible hardware-derived defaults
# ---------------------------------------------------------------------------
DEFAULT_MODEL_PATH = Path(
    r"C:\Users\des\OneDrive\Desktop\clint\Huihui-Qwen3.5-4B-abliterated.Q4_K_M.gguf"
)
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_LOG_PATH = SCRIPT_DIR / "destroyer_backend.log"
TUNING_CONFIG_PATH = SCRIPT_DIR / "destroyer_ai_tuning.json"
APP_VERSION = "2.3.0"

def env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        console.print(f"[yellow]Ignoring invalid {name}={raw!r}; using {default}.[/yellow]")
        return default
    return max(minimum, min(maximum, value))


console = Console(highlight=False)

FAST_MAX_TOKENS = env_int("DESTROYER_FAST_TOKENS", 256, 32, 2048)
THINK_MAX_TOKENS = env_int("DESTROYER_THINK_TOKENS", 768, 64, 4096)
RESEARCH_MAX_TOKENS = env_int("DESTROYER_RESEARCH_TOKENS", 1100, 64, 4096)

SYSTEM_PROMPT = (
    "You are Destroyer AI, a local technical assistant. Be direct, concise, "
    "analytical and technically precise. Do not introduce yourself or repeat "
    "your capabilities. Expand when the task requires it. Distinguish verified "
    "facts from assumptions and uncertainty. Never fabricate citations, "
    "measurements, tool results, or claims of external verification. This runtime "
    "has no web access. For code and security questions, prefer reproducible "
    "explanations, explicit assumptions, and practical validation steps."
)

RESEARCH_INSTRUCTION = (
    "[OFFLINE RESEARCH-STYLE ANALYSIS]\n"
    "Produce a rigorous, structured analysis using only your trained knowledge "
    "and the conversation. Do not claim to have searched the web, read current "
    "papers, checked CVEs, or verified external sources. Do not invent citations. "
    "Separate established information, reasoning, uncertainty, and missing "
    "evidence. Use headings for scope, key findings, technical analysis, risks, "
    "and conclusions. State when freshness cannot be established.\n\n"
    "Research question: "
)

@dataclass
class HardwareProfile:
    cpu_name: str
    physical_cores: int
    logical_cores: int
    total_ram_gb: float | None
    available_ram_gb: float | None
    vulkan_devices: list[str]
    vulkan_output: str
    vulkan_tool: str | None
    llama_gpu_offload_supported: bool | None
    llama_gpu_support_detail: str
    llama_gpu_probe_log: str

    @property
    def has_vulkan_gpu(self) -> bool:
        return bool(self.vulkan_devices)

    def fingerprint(self, model_path: Path, settings: RuntimeSettings | None = None) -> str:
        """Stable tuning key; include driver, model identity and memory-shape settings."""
        try:
            stat = model_path.stat()
            model_size = stat.st_size
            model_mtime_ns = stat.st_mtime_ns
        except OSError:
            model_size = 0
            model_mtime_ns = 0
        driver_lines = [
            line.strip()
            for line in self.vulkan_output.splitlines()
            if re.match(
                r"\s*(?:driverName|driverInfo|driverVersion|apiVersion|vendorID|deviceID)\s*=",
                line,
                flags=re.IGNORECASE,
            )
        ]
        try:
            native_module = getattr(llama_cpp, "llama_cpp", None)
            native_module_path = getattr(native_module, "__file__", "unknown")
        except Exception:
            native_module_path = "unknown"
        payload = {
            "cpu": self.cpu_name,
            "physical_cores": self.physical_cores,
            "logical_cores": self.logical_cores,
            "ram_total_gb": round(self.total_ram_gb or 0, 1),
            "vulkan_devices": self.vulkan_devices,
            "vulkan_driver": driver_lines,
            "vulkan_sdk": os.environ.get("VULKAN_SDK", ""),
            "llama_gpu_offload_supported": self.llama_gpu_offload_supported,
            "model": str(model_path.resolve()).lower(),
            "model_size": model_size,
            "model_mtime_ns": model_mtime_ns,
            "llama_cpp_python": getattr(llama_cpp, "__version__", "unknown"),
            "llama_cpp_path": getattr(llama_cpp, "__file__", "unknown"),
            "llama_cpp_native_path": native_module_path,
            "python_version": platform.python_version(),
            "python_executable": str(Path(sys.executable).resolve()).lower(),
            "app_version": APP_VERSION,
            "runtime_shape": (
                {
                    "n_ctx": settings.n_ctx,
                    "n_batch": settings.n_batch,
                    "n_ubatch": settings.n_ubatch,
                }
                if settings is not None else None
            ),
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


@dataclass
class RuntimeSettings:
    n_ctx: int
    n_batch: int
    n_ubatch: int
    n_threads: int
    n_threads_batch: int


def get_memory_status() -> tuple[float | None, float | None]:
    """Return total and currently available physical RAM in GiB."""
    if os.name == "nt":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        try:
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                gib = float(1024**3)
                return status.ullTotalPhys / gib, status.ullAvailPhys / gib
        except (AttributeError, OSError):
            pass

    # Optional fallback for non-Windows or restricted environments.
    try:
        import psutil  # type: ignore

        vm = psutil.virtual_memory()
        gib = float(1024**3)
        return vm.total / gib, vm.available / gib
    except Exception:
        return None, None


def locate_vulkaninfo() -> str | None:
    found = shutil.which("vulkaninfo") or shutil.which("vulkaninfo.exe")
    if found:
        return found
    sdk_root = os.environ.get("VULKAN_SDK")
    if sdk_root:
        for name in ("vulkaninfo.exe", "vulkaninfo"):
            candidate = Path(sdk_root) / "Bin" / name
            if candidate.is_file():
                return str(candidate)
    return None


def detect_vulkan_devices() -> tuple[list[str], str, str | None]:
    tool = locate_vulkaninfo()
    if not tool:
        return [], "vulkaninfo not found", None
    try:
        result = subprocess.run(
            [tool, "--summary"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=12,
            check=False,
        )
        output = (result.stdout or "") + "\n" + (result.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], f"vulkaninfo failed: {exc}", tool

    devices: list[str] = []
    # vulkaninfo --summary groups devices under GPU0, GPU1, etc.
    blocks = re.split(r"(?=^GPU\d+\s*:)", output, flags=re.MULTILINE)
    for block in blocks:
        name_match = re.search(r"deviceName\s*=\s*(.+)", block)
        if not name_match:
            continue
        name = name_match.group(1).strip()
        type_match = re.search(r"deviceType\s*=\s*(.+)", block)
        device_type = type_match.group(1).strip().upper() if type_match else ""
        if "CPU" in device_type or any(x in name.lower() for x in ("llvmpipe", "swiftshader", "lavapipe")):
            continue
        devices.append(name)

    # Some vulkaninfo builds do not emit GPU block headers with --summary.
    if not devices:
        names = re.findall(r"deviceName\s*=\s*(.+)", output)
        types = re.findall(r"deviceType\s*=\s*(.+)", output)
        if names:
            for index, name in enumerate(names):
                kind = types[index].upper() if index < len(types) else ""
                if "CPU" not in kind and not any(
                    x in name.lower() for x in ("llvmpipe", "swiftshader", "lavapipe")
                ):
                    devices.append(name.strip())

    return list(dict.fromkeys(devices)), output, tool


def detect_llama_gpu_offload_support() -> tuple[bool | None, str, str]:
    """Probe llama.cpp's compiled backend registry and preserve its log output.

    Some llama.cpp builds enumerate Vulkan devices only on the first backend
    registry call. Capturing this probe is important: otherwise a later model
    load may log layer allocation but no longer repeat the device identity.
    """
    try:
        from llama_cpp import llama_cpp as native

        checker = getattr(native, "llama_supports_gpu_offload", None)
        if checker is None:
            return None, "llama_supports_gpu_offload() is unavailable in this binding", ""
        with capture_backend_logs(clear=False, mirror=False) as probe_buffer:
            supported = bool(checker())
        detail = (
            "llama.cpp C API reports GPU/IGPU backend available"
            if supported else
            "llama.cpp C API reports no GPU/IGPU backend in this build/runtime"
        )
        return supported, detail, probe_buffer.getvalue()
    except Exception as exc:
        return None, f"GPU backend capability check failed: {type(exc).__name__}: {exc}", ""


def detect_physical_cores(logical: int) -> int:
    try:
        import psutil  # type: ignore
        count = psutil.cpu_count(logical=False)
        if count:
            return max(1, int(count))
    except Exception:
        pass
    # On the user's Ryzen 3 3200G this resolves to four logical/physical cores.
    return max(1, logical)


def detect_hardware() -> HardwareProfile:
    total_ram, available_ram = get_memory_status()
    vulkan_devices, vulkan_output, vulkan_tool = detect_vulkan_devices()
    logical = max(1, os.cpu_count() or 4)
    physical = detect_physical_cores(logical)
    cpu_name = platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "Unknown CPU")
    gpu_support, gpu_detail, gpu_probe_log = detect_llama_gpu_offload_support()
    return HardwareProfile(
        cpu_name=cpu_name,
        physical_cores=physical,
        logical_cores=logical,
        total_ram_gb=total_ram,
        available_ram_gb=available_ram,
        vulkan_devices=vulkan_devices,
        vulkan_output=vulkan_output,
        vulkan_tool=vulkan_tool,
        llama_gpu_offload_supported=gpu_support,
        llama_gpu_support_detail=gpu_detail,
        llama_gpu_probe_log=gpu_probe_log,
    )


def choose_settings(profile: HardwareProfile) -> RuntimeSettings:
    available = profile.available_ram_gb
    # Conservative starting point for 16 GB-class Windows PCs with an iGPU
    # that borrows system RAM. Context and batch settings are heuristics; the
    # app never assumes the largest setting is automatically the fastest.
    if available is None:
        # When memory telemetry fails, choose a low-risk profile rather than
        # assuming the machine has abundant free RAM.
        ctx, batch, ubatch = 2048, 128, 64
    elif available >= 8.0:
        ctx, batch, ubatch = 4096, 256, 128
    elif available >= 5.5:
        ctx, batch, ubatch = 3072, 192, 96
    elif available >= 3.5:
        ctx, batch, ubatch = 2048, 128, 64
    else:
        ctx, batch, ubatch = 1536, 96, 48

    cores = max(1, min(profile.physical_cores, profile.logical_cores, 8))
    ctx = env_int("DESTROYER_N_CTX", ctx, 1024, 32768)
    batch = env_int("DESTROYER_N_BATCH", batch, 32, min(2048, ctx))
    ubatch = env_int("DESTROYER_N_UBATCH", ubatch, 16, batch)
    threads = env_int("DESTROYER_THREADS", cores, 1, 64)
    threads_batch = env_int("DESTROYER_THREADS_BATCH", cores, 1, 64)
    return RuntimeSettings(
        n_ctx=ctx,
        n_batch=batch,
        n_ubatch=min(ubatch, batch),
        n_threads=threads,
        n_threads_batch=threads_batch,
    )


def find_model_path() -> Path:
    env_path = os.getenv("DESTROYER_MODEL_PATH")
    candidates: list[Path] = []
    if env_path:
        candidates.append(Path(env_path).expanduser())
    candidates.append(DEFAULT_MODEL_PATH)
    candidates.extend(
        [
            SCRIPT_DIR / DEFAULT_MODEL_PATH.name,
            Path.cwd() / DEFAULT_MODEL_PATH.name,
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    search_dirs = list(dict.fromkeys([Path.cwd(), SCRIPT_DIR, DEFAULT_MODEL_PATH.parent]))
    matches: list[Path] = []
    for directory in search_dirs:
        try:
            matches.extend(
                p for p in directory.glob("*Qwen*3.5*4B*abliterated*.gguf") if p.is_file()
            )
        except OSError:
            continue
    unique = list(dict.fromkeys(p.resolve() for p in matches))
    if len(unique) == 1:
        return unique[0]
    if len(unique) > 1:
        exact = [p for p in unique if "Q4_K_M" in p.name.upper()]
        if len(exact) == 1:
            return exact[0]
        raise FileNotFoundError(
            "Multiple matching Qwen3.5 abliterated GGUF files were found. Set "
            "DESTROYER_MODEL_PATH to the exact file.\n" + "\n".join(map(str, unique))
        )
    raise FileNotFoundError(
        "Could not find the model GGUF. Set DESTROYER_MODEL_PATH to its full path. "
        f"Expected default: {DEFAULT_MODEL_PATH}"
    )


# ---------------------------------------------------------------------------
# Backend logging and truthful GPU status
# ---------------------------------------------------------------------------
class StderrTee:
    """Mirror llama.cpp's Python log callback to console, file, and memory."""
    def __init__(self, original: Any, file_handle: Any, buffer: StringIO, mirror: bool = True):
        self.original = original
        self.file_handle = file_handle
        self.buffer = buffer
        self.mirror = mirror

    def write(self, text: str) -> int:
        if self.mirror:
            self.original.write(text)
        self.file_handle.write(text)
        self.buffer.write(text)
        return len(text)

    def flush(self) -> None:
        if self.mirror:
            self.original.flush()
        self.file_handle.flush()

    def isatty(self) -> bool:
        return bool(getattr(self.original, "isatty", lambda: False)())

    @property
    def encoding(self) -> str:
        return getattr(self.original, "encoding", "utf-8")

    def fileno(self) -> int:
        return self.original.fileno()


@contextlib.contextmanager
def capture_backend_logs(clear: bool = False, mirror: bool = True):
    if clear:
        BACKEND_LOG_PATH.write_text("", encoding="utf-8")
    buffer = StringIO()
    with BACKEND_LOG_PATH.open("a", encoding="utf-8", errors="replace", buffering=1) as log_file:
        tee = StderrTee(sys.stderr, log_file, buffer, mirror=mirror)
        with contextlib.redirect_stderr(tee):
            yield buffer


def compose_backend_validation_log(probe_log: str, persisted_log: str, attempt_log: str) -> str:
    """Keep registry/device identity but isolate layer evidence to this load attempt."""
    identity_pattern = re.compile(
        r"ggml_vulkan.*(?:using|device|found|detected|\d+\s*=)", re.IGNORECASE
    )
    historical_device_lines = "\n".join(
        line for line in persisted_log.splitlines() if identity_pattern.search(line)
    )
    return "\n".join(
        part for part in (probe_log, historical_device_lines, attempt_log) if part
    )


def parse_backend_status(log_text: str, requested_layers: int) -> tuple[str, int | None, int | None]:
    """Parse llama.cpp logs; never equate a requested GPU split with offload."""
    lines = log_text.splitlines()
    device_lines = [
        line.strip()
        for line in lines
        if "ggml_vulkan" in line.lower()
        and (
            any(word in line.lower() for word in ("using", "device", "found", "detected"))
            or re.search(r"ggml_vulkan\s*:\s*\d+\s*=", line, re.IGNORECASE)
        )
    ]

    layer_count: int | None = None
    total_count: int | None = None
    patterns = (
        r"offloaded\s+(\d+)\s*/\s*(\d+)\s+layers?\s+to\s+GPU",
        r"offloaded\s+(\d+)\s+layers?\s+to\s+GPU",
        r"offloading\s+(\d+)\s+repeating\s+layers?\s+to\s+GPU",
    )
    for pattern in patterns:
        matches = list(re.finditer(pattern, log_text, flags=re.IGNORECASE))
        if matches:
            match = matches[-1]
            layer_count = int(match.group(1))
            if match.lastindex and match.lastindex >= 2:
                total_count = int(match.group(2))
            break

    device_description = "; ".join(device_lines[-2:])
    # A CPU-only request is authoritative even if the supplied diagnostic text
    # accidentally contains an unrelated historical GPU-allocation line.
    if requested_layers == 0:
        total = f"/{total_count}" if total_count is not None else ""
        detail = f"; llama.cpp reported zero GPU-offloaded layers (0{total})" if layer_count == 0 else ""
        return f"CPU-only mode selected (n_gpu_layers=0){detail}", 0, total_count
    if layer_count is not None and layer_count > 0:
        total = f"/{total_count}" if total_count is not None else ""
        if device_lines:
            return (
                f"Vulkan GPU offload confirmed by llama.cpp: {layer_count}{total} layers; "
                f"{device_description}",
                layer_count,
                total_count,
            )
        return (
            f"GPU layer offload reported ({layer_count}{total}), but ggml_vulkan "
            "device identity was not captured; inspect destroyer_backend.log",
            layer_count,
            total_count,
        )

    if requested_layers == 0:
        total = f"/{total_count}" if total_count is not None else ""
        detail = f"; llama.cpp reported zero GPU-offloaded layers (0{total})" if layer_count == 0 else ""
        return f"CPU-only mode selected (n_gpu_layers=0){detail}", 0, total_count
    if layer_count == 0:
        total = f"/{total_count}" if total_count is not None else ""
        return (
            f"llama.cpp reported zero GPU-offloaded layers (0{total})",
            0,
            total_count,
        )
    if device_lines:
        return (
            "Vulkan backend/device was initialized, but no layer-allocation line was "
            f"parsed; inspect backend log. {device_description}",
            None,
            None,
        )
    return "GPU offload requested but not confirmed by llama.cpp backend logs", None, None


# ---------------------------------------------------------------------------
# Llama initialization and model-native chat template
# ---------------------------------------------------------------------------
def make_llama(model_path: Path, settings: RuntimeSettings, gpu_layers: int) -> Llama:
    return Llama(
        model_path=str(model_path),
        n_ctx=settings.n_ctx,
        n_batch=settings.n_batch,
        n_ubatch=settings.n_ubatch,
        n_threads=settings.n_threads,
        n_threads_batch=settings.n_threads_batch,
        n_gpu_layers=gpu_layers,
        use_mmap=True,
        use_mlock=False,
        offload_kqv=True,
        flash_attn=False,  # Keep off until measured on this Vulkan driver.
        no_perf=False,     # Capture llama.cpp prompt/decode metrics per request.
        verbose=True,      # Required for trustworthy backend diagnostics.
    )


def read_token_text(llm: Llama, token_id: int) -> str:
    if token_id < 0:
        return ""
    # Prefer the public tokenizer API. Keep the private-model fallback only for
    # older bindings that cannot detokenize a special token through Llama.
    try:
        value = llm.detokenize([token_id], special=True)
        return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
    except Exception:
        value = llm._model.token_get_text(token_id)  # type: ignore[attr-defined]
        return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)



def apply_qwen_cache_prefix_fix(template: str) -> tuple[str, bool]:
    """Patch Qwen's non-thinking history branch for exact KV-prefix reuse.

    The upstream Qwen template adds an empty think block to the generation
    prefix when enable_thinking=False, but omits it from completed assistant
    history. That makes turn N's prompt cease to be a prefix of turn N+1.
    Insert the upstream-reported ``elif`` branch, preserving the original
    thinking-enabled branch byte-for-byte. Refuse to patch unknown templates.
    """
    marker = "loop.index0 > ns.last_query_index"
    if marker not in template or "reasoning_content" not in template:
        return template, False

    # Match only the exact history branch's else clause. Do not rewrite the
    # existing thinking-enabled serialization or the generation prefix.
    pattern = re.compile(
        r"(?P<if>\{%-?\s*if\s+loop\.index0\s*>\s*ns\.last_query_index\s*-?%\})"
        r"(?P<body>.*?)"
        r"(?P<else>\{%-?\s*else\s*-?%\})",
        flags=re.DOTALL,
    )
    matches = list(pattern.finditer(template))
    if len(matches) != 1:
        raise RuntimeError(
            "Detected a Qwen assistant-history condition, but could not locate "
            "one unambiguous last-query else branch. Refusing to modify the template."
        )
    match = matches[0]
    # The upstream model template may already contain this compatibility
    # branch. Make the patch idempotent to avoid generating invalid Jinja.
    existing_fix = re.search(
        r"\{%-?\s*elif\s+enable_thinking\s+is\s+defined\s+and\s+"
        r"enable_thinking\s+is\s+false\s*-?%\}",
        match.group("body"),
    )
    if existing_fix:
        return template, False
    insertion = (
        "{%- elif enable_thinking is defined and enable_thinking is false %}\n"
        "{{- '<|im_start|>' + message.role + '\\n<think>\\n\\n</think>\\n\\n' + content -}}"
    )
    patched = template[:match.start('else')] + insertion + template[match.start('else'):]
    return patched, True

def build_template_formatter(llm: Llama, model_path: Path) -> tuple[Any, bool, str]:
    metadata = getattr(llm, "metadata", {}) or {}
    template = metadata.get("tokenizer.chat_template")
    template_source = "GGUF metadata"

    if not isinstance(template, str) or not template.strip():
        named_templates = [
            (key, value)
            for key, value in metadata.items()
            if key.startswith("tokenizer.chat_template.") and isinstance(value, str)
        ]
        default_named = next(
            ((k, v) for k, v in named_templates if k.endswith(".default")),
            named_templates[0] if len(named_templates) == 1 else None,
        )
        if default_named:
            template = default_named[1]
            template_source = default_named[0]
        elif named_templates:
            raise RuntimeError(
                "GGUF contains multiple named chat templates but no unambiguous default. "
                "Refusing to choose an arbitrary template."
            )

    if not isinstance(template, str) or not template.strip():
        # Prefer the model's own exported tokenizer_config.json before looking
        # for a standalone Jinja file. HF stores chat_template as either a
        # string or a named list of {name, template} objects.
        tokenizer_configs = [
            model_path.parent / "tokenizer_config.json",
            SCRIPT_DIR / "tokenizer_config.json",
        ]
        for config_path in tokenizer_configs:
            if not config_path.is_file():
                continue
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
                candidate = config.get("chat_template")
                if isinstance(candidate, str) and candidate.strip():
                    template = candidate
                    template_source = str(config_path) + " (chat_template)"
                    break
                if isinstance(candidate, list):
                    named = [
                        item for item in candidate
                        if isinstance(item, dict)
                        and isinstance(item.get("template"), str)
                        and item["template"].strip()
                    ]
                    selected = next(
                        (item for item in named if item.get("name") == "default"),
                        named[0] if len(named) == 1 else None,
                    )
                    if selected:
                        template = selected["template"]
                        template_source = str(config_path) + " (chat_template list)"
                        break
                    if named:
                        raise RuntimeError(
                            f"{config_path} contains multiple named chat templates "
                            "without a 'default' entry. Refusing to choose arbitrarily."
                        )
            except (OSError, json.JSONDecodeError, TypeError):
                continue

    if not isinstance(template, str) or not template.strip():
        external_candidates = [
            model_path.parent / "chat_template.jinja",
            SCRIPT_DIR / "chat_template.jinja",
        ]
        for external_template in external_candidates:
            if external_template.is_file():
                template = external_template.read_text(encoding="utf-8")
                template_source = str(external_template)
                break

    if not isinstance(template, str) or not template.strip():
        raise RuntimeError(
            "No chat template was found in GGUF metadata, tokenizer_config.json, "
            "or chat_template.jinja. Refusing to guess ChatML. For this model, "
            "download the author's chat_template.jinja beside the GGUF from: "
            "https://huggingface.co/huihui-ai/Huihui-Qwen3.5-4B-abliterated/resolve/main/chat_template.jinja"
        )

    template, cache_patch_applied = apply_qwen_cache_prefix_fix(template)
    if cache_patch_applied:
        template_source += " (Qwen KV-cache-prefix compatibility patch)"

    eos_id = llm.token_eos()
    bos_id = llm.token_bos()
    eos_text = read_token_text(llm, eos_id)
    bos_text = read_token_text(llm, bos_id)
    formatter = Jinja2ChatFormatter(
        template=template,
        eos_token=eos_text,
        bos_token=bos_text,
        add_generation_prompt=True,
        stop_token_ids=[eos_id] if eos_id >= 0 else None,
    )

    # Verify that the template really responds to enable_thinking. Merely
    # inserting a variable into a Jinja render is not enough; rendered prompts
    # must differ between OFF and ON for this switch to be trusted.
    probe = [{"role": "user", "content": "template capability check"}]
    fast_probe = formatter(messages=probe, enable_thinking=False)
    think_probe = formatter(messages=probe, enable_thinking=True)
    # For this Qwen3.5 template, OFF must explicitly close an empty think block
    # while ON must leave a think prefix open. This avoids a false-positive from
    # a template that merely references the variable without changing the mode.
    fast_lower = fast_probe.prompt.lower()
    think_lower = think_probe.prompt.lower()
    fast_open_pos = fast_lower.rfind("<think>")
    fast_close_pos = fast_lower.rfind("</think>")
    think_open_pos = think_lower.rfind("<think>")
    think_close_pos = think_lower.rfind("</think>")
    fast_is_closed = fast_close_pos > fast_open_pos >= 0
    think_is_open = think_open_pos > think_close_pos
    has_qwen_switch = (
        "enable_thinking" in template
        and fast_is_closed
        and think_is_open
        and fast_probe.prompt != think_probe.prompt
    )
    supports_toggle = bool(has_qwen_switch)

    # Verify that a one-turn prompt remains an exact prefix when its assistant
    # response and the next user turn are added. If not, reset llama.cpp's KV
    # state between turns rather than relying on broken prefix reuse.
    prefix_probe_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "Destroyer cache-prefix probe one"},
    ]
    prefix_first = formatter(messages=prefix_probe_messages, enable_thinking=False).prompt
    prefix_second = formatter(
        messages=[
            *prefix_probe_messages,
            {"role": "assistant", "content": "DESTROYER_CACHE_SENTINEL"},
            {"role": "user", "content": "Destroyer cache-prefix probe two"},
        ],
        enable_thinking=False,
    ).prompt
    expected_continuation = (
        "DESTROYER_CACHE_SENTINEL<|im_end|>\n"
        "<|im_start|>user\nDestroyer cache-prefix probe two<|im_end|>\n"
    )
    prefix_cache_safe = prefix_second.startswith(prefix_first + expected_continuation)
    try:
        setattr(formatter, "_destroyer_prefix_cache_safe", prefix_cache_safe)
    except Exception:
        # Conservative default in generate_stream is to reset KV state.
        prefix_cache_safe = False
    if prefix_cache_safe:
        template_source += " (assistant-history KV prefix verified)"
    else:
        template_source += " (KV state reset between turns for safety)"

    return formatter, supports_toggle, template_source


def load_model(
    model_path: Path,
    settings: RuntimeSettings,
    profile: HardwareProfile,
    requested_layers: int,
    *,
    clear_log: bool = False,
) -> tuple[Llama, Any, bool, str, str]:
    if clear_log:
        # Keep the backend-enumeration lines captured by the capability probe;
        # they may be emitted only once per process by llama.cpp.
        BACKEND_LOG_PATH.write_text(profile.llama_gpu_probe_log, encoding="utf-8")
    with capture_backend_logs(clear=False, mirror=False) as log_buffer:
        llm = make_llama(model_path, settings, requested_layers)
    try:
        formatter, supports_toggle, template_source = build_template_formatter(llm, model_path)
    except Exception:
        try:
            llm.close()
        except Exception:
            pass
        raise
    try:
        # Device enumeration may occur only once. Reuse historical Vulkan
        # identity lines, but NEVER historical layer-allocation lines: otherwise
        # an earlier successful candidate could falsely validate a later one.
        persisted_backend_log = BACKEND_LOG_PATH.read_text(encoding="utf-8", errors="replace")
    except OSError:
        persisted_backend_log = ""
    combined_backend_log = compose_backend_validation_log(
        profile.llama_gpu_probe_log,
        persisted_backend_log,
        log_buffer.getvalue(),
    )
    backend_status, _, _ = parse_backend_status(combined_backend_log, requested_layers)
    if not profile.has_vulkan_gpu and requested_layers != 0:
        backend_status = "No Vulkan physical GPU detected by vulkaninfo; offload status unverified"
    return llm, formatter, supports_toggle, backend_status, template_source


def load_tuning_choice(
    profile: HardwareProfile,
    model_path: Path,
    settings: RuntimeSettings,
) -> dict[str, Any] | None:
    try:
        data = json.loads(TUNING_CONFIG_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        if data.get("fingerprint") != profile.fingerprint(model_path, settings):
            return None
        layers = int(data["gpu_layers"])
        if layers < -1:
            return None
        return data
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def choose_initial_gpu_layers(
    profile: HardwareProfile,
    model_path: Path,
    settings: RuntimeSettings,
) -> int:
    # An explicit environment override wins. Otherwise load a model/driver/
    # runtime-shape-specific measured setting, including tuned CPU threads.
    saved = load_tuning_choice(profile, model_path, settings)
    if saved:
        if os.getenv("DESTROYER_THREADS") is None:
            try:
                settings.n_threads = max(1, min(profile.physical_cores, int(saved.get("n_threads", settings.n_threads))))
            except (TypeError, ValueError):
                pass
        if os.getenv("DESTROYER_THREADS_BATCH") is None:
            try:
                settings.n_threads_batch = max(1, min(profile.physical_cores, int(saved.get("n_threads_batch", settings.n_threads_batch))))
            except (TypeError, ValueError):
                pass

    explicit = os.getenv("DESTROYER_GPU_LAYERS")
    if explicit is not None:
        try:
            value = int(explicit)
            if value < -1:
                raise ValueError
            return value
        except ValueError as exc:
            raise ValueError("DESTROYER_GPU_LAYERS must be an integer such as -1, 16, or 0") from exc

    if saved:
        return int(saved["gpu_layers"])
    if not profile.has_vulkan_gpu or profile.llama_gpu_offload_supported is False:
        return 0
    return -1

def initialize_with_fallback(
    model_path: Path,
    settings: RuntimeSettings,
    profile: HardwareProfile,
    requested_layers: int,
    *,
    clear_log: bool = True,
) -> tuple[Llama, Any, bool, str, int, str]:
    if (
        not profile.has_vulkan_gpu
        or profile.llama_gpu_offload_supported is False
        or requested_layers == 0
    ):
        candidates = [0]
    elif requested_layers == -1:
        # If full offload fails or is not confirmed, reduce the split in steps.
        candidates = [-1, 16, 8, 0]
    elif requested_layers > 16:
        candidates = [requested_layers, 16, 8, 0]
    elif requested_layers > 8:
        candidates = [requested_layers, 8, 0]
    else:
        candidates = [requested_layers, 0]

    errors: list[str] = []
    first = True
    for layers in list(dict.fromkeys(candidates)):
        try:
            llm, formatter, supports_toggle, status, template_source = load_model(
                model_path,
                settings,
                profile,
                layers,
                clear_log=clear_log and first,
            )
            if layers > 0 and profile.has_vulkan_gpu and not status.startswith("Vulkan GPU offload confirmed"):
                # Do not report a GPU-accelerated session merely because
                # n_gpu_layers was requested. Require llama.cpp's layer-count
                # diagnostic; otherwise continue through partial/CPU fallback.
                try:
                    llm.close()
                except Exception:
                    pass
                raise RuntimeError(
                    "Vulkan GPU layer offload was requested but llama.cpp did not "
                    f"confirm any offloaded layers ({status})."
                )
            return llm, formatter, supports_toggle, status, layers, template_source
        except Exception as exc:
            errors.append(f"n_gpu_layers={layers}: {type(exc).__name__}: {exc}")
            console.print(
                f"[yellow]Initialization attempt n_gpu_layers={layers} failed: "
                f"{type(exc).__name__}: {exc}[/yellow]"
            )
        first = False
    raise RuntimeError("All model initialization attempts failed:\n" + "\n".join(errors))


# ---------------------------------------------------------------------------
# Prompt fitting, thinking-tag filter and streaming generation
# ---------------------------------------------------------------------------
class ThoughtFilter:
    """Discard <think>...</think> content, including markers split across chunks."""
    OPEN = "<think>"
    CLOSE = "</think>"

    def __init__(self, start_inside_thought: bool):
        self.in_thought = start_inside_thought
        self.buffer = ""

    def feed(self, text: str) -> str:
        self.buffer += text
        output: list[str] = []
        while self.buffer:
            if self.in_thought:
                end = self.buffer.find(self.CLOSE)
                if end < 0:
                    keep = len(self.CLOSE) - 1
                    self.buffer = self.buffer[-keep:] if keep else ""
                    break
                self.buffer = self.buffer[end + len(self.CLOSE):]
                self.in_thought = False
                continue

            start = self.buffer.find(self.OPEN)
            close = self.buffer.find(self.CLOSE)
            if close >= 0 and (start < 0 or close < start):
                output.append(self.buffer[:close])
                self.buffer = self.buffer[close + len(self.CLOSE):]
                continue
            if start >= 0:
                output.append(self.buffer[:start])
                self.buffer = self.buffer[start + len(self.OPEN):]
                self.in_thought = True
                continue

            # Retain only a suffix that could be the beginning of a split <think>.
            keep = 0
            max_keep = min(len(self.buffer), len(self.OPEN) - 1)
            for n in range(1, max_keep + 1):
                if self.buffer.endswith(self.OPEN[:n]):
                    keep = n
            if keep:
                output.append(self.buffer[:-keep])
                self.buffer = self.buffer[-keep:]
            else:
                output.append(self.buffer)
                self.buffer = ""
            break
        return "".join(output)

    def finish(self) -> tuple[str, bool]:
        if self.in_thought:
            return "", True
        tail = self.buffer
        self.buffer = ""
        return tail, False


def render_prompt(formatter: Any, messages: list[dict[str, str]], thinking: bool) -> Any:
    return formatter(messages=messages, enable_thinking=thinking)


def prompt_token_count(llm: Llama, formatted: Any) -> int:
    return len(
        llm.tokenize(
            formatted.prompt.encode("utf-8"),
            add_bos=not bool(formatted.added_special),
            special=True,
        )
    )


def fit_history(
    llm: Llama,
    formatter: Any,
    history: list[dict[str, str]],
    *,
    thinking: bool,
    requested_max_tokens: int,
) -> tuple[Any, int, int]:
    max_tokens = requested_max_tokens
    formatted = render_prompt(formatter, history, thinking)
    prompt_tokens = prompt_token_count(llm, formatted)

    # Remove oldest *complete* user/assistant pairs while retaining the system
    # instruction and current user request. This counts the actual Jinja output.
    while prompt_tokens + max_tokens + 32 > llm.n_ctx() and len(history) > 3:
        del history[1:3]
        formatted = render_prompt(formatter, history, thinking)
        prompt_tokens = prompt_token_count(llm, formatted)

    remaining = llm.n_ctx() - prompt_tokens - 32
    if remaining < 32:
        raise ValueError(
            f"Current request is too large for n_ctx={llm.n_ctx()} "
            f"(prompt≈{prompt_tokens} tokens). Shorten the current request or "
            "increase DESTROYER_N_CTX if memory permits."
        )
    max_tokens = min(max_tokens, remaining)
    return formatted, prompt_tokens, max_tokens


def parse_llama_perf(log_text: str) -> dict[str, float | int]:
    """Extract llama.cpp's own prefill/decode rates, when its log emits them."""
    result: dict[str, float | int] = {}
    prompt_matches = list(re.finditer(
        r"prompt eval time\s*=\s*([0-9.]+)\s*ms\s*/\s*(\d+)\s*tokens?\s*\([^)]*?([0-9.]+)\s*tokens?\s*per second",
        log_text,
        flags=re.IGNORECASE,
    ))
    decode_matches = list(re.finditer(
        r"eval time\s*=\s*([0-9.]+)\s*ms\s*/\s*(\d+)\s*runs?\s*\([^)]*?([0-9.]+)\s*tokens?\s*per second",
        log_text,
        flags=re.IGNORECASE,
    ))
    if prompt_matches:
        match = prompt_matches[-1]
        result["backend_prompt_ms"] = float(match.group(1))
        result["backend_prompt_tokens"] = int(match.group(2))
        result["backend_prompt_tps"] = float(match.group(3))
    if decode_matches:
        match = decode_matches[-1]
        result["backend_decode_ms"] = float(match.group(1))
        result["backend_decode_tokens"] = int(match.group(2))
        result["backend_decode_tps"] = float(match.group(3))
    return result


def sampling_parameters(mode: str) -> dict[str, float | int]:
    """Qwen3.5 sampling profiles from the official model card."""
    if mode == "think":
        # Official general-task thinking profile.
        return {
            "temperature": 1.0,
            "top_p": 0.95,
            "top_k": 20,
            "min_p": 0.0,
            "repeat_penalty": 1.0,
            "presence_penalty": 1.5,
            "frequency_penalty": 0.0,
        }
    if mode == "research":
        # Official non-thinking reasoning-task profile; no private think trace.
        return {
            "temperature": 1.0,
            "top_p": 1.0,
            "top_k": 40,
            "min_p": 0.0,
            "repeat_penalty": 1.0,
            "presence_penalty": 2.0,
            "frequency_penalty": 0.0,
        }
    return {
        # Official non-thinking general-task profile for low-latency chat.
        "temperature": 0.7,
        "top_p": 0.8,
        "top_k": 20,
        "min_p": 0.0,
        "repeat_penalty": 1.0,
        "presence_penalty": 1.5,
        "frequency_penalty": 0.0,
    }


def generate_stream(
    llm: Llama,
    formatter: Any,
    history: list[dict[str, str]],
    *,
    mode: str,
    max_tokens: int,
    live_display: bool = True,
    supports_thinking_toggle: bool = True,
) -> tuple[str, dict[str, float | int]]:
    # Huihui's fine-tuning data is explicitly non-thinking. FAST and extended
    # RESEARCH therefore stay in-distribution; /think is the deliberate opt-in.
    # Only request the native template switch after the startup self-test passes.
    thinking_requested = mode == "think" and supports_thinking_toggle
    formatted, input_tokens, actual_max_tokens = fit_history(
        llm,
        formatter,
        history,
        thinking=thinking_requested,
        requested_max_tokens=max_tokens,
    )
    # The rendered prompt, not the requested mode name, determines actual state.
    prompt_tail = formatted.prompt[-256:].rstrip().lower()
    prompt_opens_thinking = prompt_tail.endswith("<think>")
    thinking_enabled = prompt_opens_thinking
    effective_sampling_mode = (
        "think" if thinking_enabled else "research" if mode == "research" else "fast"
    )
    params = sampling_parameters(effective_sampling_mode)
    stream = llm.create_completion(
        prompt=formatted.prompt,
        max_tokens=actual_max_tokens,
        stream=True,
        stop=formatted.stop,
        stopping_criteria=formatted.stopping_criteria,
        **params,
    )

    # An unclosed <think> marker means generated tokens are hidden reasoning.
    parser = ThoughtFilter(prompt_opens_thinking)
    raw_parts: list[str] = []
    visible_parts: list[str] = []
    started = time.perf_counter()
    first_token_at: float | None = None
    finish_reason: str | None = None
    last_refresh = started

    titles = {
        "fast": "[bold green]DESTROYER AI • FAST CHAT[/bold green]",
        "think": "[bold cyan]DESTROYER AI • THINKING (trace hidden)[/bold cyan]",
        "research": "[bold magenta]DESTROYER AI • OFFLINE RESEARCH[/bold magenta]",
    }
    title = titles[mode]
    initial = (
        "[dim]Reasoning enabled. Internal trace is hidden; waiting for the final answer...[/dim]"
        if thinking_enabled
        else "[dim]Generating response...[/dim]"
    )

    if live_display:
        live_context = Live(
            Panel(initial, title=title, border_style="green", box=box.ROUNDED),
            console=console,
            refresh_per_second=4,
            transient=False,
        )
    else:
        live_context = contextlib.nullcontext(None)

    # Hide raw llama.cpp perf lines from the middle of the conversation while
    # retaining them in the diagnostic log and parsing their backend timings.
    with capture_backend_logs(clear=False, mirror=False) as perf_buffer:
        with live_context as live:
            for event in stream:
                choice = event.get("choices", [{}])[0]
                if choice.get("finish_reason") is not None:
                    finish_reason = str(choice["finish_reason"])
                piece = choice.get("text", "")
                if not piece:
                    continue
                if first_token_at is None:
                    first_token_at = time.perf_counter()
                raw_parts.append(piece)
                display_piece = parser.feed(piece)
                if display_piece:
                    visible_parts.append(display_piece)
                    now = time.perf_counter()
                    if live_display and live is not None and now - last_refresh >= 0.30:
                        # Plain Text is deliberately used during streaming. Parsing
                        # full Markdown on every token wastes CPU and delays display.
                        live.update(
                            Panel(
                                Text("".join(visible_parts)),
                                title=title,
                                border_style="green",
                                box=box.ROUNDED,
                            )
                        )
                        last_refresh = now

            # Capture generation completion before final parsing/Markdown rendering.
            generation_finished = time.perf_counter()
            tail, unfinished_thought = parser.finish()
            if tail:
                visible_parts.append(tail)
            final_text = "".join(visible_parts).strip()
            if live_display and live is not None:
                final_renderable: Any = (
                    Markdown(final_text)
                    if final_text
                    else Text("No final answer was produced.", style="yellow")
                )
                live.update(
                    Panel(
                        final_renderable,
                        title=title,
                        border_style="green",
                        box=box.ROUNDED,
                    )
                )

    # generation_finished is captured immediately after stream iteration,
    # before final parsing and Rich Markdown rendering.
    elapsed = max(generation_finished - started, 1e-9)
    ttft = first_token_at - started if first_token_at is not None else elapsed
    wall_decode_seconds = max(
        generation_finished - (first_token_at if first_token_at is not None else generation_finished),
        1e-9,
    )
    raw_text = "".join(raw_parts)
    try:
        generated_tokens = len(
            llm.tokenize(raw_text.encode("utf-8"), add_bos=False, special=True)
        )
    except Exception:
        generated_tokens = len(raw_parts)
    visible_tokens = 0
    if final_text:
        try:
            visible_tokens = len(
                llm.tokenize(final_text.encode("utf-8"), add_bos=False, special=True)
            )
        except Exception:
            visible_tokens = len(final_text.split())

    metrics: dict[str, float | int] = {
        "prompt_tokens": input_tokens,
        "generated_tokens": generated_tokens,
        "visible_tokens": visible_tokens,
        "ttft_seconds": ttft,
        "total_seconds": elapsed,
        "wall_decode_tps": generated_tokens / wall_decode_seconds,
        "unfinished_thought": int(unfinished_thought),
        "prompt_opens_thinking": int(prompt_opens_thinking),
        "was_truncated": int(finish_reason == "length"),
        "max_tokens": actual_max_tokens,
    }
    metrics.update(parse_llama_perf(perf_buffer.getvalue()))
    if thinking_enabled or not getattr(formatter, "_destroyer_prefix_cache_safe", False):
        # Hidden reasoning is intentionally not retained in visible history.
        # Also reset when the template fails the prefix-stability self-test.
        # This sacrifices KV reuse rather than risk stale/mismatched state.
        try:
            llm.reset()
            metrics["kv_cache_reset_after_turn"] = 1
        except Exception:
            metrics["kv_cache_reset_after_turn"] = 0
    return final_text, metrics


# ---------------------------------------------------------------------------
# Optional benchmark/autotuner
# ---------------------------------------------------------------------------
def warmup_model(llm: Llama, formatter: Any) -> float:
    """Prime the inference graph once so the first interactive turn is less cold."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "Reply with exactly: READY."},
    ]
    formatted = render_prompt(formatter, messages, thinking=False)
    params = sampling_parameters("fast")
    started = time.perf_counter()
    try:
        with capture_backend_logs(clear=False, mirror=False):
            llm.create_completion(
                prompt=formatted.prompt,
                max_tokens=8,
                stream=False,
                stop=formatted.stop,
                stopping_criteria=formatted.stopping_criteria,
                seed=20261106,
                **params,
            )
    finally:
        try:
            llm.reset()
        except Exception:
            pass
    return time.perf_counter() - started


def benchmark_one(
    llm: Llama,
    formatter: Any,
    max_tokens: int = 64,
) -> tuple[float, int, float]:
    """Measure end-to-end output throughput with UI/load time excluded.

    The timer includes prompt evaluation (TTFT) plus decoding, because that is
    closer to the response latency a person experiences than decode tok/s alone.
    The same prompt, seed, token cap and non-thinking template are used for all
    backend candidates. Rich rendering and model loading are excluded.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Explain in five concise technical sentences how CPU cache levels "
                "reduce average memory-access latency. Give enough detail to avoid "
                "a one-sentence answer."
            ),
        },
    ]
    formatted = render_prompt(formatter, messages, thinking=False)
    llm.reset()
    params = sampling_parameters("fast")
    stream = llm.create_completion(
        prompt=formatted.prompt,
        max_tokens=max_tokens,
        stream=True,
        stop=formatted.stop,
        stopping_criteria=formatted.stopping_criteria,
        seed=20261106,
        **params,
    )
    raw: list[str] = []
    with capture_backend_logs(clear=False, mirror=False):
        started = time.perf_counter()
        first: float | None = None
        for event in stream:
            piece = event.get("choices", [{}])[0].get("text", "")
            if piece:
                if first is None:
                    first = time.perf_counter()
                raw.append(piece)
        finished = time.perf_counter()
    if first is None:
        return 0.0, 0, 0.0
    try:
        tokens = len(llm.tokenize("".join(raw).encode("utf-8"), add_bos=False, special=True))
    except Exception:
        tokens = len(raw)
    total_seconds = max(finished - started, 1e-9)
    effective_response_tps = tokens / total_seconds
    return effective_response_tps, tokens, total_seconds


def run_autotune(
    model_path: Path,
    settings: RuntimeSettings,
    profile: HardwareProfile,
    current_llm: Llama | None,
) -> tuple[Llama, Any, bool, str, int, str]:
    console.print(
        Panel(
            "Testing full Vulkan offload, partial-offload levels and CPU-only inference, "
            "then tuning CPU threads for the winning split. Each candidate is warmed "
            "up and measured three times with the same prompt; model-load time and "
            "Rich rendering are excluded. Median end-to-end response throughput "
            "(prompt evaluation + generation) selects the measured configuration.",
            title="AUTOTUNE",
            border_style="magenta",
        )
    )
    candidates = (
        [-1, 24, 16, 8, 0]
        if profile.has_vulkan_gpu and profile.llama_gpu_offload_supported is not False
        else [0]
    )
    tested: list[tuple[int, float, list[float]]] = []
    if current_llm is not None:
        try:
            current_llm.close()
        except Exception:
            pass
        del current_llm
        gc.collect()

    for index, layers in enumerate(candidates):
        llm: Llama | None = None
        try:
            console.print(f"[cyan]Loading benchmark candidate n_gpu_layers={layers}...[/cyan]")
            llm, formatter, _, status, _ = load_model(
                model_path,
                settings,
                profile,
                layers,
                clear_log=(index == 0),
            )
            if layers > 0 and profile.has_vulkan_gpu and not status.startswith("Vulkan GPU offload confirmed"):
                raise RuntimeError(f"GPU offload was not confirmed: {status}")
            console.print(f"  Backend: {status}")
            _ = benchmark_one(llm, formatter, max_tokens=16)  # warm-up
            samples: list[float] = []
            for run_index in range(3):
                rate, tokens, _seconds = benchmark_one(llm, formatter, max_tokens=64)
                if rate > 0 and tokens >= 8:
                    samples.append(rate)
                console.print(
                    f"    run {run_index + 1}: {rate:.2f} effective tok/s "
                    f"({tokens} generated tokens in {_seconds:.2f}s)"
                )
            if samples:
                score = statistics.median(samples)
                tested.append((layers, score, samples))
                console.print(
                    f"  [bold]median: {score:.2f} tok/s[/bold] "
                    f"(range {min(samples):.2f}–{max(samples):.2f})"
                )
            else:
                console.print("  [yellow]No valid benchmark sample; candidate ignored.[/yellow]")
        except Exception as exc:
            console.print(
                f"[yellow]Candidate n_gpu_layers={layers} failed: "
                f"{type(exc).__name__}: {exc}[/yellow]"
            )
        finally:
            if llm is not None:
                try:
                    llm.close()
                except Exception:
                    pass
                del llm
            gc.collect()

    if not tested:
        raise RuntimeError("Autotune could not load or benchmark any backend configuration.")
    best_layers, best_score, _ = max(tested, key=lambda item: item[1])

    # Tune CPU thread count for the winning offload split. On a 4-core CPU,
    # comparing 2/3/4 threads is a modest extra cost and avoids assuming that
    # maximum threading always wins when most transformer layers are on GPU.
    thread_candidates = sorted({
        max(1, profile.physical_cores // 2),
        max(1, profile.physical_cores - 1),
        max(1, profile.physical_cores),
    })
    thread_tested: list[tuple[int, float, list[float]]] = []
    original_threads = (settings.n_threads, settings.n_threads_batch)
    if len(thread_candidates) > 1:
        for thread_count in thread_candidates:
            candidate_settings = RuntimeSettings(
                n_ctx=settings.n_ctx,
                n_batch=settings.n_batch,
                n_ubatch=settings.n_ubatch,
                n_threads=thread_count,
                n_threads_batch=thread_count,
            )
            candidate_llm: Llama | None = None
            try:
                console.print(
                    f"[cyan]Tuning CPU threads={thread_count} with n_gpu_layers={best_layers}...[/cyan]"
                )
                loaded_candidate = initialize_with_fallback(
                    model_path, candidate_settings, profile, best_layers, clear_log=False
                )
                candidate_llm, candidate_formatter = loaded_candidate[0], loaded_candidate[1]
                if loaded_candidate[4] != best_layers:
                    raise RuntimeError(
                        f"requested n_gpu_layers={best_layers}, loaded {loaded_candidate[4]}"
                    )
                _ = warmup_model(candidate_llm, candidate_formatter)
                rates: list[float] = []
                for run_index in range(3):
                    rate, tokens, seconds = benchmark_one(candidate_llm, candidate_formatter, max_tokens=64)
                    if rate > 0 and tokens >= 8:
                        rates.append(rate)
                    console.print(
                        f"    thread run {run_index + 1}: {rate:.2f} effective tok/s "
                        f"({tokens} tokens / {seconds:.2f}s)"
                    )
                if rates:
                    median_rate = statistics.median(rates)
                    thread_tested.append((thread_count, median_rate, rates))
                    console.print(f"  thread={thread_count} median: {median_rate:.2f} effective tok/s")
            except Exception as exc:
                console.print(
                    f"[yellow]Thread candidate {thread_count} failed: "
                    f"{type(exc).__name__}: {exc}[/yellow]"
                )
            finally:
                if candidate_llm is not None:
                    try:
                        candidate_llm.close()
                    except Exception:
                        pass
                    del candidate_llm
                gc.collect()

    selected_threads = original_threads
    if thread_tested:
        selected_thread_count, _, _ = max(thread_tested, key=lambda item: item[1])
        selected_threads = (selected_thread_count, selected_thread_count)
        settings.n_threads, settings.n_threads_batch = selected_threads

    TUNING_CONFIG_PATH.write_text(
        json.dumps(
            {
                "fingerprint": profile.fingerprint(model_path, settings),
                "gpu_layers": best_layers,
                "n_threads": settings.n_threads,
                "n_threads_batch": settings.n_threads_batch,
                "n_ctx": settings.n_ctx,
                "n_batch": settings.n_batch,
                "n_ubatch": settings.n_ubatch,
                "median_end_to_end_generated_tokens_per_second": round(best_score, 3),
                "benchmark_objective": "generated_tokens / (prompt_eval + decode wall time)",
                "thread_tuning": [
                    {
                        "threads": threads,
                        "median_end_to_end_generated_tokens_per_second": round(score, 3),
                        "samples": [round(value, 3) for value in samples],
                    }
                    for threads, score, samples in thread_tested
                ],
                "tested": [
                    {
                        "gpu_layers": layers,
                        "median_end_to_end_generated_tokens_per_second": round(score, 3),
                        "samples": [round(value, 3) for value in samples],
                    }
                    for layers, score, samples in tested
                ],
                "saved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    console.print(
        f"[bold green]Best measured setting: n_gpu_layers={best_layers} "
        f"({best_score:.2f} median effective tok/s, including prompt evaluation; "
        f"threads={settings.n_threads}). Saved to {TUNING_CONFIG_PATH.name}.[/bold green]"
    )
    loaded = initialize_with_fallback(
        model_path,
        settings,
        profile,
        best_layers,
        clear_log=True,
    )
    actual_layers = loaded[4]
    if actual_layers != best_layers:
        # Initialization can degrade to fewer layers if memory pressure changed
        # between the benchmark and final load. Persist what actually loaded.
        try:
            saved = json.loads(TUNING_CONFIG_PATH.read_text(encoding="utf-8"))
            saved["gpu_layers"] = actual_layers
            saved["post_benchmark_fallback"] = True
            TUNING_CONFIG_PATH.write_text(json.dumps(saved, indent=2), encoding="utf-8")
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    return loaded


# ---------------------------------------------------------------------------
# Terminal UI and main application
# ---------------------------------------------------------------------------
def show_help(supports_toggle: bool) -> None:
    toggle_note = (
        "[green]Thinking switch: verified by GGUF template self-test[/green]"
        if supports_toggle
        else "[yellow]Thinking switch: not verified by this GGUF template[/yellow]"
    )
    console.print(
        Panel(
            "[bold]Commands[/bold]\n"
            "[cyan]/fast[/cyan]       Fast response mode; template thinking OFF\n"
            "[cyan]/think[/cyan]      Enable model thinking for subsequent turns\n"
            "[cyan]/mode[/cyan]       Show current mode\n"
            "[cyan]/status[/cyan]     Show hardware/backend/template status\n"
            "[cyan]/bench[/cyan]      Benchmark the currently loaded backend\n"
            "[magenta]/autotune[/magenta]  Compare full GPU, partial GPU and CPU; save fastest\n"
            "[magenta]research <q>[/magenta] Long-form offline analysis (thinking OFF; no web retrieval)\n"
            "[cyan]/clear[/cyan]      Clear conversation history\n"
            "[cyan]/help[/cyan]       Show commands\n"
            "[red]/exit[/red]       Exit\n\n"
            + toggle_note,
            title="DESTROYER AI HELP",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )


def show_status(
    profile: HardwareProfile,
    settings: RuntimeSettings,
    backend_status: str,
    gpu_layers: int,
    template_source: str,
    supports_toggle: bool,
) -> None:
    ram = (
        f"{profile.available_ram_gb:.1f}/{profile.total_ram_gb:.1f} GB available/total"
        if profile.available_ram_gb is not None and profile.total_ram_gb is not None
        else "RAM telemetry unavailable"
    )
    gpu = ", ".join(profile.vulkan_devices) if profile.vulkan_devices else "No Vulkan GPU detected"
    console.print(
        Panel(
            f"CPU: {profile.cpu_name} ({profile.physical_cores} physical / {profile.logical_cores} logical cores)\n"
            f"Memory: {ram}\n"
            f"Vulkan physical device(s): {gpu}\n"
            f"llama.cpp GPU backend support: {profile.llama_gpu_offload_supported} "
            f"({profile.llama_gpu_support_detail})\n"
            f"llama.cpp status: {backend_status}\n"
            f"Requested n_gpu_layers: {gpu_layers}\n"
            f"Context/batch/ubatch: {settings.n_ctx}/{settings.n_batch}/{settings.n_ubatch}\n"
            f"CPU threads: {settings.n_threads}/{settings.n_threads_batch}\n"
            f"llama-cpp-python: {getattr(llama_cpp, '__version__', 'unknown')}\n"
            f"Chat template: {template_source}\n"
            f"Thinking template toggle: {'verified' if supports_toggle else 'NOT verified'}\n"
            f"Backend log: {BACKEND_LOG_PATH}",
            title="RUNTIME STATUS",
            border_style="cyan",
        )
    )


def print_metrics(metrics: dict[str, float | int], mode: str) -> None:
    hidden_note = " (includes hidden reasoning)" if metrics.get("prompt_opens_thinking", 0) else ""
    backend_decode = metrics.get("backend_decode_tps")
    backend_prompt = metrics.get("backend_prompt_tps")
    backend_note = (
        f" | llama.cpp decode: {float(backend_decode):.2f} tok/s"
        if backend_decode is not None else " | backend decode rate unavailable"
    )
    prompt_note = (
        f" | prompt eval: {float(backend_prompt):.2f} tok/s"
        if backend_prompt is not None else ""
    )
    console.print(
        "[dim]Prompt: {prompt} tokens | Generated: {generated} tokens{hidden} | "
        "Visible: {visible} | TTFT: {ttft:.2f}s | Total: {total:.2f}s | "
        "Wall decode: {tps:.2f} tok/s{backend}{prefill}[/dim]".format(
            prompt=metrics["prompt_tokens"],
            generated=metrics["generated_tokens"],
            hidden=hidden_note,
            visible=metrics["visible_tokens"],
            ttft=metrics["ttft_seconds"],
            total=metrics["total_seconds"],
            tps=metrics["wall_decode_tps"],
            backend=backend_note,
            prefill=prompt_note,
        )
    )
    if metrics["unfinished_thought"]:
        console.print(
            "[yellow]The model did not finish its thinking block within the token budget; "
            "no internal trace was displayed. Increase DESTROYER_THINK_TOKENS or use /fast.[/yellow]"
        )
    if metrics["was_truncated"]:
        console.print(
            "[yellow]Generation stopped at max_tokens. Increase the relevant token limit "
            "or ask for a shorter answer if the response is incomplete.[/yellow]"
        )


def run_chat(args: argparse.Namespace) -> None:
    model_path = find_model_path()
    profile = detect_hardware()
    settings = choose_settings(profile)
    requested_layers = choose_initial_gpu_layers(profile, model_path, settings)

    ram_banner = (
        f"{profile.available_ram_gb:.1f} GB available / {profile.total_ram_gb:.1f} GB total"
        if profile.available_ram_gb is not None and profile.total_ram_gb is not None
        else "RAM telemetry unavailable (conservative profile selected)"
    )
    console.print(
        Panel(
            f"[bold cyan]DESTROYER AI v{APP_VERSION}[/bold cyan]\n"
            "[dim]Adaptive local GGUF inference • Rich terminal interface[/dim]\n"
            f"[dim]Model: {model_path.name}[/dim]\n"
            f"[dim]RAM: {ram_banner}[/dim]\n"
            f"[dim]CPU: {profile.physical_cores} physical / {profile.logical_cores} logical cores[/dim]",
            title="HARDWARE DETECTION",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )
    if profile.has_vulkan_gpu:
        console.print(f"[green]Vulkan device detected:[/green] {', '.join(profile.vulkan_devices)}")
    else:
        console.print("[yellow]No Vulkan physical GPU was detected. Selecting CPU inference.[/yellow]")

    if args.autotune:
        # Do not load the model once just to close it before the benchmark.
        # The autotuner loads each candidate directly, then leaves the winner loaded.
        try:
            llm, formatter, supports_toggle, backend_status, gpu_layers, template_source = run_autotune(
                model_path, settings, profile, None
            )
        except Exception as exc:
            console.print(
                f"[yellow]Startup autotune failed ({type(exc).__name__}: {exc}); "
                "restoring the safest available backend.[/yellow]"
            )
            llm, formatter, supports_toggle, backend_status, gpu_layers, template_source = initialize_with_fallback(
                model_path, settings, profile, requested_layers, clear_log=True
            )
    else:
        with console.status(
            "[bold cyan]Initializing model and verifying the backend/chat template...[/bold cyan]",
            spinner="dots",
        ):
            llm, formatter, supports_toggle, backend_status, gpu_layers, template_source = initialize_with_fallback(
                model_path,
                settings,
                profile,
                requested_layers,
                clear_log=True,
            )

    # Show READY only after the selected model/backend and template are loaded.
    console.print(
        Panel(
            f"Backend: [bold]{backend_status}[/bold]\n"
            f"GPU layer request (n_gpu_layers): {gpu_layers}\n"
            f"Context: {settings.n_ctx} | Batch: {settings.n_batch}/{settings.n_ubatch}\n"
            f"Chat template: {template_source}\n"
            f"Thinking toggle: {'[green]verified[/green]' if supports_toggle else '[yellow]not verified[/yellow]'}\n"
            f"Default mode: [green]FAST[/green] / "
            f"{'[green]THINKING OFF verified[/green]' if supports_toggle else '[yellow]GGUF template default; switch unverified[/yellow]'}\n"
            "Thinking mode: optional; /think requests the native template switch.\n"
            "Research mode: longer offline analysis using the non-thinking state; use /think for explicit reasoning.\n"
            "No live web retrieval or image input is configured in this terminal build.\n"
            "Use [magenta]research <question>[/magenta] for extended offline analysis.\n"
            "Use [cyan]/autotune[/cyan] to compare Vulkan/CPU configurations and save the fastest measured path.\n"
            f"Backend log: [dim]{BACKEND_LOG_PATH.name}[/dim]",
            title="DESTROYER AI READY",
            border_style="cyan",
            box=box.DOUBLE,
        )
    )

    history: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    current_mode = "fast"

    try:
        with console.status("[cyan]Warming the inference graph for the first reply...[/cyan]", spinner="dots"):
            warmup_seconds = warmup_model(llm, formatter)
        console.print(f"[dim]Warm-up complete: {warmup_seconds:.2f}s. Ready for interactive inference.[/dim]")
    except Exception as exc:
        console.print(f"[yellow]Warm-up skipped ({type(exc).__name__}: {exc}); normal inference remains available.[/yellow]")

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
                show_help(supports_toggle)
                continue
            if lowered == "/clear":
                history = [{"role": "system", "content": SYSTEM_PROMPT}]
                llm.reset()
                console.print("[green]Conversation history cleared.[/green]")
                continue
            if lowered == "/fast":
                current_mode = "fast"
                console.print("[green]Fast mode selected; thinking OFF when the GGUF template supports it.[/green]")
                continue
            if lowered == "/think":
                if not supports_toggle:
                    console.print(
                        "[yellow]This GGUF template did not pass the enable_thinking self-test. "
                        "Thinking mode cannot be switched reliably with this file.[/yellow]"
                    )
                    continue
                current_mode = "think"
                console.print("[cyan]Thinking mode enabled. Internal think text will be hidden.[/cyan]")
                continue
            if lowered == "/mode":
                console.print(f"Current mode: [bold]{current_mode.upper()}[/bold]")
                continue
            if lowered == "/status":
                show_status(profile, settings, backend_status, gpu_layers, template_source, supports_toggle)
                continue
            if lowered == "/bench":
                with console.status("[cyan]Warm-up and 3-run backend benchmark (no UI overhead)...[/cyan]", spinner="dots"):
                    _ = benchmark_one(llm, formatter, max_tokens=16)
                    samples = [benchmark_one(llm, formatter, max_tokens=64)[0] for _ in range(3)]
                valid = [value for value in samples if value > 0]
                if valid:
                    console.print(
                        f"[bold green]Median end-to-end response throughput: "
                        f"{statistics.median(valid):.2f} effective tok/s[/bold green] "
                        f"(samples: {', '.join(f'{v:.2f}' for v in valid)})"
                    )
                else:
                    console.print("[yellow]Benchmark produced no valid samples.[/yellow]")
                continue
            if lowered == "/autotune":
                try:
                    llm, formatter, supports_toggle, backend_status, gpu_layers, template_source = run_autotune(
                        model_path, settings, profile, llm
                    )
                except Exception as exc:
                    # If tuning failed after closing the active model, recover
                    # automatically using the originally selected configuration.
                    console.print(
                        f"[yellow]Autotune failed ({type(exc).__name__}: {exc}); "
                        "reloading the default backend.[/yellow]"
                    )
                    llm, formatter, supports_toggle, backend_status, gpu_layers, template_source = initialize_with_fallback(
                        model_path, settings, profile, choose_initial_gpu_layers(profile, model_path, settings), clear_log=True
                    )
                try:
                    with console.status("[cyan]Warming the selected backend...[/cyan]", spinner="dots"):
                        warmup_seconds = warmup_model(llm, formatter)
                    console.print(f"[dim]Selected backend warm-up: {warmup_seconds:.2f}s.[/dim]")
                except Exception as exc:
                    console.print(f"[yellow]Warm-up skipped: {type(exc).__name__}: {exc}[/yellow]")
                show_status(profile, settings, backend_status, gpu_layers, template_source, supports_toggle)
                continue

            is_research = lowered.startswith("research ")
            if is_research:
                question = user_input[len("research "):].strip()
                if not question:
                    console.print("[yellow]Usage: research <question>[/yellow]")
                    continue
                turn_mode = "research"
                user_content = RESEARCH_INSTRUCTION + question
                max_tokens = RESEARCH_MAX_TOKENS
                if not supports_toggle:
                    console.print(
                        "[yellow]Template thinking switch is not verified; research will use the GGUF template default. "
                        "This remains offline analysis, not web research.[/yellow]"
                    )
            else:
                turn_mode = current_mode
                user_content = user_input
                max_tokens = THINK_MAX_TOKENS if turn_mode == "think" else FAST_MAX_TOKENS

            if turn_mode == "think" and not supports_toggle:
                console.print(
                    "[yellow]Thinking control is not verified for this GGUF. "
                    "Use /fast or install a GGUF with a compatible embedded Qwen chat template.[/yellow]"
                )
                continue

            history.append({"role": "user", "content": user_content})
            try:
                answer, metrics = generate_stream(
                    llm,
                    formatter,
                    history,
                    mode=turn_mode,
                    max_tokens=max_tokens,
                    supports_thinking_toggle=supports_toggle,
                )
                if answer:
                    history.append({"role": "assistant", "content": answer})
                else:
                    history.pop()
                print_metrics(metrics, turn_mode)
            except KeyboardInterrupt:
                if history and history[-1]["role"] == "user":
                    history.pop()
                llm.reset()
                console.print("\n[yellow]Generation interrupted.[/yellow]")
            except Exception as exc:
                if history and history[-1]["role"] == "user":
                    history.pop()
                try:
                    llm.reset()
                except Exception:
                    pass
                console.print(
                    Panel(
                        f"[red]{type(exc).__name__}: {exc}[/red]",
                        title="GENERATION ERROR",
                        border_style="red",
                    )
                )
    finally:
        console.print("[dim]Releasing model resources...[/dim]")
        try:
            llm.close()
        except Exception:
            pass
        del llm
        gc.collect()
        console.print("[green]Destroyer AI shut down.[/green]")


def run_diagnostics() -> int:
    """Report the selected Python, bindings, Vulkan runtime and detected device."""
    profile = detect_hardware()
    settings = choose_settings(profile)
    model_text = str(DEFAULT_MODEL_PATH)
    console.print(
        Panel(
            f"Python: {sys.version.split()[0]}\n"
            f"Executable: {sys.executable}\n"
            f"llama-cpp-python: {getattr(llama_cpp, '__version__', 'unknown')}\n"
            f"Model default: {model_text}\n"
            f"CPU: {profile.cpu_name}\n"
            f"Cores: {profile.physical_cores} physical / {profile.logical_cores} logical\n"
            f"RAM: {profile.available_ram_gb!s} GiB available / {profile.total_ram_gb!s} GiB total\n"
            f"Vulkan tool: {profile.vulkan_tool}\n"
            f"Vulkan devices: {', '.join(profile.vulkan_devices) if profile.vulkan_devices else 'none'}\n"
            f"llama.cpp GPU offload support: {profile.llama_gpu_offload_supported}\n"
            f"GPU support detail: {profile.llama_gpu_support_detail}\n"
            f"Auto settings: ctx={settings.n_ctx}, batch={settings.n_batch}, "
            f"ubatch={settings.n_ubatch}, threads={settings.n_threads}",
            title="DESTROYER AI DIAGNOSTICS",
            border_style="cyan",
        )
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Adaptive Destroyer AI local GGUF assistant")
    parser.add_argument(
        "--autotune",
        action="store_true",
        help="benchmark full GPU, partial GPU and CPU before entering chat",
    )
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="detect Python, llama.cpp GPU backend, Vulkan device and automatic settings",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.diagnose:
            return run_diagnostics()
        run_chat(args)
        return 0
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        return 130
    except Exception as exc:
        console.print(
            Panel(
                f"[bold red]{type(exc).__name__}: {exc}[/bold red]",
                title="FATAL ERROR",
                border_style="red",
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
