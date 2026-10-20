#!/bin/bash
# Run a hindrance round against the Vast vLLM endpoint (tunnel 127.0.0.1:18000).
#   MEM=6000 run_vast_round.sh MANIFEST OUTPUT_DIR [extra hindrance_model_run.py args, e.g. --concurrency 32 --concurrency-file vast/concurrency.txt]
set -euo pipefail
MANIFEST=$(realpath "$1"); OUTPUT=$(realpath -m "$2"); shift 2
cd "${RUNTREE:-/home/bjorn/code/LLM_proj_uu-worktrees/hindrance-run8-20261020}"
export PYTHONPATH="$PWD:/home/bjorn/code/cau-merge-20261016" TASK_SOURCE_BINDING=current \
  HARNESS_AX_TOKENIZER="$PWD/.local/website-38-concept-world-20261006-v1/assets/tokenizer.json" \
  LD_LIBRARY_PATH=/home/bjorn/code/LLM_proj_uu/.local/system-libs/usr/lib/x86_64-linux-gnu \
  OPENBLAS_NUM_THREADS=1 DISPLAY=:99
exec python3 scripts/run_bounded_job.py --tasks 0 --memory-mib "${MEM:-3000}" --receipt "$OUTPUT-receipt" -- \
  /home/bjorn/code/LLM_proj_uu/.venv/bin/python scripts/hindrance_model_run.py \
  --manifest "$MANIFEST" --output "$OUTPUT" \
  --openai-base-url http://127.0.0.1:18000/v1 --model Qwen/Qwen3.8-27B-FP8 \
  --max-steps 0 --max-input-tokens 250000 --max-total-input-tokens 8000000 \
  --max-total-output-tokens 120000 --shared-tokenizer "$@"
