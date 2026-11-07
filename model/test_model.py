import os
import sys
import time
import gc
import ctypes
import platform
import llama_cpp
from llama_cpp import Llama

# Optional CPU Speculative Decoding support built into llama-cpp-python
try:
    from llama_cpp.llama_speculative import LlamaPromptLookupDecoding
    HAS_SPECULATIVE = True
except ImportError:
    HAS_SPECULATIVE = False

MODEL_PATH = r"C:\Users\des\OneDrive\Desktop\clint\Huihui-Qwen3.5-4B-abliterated.Q4_K_M.gguf"

# =====================================================================
# 1. SYSTEM & C++ BACKEND DIAGNOSTICS (Zero extra libraries required)
# =====================================================================
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
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]

def get_memory_info():
    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
    return {
        "total_ram_gb": stat.ullTotalPhys / (1024**3),
        "avail_ram_gb": stat.ullAvailPhys / (1024**3),
        "ram_load_pct": stat.dwMemoryLoad,
        "used_pagefile_gb": (stat.ullTotalPageFile - stat.ullAvailPageFile) / (1024**3),
        "total_pagefile_gb": stat.ullTotalPageFile / (1024**3),
    }

def get_cpp_backend_flags():
    try:
        raw_info = llama_cpp.llama_print_system_info().decode("utf-8", errors="ignore")
        return raw_info.strip()
    except Exception as e:
        return f"Unavailable ({e})"

def print_system_header():
    mem = get_memory_info()
    cpp_flags = get_cpp_backend_flags()
    has_avx2 = "AVX2 = 1" in cpp_flags
    has_fma = "FMA = 1" in cpp_flags

    print("=" * 78)
    print("                 DESTROYER LOCAL AI BENCHMARK & DIAGNOSTICS                 ")
    print("=" * 78)
    print(f" OS / Platform     : {platform.system()} {platform.release()} ({platform.version()})")
    print(f" Logical CPUs      : {os.cpu_count()} Cores")
    print(f" Physical RAM      : {mem['avail_ram_gb']:.2f} GB Free / {mem['total_ram_gb']:.2f} GB Total ({mem['ram_load_pct']}% Used)")
    print(f" Virtual Commit    : {mem['used_pagefile_gb']:.2f} GB Used / {mem['total_pagefile_gb']:.2f} GB Max")
    print(f" Model File        : {os.path.basename(MODEL_PATH)} ({os.path.getsize(MODEL_PATH)/(1024**3):.2f} GB)")
    print("-" * 78)
    print(f" C++ Build Flags   : {cpp_flags}")
    print(f" Vector Math Check : AVX2={'ENABLED' if has_avx2 else 'MISSING!'} | FMA={'ENABLED' if has_fma else 'MISSING!'}")
    if mem["avail_ram_gb"] < 3.5:
        print(" [!] WARNING       : Available RAM is below 3.5 GB! Close background apps to avoid swap lag.")
    print("=" * 78)

# =====================================================================
# 2. PHASE 1: HARDWARE PARAMETER MATRIX
# =====================================================================
HW_CONFIGS = [
    {"name": "3T | Batch 256 | Std",        "threads": 3, "batch": 256, "flash_attn": False, "speculative": False},
    {"name": "3T | Batch 512 | Std",        "threads": 3, "batch": 512, "flash_attn": False, "speculative": False},
    {"name": "4T | Batch 512 | Std",        "threads": 4, "batch": 512, "flash_attn": False, "speculative": False},
    {"name": "4T | Batch 512 | FlashAttn",  "threads": 4, "batch": 512, "flash_attn": True,  "speculative": False},
]

if HAS_SPECULATIVE:
    HW_CONFIGS.append(
        {"name": "4T | B512 | Flash + Lookup", "threads": 4, "batch": 512, "flash_attn": True, "speculative": True}
    )

HW_PROMPT = (
    "<|im_start|>system\nYou are a fast network parser.<|im_end|>\n"
    "<|im_start|>user\nExtract the IP, port, and status from this log into JSON: "
    "'Node 192.168.31.182 responded on port 8080 with status ONLINE_READY'.<|im_end|>\n"
    "<|im_start|>assistant\n<think>\n\n</think>\n\n"
)

def run_hardware_matrix():
    print("\n[PHASE 1] RUNNING HARDWARE CONFIGURATION MATRIX (No-Think Baseline)")
    print("-" * 78)
    print(f"{'CONFIG NAME':<28} | {'LOAD(s)':<7} | {'PROMPT(t/s)':<11} | {'GEN(t/s)':<9} | {'RAM FREE':<8}")
    print("-" * 78)

    results = []
    for cfg in HW_CONFIGS:
        gc.collect()
        t_load_start = time.perf_counter()
        try:
            draft = LlamaPromptLookupDecoding(num_pred_tokens=3) if cfg["speculative"] else None
            llm = Llama(
                model_path=MODEL_PATH,
                n_ctx=2048,
                n_threads=cfg["threads"],
                n_threads_batch=4,
                n_batch=cfg["batch"],
                n_ubatch=cfg["batch"],
                flash_attn=cfg["flash_attn"],
                draft_model=draft,
                n_gpu_layers=0,
                use_mmap=True,
                verbose=False,
            )
            load_time = time.perf_counter() - t_load_start

            # Warmup pass (1 token) to measure Prompt Evaluation speed (TTFT)
            t_p_start = time.perf_counter()
            p_res = llm(HW_PROMPT, max_tokens=1, temperature=0.0, stop=["<|im_end|>"])
            p_time = time.perf_counter() - t_p_start
            p_tokens = p_res["usage"]["prompt_tokens"]
            prompt_tps = p_tokens / p_time if p_time > 0 else 0

            # Reset KV cache so generation test evaluates cleanly
            llm.reset()

            # Full generation pass
            t_g_start = time.perf_counter()
            g_res = llm(HW_PROMPT, max_tokens=45, temperature=0.1, stop=["<|im_end|>"])
            total_time = time.perf_counter() - t_g_start

            gen_tokens = g_res["usage"]["completion_tokens"]
            # Subtract prompt eval time to isolate pure token generation speed
            gen_only_time = max(total_time - p_time, 0.01)
            gen_tps = gen_tokens / gen_only_time
            e2e_tps = gen_tokens / total_time

            avail_ram = get_memory_info()["avail_ram_gb"]

            row = {
                **cfg,
                "load_time": load_time,
                "prompt_tps": prompt_tps,
                "gen_tps": gen_tps,
                "e2e_tps": e2e_tps,
                "avail_ram": avail_ram,
            }
            results.append(row)
            print(f"{cfg['name']:<28} | {load_time:<7.2f} | {prompt_tps:<11.2f} | {gen_tps:<9.2f} | {avail_ram:.2f} GB")

            llm.close()
            del llm
            gc.collect()

        except Exception as e:
            print(f"{cfg['name']:<28} | FAILED: {e}")

    results.sort(key=lambda x: x["gen_tps"], reverse=True)
    return results

# =====================================================================
# 3. PHASE 2: THINKING vs. EFFORT MODE BENCHMARK
# =====================================================================
TASK_USER_PROMPT = (
    "Scraped HTML snippet: `<div class='price'>$49.99</div><script src='ads.js'></script>"
    "<p>Stock: In Stock (12 units)</p>`. "
    "Extract Product Price and Stock Count as 2 short bullet points."
)

def run_effort_benchmark(best_hw):
    print("\n[PHASE 2] THINKING & EFFORT MODE BENCHMARK (Using Best Hardware Config)")
    print(f"Active Hardware Settings: {best_hw['name']}")
    print("-" * 78)

    draft = LlamaPromptLookupDecoding(num_pred_tokens=3) if best_hw["speculative"] else None
    llm = Llama(
        model_path=MODEL_PATH,
        n_ctx=2048,
        n_threads=best_hw["threads"],
        n_threads_batch=4,
        n_batch=best_hw["batch"],
        n_ubatch=best_hw["batch"],
        flash_attn=best_hw["flash_attn"],
        draft_model=draft,
        n_gpu_layers=0,
        use_mmap=True,
        verbose=False,
    )

    modes = [
        {
            "mode": "1. NO_THINK (Instant)",
            "type": "single",
            "prompt": (
                "<|im_start|>system\nYou are a concise data extractor.<|im_end|>\n"
                f"<|im_start|>user\n{TASK_USER_PROMPT}<|im_end|>\n"
                "<|im_start|>assistant\n<think>\n\n</think>\n\n"
            ),
            "max_tokens": 80,
        },
        {
            "mode": "2. LOW_EFFORT (Guided 1-Line)",
            "type": "single",
            "prompt": (
                "<|im_start|>system\nYou are a concise data extractor. Think in 1 short sentence only.<|im_end|>\n"
                f"<|im_start|>user\n{TASK_USER_PROMPT}<|im_end|>\n"
                "<|im_start|>assistant\n<think>\nQuick check: ignore script tag, grab price and stock."
            ),
            "max_tokens": 120,
        },
        {
            "mode": "3. BUDGET_THINK (Max 25 Tok)",
            "type": "budget",
            "think_budget": 25,
            "prompt": (
                "<|im_start|>system\nYou are a concise data extractor.<|im_end|>\n"
                f"<|im_start|>user\n{TASK_USER_PROMPT}<|im_end|>\n"
                "<|im_start|>assistant\n<think>\n"
            ),
            "max_tokens": 80,
        },
        {
            "mode": "4. FULL_THINK (Unrestricted)",
            "type": "single",
            "prompt": (
                "<|im_start|>system\nYou are a concise data extractor.<|im_end|>\n"
                f"<|im_start|>user\n{TASK_USER_PROMPT}<|im_end|>\n"
                "<|im_start|>assistant\n<think>\n"
            ),
            "max_tokens": 220,
        },
    ]

    print(f"{'EFFORT MODE':<28} | {'THINK TOK':<9} | {'ANS TOK':<7} | {'TOTAL TIME':<10} | {'SPEED(t/s)':<10}")
    print("-" * 78)

    mode_results = []
    for m in modes:
        llm.reset()
        t0 = time.perf_counter()

        if m["type"] == "single":
            res = llm(m["prompt"], max_tokens=m["max_tokens"], temperature=0.2, stop=["<|im_end|>"])
            raw_text = res["choices"][0]["text"]
            total_tok = res["usage"]["completion_tokens"]

            if "</think>" in raw_text:
                think_part, ans_part = raw_text.split("</think>", 1)
                think_tok = len(llm.tokenize(think_part.encode("utf-8")))
                ans_tok = max(total_tok - think_tok, 1)
            else:
                think_part = ""
                ans_part = raw_text
                think_tok = 0
                ans_tok = total_tok

        elif m["type"] == "budget":
            # Stage 1: Generate up to `think_budget` thinking tokens
            res_think = llm(
                m["prompt"],
                max_tokens=m["think_budget"],
                temperature=0.2,
                stop=["</think>", "<|im_end|>"],
            )
            think_part = res_think["choices"][0]["text"]
            think_tok = res_think["usage"]["completion_tokens"]

            # Stage 2: Force close </think> and generate the answer immediately
            forced_prompt = m["prompt"] + think_part + "\n</think>\n\n"
            res_ans = llm(
                forced_prompt,
                max_tokens=m["max_tokens"],
                temperature=0.2,
                stop=["<|im_end|>"],
            )
            ans_part = res_ans["choices"][0]["text"]
            ans_tok = res_ans["usage"]["completion_tokens"]
            total_tok = think_tok + ans_tok

        elapsed = time.perf_counter() - t0
        tps = total_tok / elapsed if elapsed > 0 else 0

        mode_results.append({
            "mode": m["mode"],
            "think_tok": think_tok,
            "ans_tok": ans_tok,
            "elapsed": elapsed,
            "tps": tps,
            "answer_preview": ans_part.strip().replace("\n", " "),
        })

        print(f"{m['mode']:<28} | {think_tok:<9} | {ans_tok:<7} | {elapsed:<8.2f} s | {tps:<10.2f}")

    llm.close()
    del llm
    gc.collect()
    return mode_results

# =====================================================================
# 4. MAIN RUNNER & FINAL REPORT
# =====================================================================
if __name__ == "__main__":
    if not os.path.exists(MODEL_PATH):
        print(f"ERROR: Model file not found at {MODEL_PATH}")
        sys.exit(1)

    print_system_header()
    hw_results = run_hardware_matrix()

    if not hw_results:
        print("All hardware tests failed.")
        sys.exit(1)

    best_hw = hw_results[0]
    effort_results = run_effort_benchmark(best_hw)

    print("\n" + "=" * 78)
    print("                     OUTPUT QUALITY VERIFICATION PREVIEW                     ")
    print("=" * 78)
    for er in effort_results:
        print(f" {er['mode']:<28} -> {er['answer_preview'][:75]}")

    print("\n" + "=" * 78)
    print("                FINAL RECOMMENDED CONFIGURATION FOR DESTROYER                ")
    print("=" * 78)
    print(f" Winning Hardware Setup : {best_hw['name']} ({best_hw['gen_tps']:.2f} tokens/sec)")
    print(f" Fastest Agent Mode     : {effort_results[0]['mode']} ({effort_results[0]['elapsed']:.2f}s total wait)")
    print(f" Best Balanced Reasoning: {effort_results[2]['mode']} ({effort_results[2]['elapsed']:.2f}s total wait)")
    print("-" * 78)
    print(" Copy-Paste Llama() Init for Your Scripts:")
    print(
        f" llm = Llama(model_path=MODEL_PATH, n_ctx=2048, n_threads={best_hw['threads']}, "
        f"n_threads_batch=4, n_batch={best_hw['batch']}, flash_attn={best_hw['flash_attn']}, n_gpu_layers=0)"
    )
    print("=" * 78)