#!/usr/bin/env bash
# Executed only on a rented GPU node, from a frozen minimal upload.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export PYTHONPATH="$PWD"
export HF_HOME="${HF_HOME:-$PWD/.cache/huggingface}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$PWD/.cache/uv}"
export CUDA_HOME="${CUDA_HOME:-/usr/local/cuda}"
export PATH="$PWD/envs/rl/.venv/bin:$PWD/.bootstrap/bin:$CUDA_HOME/bin:$HOME/.local/bin:$PATH"
export VLLM_NO_USAGE_STATS=1 TOKENIZERS_PARALLELISM=false
stage="${3:-all}"
case "$stage" in all|setup|download|benchmark) ;; *) echo 'Unknown worker stage' >&2; exit 2 ;; esac
mkdir -p outputs/packet
# Read only the explicitly selected HF key from SSH stdin. No whole .env upload.
read -r HF_TOKEN || true
export HF_TOKEN
trap 'unset HF_TOKEN' EXIT
date -u +%FT%TZ >> outputs/packet/worker-started.txt
if [[ "$stage" == all || "$stage" == setup ]]; then
df -h . > outputs/packet/disk.txt
if [[ "$(df -Pk . | awk 'NR==2 {print $4}')" -lt 65000000 ]]; then
  echo 'Need at least 65 GB free for FP8 weights, locked environment and cache.' >&2
  exit 1
fi
if ! command -v uv >/dev/null || [[ "$(uv --version)" != 'uv 0.10.8' ]]; then
  # SSH need not inherit container PIP_BREAK_SYSTEM_PACKAGES. Use an isolated
  # bootstrap venv so Ubuntu's PEP 668 policy cannot reject --user installs.
  python3 -m venv .bootstrap
  .bootstrap/bin/python -m pip install 'uv==0.10.8'
  export PATH="$PWD/.bootstrap/bin:$PATH"
fi
uv python install 3.12.12
uv sync --project envs/rl --locked --python 3.12.12
uv pip freeze --python envs/rl/.venv/bin/python > outputs/packet/packages.txt
envs/rl/.venv/bin/python scripts/verify_gpu.py --min-gpus 1 > outputs/packet/gpu.txt
fi
if [[ "$stage" == all || "$stage" == setup || "$stage" == benchmark ]]; then
  # Fail before downloading/reloading weights if SSH discarded compiler paths.
  ninja --version > outputs/packet/toolchain.txt
  nvcc --version >> outputs/packet/toolchain.txt
  envs/rl/.venv/bin/python -c 'from vllm.utils.flashinfer import has_flashinfer; assert has_flashinfer(), "FlashInfer unavailable: verify package and CUDA compiler discovery"' \
    >> outputs/packet/toolchain.txt 2>&1
fi
if [[ "$stage" == all || "$stage" == download ]]; then
envs/rl/.venv/bin/python scripts/download_models.py fp8 > outputs/packet/model.txt
fi
unset HF_TOKEN  # Public checkpoint already cached; inference needs no credentials.
if [[ "$stage" == all || "$stage" == benchmark ]]; then
envs/rl/.venv/bin/python scripts/benchmark_vllm_native.py \
  --suite residency --preset "${1:-baseline}" --seconds "${2:-900}" --output outputs/packet/benchmark
fi
