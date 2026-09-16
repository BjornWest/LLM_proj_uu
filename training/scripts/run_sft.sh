#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
export CUDA_VISIBLE_DEVICES="${SFT_GPU:-0}"
exec "${SFT_PYTHON:-$TRAINING_ROOT/envs/sft/.venv/bin/python}" scripts/run_sft.py "$@"
