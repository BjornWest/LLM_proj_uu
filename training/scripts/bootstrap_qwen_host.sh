#!/usr/bin/env bash
# Ubuntu24.04 SSH host only. Default prints the plan; never allocates a VM.
set -euo pipefail
umask 077
release=/opt/qwen-release
runtime=/opt/qwen-runtime
models=/model-cache
execute=false
download=false
deadline=
while [[ $# -gt 0 ]]; do
  case "$1" in
    --release) release="${2:?Missing release}"; shift 2 ;;
    --runtime) runtime="${2:?Missing runtime}"; shift 2 ;;
    --models) models="${2:?Missing models}"; shift 2 ;;
    --deadline-utc) deadline="${2:?Missing allocation-anchored deadline}"; shift 2 ;;
    --execute) execute=true; shift ;;
    --download-model) download=true; shift ;;
    -h|--help)
      echo 'Usage: bootstrap_qwen_host.sh [--release ABS] [--runtime ABS] [--models ABS] [--execute --deadline-utc UNIX_SECONDS] [--download-model]'
      echo 'Downloads/installation require an approved rental. Default: print commands only.'
      exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done
release="$(realpath -m -- "$release")"
runtime="$(realpath -m -- "$runtime")"
models="$(realpath -m -- "$models")"
for target in "$release" "$runtime" "$models"; do
  [[ "$target" == /* && "$target" != / && "$target" != *$'\n'* ]] || {
    echo 'Use absolute non-root paths with no newline.' >&2; exit 2;
  }
done
for target in "$runtime" "$models"; do
  case "$target" in /opt|/mnt|/home|/usr|/var|/tmp|/root|/etc|/srv)
    echo 'Use a dedicated runtime/cache directory, not a system directory.' >&2; exit 2;; esac
  [[ "$target" != "$release" && "$target" != "$release/"* && "$release" != "$target/"* ]] || {
    echo 'Environments/caches and frozen sources must not contain each other.' >&2; exit 2;
  }
done
if $execute; then
  [[ -n "$deadline" ]] || { echo 'Execution requires the original rental deadline.' >&2; exit 2; }
  # A local WSL workstation or container is not an approved suitable SSH VM.
  [[ "$(. /etc/os-release; printf '%s:%s' "$ID" "$VERSION_ID")" == ubuntu:24.04 ]] || {
    echo 'This bootstrap is qualified for Ubuntu24.04 only.' >&2; exit 2;
  }
  [[ "$(cat /proc/1/comm)" == systemd && -f /sys/fs/cgroup/cgroup.controllers ]] || {
    echo 'Require a systemd/cgroup-v2 VM; this is not a container bootstrap.' >&2; exit 2;
  }
  [[ "$(uname -r)" != *[Mm]icrosoft* ]] && ! systemd-detect-virt --container --quiet || {
    echo 'WSL/containers are not suitable execution hosts for this bootstrap.' >&2; exit 2;
  }
  command -v nvidia-smi >/dev/null || { echo 'Require a CUDA GPU VM image.' >&2; exit 2; }
  for pair in rl suite-browser; do
    [[ -f "$release/training/envs/$pair/pyproject.toml" && -f "$release/training/envs/$pair/uv.lock" ]] || {
      echo 'Install and verify the frozen Training export before bootstrap.' >&2; exit 2;
    }
  done
  for name in training/scripts/apply_vllm_cpu_kv_patch.py \
    training/scripts/apply_vllm_qwen_schema_patch.py training/scripts/verify_gpu.py \
    training/browser_training/vllm_qwen_schema_patch.py training/patches/vllm028_mtp_cpu_offload.patch \
    worker-support/scripts/run_bounded_job.py; do
    [[ -f "$release/$name" ]] || { echo "Missing required export: $name" >&2; exit 2; }
  done
  for target in "$runtime" "$models"; do
    [[ ! -e "$target" || ( -d "$target" && -w "$target" && -O "$target" ) ]] || {
      echo 'Existing runtime/cache directories must be owned and writable; provision a dedicated subdirectory.' >&2; exit 2;
    }
  done
fi
run() {
  if ! $execute; then
    printf '%q ' "$@"; printf '\n'
    return
  fi
  local remaining
  remaining="$(python3 - "$deadline" <<'PY'
import math, sys, time
end = float(sys.argv[1])
remaining = end - time.time()
budget = math.floor(remaining - 5) if math.isfinite(end) else 0
if not math.isfinite(end) or remaining > 86400:
    raise SystemExit('Finite original rental deadline within24h required; stop bootstrap.')
if budget < 1:
    raise SystemExit('Original rental deadline reached; stop bootstrap.')
print(budget)
PY
  )"
  if [[ "${1:-}" == sudo && "${2:-}" == -n ]]; then
    shift 2
    # The timeout must run with the same privileges as the processes it stops.
    sudo -n timeout --signal=TERM --kill-after=5s "$remaining" "$@"
  else
    timeout --signal=TERM --kill-after=5s "$remaining" "$@"
  fi
}
# Credentials and workstation path overrides are never passed to installers.
# Keep the same HOME for managed Python/Chromium caches; do not repurpose it.
clean=(env -i "HOME=$HOME" "USER=$(id -un)" "LOGNAME=$(id -un)"
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
  LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
  "XDG_RUNTIME_DIR=/run/user/$(id -u)"
  "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus"
  "PLAYWRIGHT_BROWSERS_PATH=$runtime/chromium")
admin=(sudo -n)
if [[ $(id -u) == 0 ]]; then admin=(); fi
run "${admin[@]}" env DEBIAN_FRONTEND=noninteractive apt-get update
run "${admin[@]}" env DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=120 install -y --no-install-recommends \
  python3-venv build-essential git libgomp1 ca-certificates curl dbus-user-session \
  fonts-liberation fonts-noto-color-emoji libfontconfig1 libfreetype6 \
  libasound2t64 libatk-bridge2.0-0t64 libatk1.0-0t64 libatspi2.0-0t64 \
  libcairo2 libcups2t64 libdbus-1-3 libdrm2 libgbm1 libglib2.0-0t64 \
  libnspr4 libnss3 libpango-1.0-0 libwayland-client0 libx11-6 libxcb1 \
  libxcomposite1 libxdamage1 libxext6 libxfixes3 libxkbcommon0 libxrandr2
for target in "$runtime" "$models"; do
  if ! $execute || [[ ! -e "$target" ]]; then
    run "${admin[@]}" install -d -o "$(id -u)" -g "$(id -g)" -m 0700 "$target"
  fi
done
run "${clean[@]}" python3 -m venv "$runtime/tools"
run "${clean[@]}" "$runtime/tools/bin/python" -m pip install uv==0.10.8
uv="$runtime/tools/bin/uv"
run "${clean[@]}" "$uv" python install 3.12.12
for pair in rl suite-browser; do
  run install -d -m 0700 "$runtime/$pair"
  # Identical destination inputs are reusable; refuse a different old release.
  for name in pyproject.toml uv.lock; do
    if $execute && [[ -e "$runtime/$pair/$name" ]]; then
      run cmp "$release/training/envs/$pair/$name" "$runtime/$pair/$name"
    else
      run cp -n "$release/training/envs/$pair/$name" "$runtime/$pair/$name"
    fi
  done
  run "${clean[@]}" "$uv" sync --project "$runtime/$pair" --locked \
    --python 3.12.12 --default-index https://pypi.org/simple
  run "${clean[@]}" "$uv" pip check --python "$runtime/$pair/.venv/bin/python"
done
rl="$runtime/rl/.venv/bin/python"
browser="$runtime/suite-browser/.venv/bin/python"
run "${clean[@]}" "$browser" -I -B -m playwright install chromium
run "${clean[@]}" "$browser" -I -B -c 'from playwright.sync_api import sync_playwright
with sync_playwright() as p:
 b=p.chromium.launch(headless=True)
 try:
  page=b.new_page(); page.set_content("<title>Qwen host preflight</title><button>Ready</button>")
  page.get_by_role("button",name="Ready").click()
  assert page.title()=="Qwen host preflight" and b.version=="125.0.6422.26", b.version
  print({"metadata":{"tags":["scripted","browser-preflight"]},"chromium":b.version,"launch_click":"passed"})
 finally: b.close()'
run "${clean[@]}" "$rl" -I -B "$release/training/scripts/apply_vllm_cpu_kv_patch.py" \
  --install-in-place --receipt "$runtime/mtp-offload-backport.json"
run "${clean[@]}" "$rl" -I -B "$release/training/scripts/apply_vllm_cpu_kv_patch.py" --verify-only
run "${clean[@]}" "$rl" -I -B "$release/training/scripts/apply_vllm_qwen_schema_patch.py"
run "${clean[@]}" "$rl" -I -B "$release/training/scripts/verify_gpu.py" --min-gpus 1
run df -B1 /dev/shm "$models"
run free -b
run "${admin[@]}" loginctl enable-linger "$(id -un)"
run "${admin[@]}" systemctl start "user@$(id -u).service"
run "${clean[@]}" systemctl --user show --property=ControlGroup
run "${clean[@]}" "$browser" -I -B "$release/worker-support/scripts/run_bounded_job.py" \
  --memory-mib 256 --tasks 64 --receipt "$runtime/bootstrap-budget-$(date -u +%Y%m%dT%H%M%S)-$$" \
  -- "$browser" -I -B -c 'print("Actual user-systemd/cgroup enforcement passed")'
if $download; then
  # Public pinned checkpoint; no token or entire .env is copied onto the host.
  run "${clean[@]}" "$rl" -I -B -c 'from huggingface_hub import snapshot_download
import sys
print(snapshot_download("Qwen/Qwen3.8-27B-FP8", revision="017b9c7af6b5689d5dd426a76e0bc077eb5ca20a", cache_dir=sys.argv[1], token=False))' "$models/hub"
fi
if $execute; then
  printf '%s\n' 'Bootstrap commands complete; shared-harness/serving/wire qualification still required.'
else
  printf '%s\n' '# Plan only, for inspection on this machine; execute the script on the approved VM, not these locally resolved values.'
fi
