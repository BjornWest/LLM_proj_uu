#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
# Explicitly run this on a CPU machine / persistent volume BEFORE GPU allocation.
# HF_TOKEN is optional for these public models; never logged here.
exec "$TRAINING_ROOT/envs/sft/.venv/bin/python" scripts/download_models.py "$@"
