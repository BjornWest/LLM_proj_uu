#!/bin/bash
# Start the Raven demo service on PORT (default 8770) with the native Windows browser.
# Stops a previous service on that port and any leftover Raven Chrome-for-Testing
# processes (only binaries under ...\AppData\Local\raven-demo; never the user's Chrome).
# Paths come from apps/raven/paths.py; optional non-secret machine settings
# (RAVEN_BOUNDED=0, RAVEN_CAU_PATH, ...) from .local/raven-demo.env.
PORT=${1:-8770}; shift
cd "$(dirname "$0")/../.."
[ -f .local/raven-demo.env ] && { set -a; . .local/raven-demo.env; set +a; }
eval "$(python3 -m apps.raven.paths --shell)" || exit 1
P=$(ss -ltnp 2>/dev/null | grep ":$PORT " | grep -o 'pid=[0-9]*' | cut -d= -f2 | head -1)
[ -n "$P" ] && kill "$P" && sleep 3
powershell.exe -NoProfile -Command "Get-Process chrome -ErrorAction SilentlyContinue | Where-Object { \$_.Path -like '*raven-demo*' } | Stop-Process -Force" 2>/dev/null
sleep 2
export DISPLAY=${RAVEN_DISPLAY:-:99} TASK_SOURCE_BINDING=current OPENBLAS_NUM_THREADS=1
# Linux-side browsers (background modes) use an invisible X display; start one if absent.
if [ "$DISPLAY" = :99 ] && ! ss -xl 2>/dev/null | grep -q '/tmp/.X11-unix/X99' && command -v Xvfb >/dev/null; then
  nohup Xvfb :99 -screen 0 1600x1000x24 -nolisten tcp >/dev/null 2>&1 &
  sleep 1
fi
mkdir -p .local/raven-logs
LOG=${RAVEN_LOG:-$PWD/.local/raven-logs/raven-$PORT.log}
# RAVEN_BOUNDED=0 (e.g. on the presentation laptop) runs without the workstation's cgroup launcher.
BOUND=()
[ "${RAVEN_BOUNDED:-1}" = 1 ] && BOUND=(python3 scripts/run_bounded_job.py --tasks 0 --memory-mib 4096 --)
nohup "${BOUND[@]}" "$RAVEN_PYTHON" apps/raven/backend.py --port "$PORT" \
  --windows-browser --demo-mode --reasoning-effort low "$@" > "$LOG" 2>&1 &
for i in $(seq 1 60); do curl -s -m 2 "http://127.0.0.1:$PORT/api/health" >/dev/null && { echo "Raven ready on http://localhost:$PORT"; exit 0; }; sleep 1; done
echo "Raven did not start; see $LOG"; tail -5 "$LOG"; exit 1
