# Episode capacity controller

Implementation: `training/browser_training/capacity_control.py`. CPU-only protocol,
concurrency tests and the executable smoke cover simulated episode turns. This
has **not** been deployed into a browser suite/RL caller or qualified with GPU
KV offloading. Evaluation owns prospective caller/channel composition. Existing
frozen callers, including the current MiMo suite, remain unchanged.

## How it behaves

One parent process owns one `SharedMetricsPoller` and one
`EpisodeCapacityController` per dedicated vLLM server/model/engine. All children
share the parent's gate; creating a controller per child defeats the limit.
Process callers must carry register/acquire/release/finish over their admission
channel. Those RPC bindings are caller work, not implemented by this module. An RPC
server must service blocked acquires concurrently so releases, metrics and
cancellation are never stuck behind an acquire on one serial channel thread.

| Event | Action |
| --- | --- |
| Two fresh samples show capacity waiting **and** high active KV usage | Select lowest-priority established episode; let its sent request finish, then block its next request. |
| Waiting backlog grows | Select the next-lowest-priority episode, retaining at least one established episode able to drain. |
| Stable waiting count persists | Keep the same victims; do not repeatedly rotate or add victims. |
| A preemption counter increment appears | Log the event; it does not bypass the waiting/KV debounce gate. |
| A whole episode finishes | Grant one currently selected victim permission to resume once fresh telemetry shows zero capacity waiting and low KV usage. |
| Only a model/tool turn finishes, or metrics become healthy | Keep parked episodes parked; no terminal completion grant. |
| Telemetry is missing/stale | Block new requests with bounded, cancelable waits; do not abort sent requests. |
| Selected episode fails/cancels | Caller cleans up its actual request/process, then reports terminal completion. |

Lower numeric priority means higher importance. Equal priorities favor earlier
registration. Aggregate metrics cannot identify *which* request vLLM is waiting
on; selecting our victim by priority is deliberate. Turn return ordering does
not change that victim. This is reactive admission control, not a prediction of
an episode's eventual memory demand or a guarantee against vLLM preemption.

The `max_active_episodes` cap includes parked episodes and cancelled episodes
awaiting cleanup. It must match the existing queue lifecycle cap (currently 3 in
the inspected caller). Parking does not free an episode slot or permit extra
browser admissions. `max_generation_requests` independently limits simultaneous
model calls. Existing FIFO/prewarming rules remain caller responsibilities.

## Caller contract

```python
controller = EpisodeCapacityController(ParkingConfig(
    max_active_episodes=3, max_generation_requests=3,
))
poller = SharedMetricsPoller(
    "http://127.0.0.1:8000/metrics", model=served_model_name,
    engine="0", on_snapshot=controller.observe,
).start()
controller.register_episode(case_id, priority=priority)

# Case-owned wrapper around backend.complete; both policy and formatter paths.
# First check existing source/admission/budget gates. No permit for tokenization,
# background capture, tools or prewarming. Request IDs contain phase + sequence.
with controller.turn(case_id, f"{case_id}:{phase}:{request_index}",
                     timeout=remaining_rental_seconds, stop_event=cancel):
    response = backend.complete(messages)
    # Fully consume/close streaming responses here if the backend streams.

# Outer episode finally, after process/client cleanup and native grades/evidence:
controller.finish_episode(case_id)
```

The context manager releases every successfully acquired permit in `finally`,
including HTTP errors and timeouts. An HTTP response hook alone misses failures
before a response arrives. Do not use a global backend monkeypatch; qualify the
case-owned wrapper for native tools/background completion and every actual
policy/formatter dispatch. For an async/process transport, preserve these exact
boundaries with acquire/release RPCs and guaranteed finally cleanup.

`cancel_episode()` wakes pending local calls; it **does not abort an existing
HTTP request**. The caller owns cancellation and closing any stream. Never call
`finish_episode()` while a sent request still exists. If a child dies before its
finally runs, the parent must first close/abort and verify cleanup of the actual
HTTP work, then release the exact recorded request ID from `status()` before
terminal notification. Never release a live request merely to free capacity. Failed startup still needs
terminal cleanup if registration succeeded. Request IDs must be unique per
case/phase/sequence; episode IDs must be globally unique within the run. Only a
bounded recent terminal history is retained, so old ID reuse cannot be detected
forever. Controller events and recent terminal rows are bounded; persist snapshots
or export them to the existing logging path if long-term history is required.
Deduplicate events by sequence number; consume faster than the bounded ring wraps.
Treat a gate `TimeoutError` as a capacity/rental watchdog outcome, separately from
HTTP/provider errors even though Python also makes it an `OSError`.

Waiting timeout is an operational/rental watchdog, not a new turn/token budget.
Set it from the existing caller deadline. The controller does not modify context
limits, grading, policy reservations, adapters or retry behavior. A parked RL
episode retains its original policy lease until its normal terminal cleanup.

## Metrics and defaults

Pinned source basis is vLLM **0.28.0**. Enable statistics. Parse one exact
`model_name`/`engine`, never sum engines or erase reason labels:

| Metric | Meaning |
| --- | --- |
| `vllm:num_requests_waiting_by_reason{reason="capacity"}` | Schedulable requests waiting; may reflect token/sequence limits as well as KV exhaustion. |
| Same series, `reason="deferred"` | KV transfer/LoRA/grammar deferral; not a parking trigger alone. |
| `vllm:kv_cache_usage_perc` | Active GPU allocation fraction; excludes idle reusable prefixes. |
| `vllm:num_preemptions_total` | Cumulative preemptions; increments are recorded for diagnosis, decreases are treated as counter resets. |
| `vllm:num_requests_running`, `vllm:num_requests_waiting` | Running/total waiting; total must equal the two known reason counts. |

Default poll interval 1 second, read timeout 2 seconds, response limit 1 MiB,
pressure debounce 2 samples, high water 85%, low water 70%, telemetry freshness
3 seconds. **These are conservative starting values, not tuned GPU results.**
Poll failures use exponential backoff capped at 30 seconds and keep the old
observation timestamp. With these defaults even one failed scrape can briefly
exceed freshness; this intentionally blocks dispatch rather than assuming
headroom. Prolonged failures can delay recovery detection by up to the backoff.
Readers share `status()` without making requests. HTTP
keepalive avoids a connection per scrape. A shutdown watchdog bounds response
headers/body even if bytes trickle continuously; stop interrupts an active read.
OS hostname resolution is not cancellable by this watchdog: prefer a colocated
numeric/localhost endpoint. The callback must be short and nonblocking.

At high pressure no additional model call starts while a call is in flight.
With none in flight, one established unparked episode may drain; new first turns
wait. This avoids deadlock while contexts grow and favors finishing episodes.
Neither poll failures nor this escape automatically retries any generation.

## CPU cache and GPU acceptance

No prefix pinning, CPU lease, custom eviction or cache reset is implemented.
Configure ordinary vLLM CPU KV offloading separately and rely on its LRU policy.
Parking may let a prefix become cold and move/restore through the CPU tier, but
this is best effort: idle prefixes can still be evicted. New observations always
require some prefill; generated tails may only be stored on a later prompt.

A future bounded GPU integration should:

1. Qualify the future caller's complete-wrapper/finally and lifecycle cap first.
2. Use a dedicated vLLM server with ordinary CPU LRU (~20 GiB if host/shared memory permits).
3. Create unequal-priority multi-turn episodes and induced capacity pressure.
4. Record shared metrics, park/resume events, request IDs and existing policy versions.
5. Assert no selected actor sends a new turn until the proper terminal/headroom gate;
   no extra browser admission occurs and no generation is cancelled/retried by the controller.
6. Track actual cached tokens and CPU load/store bytes on return, not CPU usage
   gauge alone (that gauge tracks transfer pins, not total stored prefixes).
7. Measure idle active KV usage after all unparked episodes finish; if it stays
   above low water, fail the test and inspect delayed frees rather than silently
   bypassing the headroom guard.
8. Confirm full cleanup: no outstanding permits, parked live actors, processes or leases.

No cloud allocation or real-model qualification is implied by the CPU evidence.

## Local checks

From the source checkout, use the existing bounded-job launcher and Python env:

```bash
python3 scripts/run_bounded_job.py --memory-mib 2048 --tasks 128 -- \
  training/.venv/bin/python -B -m pytest -c training/pyproject.toml \
  training/tests/test_capacity_control.py -q
python3 scripts/run_bounded_job.py --memory-mib 2048 --tasks 128 -- \
  training/.venv/bin/python -B training/scripts/smoke_capacity_control.py \
  --output .local/capacity-smoke.json
```

The smoke starts an actual localhost HTTP exporter and shared poller, simulates
in-flight turns with threads, parks two victims, and resumes them in priority
order after whole-episode completions. It tags its output `scripted`; it does not
launch a browser, vLLM, GPU or provider.

Upstream: [metrics](https://docs.vllm.ai/en/v0.28.0/usage/metrics/),
[CPU KV offloading](https://docs.vllm.ai/en/v0.28.0/features/kv_offloading_usage/),
[scheduler source](https://github.com/vllm-project/vllm/blob/v0.28.0/vllm/v1/core/sched/scheduler.py).
