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

## Finite speed test: active-cache residency profile

The default is now `--suite residency`, following the user's request to replicate
methods from `/home/bjorn/code/inference_stuff`. The original small random suite
remains available as `--suite smoke`; it is no longer Packet's default worker
workload. The user's later instruction replaces the original 185-request shape;
the approved thirty-minute whole-attempt limit and no allocation retries remain.
No additional MTP run or paid time extension is implied.

The prior exact-model suite is recorded in
`inference_stuff/docs/experiments/qwen38-browser-suite-v1.md`. We freeze its
synthetic browser-history generator in `browser_benchmark_prompts.py` and port
its capacity and guarded-decode methods. Source SHA256 is in the module.
No source file in that repository was modified. These are synthetic browser
observations, not captured traffic or task-success evidence.

The target server uses the same checkpoint/tokenizer revision, FP8 E4M3 attention
KV, BF16 convolution state, FP32 recurrent state, Triton GDN prefill, CUDA graphs,
95% memory utilization, scheduler ceiling 256 and 8,192 batched tokens. Context
capacity is 31,008 tokens: 30,000 input + 1,000 output + eight lookahead tokens.
Prefix caching defaults **off**, with Mamba cache mode `none`, matching the old
cold-prefix capacity recipe. Pass `--prefix-caching` to the benchmark script for
an explicitly separate APC/`align` experiment; pass `--kv-dtype auto` to compare
BF16 attention KV. FP8 KV speed does not establish task-quality equivalence.
Our version remains locked vLLM **0.28.0**, while the earlier Modal suite used
**0.29.0**: this is a replication of workload/methods, not an isolated provider
comparison. Host CPU count also differs.

The read-only startup probe calls vLLM's own group-aware cache-capacity helper
on copied model/draft configurations. It includes hybrid state, page padding,
output growth, speculative state and the reserved null block. It does not modify
live allocation, scheduling or forward computation. Select maximum integer
concurrency that fits a complete 30K or 5K request, bounded by 256. Re-profile
for each engine/preset instead of recycling previous numerical concurrency.
The plan records predicted reservation, whether the scheduler ceiling limited
capacity, and observed active-cache usage. Near-full cache is a target for the
maximum-concurrency decode cases, not a promised outcome for every phase.

| Case | Exact Qwen3.8 input tokens | Output tokens | Concurrent requests |
|---|---:|---:|---|
| Long-context decode | 30,000 | 1,000 | Complete-request maximum for 31,008-token reservation |
| Short-context decode | 5,000 | 1,000 | Complete-request maximum for 6,008-token reservation |
| Long prefill probe | 30,000 | 1 | Same concurrency as long decode |
| Short prefill probe | 5,000 | 1 | Same concurrency as short decode |
| Short decode comparison | 5,000 | 1,000 | Half the short maximum |

Each arm submits **one cohort of C distinct requests**, with request count equal
to concurrency, no oversampling, no preliminary model request, no warmup and no
turnover. At most five arms and 1,152 model requests; actual concurrency is
resolved on the GPU and recorded before execution. There is one repeat, not an
open-ended search. Maximum-residency decode cases run first. Partial coverage
under the existing deadline is preserved and explicitly marked incomplete;
time limits are not extended to finish the last case. The half-capacity point
checks whether peak throughput occurs below the memory ceiling. Short-input
results bound performance only over the tested grid, not all possible settings.

The client still uses **`vllm bench serve`**, now with custom JSONL browser
prompts, greedy sampling and ignore-EOS. The model's chat prefix and final task/
generation suffix are preserved. Token IDs decoded to text can merge again at
history boundaries, so prompt preparation verifies exact lengths with the
pinned tokenizer and adjusts only that boundary. Native server-reported input
and output lengths must then match every reserved request exactly.

Cases deliberately run sequentially on one shared GPU: concurrent arms would
contaminate occupancy and phase counters. Requests within each case are concurrent.
Every case preserves 500 ms server metric samples and native detailed stream
chunk timings. Measurements follow the prior guarded-window method:

1. Wait until the latest first-chunk arrival among all C streams; add one second.
2. End one second before the earliest final-chunk arrival.
3. Keep only consecutive, timely scrapes entirely inside that window, with
   running=C, waiting=0, no new computed prompt tokens and no preemption.
4. Divide generation-counter deltas by durations between those same snapshots.
   Require at least five seconds of clean overlap; otherwise report decode rate
   unavailable rather than substituting whole-batch throughput.
5. Record active KV fraction during those decode intervals. Persistent inactive
   cache, allocated pool bytes, active occupancy and total VRAM are different
   quantities; configured client concurrency is not actual forward batch size.

Prefill is measured independently with one-output-token cold cohorts. Report
whole-case input processing rate as **prefill-dominated service throughput**.
Also recover fresh-prefill counter rates from sampled intervals with positive
computed-prompt increments and zero generation increments. These are observed
server intervals, not isolated GPU kernel timings, and may be absent when
prefill/decode overlap or sampling is too coarse. Do not reinterpret a mixed
interval or a median TTFT as pure prefill speed. MTP stream bursts are not
individual forward timings.

The `mtp` preset adds three native speculative tokens and profiles its own
changed memory capacity. A maximum-capacity baseline/MTP comparison can have
different C; it does not isolate the effect of speculation at fixed C. Runtime
LoRA+MTP and DFlash remain outside this base-model qualification.

### CPU replay of the previous RTX PRO result

Reanalysis of archived FP8/MTP-off run
`20260914-233252-qwen38-fp8-mtp0-3b0ca029` recovered **2,044.47 decode tokens/s**
at **5K input / concurrency 172**, versus the original analysis's **2,044.44**:
about **0.0014%** difference from midpoint versus scrape-start timing.
The clean window covers **72.27 seconds**, with sampled active KV occupancy
**99.67%**. Whole-workload output throughput was about **1,005.8 tokens/s**.
These are prior real RTX results, not new Packet measurements. Pure-prefill
intervals were unavailable in that replay and are not invented from TTFT.
The concise replay receipt is
`training/research/packet-phase-replay-validation.json`; raw evidence remains
in the inference repository. This validates the ported accounting on real
saved traces before paying for another GPU.

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
The optional smoke suite's cached warmup appears in the Prometheus delta but not the measured
benchmark duration; do not divide that whole delta by the native measured
duration. Short-output, cold-input cases approximate prefill-dominated throughput,
not a pure isolated prefill kernel benchmark. The optional smoke suite's c1
point also measures per-user latency. The residency grid targets saturation;
neither replaces realistic browser-loop latency measurements.

The historical cost heuristic assumes 1,000 aggregate decode tokens/s and
5,000 fresh prefill tokens/s with context retained. This shared offer has to
demonstrate those assumptions. At $0.66/hour and full saturation they imply
$0.183 per million decode tokens and $0.0367 per million fresh prefill tokens;
divide by the useful utilization fraction to account for idle/browser time.
For cached input there is no separate per-token billing, but cache memory and
long-context decoding still consume resources.

## Local validation

```bash
training/.venv/bin/python -m pytest -q training/tests/test_packet_cloud.py training/tests/test_vllm_residency.py
bash -n training/scripts/packet_vllm_worker.sh
```

Tests cover hourly/monthly price selection, absent capacity/price limits, strict
SSH command parsing, secret-free upload archives, context sizing, failure and
interrupt cleanup, ambiguous allocation handling, and refusal to run without
`--execute`. New tests cover copied-config capacity probes, output reservations,
scheduler-limited memory claims, guarded intervals, missing overlap, counter resets
and preemption. All five residency commands and baseline/MTP server flags with
APC on/off were parsed against installed vLLM 0.28.0 argparse; the older six
smoke commands had passed the same check. Cached tokenizer/template checksums
match the exact FP8 revision, and four distinct 5K plus four 30K prompts passed
the official tokenizer and native CustomDataset path on CPU. No model was
loaded or CUDA executed. Live SSH transport, provisioning, deletion and
CUDA-proxy behavior still require the paid qualification attempt.

References: [native vLLM 0.28.0 serving benchmark](https://docs.vllm.ai/en/v0.28.0/cli/bench/serve/),
[HF downloads](https://huggingface.co/docs/huggingface_hub/en/guides/download),
[official checkpoint](https://huggingface.co/Qwen/Qwen3.8-27B-FP8/tree/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a).
