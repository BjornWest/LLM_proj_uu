# Qwen SSH host bootstrap and first wire qualification

This source preparation downloads nothing by default and allocates nothing.
The commands below need an explicitly approved finite GPU rental. They are not
an execution release: Evaluation still owns the relocated caller, private
packages, native grading and viewer acceptance. The combined worker must own
serving, capture its actual measurements and stop it on terminal caller failure.

## Bootstrap

Install the verified Training export under `/opt/qwen-release`, the unchanged
standalone launcher under `worker-support/scripts/run_bounded_job.py`, and the
indexed caller and case roots at their agreed paths. Keep all caches and virtual
environments outside these immutable source roots. The script assumes this
export's manifest has already been checked; it does not verify the full bundle.

```bash
bash /opt/qwen-release/training/scripts/bootstrap_qwen_host.sh
```

The default prints shell-escaped commands only. `--release`, `--runtime` and
`--models` override absolute paths. To execute on the approved Ubuntu24.04 VM:

```bash
bash /opt/qwen-release/training/scripts/bootstrap_qwen_host.sh \
  --execute --deadline-utc ACTUAL_ALLOCATION_ANCHORED_UNIX_DEADLINE \
  --download-model
```

Omit `--download-model` when the exact checkpoint is already cached. The script
uses public Hugging Face downloads without a token. It does not inherit the
workstation `.env`, W&B/provider keys or Python path overrides. It installs the
two exact separate locks, Ubuntu24's Chromium dependencies, Chromium1117, both
required vLLM patches, and runs the tiny CUDA preflight. Browser launch/click is
explicitly scripted. User-systemd lingering and a real bounded-launcher smoke
check establish the browser process-limit boundary; the actual VM must support
systemd and cgroup v2. This is deliberately a VM bootstrap, not a container setup.

Existing identical lock inputs are reusable; different old inputs are refused.
Each subprocess is clipped to the remaining original rental, with five seconds
for forced termination. Privileged commands put that timeout inside `sudo`;
less than one positive second after the reserve is refused. This is a process
deadline, not provider deletion.
The workstation deletion watchdog must remain alive independently. Installed
package/cache state after an interrupted install is not readiness. Preserve its
log and diagnose it manually, without allocating an automatic replacement.

The RL environment is several GB of wheels; the public FP8 model is about31GB.
Ubuntu24 libraries, managed Python downloads and actual CUDA/browser behavior
remain live-host acceptance items. Successful local command construction does
not establish them. At least21GiB free `/dev/shm` is separately enforced by the
serving entry point; do not reduce the20GiB CPU tier to work around a host error.

## First-time wire qualification

`training/scripts/qualify_qwen_wire.py` prepares a bounded once-per-stack check.
It uses the actual planned native tool schema from a pinned OpenAI request,
Evaluation's exact `tokenize_payload`, and the official cached Qwen processor.
The HF reference normalizes JSON tool-argument strings and reasoning aliases
as the pinned vLLM0.28 chat renderer does, including its Pydantic tool dump;
the HTTP request is unchanged. The pinned actual system message is retained.

Six probes cover three image sizes, retained tool/reasoning history, an exact
250000-token complete input, and a tool-free strict JSON-schema formatter.
Only history, input boundary and formatter generate: **five requests, at most
nine generated tokens total**. The250k prefill can still take appreciable time.
History is generated again with changed output/parallel controls, and the
formatter is generated again without its grammar. Every compared prompt token
ID, official count, server count and usage must agree. Missing probes, a shorter
boundary or an output-control change that inserts hidden prompt text fail.
The native-tool check establishes wire/template parity, not that the model solves
browser tasks; those remain the actual canaries' purpose.

Use the serving Python and approved worker's exact files:

```bash
/opt/qwen-runtime/rl/.venv/bin/python -I -B \
  /opt/qwen-release/training/scripts/qualify_qwen_wire.py \
  --runtime /opt/qwen-release/caller/scripts/qwen_suite_runtime.py \
  --runtime-sha256 ACTUAL_REVIEWED_RUNTIME_SHA256 \
  --request /private/qwen-runs/RUN/native-probe-request.json \
  --request-sha256 ACTUAL_PLANNED_REQUEST_SHA256 \
  --launch /private/qwen-runs/RUN/installed-serving.json \
  --launch-sha256 ACTUAL_LAUNCH_SHA256 \
  --owner /private/qwen-runs/RUN/serving-process.json \
  --owner-sha256 ACTUAL_OWNER_SHA256 \
  --rental /private/qwen-runs/RUN/rental.json \
  --rental-sha256 ACTUAL_RENTAL_SHA256 \
  --snapshot /model-cache/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a \
  --deadline-utc ACTUAL_ALLOCATION_ANCHORED_UNIX_DEADLINE \
  --output /private/qwen-runs/RUN/wire-qualification
```

Without `--execute`, this checks pins and prints the plan, with no torch import,
socket probe, download or GPU call. Execution additionally requires one actual
SM120 GPU, matching owned launch argv/PID/socket, actual model/context metadata,
and a separately recorded `qualification_authorized=true`. The rental record
binds numeric `allocation_utc`, integer `approved_rental_seconds` (at most24h)
and matching `deadline_utc`; no deadline restarts after setup. The owner pin holds
`pid`, `start_ticks`, `boot_id`, captured by the worker when it creates the
process. It must not discover an arbitrary existing server. Requests use direct
IPv4 localhost with overall timeouts, clipped to the original rental.
The rental record also binds canonical distinct `run_id`/`instance_id` and this
launch's `serving_session_id`. GPU inspection runs in a short subprocess so its
CUDA context is released before the long prefill. Manual reruns still need
authorization; this tool does not implement an allowance ledger.

Output requires an existing private owned run directory as its parent. It writes
a new private directory of immutable progress snapshots and `wire-proof.json`.
Requests are recorded as attempts before dispatch, without claiming the server
accepted them. Paid responses and bounded HTTP error bodies are saved before
comparison or post-response ownership/deadline failures. Large responses are
stored once as private pinned raw-byte artifacts with HTTP status and body hashes; summary proofs retain token-ID hashes. A mismatching tokenize response is also saved once for offline token-by-token inspection. Declared body length and local deadline closure distinguish incomplete responses from server failures. Stop signals cannot be swallowed by normal library exception handlers. An
interrupted run records failure and available progress. No
automatic retries occur, and a failed check does not authorize a hinted
generation. This evidence alone **does not create a stack capability or dispatch
approval**. The owned collector must still bind installed packages and patches,
lock/helper hashes, actual executable/environment, checkpoint assets, resolved
backends and fresh session to the compatibility fingerprint and its three typed
qualification/deployment/processor proofs. It cannot mark that measurement
passed from receipt labels or CPU fixture results. The complete collector and
remote process-owner/return composition remain separate work.

After first-time actual qualification, use
[the reuse adapter](qwen-serving-qualification.md) on compatible fresh hosts.
Do not rerun these generations at every launch. New vLLM/CUDA/kernel/patch or
effective model/processor changes require an explicit compatibility assessment.

## Local verification

The comparison-core tests use fake exchanges and localhost HTTP and prove failure handling;
they confer no serving authority. The CPU processor preparation uses an
illustrative tool schema and actual official assets, proving only that the
six input shapes and exact250k boundary can be constructed without model weights.
The real canary tool schema and server parity still need actual acceptance.

```bash
bash -n training/scripts/bootstrap_qwen_host.sh
python3 /home/bjorn/code/LLM_proj_uu/scripts/run_bounded_job.py --memory-mib 1024 --tasks 128 -- \
  timeout --kill-after=10s 90s training/.venv/bin/python -B -m pytest \
  -q -p no:cacheprovider training/tests/test_qualify_qwen_wire.py
```
