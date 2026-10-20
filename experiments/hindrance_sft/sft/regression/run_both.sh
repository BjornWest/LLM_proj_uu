#!/bin/bash
# Run base and SFT concurrently (16 + 16 = vLLM --max-num-seqs 32), then compare.
#   run_both.sh OUTROOT [extra regress.py args for both]
# Env: BASE_MODEL (default Qwen/Qwen3.8-27B-FP8), SFT_MODEL (default qwen-sft), BASE_URL, MEM.
set -euo pipefail
[ $# -ge 1 ] || { sed -n 2,4p "$0"; exit 2; }
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(realpath -m "$1"); shift
mkdir -p "$ROOT"
BASE_MODEL=${BASE_MODEL:-Qwen/Qwen3.8-27B-FP8}; SFT_MODEL=${SFT_MODEL:-qwen-sft}
start=$(date +%s)
"$HERE/run_regression.sh" "$BASE_MODEL" "$ROOT/base" "$@" > "$ROOT/base.log" 2>&1 & pa=$!
"$HERE/run_regression.sh" "$SFT_MODEL" "$ROOT/sft" "$@" > "$ROOT/sft.log" 2>&1 & pb=$!
rc=0; wait $pa || rc=$?; wait $pb || rc=$?
echo "wall $(( $(date +%s) - start ))s; exit $rc" | tee "$ROOT/wall.txt"
tail -n 4 "$ROOT/base.log" "$ROOT/sft.log"
"$HERE/.venv/bin/python" "$HERE/compare.py" "$ROOT/base" "$ROOT/sft" --out "$ROOT/comparison.md"
exit $rc
