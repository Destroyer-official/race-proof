# Destroyer AI — local GGUF terminal assistant

This package is configured around the user's Windows system and local model:

- CPU: AMD Ryzen 3 3200G (4 cores / 4 logical threads)
- GPU: AMD Radeon Vega 8 integrated graphics
- RAM: 16 GB DDR4, shared with the integrated GPU
- Model: `Huihui-Qwen3.5-4B-abliterated.Q4_K_M.gguf`
- Backend: `llama-cpp-python` with Vulkan support

## Files

- `destroyer_ai_final.py` — the assistant.
- `Run_Destroyer_AI.ps1` — PowerShell launcher; selects the known Python 3.15 environment, checks imports, and exposes the Vulkan SDK DLL directory.

The Python file looks for the model at the known path from the conversation. You can override it with `-ModelPath` or `DESTROYER_MODEL_PATH`.

## Prerequisites

Use the same Python interpreter that has the Vulkan-enabled `llama-cpp-python` build. `rich` is also required.

```powershell
& 'D:\program_software\sdks\Python315\python.exe' -m pip install rich
& 'D:\program_software\sdks\Python315\python.exe' -c 'import llama_cpp, rich; print(getattr(llama_cpp, "__version__", "unknown"))'
```

The Vulkan SDK and AMD Vulkan driver must already be installed. The script detects a Vulkan physical GPU with `vulkaninfo`, but the definitive offload check is llama.cpp's own `offloaded N/M layers to GPU` log line.

## Launch

From the directory containing the two files:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\Run_Destroyer_AI.ps1
```

Run a one-time backend benchmark to compare full GPU, partial GPU, and CPU-only paths:

```powershell
.\Run_Destroyer_AI.ps1 -AutoTune
```

Autotuning warms up each candidate, takes three measurements, selects the median `llama.cpp` decode rate, and saves the winning layer count to `destroyer_ai_tuning.json`. The choice is fingerprinted to the CPU, RAM, Vulkan device, model path/size, and llama-cpp-python version. A later launch reuses it. Use `/autotune` to repeat after changing drivers, package versions, or model files.

## Commands

- `/fast` — fast generation, thinking off.
- `/think` — enable the model's native thinking prompt mode, if the GGUF template passes the startup self-test.
- `/mode` — show the current mode.
- `/status` — display hardware, backend, template, and runtime configuration.
- `/bench` — warm up and measure the active backend three times without terminal UI overhead.
- `/autotune` — compare full Vulkan, partial Vulkan, and CPU-only configurations.
- `research <question>` — longer, structured **offline** analysis with thinking off.
- `/clear` — clear conversation history and reset the model context.
- `/help` — show commands.
- `/exit` — quit.

## Model-specific behavior

FAST is the default. The model author's card says the fine-tuning dataset operates in non-thinking mode. Therefore `/think` is opt-in; it is not assumed to improve every response. Research mode is longer-form answer generation with thinking disabled, not a forced hidden-reasoning run.

The assistant is local and has **no web-search or live-paper retrieval implementation**. Its `research` mode cannot verify information published after the model's training cutoff. Do not treat its offline output as current research evidence or as a substitute for external source verification.

## Automatic resource settings

At startup, the script detects available system RAM and chooses a conservative context/batch profile. On a machine with roughly 8 GB or more RAM available, it starts at 4096 context, 256 batch, and 128 microbatch. Lower available-memory levels reduce these values. CPU thread count is capped by detected logical processors. The defaults can be overridden with environment variables:

```powershell
$env:DESTROYER_N_CTX = '4096'
$env:DESTROYER_N_BATCH = '256'
$env:DESTROYER_N_UBATCH = '128'
$env:DESTROYER_THREADS = '4'
$env:DESTROYER_THREADS_BATCH = '4'
$env:DESTROYER_FAST_TOKENS = '256'
$env:DESTROYER_THINK_TOKENS = '768'
$env:DESTROYER_RESEARCH_TOKENS = '1100'
$env:DESTROYER_GPU_LAYERS = '-1'  # -1 all possible; 0 CPU only; positive partial offload
```

Do not set `DESTROYER_GPU_LAYERS` manually if you want the saved autotune choice to apply.

## Logs and generated configuration

- `destroyer_backend.log` — backend initialization, GPU device and layer-offload diagnostics, plus llama.cpp performance records.
- `destroyer_ai_tuning.json` — autotuner results and the selected GPU layer count.

The application only reports GPU offload as confirmed when it parses a positive layer count from llama.cpp's own backend log. If a requested Vulkan configuration does not confirm offload, it retries a smaller split and ultimately CPU-only mode.
