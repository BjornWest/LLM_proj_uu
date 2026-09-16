#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
export CUDA_VISIBLE_DEVICES="${TRAIN_GPU:-1}"
exec "${RL_PYTHON:-$TRAINING_ROOT/envs/rl/.venv/bin/python}" scripts/run_async_grpo.py "$@"
