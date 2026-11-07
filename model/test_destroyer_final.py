import importlib.util
import json
import os
import tempfile
import sys
import types
from types import SimpleNamespace
from pathlib import Path

# Minimal package stubs: this environment does not contain the native llama_cpp wheel.
pkg = types.ModuleType('llama_cpp')
pkg.__path__ = []
pkg.__version__ = '0.3.36'
class DummyLlama:
    pass
pkg.Llama = DummyLlama
native = types.ModuleType('llama_cpp.llama_cpp')
native.llama_supports_gpu_offload = lambda: True
pkg.llama_cpp = native
chat = types.ModuleType('llama_cpp.llama_chat_format')
class Jinja2ChatFormatter:
    def __init__(self, template, eos_token, bos_token, add_generation_prompt=True, stop_token_ids=None):
        from jinja2 import Environment
        self.env = Environment(trim_blocks=True, lstrip_blocks=True)
        self.template = template
        self.eos_token = eos_token
        self.bos_token = bos_token
        self.add_generation_prompt = add_generation_prompt
        self.stop_token_ids = stop_token_ids
    def __call__(self, *, messages, **kwargs):
        prompt = self.env.from_string(self.template).render(
            messages=messages, eos_token=self.eos_token, bos_token=self.bos_token,
            add_generation_prompt=self.add_generation_prompt, **kwargs
        )
        return SimpleNamespace(prompt=prompt, stop=[self.eos_token], stopping_criteria=None, added_special=True)
chat.Jinja2ChatFormatter = Jinja2ChatFormatter
sys.modules['llama_cpp'] = pkg
sys.modules['llama_cpp.llama_cpp'] = native
sys.modules['llama_cpp.llama_chat_format'] = chat

path = Path('/mnt/data/DestroyerAI_Final.py')
spec = importlib.util.spec_from_file_location('destroyer_final_test', path)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

# GPU backend parser: confirmed only when device + positive layer-offload evidence exist.
log = '''ggml_vulkan: Found 1 Vulkan devices:\nggml_vulkan: 0 = AMD Radeon(TM) Vega 8 Graphics (AMD proprietary driver)\nllama_model_load: offloaded 33/33 layers to GPU\n'''
status, count, total = mod.parse_backend_status(log, -1)
assert status.startswith('Vulkan GPU offload confirmed'), status
assert (count, total) == (33, 33), (count, total)
status2, count2, _ = mod.parse_backend_status('llama_model_load: offloaded 0/33 layers to GPU', 0)
assert count2 == 0 and 'zero gpu' in status2.lower(), status2
status3, count3, _ = mod.parse_backend_status(log, 0)
assert count3 == 0 and status3.startswith('CPU-only mode selected'), status3

# Streaming hidden-thought filter handles split tags.
f = mod.ThoughtFilter(False)
out = f.feed('Hello <thi') + f.feed('nk>secret</thi') + f.feed('nk> world')
tail, unfinished = f.finish()
assert (out + tail) == 'Hello  world', (out, tail)
assert not unfinished
f2 = mod.ThoughtFilter(True)
out = f2.feed('internal reasoning') + f2.feed('</think>Final answer')
tail, unfinished = f2.finish()
assert out + tail == 'Final answer'
assert not unfinished

# Settings and performance parser.
unknown = mod.HardwareProfile('CPU', 4, 4, None, None, [], '', None, None, 'unknown', '')
assert mod.choose_settings(unknown).n_ctx == 2048
sample = '''llama_perf_context_print: prompt eval time = 3603.92 ms / 92 tokens (39.17 ms per token, 25.53 tokens per second)\nllama_perf_context_print: eval time = 10191.45 ms / 106 runs (96.15 ms per token, 10.40 tokens per second)'''
perf = mod.parse_llama_perf(sample)
assert perf['backend_decode_tps'] == 10.40
assert perf['backend_prompt_tps'] == 25.53

# Native Qwen3.5-style hard thinking switch self-test.
template = '''{% for message in messages %}{{ '<|im_start|>' + message['role'] + '\\n' + message['content'] + '<|im_end|>\\n' }}{% endfor %}{% if add_generation_prompt %}{{ '<|im_start|>assistant\\n' }}{% if enable_thinking is defined and enable_thinking is false %}{{ '<think>\\n\\n</think>\\n\\n' }}{% else %}{{ '<think>\\n' }}{% endif %}{% endif %}'''
class FakeLLM:
    metadata = {'tokenizer.chat_template': template}
    def token_eos(self): return 2
    def token_bos(self): return 1
    def detokenize(self, token_ids, special=False): return b'<eos>' if token_ids[0] == 2 else b'<bos>'
formatter, supports, source = mod.build_template_formatter(FakeLLM(), Path('/tmp/model.gguf'))
assert supports, 'Qwen3.5 thinking switch was not detected'
fast = formatter(messages=[{'role':'user','content':'hello'}], enable_thinking=False).prompt
think = formatter(messages=[{'role':'user','content':'hello'}], enable_thinking=True).prompt
assert fast.rstrip().endswith('</think>')
assert think.rstrip().endswith('<think>')

print('PASS: syntax/import, GPU log parser, thought filter, RAM fallback, perf parser, Qwen template switch')

# Verify the shipped Huihui/Qwen-style cache-prefix workaround and prefix self-test.
legacy_template = r'''{% set ns = namespace(last_query_index=0) %}{% for m in messages %}{% if m.role == 'user' %}{% set ns.last_query_index = loop.index0 %}{% endif %}{% endfor %}{% for message in messages %}{% if message.role == 'user' %}{{ '<|im_start|>user\n' + message.content + '<|im_end|>\n' }}{% elif message.role == 'assistant' %}{% set content = message.content %}{% set reasoning_content = '' %}{% if loop.index0 > ns.last_query_index %}{{ '<|im_start|>assistant\n<think>\n' + content + '\n</think>\n\n' }}{% else %}{{ '<|im_start|>assistant\n' + content }}{% endif %}{{ '<|im_end|>\n' }}{% endif %}{% endfor %}{% if add_generation_prompt %}{{ '<|im_start|>assistant\n' }}{% if enable_thinking is defined and enable_thinking is false %}{{ '<think>\n\n</think>\n\n' }}{% else %}{{ '<think>\n' }}{% endif %}{% endif %}'''
patched_template, was_patched = mod.apply_qwen_cache_prefix_fix(legacy_template)
assert was_patched and 'loop.index0 > ns.last_query_index' in patched_template
already_patched, patched_again = mod.apply_qwen_cache_prefix_fix(patched_template)
assert not patched_again and already_patched == patched_template, 'Qwen template patch must be idempotent'
assert '{%- elif enable_thinking is defined and enable_thinking is false %}' in patched_template
assert 'reasoning_content' in patched_template  # thinking-enabled history branch is preserved
class FakeCacheLLM(FakeLLM):
    metadata = {'tokenizer.chat_template': legacy_template}
formatter2, supports2, source2 = mod.build_template_formatter(FakeCacheLLM(), Path('/tmp/model.gguf'))
assert supports2
assert getattr(formatter2, '_destroyer_prefix_cache_safe', False), source2
assert 'Qwen KV-cache-prefix compatibility patch' in source2
fast_history = formatter2(messages=[{'role':'user','content':'one'}, {'role':'assistant','content':'answer'}, {'role':'user','content':'two'}], enable_thinking=False).prompt
think_history = formatter2(messages=[{'role':'user','content':'one'}, {'role':'assistant','content':'answer'}, {'role':'user','content':'two'}], enable_thinking=True).prompt
assert '<think>\n\n</think>\n\nanswer' in fast_history, fast_history
assert '<think>\n\n</think>\n\nanswer' not in think_history, think_history
print('PASS: upstream Qwen cache-prefix issue patched with minimal elif; thinking-on serialization preserved')

# A previous candidate's layer-allocation line must never validate a new load.
old_attempt = log
validation_without_current_allocation = mod.compose_backend_validation_log(
    "", old_attempt, "new candidate: model-load attempted; no offload record"
)
status_stale, stale_count, _ = mod.parse_backend_status(
    validation_without_current_allocation, 24
)
assert stale_count is None and not status_stale.startswith("Vulkan GPU offload confirmed"), status_stale
current_attempt = "llama_model_load: offloaded 16/33 layers to GPU"
validation_current = mod.compose_backend_validation_log("", old_attempt, current_attempt)
status_current, current_count, _ = mod.parse_backend_status(validation_current, 16)
assert current_count == 16 and status_current.startswith("Vulkan GPU offload confirmed"), status_current

# Tuning cache key changes with driver and memory-shape/runtime settings.
settings_a = mod.RuntimeSettings(4096, 256, 128, 4, 4)
profile_a = mod.HardwareProfile(
    "AMD Ryzen 3 3200G", 4, 4, 16.0, 8.0, ["AMD Radeon(TM) Vega 8 Graphics"],
    "GPU0:\n driverName = AMD proprietary driver\n driverInfo = 26.5.2\n apiVersion = 1.3.260",
    "vulkaninfo.exe", True, "GPU backend available", ""
)
key_a = profile_a.fingerprint(Path('/tmp/no_model.gguf'), settings_a)
profile_b = mod.HardwareProfile(
    "AMD Ryzen 3 3200G", 4, 4, 16.0, 8.0, ["AMD Radeon(TM) Vega 8 Graphics"],
    "GPU0:\n driverName = AMD proprietary driver\n driverInfo = 26.6.0\n apiVersion = 1.3.260",
    "vulkaninfo.exe", True, "GPU backend available", ""
)
assert key_a != profile_b.fingerprint(Path('/tmp/no_model.gguf'), settings_a)
assert key_a != profile_a.fingerprint(Path('/tmp/no_model.gguf'), mod.RuntimeSettings(2048, 128, 64, 4, 4))

# A matching tuning cache restores a measured thread count unless overridden.
original_tuning_path = mod.TUNING_CONFIG_PATH
old_env = {name: os.environ.get(name) for name in ('DESTROYER_GPU_LAYERS', 'DESTROYER_THREADS', 'DESTROYER_THREADS_BATCH')}
try:
    with tempfile.TemporaryDirectory() as temp_dir:
        mod.TUNING_CONFIG_PATH = Path(temp_dir) / 'tuning.json'
        saved_settings = mod.RuntimeSettings(4096, 256, 128, 4, 4)
        mod.TUNING_CONFIG_PATH.write_text(json.dumps({
            'fingerprint': profile_a.fingerprint(Path('/tmp/no_model.gguf'), saved_settings),
            'gpu_layers': 16, 'n_threads': 3, 'n_threads_batch': 3,
        }), encoding='utf-8')
        for name in old_env:
            os.environ.pop(name, None)
        chosen = mod.choose_initial_gpu_layers(profile_a, Path('/tmp/no_model.gguf'), saved_settings)
        assert chosen == 16 and (saved_settings.n_threads, saved_settings.n_threads_batch) == (3, 3)
finally:
    mod.TUNING_CONFIG_PATH = original_tuning_path
    for name, value in old_env.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

print('PASS: stale GPU log rejection, driver/runtime fingerprint invalidation, and saved thread reuse')
