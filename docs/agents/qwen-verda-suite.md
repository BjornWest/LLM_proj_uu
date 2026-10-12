# Qwen suite on a Verda SSH VM

This is preparation for the inference-only shared-harness suite. It is not an
allocation or model-dispatch release. Evaluation owns the exact cases, frozen
worlds, caller, automatic grades, fact captures and viewer acceptance. Training
owns serving and host composition. The final portable caller bundle and global
rental controller must be bound before requesting allocation approval.

## Host choice and storage

The read-only account query on 2026-10-12 returned the following proposal. Quotes
and stock must be rechecked before allocation; nothing was created.

| Item | Proposal / observed quote |
| --- | --- |
| Instance | `1RTXPRO6000.30V`, on-demand, one RTX PRO 6000 96GB |
| Location | FIN-02 had stock at the query time |
| CPU / host RAM | Catalog says 30 CPU / 90GB RAM; measure actual available bytes |
| Image | `24.04.cuda13.0.docker`, ID `59cd1ccb-499e-4053-9690-3ca4c898351b` |
| Compute | Account-currency quote €1.994/hour; two hours ≈ €3.99 |
| Disk | Proposed 128GB in the API's units; NVMe quote €0.17436498/GB-month |
| Retaining that disk | Approximately €22.32/month; retention needs an agreed duration |
| Access | One existing registered public key matches local `~/.ssh/id_ed25519.pub` |

Do not conflate GB catalog/API units with GiB used by the CPU-KV limit. Keep model
weights, installed locks and compiler caches on the agreed volume. Deleting a VM
can detach and retain its OS disk for later reuse as an image. Retained storage
continues billing. Provider `shutdown` alone continues compute billing: use the
API's `delete` action and explicitly select which volumes to remove. An explicit
empty `volume_ids` retains all volumes; omitting it deletes the OS disk. When
removing selected volumes, also specify `delete_permanently=true`; it otherwise
defaults to false. Trash retention and quota are distinct from confirmed billing
cessation. Verify deletion through the API rather than treating an accepted
action as completion.
[Verda API](https://api.verda.com/v1/docs),
[storage](https://docs.verda.com/cli/storage/).

There is no need to install a provider SDK on the GPU host. The existing local
client ID/secret suffice for OAuth plus REST from the workstation. Verda also
has a CLI, but it is not installed or required for this preparation.
[CLI authentication](https://docs.verda.com/cli/getting-started/).

## Frozen portable closure

Export the reviewed Training Git source and Evaluation's accepted project,
common-agent utilities, recipes, website assets and caller releases. Verify each
supplied manifest/hash after transfer. Never rsync the mutable project root or
its `.env`. Keep the browser environment separate from the RL/vLLM environment.

The shared-browser service and clients must both use the corrected Harness
release at `1f60d52b816bbfcd037c8793d0d9f342faaa8ea0` (or its explicitly mapped
successor). Include `intent_browser/model_tokenizers.json` and the Chromium
helper, chat assets and observation script; a wheel alone previously omitted the
tokenizer registry. The paired common source is
`404dbca11661bba4609f568cf0f7b9c6f38ea5b6`.

Browser qualification currently pins Python3.12, BrowserGym-core0.14.3,
Playwright1.44.0 with its bundled Node, Chromium1117/125.0.6422.26 and
tokenizers0.23.2. Package the exact official tokenizer files and all required
Linux browser libraries. WSL's library paths are not portable. Evaluation's final
browser lock/assets manifest and actual-world acceptance remain required.

The four proposed canaries B02/B14/H03/H05 explicitly use `helpers=False` and
`data_tools=False`, with native GUI/vision tools. Docker being installed does not
qualify Python tools. If a later adopted profile advertises them, build and bind
the immutable sandbox image and run a zero-provider sandbox execution preflight;
the tool profile must remain explicit.

## Future host preparation commands

These commands are for an approved fresh Ubuntu VM after a verified bundle is
installed at `/opt/qwen-release`. They have not been run remotely. The first
block downloads dependencies, and the model block downloads about31GB if absent.
Root/sudo access and disk capacity must be established on the actual VM.

```bash
sudo apt-get update
sudo apt-get install -y python3-venv build-essential git libgomp1
sudo install -d -o "$(id -u)" -g "$(id -g)" -m 0700 \
  /opt/qwen-tools /opt/qwen-runtime /model-cache /private/qwen-runs
python3 -m venv /opt/qwen-tools
/opt/qwen-tools/bin/python -m pip install uv==0.10.8

export QWEN_RELEASE=/opt/qwen-release
export QWEN_UV=/opt/qwen-tools/bin/uv
export QWEN_RUNTIME=/opt/qwen-runtime
export HF_HOME=/model-cache
export HF_HUB_CACHE=/model-cache/hub
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1

"$QWEN_UV" python install 3.12.12
mkdir -p "$QWEN_RUNTIME/rl"
cp "$QWEN_RELEASE/training/envs/rl/pyproject.toml" "$QWEN_RUNTIME/rl/pyproject.toml"
cp "$QWEN_RELEASE/training/envs/rl/uv.lock" "$QWEN_RUNTIME/rl/uv.lock"
cmp "$QWEN_RELEASE/training/envs/rl/pyproject.toml" "$QWEN_RUNTIME/rl/pyproject.toml"
cmp "$QWEN_RELEASE/training/envs/rl/uv.lock" "$QWEN_RUNTIME/rl/uv.lock"
"$QWEN_UV" sync --project "$QWEN_RUNTIME/rl" --locked \
  --python 3.12.12 --default-index https://pypi.org/simple
export QWEN_RL_PY="$QWEN_RUNTIME/rl/.venv/bin/python"
"$QWEN_UV" pip check --python "$QWEN_RL_PY"

"$QWEN_RL_PY" -B "$QWEN_RELEASE/training/scripts/apply_vllm_cpu_kv_patch.py" \
  --install-in-place --receipt "$QWEN_RUNTIME/mtp-offload-backport.json"
"$QWEN_RL_PY" -B "$QWEN_RELEASE/training/scripts/apply_vllm_cpu_kv_patch.py" --verify-only
"$QWEN_RL_PY" -B "$QWEN_RELEASE/training/scripts/apply_vllm_qwen_schema_patch.py"
"$QWEN_RL_PY" -B "$QWEN_RELEASE/training/scripts/verify_gpu.py" --min-gpus 1
df -B1 /dev/shm /model-cache
free -b
```

The two patch installers reject unknown installed source. The serving entry
point rechecks both patches and the installed parser regression tests before
importing a vLLM worker. CUDA compilation uses the locked NVCC wheels through the
existing compiler helper rather than assuming the image's `PATH` is correct.
The environment, compiler caches and receipts are outside the frozen bundle;
installing them must not add files inside a source root whose manifest rejects
unlisted files. The copied lock inputs remain byte-identical to the release.

At least **21GiB free `/dev/shm`** is required for the 20GiB CPU-KV tier. Size
tmpfs and finite service memory caps from the measured host RAM, preserving room
for model loading, Chromium, tokenizer and case processes. Catalog90GB is not
Modal96GiB. Containerized serving would also need an explicit shared-memory
size; the proposed serving process runs on the VM host.

Download or reuse the exact model revision before starting offline serving:

```bash
"$QWEN_RL_PY" -B - <<'PY'
from huggingface_hub import snapshot_download
print(snapshot_download(
    'Qwen/Qwen3.8-27B-FP8',
    revision='017b9c7af6b5689d5dd426a76e0bc077eb5ca20a',
    cache_dir='/model-cache/hub'))
PY
```

Do not embed credentials in commands or source bundles. The public checkpoint
does not require a token. A token used temporarily for an authorized faster
download must be removed before episode processes start. Provider credentials
and the sole suite W&B writer stay on the workstation.

## Serving and canary composition

The reviewed `serve_qwen_suite.py` constructs a fixed localhost native-tool and
vision profile: full262144-token context, FP8 base/E4M3 KV, MTP3, BF16 Mamba/FP32
SSM, block1664, native LRU 20GiB CPU offload, interactivity mode and eight server
sequences. There is no forced12GiB GPU-KV pool from the diagnostic fixture.
The runner independently caps active episodes4/generation4 and prewarms1;
parked episodes still count as active. These are proposed values pending final
consumer acceptance.

After the reviewed provider/rental controller has established its absolute
allocation-anchored deadline, it can own this foreground process and its log:

```bash
export QWEN_RUN_ROOT=/private/qwen-runs/unique-run
install -d -m 0700 "$QWEN_RUN_ROOT"
env -u PYTHONPATH -u PYTHONHOME "$QWEN_RL_PY" -B "$QWEN_RELEASE/training/scripts/serve_qwen_suite.py" \
  --snapshot /model-cache/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a \
  --receipt "$QWEN_RUN_ROOT/installed-serving.json" \
  --cache-root /model-cache/compiled/qwen-native-mtp3 \
  > "$QWEN_RUN_ROOT/vllm.log" 2>&1
```

Add `--dry-run` to construct argv with no source installation, model load or GPU
use. Normal execution replaces the process with vLLM. **The entry point does not
enforce a rental deadline or delete a VM**: the final local provider controller
and remote process owner must supply those boundaries. Stopping the serving
process does not stop billing.

Developer-mode mutation routes are disabled for browser-facing serving. Do not
enable them to get `/server_info`; any future diagnostic exception needs its own
isolation and source review. Installed-source receipts identify each attempt,
actual argv/settings, Python/vLLM identity, compiler path and the controlled
environment. Failed guards replace earlier receipts with a failed attempt.
These receipts never claim that a model is loaded or ready. The child runs with
safe import paths and no inherited benchmark instrumentation or credentials.
The launcher refuses Python path/home overrides to ensure it verifies the same
installation its sanitized child will import. OpenMP threads are fixed to one,
matching the isolated CPU-KV qualification; later tuning is a separate profile.
The recorded PID survives exec and must be matched to the owned live process by
the final controller. Do not accept a new receipt while an old server holds the
port. Usage errors before argument parsing still require the controller to treat
the nonzero exit as terminal rather than consume an old receipt.

Wait for actual health and bind the installed fingerprints, processor/template,
model revision, session and deadline to the accepted caller. The suite counter
must establish official complete-wire ordered parity. Retain the250000-token
complete-input ceiling and clip actual output allowance to
`min(configured_max_output, 262144-exact_complete_input_tokens)`. No blanket
32768-token output reservation at250000 input, no cumulative-token ceiling and
no arbitrary episode time/turn cutoff. The finite rental and600-second request
watchdogs remain.

Compose the pool and AX tokenizer with the exact accepted caller. Four active
plus one warm environment normally needs ten task/chat leases; proposed pool
caps16/per-server8. Shared AX tokenization does not replace the official vLLM
complete-input counter. Launch only the approved canary episodes, preserving
native grades, original fact captures and viewer registration. Count successful
canaries in the suite rather than rerunning them. Use the same VM for the rest
only after the combined canary/cleanup acceptance succeeds.

## Human status and artifact return

From the workstation, use the actual private log path:

```bash
ssh -T GPU_HOST 'tail -n40 -F /private/qwen-runs/unique-run/vllm.log'
```

The serving entry point enables vLLM statistics every five seconds and disables
routine uvicorn access lines to keep that log readable. The suite's
single metrics poller can also feed `ServingTelemetry.observe`; the accepted
caller owns bounded incremental transport, a local JSONL journal and the sole
suite W&B writer. See [serving status](qwen-serving-status.md) for graph names
and meaning. That source component is reviewed; journal/transport/dashboard
composition is still separate. Prefill-completed accounting can be spiky and
does not measure instantaneous kernel speed.

Keep model history and browser exchanges on the VM. Return compact status rows,
Events/grades and selected trace artifacts incrementally with bounded transfers;
never resend every full history to the workstation each turn. Final trace/viewer
projection and teardown receipts must be returned before declaring completion.

No current VM exists. The final reviewed portable bundle, caller/telemetry
integration, global termination controller, fresh host acceptance and allocation
approval are still outstanding. Historical Modal restores qualify their exact
probe stack; they do not certify this new combined deployment.
