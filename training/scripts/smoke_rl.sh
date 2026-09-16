#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
# Start the matching 0.6B LoRA server separately, or use preflight.sh tiny.
exec scripts/run_async_grpo.sh --config configs/rl_smoke.py "$@"
