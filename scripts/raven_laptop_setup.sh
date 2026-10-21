#!/bin/bash
# Idempotent Raven demo setup for WSL2 Ubuntu (backend in WSL, Chrome for Testing on Windows).
# Run from anywhere inside the checkout:   bash scripts/raven_laptop_setup.sh
# Never handles secrets: create .env yourself (see LAPTOP_SETUP.md, "Raven demo on the laptop").
# Switches: RAVEN_SKIP_SUDO=1 (no apt / playwright install-deps), RAVEN_SKIP_WINDOWS=1,
#   RAVEN_SKIP_SMOKE=1, RAVEN_SMOKE_PORT (default 8790), RAVEN_CAU_PATH (default
#   ../common_agent_util), RAVEN_CAU_SOURCE (Git URL, path or bundle for common_agent_util).
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
CAU_COMMIT=73cf7e922c231727a29922f918a9bfb2da80ffec
CAU_PATH=${RAVEN_CAU_PATH:-$(dirname "$ROOT")/common_agent_util}
CAU_SOURCE=${RAVEN_CAU_SOURCE:-https://github.com/BjornWest/common_agent_util.git}
step() { printf '\n== %s\n' "$*"; }

step "1/7 System packages"
if [ "${RAVEN_SKIP_SUDO:-0}" != 1 ]; then
  sudo apt-get update -qq
  if apt-cache show python3.12-venv >/dev/null 2>&1; then PYPKG=python3.12; else PYPKG=python3.11; fi
  sudo apt-get install -y -qq "$PYPKG" "$PYPKG-venv" git curl xvfb
else
  echo "skipped (RAVEN_SKIP_SUDO=1)"
fi
PY=$(command -v python3.12 || command -v python3.11 || true)
[ -n "$PY" ] || { echo "Need python3.12 (or 3.11)"; exit 1; }

step "2/7 Virtualenv and Python requirements (.venv)"
[ -x .venv/bin/python ] || "$PY" -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.lock.txt

step "3/7 Playwright Chromium (Linux side: smoke checks and background modes)"
.venv/bin/python -m playwright install chromium
if [ "${RAVEN_SKIP_SUDO:-0}" != 1 ]; then
  sudo "$ROOT/.venv/bin/python" -m playwright install-deps chromium
fi

step "4/7 common_agent_util (agent_trace) at $CAU_COMMIT -> $CAU_PATH"
[ -d "$CAU_PATH/.git" ] || git clone -q "$CAU_SOURCE" "$CAU_PATH"
if ! git -C "$CAU_PATH" cat-file -e "$CAU_COMMIT^{commit}" 2>/dev/null; then
  git -C "$CAU_PATH" fetch -q "$CAU_SOURCE" || true
  git -C "$CAU_PATH" fetch -q "$CAU_SOURCE" "$CAU_COMMIT" 2>/dev/null || true
fi
git -C "$CAU_PATH" cat-file -e "$CAU_COMMIT^{commit}" 2>/dev/null || {
  echo "Commit $CAU_COMMIT is not available from $CAU_SOURCE."
  echo "Push it to GitHub, or copy a bundle and rerun with RAVEN_CAU_SOURCE=/path/to/cau.bundle"; exit 1; }
if [ "$(git -C "$CAU_PATH" rev-parse HEAD)" != "$CAU_COMMIT" ]; then
  [ -z "$(git -C "$CAU_PATH" status --porcelain)" ] || { echo "$CAU_PATH has local changes; not switching commits"; exit 1; }
  git -C "$CAU_PATH" checkout -q --detach "$CAU_COMMIT"
fi
.venv/bin/python -m pip install -q --no-deps -e "$CAU_PATH"
mkdir -p .local
if [ ! -f .local/raven-demo.env ]; then
  # Non-secret machine settings read by apps/raven/start_demo.sh.
  printf 'RAVEN_CAU_PATH=%s\nRAVEN_BOUNDED=0\n' "$CAU_PATH" > .local/raven-demo.env
fi

step "5/7 Pinned Qwen tokenizer (context accounting; ~13 MB, hash-verified, no weights)"
.venv/bin/python scripts/fetch_model_tokenizer.py qwen/qwen3.8-27b
BUNDLE=.local/model-tokenizers/qwen3.8-27b-1d4bf0f2
mkdir -p training/.cache/qwen38-tokenizer   # default path of the standard harness profile
for f in tokenizer.json tokenizer_config.json chat_template.jinja; do
  [ -f "training/.cache/qwen38-tokenizer/$f" ] || cp "$BUNDLE/$f" "training/.cache/qwen38-tokenizer/$f"
  cmp -s "$BUNDLE/$f" "training/.cache/qwen38-tokenizer/$f" || { echo "training/.cache/qwen38-tokenizer/$f differs from the pinned file"; exit 1; }
done

step "6/7 Windows Chrome for Testing (%LOCALAPPDATA%\\raven-demo)"
if [ "${RAVEN_SKIP_WINDOWS:-0}" = 1 ]; then
  echo "skipped (RAVEN_SKIP_WINDOWS=1)"
elif ! command -v powershell.exe >/dev/null; then
  echo "powershell.exe not on PATH: enable WSL interop (see LAPTOP_SETUP.md troubleshooting)"; exit 1
else
  PYTHONPATH="$ROOT" .venv/bin/python -m apps.raven.windows_browser --setup
fi

step "7/7 No-model smoke check (backend on 127.0.0.1:${RAVEN_SMOKE_PORT:-8790}, scripted UI fixture)"
if [ "${RAVEN_SKIP_SMOKE:-0}" = 1 ]; then
  echo "skipped (RAVEN_SKIP_SMOKE=1)"
else
  PORT=${RAVEN_SMOKE_PORT:-8790}
  if ss -ltn | grep -q ":$PORT "; then echo "Port $PORT is busy; set RAVEN_SMOKE_PORT"; exit 1; fi
  set -a; . .local/raven-demo.env; set +a
  eval "$(python3 -m apps.raven.paths --shell)"
  mkdir -p .local/raven-logs
  export DISPLAY=${DISPLAY:-:99} TASK_SOURCE_BINDING=current OPENBLAS_NUM_THREADS=1
  "$RAVEN_PYTHON" apps/raven/backend.py --port "$PORT" --demo-mode --model-backend openrouter \
    > .local/raven-logs/setup-smoke-backend.log 2>&1 &
  BACKEND=$!
  trap 'kill $BACKEND 2>/dev/null || true' EXIT
  for i in $(seq 1 60); do curl -s -m 2 "http://127.0.0.1:$PORT/api/health" >/dev/null && break; sleep 1; done
  "$RAVEN_PYTHON" -m apps.raven.smoke --url "http://127.0.0.1:$PORT" --output .local/raven-logs/setup-smoke
fi

step "Done"
if [ ! -f .env ] || ! grep -q '^OPENROUTER_API_KEY=.' .env; then
  echo "Next: create .env with your OpenRouter key (this script never writes secrets):"
  echo "  [ -e .env ] || install -m 600 /dev/null .env"
  echo "  nano .env                       # add the line OPENROUTER_API_KEY=<your key>"
fi
echo "Start the demo: apps/raven/start_demo.sh 8770 --model-backend openrouter"
