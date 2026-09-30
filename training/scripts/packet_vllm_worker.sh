#!/usr/bin/env bash
# Executed only on a rented Packet node, from a frozen minimal upload.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export PYTHONPATH="$PWD"
export HF_HOME="${HF_HOME:-$PWD/.cache/huggingface}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$PWD/.cache/uv}"
export PATH="$HOME/.local/bin:$PATH"
export VLLM_NO_USAGE_STATS=1 TOKENIZERS_PARALLELISM=false
mkdir -p outputs/packet
# Read only the explicitly selected HF key from SSH stdin. No whole .env upload.
read -r HF_TOKEN || true
export HF_TOKEN
trap 'unset HF_TOKEN' EXIT
date -u +%FT%TZ > outputs/packet/worker-started.txt
df -h . > outputs/packet/disk.txt
if [[ "$(df -Pk . | awk 'NR==2 {print $4}')" -lt 65000000 ]]; then
  echo 'Need at least 65 GB free for FP8 weights, locked environment and cache.' >&2
  exit 1
fi
if ! command -v uv >/dev/null || [[ "$(uv --version)" != 'uv 0.10.8' ]]; then
  # Small bootstrap package, not the provider's outdated cu121 preset.
  python3 -m pip install --user 'uv==0.10.8'
fi
uv python install 3.12.12
uv sync --project envs/rl --locked --python 3.12.12
uv pip freeze --python envs/rl/.venv/bin/python > outputs/packet/packages.txt
envs/rl/.venv/bin/python scripts/verify_gpu.py --min-gpus 1 > outputs/packet/gpu.txt
envs/rl/.venv/bin/python scripts/download_models.py fp8 > outputs/packet/model.txt
unset HF_TOKEN  # Public checkpoint already cached; inference needs no credentials.
envs/rl/.venv/bin/python scripts/benchmark_vllm_native.py \
  --suite residency --preset "${1:-baseline}" --seconds "${2:-900}" --output outputs/packet/benchmark
