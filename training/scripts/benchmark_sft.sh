#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
exec "$TRAINING_ROOT/.venv/bin/python" scripts/benchmark.py sft "$@"
