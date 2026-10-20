#!/bin/bash
# OPTIONAL secondary replay: base Qwen answers the generic prompts itself (thinking on, reasoning kept).
#   gen_replay.sh [OUT_JSONL] [extra gen_replay.py args, e.g. --limit 50 --concurrency 32]
# Default OUT: replay/selfgen/replay.selfgen.jsonl. Env: BASE_URL (default http://127.0.0.1:18000/v1),
# MODEL (default Qwen/Qwen3.8-27B-FP8), MEM (MiB, default 2000). Resumable.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$(realpath -m "${1:-$HERE/selfgen/replay.selfgen.jsonl}"); [ $# -ge 1 ] && shift
mkdir -p "$(dirname "$OUT")"
cd /home/bjorn/code/LLM_proj_uu
exec python3 scripts/run_bounded_job.py --tasks 0 --memory-mib "${MEM:-2000}" \
  --receipt "$OUT.bounded-receipt-$(date +%Y%m%dT%H%M%S)-$$" -- \
  "$HERE/../regression/.venv/bin/python" "$HERE/gen_replay.py" --base-url "${BASE_URL:-http://127.0.0.1:18000/v1}" \
  --model "${MODEL:-Qwen/Qwen3.8-27B-FP8}" --out "$OUT" "$@"
