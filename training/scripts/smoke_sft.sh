#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
"$TRAINING_ROOT/.venv/bin/python" scripts/make_smoke_data.py
exec scripts/run_sft.sh --config configs/sft_smoke.yml "$@"
