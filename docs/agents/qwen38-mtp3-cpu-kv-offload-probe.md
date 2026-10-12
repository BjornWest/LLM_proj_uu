# Qwen3.8 FP8 + MTP3 CPU KV restoration probe

This is a prepared, isolated inference diagnostic. No browser, capacity controller,
LoRA adapter or RL update is involved. CPU protocol controls and argument checks
are evidence about plumbing; only a future GPU run can qualify restoration.

The earlier `inference_stuff` proof used Qwen3.5-2B and vLLM0.29. This probe uses
our pinned vLLM0.28 / CUDA13 / PyTorch2.13 stack, official Qwen3.8-27B-FP8 revision
`017b9c7af6b5689d5dd426a76e0bc077eb5ca20a`, and native MTP with three draft tokens.
It reuses the reviewed image/compiler helpers and accepted engine arguments.
The official model must already exist in `browser-training-model-cache`.
The CPU preflight uses `local_files_only=True`; missing weights stop preparation
before any GPU allocation. It checks shard presence, a representative FP8 tensor
header, compiler files, CLI/request parsing, exact prompt lengths and hashes.
No new model downloads or credentials are uploaded.
An image rebuild may still install the pinned Python/CUDA dependencies if Modal's
image cache is unavailable; the model preflight never fetches checkpoint weights.

## Experiment

One Modal RTX PRO 6000, eight CPU cores and 96 GiB requested host memory. The
native CPU offload tier is 20 GiB with ordinary LRU and prompt-only storage.
Available `/dev/shm` must exceed 21 GiB; the worker fails before model startup
otherwise. Keep the same FP8 E4M3 KV cache, hybrid/Gated DeltaNet alignment,
1664-token cache blocks and native262144 model context as the accepted benchmark.
No eager-mode or async-scheduling override is added.

Two distinct synthetic browser histories contain **59,905 input tokens each**, as
counted by the pinned Qwen tokenizer (36 cache blocks plus one token). Each main
request greedily generates exactly64 tokens, with identical request body bytes
for repeated histories. These are inference diagnostics, with explicit
`allow_ungraded` and a reason; no task-solving or behavioral quality claim.

| Phase per history | Purpose |
| --- | --- |
| Clear GPU and external cache, then cold request | Establish uncached reference. |
| Replay unchanged history | Measure GPU prefix reuse and output stability; verify this control does not load CPU KV. |
| Clear **GPU only**, preserve CPU cache, replay | Require actual CPU-to-GPU transfer and external prefix hits. |
| Final full-tier clear, replay second history | Negative control: this prefix was just restored; cached tokens, CPU load bytes and external hits must all be zero. |

There are7 main requests and at most25 one-token drain requests (32 total).
A reset can fail while asynchronous storage holds GPU blocks; at most6 attempts
per reset advance transfers through short requests. This is bounded draining,
not an automatic retry of a failed inference request. Only one model engine
starts; no fallback to no-MTP or another GPU occurs automatically.

Capture exact serving configuration, requests/responses/token IDs, prompt/body
hashes, per-phase raw Prometheus metrics, reset receipts, model revision, package
versions, source fingerprints and logs. Select the model/engine metrics explicitly;
never sum another engine or waiting-reason dimensions. Wait for generation
counters to account for each response before assigning phase deltas.

A full pass requires substantial prefix reuse, actual load bytes and external hits,
nonzero CPU stores and MTP draft activity, no new corruptions/preemptions, stable
GPU control outputs and matching CPU-restored token sequences, plus the negative
control. `restore_path_passed` separately reports the data path so pre-existing
output nondeterminism is not mistaken for a missing CPU transfer. A failed full
pass never authorizes automatic adoption into the browser/RL runtime.
External hits must independently cover the minimum prefix, and restored load
bytes must be positive and no larger than that cycle's new stores. Allocation
failures also fail the gate. NaN-in-logits detection is enabled and its counter
is required; finite but incorrect KV values require the separate token-ID check.

**This does not prove natural LRU eviction/return, high concurrency, retained
screenshots, policy-versioned adapters, browser freshness or capacity parking.**
Those follow after this isolated combination passes.

## Reproducible preparation

Use the exact reviewed source checkout, with the pinned dependencies present.
Main's concurrently deleted working files must not be restored to run this probe;
use a clean Git worktree with the required source closure.

```bash
training/.venv/bin/python -B training/scripts/modal_cpu_kv_offload.py \
  --env-file /path/to/ignored/.env --output /path/to/new/result-directory --dry-run
```

The SDK dry-run defines the image/app and prints a plan without reading the .env,
querying volumes, downloading weights or launching a remote function. Offline
controls block socket connections to verify this. Actual execution drops
`--dry-run` and requires separate explicit cloud authorization.
Add `--prepare-only` to execute only the cloud CPU preflight, without requesting
a GPU. That CPU-only mode also needs authorization before using cloud resources.

One execution is capped at1200 seconds from dispatch, including any queue delay.
The function's platform timeout is a final fallback; an absolute watchdog plus
caller cancellation terminates containers at the earlier deadline. Forty seconds
are reserved internally for cleanup/evidence. Requests have body limits and
absolute response watchdogs, rather than renewable inactivity timeouts. GPU
memory, prefix eviction and CPU transfer limits remain measured outcomes.
Sources are explicitly mounted; the project .env and unrelated repository files
are not uploaded. Persistent volumes keep weights/compiler cache and result
artifacts. CPU KV contents are ephemeral for this single engine, not saved there.
If fewer than six minutes remain when a GPU arrives, skip preparation; the driver
also refuses model startup with fewer than five minutes remaining. The driver
saves its final evidence before shutdown and kills the server process group
even after its leader exits. The wrapper repeats this cleanup from a PID receipt.

## Local checks

The RL interpreter already contains prometheus-client; unittest needs no pytest
or GPU imports. The separate Modal SDK environment performs the offline dry-run.

```bash
PYTHONPATH=training/scripts python3 scripts/run_bounded_job.py \
  --memory-mib 2048 --tasks 128 -- training/envs/rl/.venv/bin/python -B \
  -m unittest discover -s training/tests -p test_cpu_kv_offload_probe.py -v
```


Upstream basis: [native CPU offloading guide](https://docs.vllm.ai/en/v0.28.0/features/kv_offloading_usage/),
[GPU/external cache reset source](https://github.com/vllm-project/vllm/blob/v0.28.0/vllm/entrypoints/serve/dev/cache/api_router.py),
[hybrid-aware offloading connector](https://github.com/vllm-project/vllm/blob/v0.28.0/vllm/distributed/kv_transfer/kv_connector/v1/offloading_connector.py),
[MTP/speculation configuration](https://github.com/vllm-project/vllm/blob/v0.28.0/vllm/config/speculative.py).
These composable features do not establish GPU correctness for this exact combination.
