#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
exec "${LAUNCH_PYTHON:-$TRAINING_ROOT/.venv/bin/python}" -m browser_training.launch "$@"
