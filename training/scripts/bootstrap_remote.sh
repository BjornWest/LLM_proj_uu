#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
role="${1:-all}"
case "$role" in local|sft|sft-packing|rl|rl-sm120|browser|browser-validation|all) ;; *) echo 'Usage: bootstrap_remote.sh [local|sft|sft-packing|rl|rl-sm120|browser|browser-validation|all]' >&2; exit 2;; esac
if [[ "$role" == sft-packing || "$role" == rl-sm120 ]] && [[ -n "${FA2_WHEEL:-}" ]]; then
  [[ -f "$FA2_WHEEL" && -n "${FA2_WHEEL_SHA256:-}" ]] || {
    echo 'Provide an existing FA2_WHEEL and its expected FA2_WHEEL_SHA256 from the build manifest' >&2; exit 2;
  }
  printf '%s  %s\n' "$FA2_WHEEL_SHA256" "$FA2_WHEEL" | sha256sum --check --status || {
    echo 'FA2 wheel SHA-256 mismatch; artifact not installed' >&2; exit 2;
  }
fi
# Execute on a prepared CPU image builder before renting a GPU when possible.
# Requires Python/pip and git; no driver changes or model downloads.
if ! command -v uv >/dev/null; then
  python3 -m pip install --user 'uv==0.10.8'
  export PATH="$HOME/.local/bin:$PATH"
fi
uv python install 3.12.12
uv sync --project "$TRAINING_ROOT" --locked
if [[ "$role" == all ]]; then roles=(sft rl browser); elif [[ "$role" == local ]]; then roles=(); elif [[ "$role" == sft-packing ]]; then roles=(sft); elif [[ "$role" == rl-sm120 ]]; then roles=(rl); elif [[ "$role" == browser-validation ]]; then roles=(browser); else roles=("$role"); fi
for stack in "${roles[@]}"; do
  extras=()
  if [[ "$role" == browser-validation ]]; then extras=(--extra validation); fi
  uv sync --project "$TRAINING_ROOT/envs/$stack" --python 3.12.12 --locked "${extras[@]}"
  if [[ "$stack" == rl ]]; then
    "$TRAINING_ROOT/envs/rl/.venv/bin/python" scripts/patch_trl_policy.py --apply
    "$TRAINING_ROOT/envs/rl/.venv/bin/python" "$TRAINING_ROOT/scripts/apply_vllm_cpu_kv_patch.py" --install-in-place
  fi
  uv pip check --python "$TRAINING_ROOT/envs/$stack/.venv/bin/python"
  "$TRAINING_ROOT/envs/$stack/.venv/bin/python" scripts/verify_stack.py --role "$stack"
  if [[ "$stack" == sft || "$stack" == rl ]]; then
    "$TRAINING_ROOT/envs/$stack/.venv/bin/python" scripts/validate_training_cpu.py --role "$stack"
  fi
done
if [[ "$role" == sft-packing || "$role" == rl-sm120 ]]; then
  if [[ "$role" == sft-packing ]]; then build_stack=sft; build_extra=packing; else build_stack=rl; build_extra=sm120; fi
  if [[ -n "${FA2_WHEEL:-}" ]]; then
    uv pip install --python "$TRAINING_ROOT/envs/$build_stack/.venv/bin/python" --no-deps "$FA2_WHEEL"
  else
    # Compile before GPU allocation. No running GPU is required.
    if [[ "$role" == rl-sm120 && -z "${CUDA_HOME:-}" ]] && ! command -v nvcc >/dev/null; then
      export CUDA_HOME="$TRAINING_ROOT/envs/rl/.venv/lib/python3.12/site-packages/nvidia/cu13"
    fi
    if [[ -n "${CUDA_HOME:-}" ]]; then export PATH="$CUDA_HOME/bin:$PATH"; fi
    command -v nvcc >/dev/null || { echo 'Provide CUDA_HOME for a CUDA 13.0 devel toolkit before building flash-attn' >&2; exit 2; }
    compiler_version="$(nvcc --version)"
    [[ "$compiler_version" == *V13.0.88* ]] || { echo 'Use NVCC 13.0.88 to match the pinned CUDA toolchain' >&2; exit 2; }
    compiler_root="${CUDA_HOME:-$(dirname -- "$(dirname -- "$(readlink -f -- "$(command -v nvcc)")")")}"
    if [[ ! -e "$compiler_root/lib/libcudart.so" && -f "$compiler_root/lib/libcudart.so.13" ]]; then
      # Runtime wheels omit the unversioned development-library name. Keep the
      # linker shim in our cache instead of modifying the toolkit or system libs.
      linker_dir="$TRAINING_ROOT/.cache/cuda-devel-link-libs"
      mkdir -p "$linker_dir"
      ln -sfn -- "$compiler_root/lib/libcudart.so.13" "$linker_dir/libcudart.so"
      export LIBRARY_PATH="$linker_dir:$compiler_root/lib${LIBRARY_PATH:+:$LIBRARY_PATH}"
    fi
    if [[ "$role" == rl-sm120 ]]; then
      "$TRAINING_ROOT/envs/rl/.venv/bin/python" scripts/verify_cuda_toolchain.py --cuda-home "$compiler_root"
    fi
    export FLASH_ATTN_CUDA_ARCHS="${FLASH_ATTN_CUDA_ARCHS:-120}"
    export FLASH_ATTENTION_FORCE_BUILD=TRUE
    export MAX_JOBS="${MAX_JOBS:-4}"
    # packaging/setuptools already come from each stack's lock.
    uv pip install --python "$TRAINING_ROOT/envs/$build_stack/.venv/bin/python" 'ninja==1.13.2' 'wheel==0.45.1'
    uv sync --project "$TRAINING_ROOT/envs/$build_stack" --extra "$build_extra" --locked --no-build-isolation-package flash-attn
  fi
  "$TRAINING_ROOT/envs/$build_stack/.venv/bin/python" -c 'import flash_attn; assert flash_attn.__version__ == "2.8.3"; print(flash_attn.__version__)'
  uv pip check --python "$TRAINING_ROOT/envs/$build_stack/.venv/bin/python"
  if [[ "$role" == rl-sm120 ]]; then
    "$TRAINING_ROOT/envs/rl/.venv/bin/python" scripts/patch_trl_attention.py --apply
    "$TRAINING_ROOT/envs/rl/.venv/bin/python" "$TRAINING_ROOT/scripts/apply_vllm_cpu_kv_patch.py" --install-in-place
    # The optional extra's uv sync above can restore the upstream package.
    "$TRAINING_ROOT/envs/rl/.venv/bin/python" scripts/patch_trl_policy.py --apply
  fi
fi
"$TRAINING_ROOT/.venv/bin/python" -m pytest -q
