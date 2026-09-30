# Packet Dynamic: bounded Qwen FP8 inference qualification

Prepared 2026-09-30. **CPU validation and authenticated read-only API queries have
passed. No Packet GPU has been allocated, no weights downloaded, and no Packet
performance result exists yet.** This is inference preparation, not a new RL
qualification or evidence of 1,000 decode tokens/s.

The user subsequently authorized one baseline attempt with a thirty-minute limit,
no allocation retries, and persistent storage if feasible. The approved launch
command stopped **before POST/allocation** because the hourly offer had disappeared.
No GPU charge or download occurred. The monthly-only RTX capacity was deliberately
not substituted. Re-check capacity before a later attempt; no paid MTP run is
authorized by that baseline approval.

## What is ready

Installed globally: `packet-gpu-cli@1.1.1`, executable `packet`. Authentication
was validated and stored locally; the CLI credential file was restricted to mode
600. The package reports `packet --version` as 1.1.0 despite its npm version.

Read-only API checks confirmed a **$10 USD wallet**, no running instances, and
initially an available hourly **RTX PRO 6000 Blackwell Dynamic** product at
**$0.66/hour**. Later checks had only monthly RTX capacity; the approved attempt
stopped without allocation. The launch helper queries capacity again before allocation.
The product advertises 96 GB VRAM, 96 GB host RAM, six vCPUs and 150 GB ephemeral
disk. This is a shared GPU service, not exclusive bare-metal access.

The CLI has several source/documentation discrepancies:

* Use `packet-gpu-cli`, not the unrelated npm package `packet-cli` linked by one
  homepage installation example.
* `--json` is not implemented. `PACKET_API_KEY` is consumed by `packet login`,
  but other CLI commands read the saved configuration instead.
* Partial model matching selects the first product. A monthly RTX product can
  precede the hourly product; pool prices can be zero despite the hourly product
  costing $0.66. The helper matches an available **non-monthly, positive-price**
  product and one of its pools, rather than copying that selection logic.
* Login displays an invalid balance because it reads the wrong response fields.
  The helper reads the actual wallet under `/api/v1/inventory/balance`.
* CLI `launch --wait` times out without terminating the instance. The helper
  instead records its ID immediately, collects partial results, and requests
  deletion in `finally`, including ordinary Ctrl-C/SIGTERM.

Source: [published CLI package](https://registry.npmjs.org/packet-gpu-cli/1.1.1),
[Packet CLI documentation](https://packet.ai/cli),
[Dynamic architecture](https://packet.ai/dynamic-gpu-cloud),
[pricing](https://packet.ai/pricing), [terms](https://packet.ai/terms).

## Review and launch

Commands below start in the repository root. The existing lightweight training
environment needs `python-dotenv` (already present via its tracking/Modal extras).
Credentials are parsed from the ignored root `.env`, never sourced as shell code.

```bash
# Both commands are read-only with respect to Packet resources.
training/.venv/bin/python training/scripts/packet_cloud.py inspect
training/.venv/bin/python training/scripts/packet_cloud.py plan --minutes 30

# Review the actual server flags and finite benchmark cases without CUDA.
training/.venv/bin/python training/scripts/benchmark_vllm_native.py --dry-run
```

The plan creates an ignored local upload archive and SHA256 source manifest.
It includes only the explicitly listed worker, benchmark code and locked RL
environment; it excludes the root `.env`, browser traces and unrelated work.

**Paid execution follows only after authorization for the bounded attempt:**

```bash
training/.venv/bin/python training/scripts/packet_cloud.py run \
  --execute --minutes 30 --max-hourly 0.70 --preset baseline

# A separate paid attempt, not an automatic follow-up/retry:
training/.venv/bin/python training/scripts/packet_cloud.py run \
  --execute --minutes 30 --max-hourly 0.70 --preset mtp
```

At $0.66/hour, thirty minutes is **$0.33 estimated compute**. The whole attempt
includes provisioning, package installation and model download, not just benchmark
time. The worker has a timeout, and the local controller reserves cleanup time.
It requires functioning SSH within five minutes and never retries allocation.

**These are operational time limits and quoted-rate estimates, not a provider
hard billing cap.** Packet's documented Dynamic create request contains
`pool_id` and `vgpus`, not a binding product-price field. Check the dashboard's
actual rate and final invoice. Ordinary deletion failures, a lost POST response,
SIGKILL, workstation shutdown or prolonged API outage can require manual cleanup;
keep the controller alive. A returned DELETE response is only acceptance, so the
helper also checks the instance listing for termination. It records any failure
to confirm and prints the instance ID. Artifact transfers are bounded and cleanup
can add a short tail to the target duration. No persistent volume is created.

```bash
# Recovery: terminate exactly the recorded instance, never all account instances.
training/.venv/bin/python training/scripts/packet_cloud.py terminate --instance-id ID
training/.venv/bin/python training/scripts/packet_cloud.py inspect
```

The controller stays on the workstation. The Packet API key never goes to the
GPU. If supplied, only `HF_TOKEN` goes through SSH stdin to the download process;
it is unset before serving. SSH passwords returned by Packet are passed through
OpenSSH askpass, not command arguments, source files or logs. SSH host keys are
stored per attempt. No project logins, W&B key or complete repository upload.

## Remote stack and first compatibility check

The worker reuses `training/envs/rl/uv.lock`: Python 3.12.12, uv 0.10.8,
PyTorch 2.13.0/CUDA 13 dependencies, vLLM 0.28.0, Transformers 5.16.1 and
the previously pinned supporting packages. It does not compile flash-attn or
use Packet's cu121 PyTorch setup preset. The node needs working `python3`, pip,
SSH, and sufficient disk; a missing prerequisite ends the attempt instead of
performing speculative system repairs while billed. Reusing the larger RL lock
costs an initial download but tests the exact inference environment we intend
to use with RL; we avoid creating a second unqualified dependency combination.

Before weights are downloaded, `verify_gpu.py --min-gpus 1` exercises a real
BF16 backward and FP8 matrix multiplication. Packet proxies CUDA calls instead
of passing a device through conventionally: compatibility with this CUDA 13
stack, NVML, FP8 kernels, CUDA graphs and cache reporting is **unverified**.
Failure here is a useful result and stops before a 31 GB download.
The smoke matrix operation is not model training. Driver/runtime failures should
be recorded; do not silently substitute a different software stack.

The pinned checkpoint is `Qwen/Qwen3.8-27B-FP8`, revision
`017b9c7af6b5689d5dd426a76e0bc077eb5ca20a`. Hugging Face metadata at that
revision lists **66 safetensors files, 30,866,866,928 bytes** (30.9 decimal GB),
including multimodal weights even though this benchmark loads text-only.
The worker requires at least 65 decimal GB free for weights, wheels/environment
and results. Download includes metadata/tokenizer files too.

## Storage and download choices

[Packet persistent storage](https://support.packet.ai/docs/storage) documents
NFS volumes under `/data/shareXX`. They can survive instance termination and
be mounted by a subsequent GPU pod; charges continue while no GPU is running.
Adding storage after launch restarts the pod and discards ephemeral files.
Snapshots retain configuration/storage references, not packages written to the
ephemeral filesystem. Volume prices and cross-pool attachment rules need checking
in the dashboard; the published CLI has no verified storage creation/attachment
interface. We do not guess extra JSON fields for it.

After the user's persistence request, public dashboard source was inspected:
its supported frontend routes are `/instances/shared-volumes` (list/create/delete),
`/instances/shared-volumes/storage-blocks?region_id=...` (plans), and
`/instances/{id}/volumes/{volume_id}/attach`. Creating storage sends
`{name, region_id, storage_block_id}`. However, the list/plans requests return
**HTTP 401 with the working API key**; those newer dashboard routes require
dashboard session authentication. The separate documented bare-metal volume and
pricing endpoints returned **404** with this account. No volume was created,
and no rate was guessed from third-party price listings. Dashboard source also
uses newer instance fields/endpoints than the npm CLI. Treat its request schema
as a different interface, not interchangeable with the API-key CLI schema.

Source snapshots were read from the public dashboard assets
[storage client](https://dash.packet.ai/assets/useStorage-CL71lvaO.js),
[storage page](https://dash.packet.ai/assets/StoragePage-Cbq_p-26.js), and
[instance client](https://dash.packet.ai/assets/launchOptions-Y-yUw5kh.js).
The current API-key-only helper cannot attach a persistent volume. The clean
next options are a dashboard-created/attached volume with a deliberately adapted
launch workflow, or Packet publishing API-key storage support. Do not fabricate
storage fields in the legacy launch body or borrow dashboard credentials from
unrelated browser profiles.

No public CPU offer was found. Staging on a cheaper GPU could work with a suitable
shared volume, but there is little incentive for the first $0.66/hour attempt.
Start with a direct, pinned HF download. For repeated experiments, attach a
volume at creation and set `HF_HOME=/data/shareXX/huggingface` on the worker;
the helper currently uses ephemeral storage and does not provision/attach it.
The volume needs room for the ~31 GB model plus its own workload. Cache the uv
environment separately if repeatedly paying for wheel downloads becomes material.

`snapshot_download` already reuses a populated HF cache. Transferring an existing
cache from object storage or a persistent disk is another option; workstation
upload speed may make SCP slower than HF. Do not copy authentication files from
the cache. The public checkpoint requires no token. An optional HF token grants
[authenticated request limits](https://huggingface.co/docs/hub/rate-limits),
not a guaranteed increase in sustained download bandwidth. No new token is needed
to prepare this test; `HF_TOKEN` already exists locally.

## Finite speed test

The worker starts a localhost-only server with the FP8 checkpoint, BF16 compute
dtype, 65,536-token context, maximum sixteen sequences, 8,192 scheduled tokens
per batch and 85% memory utilization. KV cache dtype is `auto` initially;
`--kv-dtype fp8` is separately available in the native benchmark script.
Prefix caching is explicit, with `mamba_cache_mode=align` for hybrid attention.
There is no adapter or synchronization layer in this first base-model test.
Dev mode is enabled only for the localhost cache-reset endpoint.
The `mtp` preset adds native MTP with three speculative tokens. It does not
qualify runtime LoRA+MTP or represent DFlash performance.

The client invokes the pinned **`vllm bench serve`**, not our own timing loop:

| Case | New input | Shared prefix | Output | Concurrency | Measured requests |
|---|---:|---:|---:|---:|---:|
| Decode c1 | 512 | 0 | 512 | 1 | 16 |
| Decode c4 | 512 | 0 | 512 | 4 | 32 |
| Decode c16 | 512 | 0 | 512 | 16 | 64 |
| Cold prefill | 8,192 | 0 | 16 | 4 | 32 |
| Cached prefix | 256 | 8,192 | 256 | 4 | 32 |
| Longer context | 32,768 | 0 | 128 | 4 | 8 |

These are requested lengths in the **Qwen3.8 tokenizer**, not characters. Native
results preserve the actual token lengths. Prefix length is **additive**:
the cached case has 8,448 total input tokens. Native initial checks are disabled,
and cold cases have zero warmups; the cached case alone has one
warmup: **185 total model requests** across the six cases. Native default initial
requests would populate the first measured prompt's cache, so we explicitly
disable them after the external health check. Fixed lengths, ignore-EOS, distinct seeds and
explicit cache resets make the experiment small and interpretable. The benchmark
allows up to fifteen minutes including server load within the outer attempt.
It aborts on unsuccessful cache reset, failed requests or an incomplete result.

Native random prompts are a hardware/kernel check, not representative browser
trajectories. MTP acceptance and throughput on these prompts may differ sharply
from browser actions. Once this works, test realistic contexts and tool calls
before substituting the result into a broad-evaluation cost estimate. An eager
fallback exists as `--eager` on the native worker script, but is never retried
automatically: record CUDA graph failure first.

## Results and interpretation

Local files go under ignored `training/outputs/packet/<name>/`:
`manifest.json` (quote, balance, revisioned source hashes, git commit),
`allocation.json` (instance ID, timing, worker exit, termination status and
estimated—not invoiced—cost), `worker.log`, and `results.tar.gz`.
The remote archive contains GPU validation, disk information, frozen package
versions, model revision/path, server log, benchmark plan, execution timing,
per-case native result JSON/per-request details and Prometheus snapshots.
Failed attempts preserve whatever artifacts are available.

For each case inspect output throughput, completed/failed counts, latency/TTFT,
and request input/output lengths. Preserve metrics before and after:
`vllm:prompt_tokens_by_source_total{source="local_compute"}`, cached prompt tokens,
prefix cache hits/queries, cache utilization, preemptions and speculative metrics
where exposed. Counters may be asynchronously published; inspect them together
with server logs rather than assuming a perfect instantaneous boundary.

**Logical input tokens/s is not fresh prefill tokens/s in a cached workload.**
The cached case's warmup appears in the Prometheus delta but not the measured
benchmark duration; do not divide that whole delta by the native measured
duration. Short-output, cold-input cases approximate prefill-dominated throughput,
not a pure isolated prefill kernel benchmark. Decode c1 also measures per-user
latency, while c16 measures aggregate throughput. Both matter for browser loops.

The historical cost heuristic assumes 1,000 aggregate decode tokens/s and
5,000 fresh prefill tokens/s with context retained. This shared offer has to
demonstrate those assumptions. At $0.66/hour and full saturation they imply
$0.183 per million decode tokens and $0.0367 per million fresh prefill tokens;
divide by the useful utilization fraction to account for idle/browser time.
For cached input there is no separate per-token billing, but cache memory and
long-context decoding still consume resources.

## Local validation

```bash
training/.venv/bin/python -m pytest -q training/tests/test_packet_cloud.py
bash -n training/scripts/packet_vllm_worker.sh
```

Tests cover hourly/monthly price selection, absent capacity/price limits, strict
SSH command parsing, secret-free upload archives, context sizing, failure and
interrupt cleanup, ambiguous allocation handling, and refusal to run without
`--execute`. All six benchmark commands and both server presets were additionally
parsed against the installed vLLM 0.28.0 argparse implementations without model
loading or CUDA execution. Live SSH transport, provisioning, deletion and
CUDA-proxy behavior still require the paid qualification attempt.

References: [native vLLM 0.28.0 serving benchmark](https://docs.vllm.ai/en/v0.28.0/cli/bench/serve/),
[HF downloads](https://huggingface.co/docs/huggingface_hub/en/guides/download),
[official checkpoint](https://huggingface.co/Qwen/Qwen3.8-27B-FP8/tree/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a).
