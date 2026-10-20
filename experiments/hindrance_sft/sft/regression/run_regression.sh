#!/bin/bash
# Generic capability-regression check for ONE served model name.
#   run_regression.sh MODEL_NAME OUTDIR [extra regress.py args]
# e.g. run_regression.sh Qwen/Qwen3.8-27B-FP8 runs/base
#      run_regression.sh qwen-sft runs/sft --concurrency 16
# Env: BASE_URL (default http://127.0.0.1:18000/v1), MEM (MiB cap for the client, default 2000).
# Resumable: rerunning with the same OUTDIR only runs items without an ok result.
set -euo pipefail
[ $# -ge 2 ] || { sed -n 2,8p "$0"; exit 2; }
HERE=$(cd "$(dirname "$0")" && pwd)
MODEL=$1; OUT=$(realpath -m "$2"); shift 2
mkdir -p "$OUT"
REPO=/home/bjorn/code/LLM_proj_uu
cd "$REPO"
exec python3 scripts/run_bounded_job.py --tasks 0 --memory-mib "${MEM:-2000}" --receipt "$OUT/bounded-receipt-$(date +%Y%m%dT%H%M%S)-$$" -- \
  "$HERE/.venv/bin/python" "$HERE/regress.py" --base-url "${BASE_URL:-http://127.0.0.1:18000/v1}" \
  --model "$MODEL" --out "$OUT" "$@"
