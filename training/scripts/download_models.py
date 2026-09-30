import argparse
from huggingface_hub import snapshot_download
from browser_training.launch import MODEL_CACHE_PATTERNS, REVISIONS
p = argparse.ArgumentParser()
p.add_argument('models', nargs='+', choices=['fp8', 'bf16', 'nf4', 'smoke'])
a = p.parse_args()
for key in a.models:
    model = {'fp8': 'Qwen/Qwen3.8-27B-FP8', 'bf16': 'Qwen/Qwen3.8-27B',
             'nf4': 'greghavens/Qwen3.8-27B-bnb-4bit', 'smoke': 'Qwen/Qwen3-0.6B'}[key]
    revision = '26157380225e427827263c34df23018a1e28dff5' if key == 'nf4' else REVISIONS[model]
    path = snapshot_download(model, revision=revision, allow_patterns=MODEL_CACHE_PATTERNS)
    print(model, revision, path)
