#!/usr/bin/env bash
set -euo pipefail
TRAINING_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$TRAINING_ROOT"
export PYTHONPATH="$TRAINING_ROOT${PYTHONPATH:+:$PYTHONPATH}"
export HF_HOME="${HF_HOME:-$TRAINING_ROOT/.cache/huggingface}"
export TOKENIZERS_PARALLELISM=false
export AXOLOTL_DO_NOT_TRACK=1
export VLLM_NO_USAGE_STATS=1
