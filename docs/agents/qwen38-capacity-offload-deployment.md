# Durable MTP3 CPU-KV deployment and the next capacity test

The reviewed vLLM 0.28 backport is part of the deployment source, rather than a
manual change in a disposable GPU container. The isolated RTX PRO 6000 test
restored 58,240 prompt tokens / 2.03 GiB from CPU in 1.03–1.16 seconds, with matching
greedy token IDs. That establishes restoration after a GPU-only prefix reset;
natural LRU pressure and sticky episode parking are the next qualification.

## Keep the fix through deployment

`training/patches/vllm028_mtp_cpu_offload.patch` and
`training/scripts/apply_vllm_cpu_kv_patch.py` are required deployment inputs.
The shared `modal_rl_image.build_image()` installs and verifies them after the
locked package install. `bootstrap_remote.sh rl` and `rl-sm120` do the same,
including after the optional extra's final sync. The historical Packet/Runpod
benchmark upload allowlist also carries both inputs; its worker applies after
sync and checks before benchmarking, saving a fresh receipt. `verify_stack.py --role rl`
fails when the installed scheduler is stock or differs from the reviewed hash.
The normal RL serving launcher verifies the actual server interpreter and stores
the patch receipt in its provenance, before starting workers.

The pinned identity is:

| Field | Value |
|---|---|
| vLLM | 0.28.0 |
| Patch |`vllm028-mtp-cpu-offload-v1`|
| Installed scheduler SHA256 |`599a1613fb6088a28c14b7fb2119b7eabfe5ed5e4085b1c6fd5f4a4c8a23f3ec`|
| Patch SHA256 |`453b0238c7a3072c7c558778db91b98214ba46dca704e9dbf9932e5f2ea587b6`|
| Context |262,144 tokens, Qwen/Qwen3.8-27B-FP8|
| Qualified cache profile |native MTP3, FP8 E4M3 KV,1664-token blocks, `prefix_match_unit=null`,20 GiB native CPU offload, LRU|

An arbitrary `uv sync` can restore stock package files. Reapply before starting
workers, then verify; a historical image receipt is not enough:

```bash
training/envs/rl/.venv/bin/python -B training/scripts/apply_vllm_cpu_kv_patch.py --install-in-place
training/envs/rl/.venv/bin/python -B training/scripts/apply_vllm_cpu_kv_patch.py --verify-only
```

For a standalone SSH host, the guarded serving entry point retains the exact
cache/MTP configuration and records fresh installed-source identity:

```bash
training/envs/rl/.venv/bin/python -B training/scripts/serve_qwen_cpu_offload.py \
  --snapshot "$HF_HUB_CACHE/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a" \
  --receipt training/outputs/server/cpu-kv-serving.json
```

The default compiler comes from the locked NVCC wheel, ignoring an inherited
system `CUDA_HOME`; an explicit `--cuda-home` must have the supported wheel
layout. Its chosen path is recorded.

Use a container with at least 21 GiB free `/dev/shm`; 32 GiB or more allows headroom.
This entry point records the trusted HF cache path and configuration hash
(revision binding does not hash every shard), prepares the pinned CUDA compiler
environment and private linker/cache directories, runs offline, uses localhost,
and has no unknown
argument passthrough. It is a serving process, not a cloud allocator or rental
watchdog: the host's separately authorized lifecycle must stop it. A fresh live
`/server_info?config_format=json` validation is still required for acceptance.

Finer prefix hash units can enable an unqualified 0.28 partial-tail interaction.
Do not add them to this profile. Custom launchers must preserve the null setting
and installed-source verification; arbitrary external `vllm serve` commands
are not guarded by our Python wrapper. This does not qualify LoRA+offload,
different models, GPU architectures or alternative connectors.

Do not apply this artifact to a newer vLLM version. Its exact version/source
guard fails closed. Before removing it, verify that the successor includes
upstream fixes #52771, #52807 and #54288 and pass the isolated and integrated checks.
Include the fresh patch receipt/profile in the serving fingerprint and any
qualification reuse binding; old receipts do not certify this changed stack.

## Controlled integrated GPU diagnostic

This combines the actual shared metrics poller and episode controller with a
real Qwen/vLLM engine. Tool pauses are Python barriers. It does not qualify the
native browser runner or Evaluation's cross-process RPC integration.

1. Start the guarded FP8/MTP3 engine with20 GiB CPU KV and a deliberately smaller
   **12 GiB GPU KV pool**. Retain native262,144token context. The explicit byte
   setting overrides the automatic GPU-memory-utilization cache calculation.
2. Register six logical episodes with stable priorities. Seed six distinct
   **59,905token inputs** (64output tokens each) to establish their histories.
3. Dispatch one 512-output-token turn per episode concurrently. All six permits
   are acquired before this burst begins. Actual capacity-waiting/high-KV
   samples must trigger parking; there are no synthetic pressure signals or
   cache reset calls. Sustained pressure may cause preemption; record it.
   Attribute CPU-load/external-hit deltas across the burst and compare its first
   64 generated token IDs with each seed. The equality gate is conservative:
   a mismatch under concurrent MTP can reflect numerical near-ties and does not
   establish cache corruption by itself. Restores during this burst count even
   when parked actors subsequently remain GPU-resident.
4. Allow already-dispatched turns to finish. Hold all episode-terminal signals
   so parked actors cannot consume an early completion credit. Assert they
   still count against the six-episode lifecycle cap.
5. Attempt a parked next turn and verify across two fresh telemetry samples
   that it stays outside vLLM (no controller request ID or dispatch increment). Finish one
   unparked episode, then allow priority-ordered resumptions with 64 output
   tokens each. Capture fresh CPU-load bytes, external-hit tokens, cached-input
   tokens and greedy output equality against each actor's initial seed.
6. Verify every acquired permit is released, every actor retires dispatch and
   completes cleanup, no credit leaks, and the worker/server stop. Distinguish
   parking correctness, model/cache health and observing natural CPU restoration.
   Report parked-actor CPU return separately from any CPU return during the burst. If pressure
   never triggers or no CPU return occurs, the intended scenario is unproven;
   do not quietly retry or call it a full integration pass.

The maximum is 18 inference requests, no training, no downloads and no automatic
retries. The phases share one engine/cache and depend on prior phases, so only
the deliberate burst is parallel. The12 GiB pool is a test fixture, not a
throughput deployment recommendation. Its suitability still needs GPU loading;
the script fails if native context cannot fit or the pool is not applied.

Offline plan (no .env read, allocation or network):

```bash
training/.venv/bin/python -B training/scripts/modal_cpu_kv_offload.py \
  --scenario capacity --env-file /path/to/ignored/.env \
  --output /path/to/new/results --dry-run
```

Execution requires a newly authorized single Modal allocation. The default is
20 minutes from dispatch, including queue/startup, plus a platform fallback;
capacity mode accepts only 15–20 minute job caps, rejecting shorter caps locally;
cleanup reserves are internal and retries remain disabled. The capacity mode
requires at least 12 minutes remaining on GPU arrival, 10 minutes before model
startup and 4 minutes after startup before it seeds histories. A late allocation
fails without starting an experiment that cannot reasonably finish. Removing `--dry-run`
uses cached model weights, records exact sources and the patch identity, commits
intermediate evidence to the results volume, and terminates the allocation.
This diagnostic's finite cap is separate from any browser episode run budget.

## Native browser follow-up

Evaluation's approved RPC source (`cc8304da`, controller `d7ff5ed9`) is CPU-ready.
A newer candidate (`ee7abc51`) closes its five source followups and the
admission/terminal bindings. Six separate-process native browser, grade and
current-HTTP positive controls pass with synthetic metrics, including parking
and warming; its independent review is pending. Actual native cancellation and
failed-cleanup acceptance remain separate. Evaluation owns that caller.

Do not replace an in-flight suite's simpler queue or treat the controlled GPU
diagnostic as native browser/RPC qualification. After the caller's review,
integration and required model-free acceptance, bind its exact source/runtime
to this guarded serving stack for a separately authorized browser experiment.

## CPU checks

Use the RL interpreter for the model-free HTTP/metrics composition (`unittest`
needs no pytest). The light SDK environment skips that one check when
prometheus-client is absent; it still runs the pure serving/permit guards.

```bash
python3 scripts/run_bounded_job.py --memory-mib 2048 --tasks 96 -- \
  training/envs/rl/.venv/bin/python -B -m unittest discover \
  -s training/tests -p 'test_capacity_kv_offload_probe.py' -v
```

Missing load/store/allocation-failure counters are zero until the native
exporter creates them. Preserve startup metrics and poller errors on failures;
missing optional counters alone are not an infrastructure fault.
