#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
# Local WSL fallback used during validation; remote images should install OS libs.
browser_libs="$TRAINING_ROOT/.cache/browser-libs/root/usr/lib/x86_64-linux-gnu"
if [[ -d "$browser_libs" ]]; then
  export LD_LIBRARY_PATH="$browser_libs${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
probe=validate_browser.py
probe_python="$TRAINING_ROOT/envs/browser/.venv/bin/python"
if [[ "${1:-}" == --metrics ]]; then
  probe=validate_browser_metrics.py
  shift
elif [[ "${1:-}" == --harness ]]; then
  probe=validate_harness_worker.py
  shift
elif [[ "${1:-}" == --spawned ]]; then
  probe=validate_spawned_harness.py
  probe_python="$TRAINING_ROOT/envs/rl/.venv/bin/python"
  shift
elif [[ "${1:-}" == --policy-sessions ]]; then
  probe=validate_policy_sessions.py
  probe_python="$TRAINING_ROOT/envs/rl/.venv/bin/python"
  shift
fi
exec "$probe_python" "scripts/$probe" "$@"
