#!/bin/bash
# Start the Raven demo service on PORT (default 8770) with the native Windows browser.
# Stops a previous service on that port and any leftover Raven Chrome-for-Testing
# processes (only binaries under ...\AppData\Local\raven-demo; never the user's Chrome).
PORT=${1:-8770}; shift
cd "$(dirname "$0")/../.."
P=$(ss -ltnp 2>/dev/null | grep ":$PORT " | grep -o 'pid=[0-9]*' | cut -d= -f2 | head -1)
[ -n "$P" ] && kill "$P" && sleep 3
powershell.exe -NoProfile -Command "Get-Process chrome -ErrorAction SilentlyContinue | Where-Object { \$_.Path -like '*raven-demo*' } | Stop-Process -Force" 2>/dev/null
sleep 2
export DISPLAY=:99 TASK_SOURCE_BINDING=current OPENBLAS_NUM_THREADS=1
export PYTHONPATH="$PWD:/home/bjorn/code/cau-merge-20261016"
export LD_LIBRARY_PATH=/home/bjorn/code/LLM_proj_uu/.local/system-libs/usr/lib/x86_64-linux-gnu
LOG=/home/bjorn/code/LLM_proj_uu/.local/coordination/demo-sprint/raven-$PORT.log
nohup python3 scripts/run_bounded_job.py --tasks 0 --memory-mib 4096 -- \
  /home/bjorn/code/LLM_proj_uu/.venv/bin/python apps/raven/backend.py --port "$PORT" \
  --windows-browser --reasoning-effort low "$@" > "$LOG" 2>&1 &
for i in $(seq 1 60); do curl -s -m 2 "http://127.0.0.1:$PORT/api/health" >/dev/null && { echo "Raven ready on http://localhost:$PORT"; exit 0; }; sleep 1; done
echo "Raven did not start; see $LOG"; tail -5 "$LOG"; exit 1
