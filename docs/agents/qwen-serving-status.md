# Qwen serving logs and live metrics

The serving observer is source preparation for the next Qwen suite. It does not
start a model, allocate a GPU, create a W&B run or publish a dashboard. The suite
caller must adopt the reviewed source and attach the observer/sinks before launch.

The intended human view combines the raw vLLM log over SSH with concurrency and
throughput charts in the **same W&B suite run** as task results. Keep the full
`vllm.log` in the remote run directory. The human can follow it directly:

```bash
ssh -T GPU_HOST 'tail -n 40 -F /absolute/private/run/vllm.log'
```

Replace the host/path with the actual authorized deployment's values. Set
`VLLM_LOG_STATS_INTERVAL=5` before launching and keep vLLM stats enabled. This
provides periodic status plus startup/warning logs; it is independent of the
one-second Prometheus sampling. The controller's log relay, if used, must read
bounded newly appended byte chunks, never resend the whole file every tick.
The same observer also works on Modal; its console log is the alternate raw-log
view there. Share the actual SSH command and W&B run/report URL once deployed.

## What the charts mean

| Metric | Meaning |
|---|---|
| `serving/running_requests` | Requests currently scheduled by vLLM, including prefill and decode. This is not the number of browser episodes or GPU forward batch size. |
| `serving/waiting_requests` | All vLLM waiting requests. Capacity waiting and deferred waiting are also shown separately. Parked episodes outside vLLM do not contribute. |
| `serving/initial_prefill_tokens_per_s` | Initial prompt tokens accounted at first output, excluding cached tokens. Credited in a lump when initial prefill finishes, so it can show zeros followed by spikes. Excludes repeated prefill after preemption; this is completed initial-prefill accounting, not instantaneous GPU prefill speed. |
| `serving/output_tokens_per_s` | Aggregate generation counter increment per wall-clock second across requests. Includes mixed prefill/decode/tool-pause intervals; not an isolated decode benchmark or single-request TPS. |
| `serving/kv_cache_percent` | Engine GPU KV-pool use, not total GPU VRAM. |
| `serving/cached_input_percent` | Fraction of initial prompt-source tokens reused locally or externally, accounted at first output. Shares the same lumping and excludes post-preemption repeats. Empty if no prompt tokens were accounted. |
| `serving/cpu_load_bytes_per_s` / `serving/cpu_store_bytes_per_s` | Connector transfer rates, not how many bytes remain resident in CPU cache. Missing lazy exporter series stay unavailable. |
| `serving/preemptions_per_s` | Engine preemption counter increments per sampled second. |
| `serving_total/*` | Observed cumulative counters for this engine process. Show the first lazy CPU transfer even though no previous observation exists for a rate. Resets remain resets, not a continuous lifetime sum. |
| `serving/counter_reset` / `serving/sample_gap` | Interval flags; inspect alongside rates so a chart connecting surviving points is not mistaken for uninterrupted measurement. |

The counters come from pinned vLLM 0.28's `v1/metrics/loggers.py` and
`v1/metrics/stats.py`; `prompt_tokens_by_source_total{source="local_compute"}`
counts uncached **initial** prefill, credited at first output. It does not
measure repeat-prefill work or GPU kernel time. Select exactly one `model_name` and `engine`;
do not sum arbitrary replicas or include other models.

Rates need two observations. Counter resets and gaps over five seconds create
a new segment with unavailable rates at its first point. A missing measurement
is not zero. Check the batch's `latest_sample_age_seconds` and the poller's
`last_error`/`observer_error` before interpreting a flat graph as an idle engine.
Observer active/last/max durations are exposed in poller status. Arbitrary Python
callbacks cannot be preempted; a blocked callback can make capacity telemetry
stale, so use only the fast in-memory observer on this hook. Observer `BaseException`
errors are recorded and do not kill the poller. Do not infer continuous prefill
throughput from the initial-prefill completion spikes.

## Caller integration

The capacity parent owns **one** metrics poller. Its optional `on_scrape`
callback receives the same response plus the poller's explicit model/engine;
the observer rejects mismatched identities. There is no
second HTTP poller. Only bounded parsing and memory updates happen in that
callback. Observer errors are separate from genuine capacity-telemetry failures.
Keep arbitrary disk/network/W&B work outside both poller callbacks.

```python
telemetry = ServingTelemetry(
    session_id=serving_session_id, model=model, model_revision=revision,
)
poller = SharedMetricsPoller(
    "http://127.0.0.1:8000/metrics", model=model,
    interval=1, on_snapshot=controller.observe, on_scrape=telemetry.observe,
)
```

Every five seconds, the remote worker reads
`telemetry.read(after=cursor, observer_id=cursor_observer_id)` and
passes only the new rows through its existing controller channel. Each batch
has at most 120 rows; the history retains at most 7,200 samples by default.
On the first read use cursor zero and observer ID None. Bind the batch's session
ID to the live deployment and retain its observer ID before updating the cursor.
A new observer has a new nonce even under the same serving session: an old
nonzero cursor is rejected. Explicitly rebind and reset the cursor rather than
silently losing early rows. Preserve observer ID in the journal. W&B uses UTC
sample time so observer-relative elapsed time cannot overlap after recreation.
Persist the rows as `serving-metrics.jsonl` beside the suite traces, checking
sequence/order and reporting `gap=True` explicitly if the reader fell behind.
Print `status_line(last_row)` to the console; retain every received row in the
journal so an agent can read the same measurements without W&B access.

On the **local** controller, the single W&B writer for this suite can publish
`wandb_values(row)` to its existing run:

```python
run.define_metric("serving/sample_utc")
run.define_metric("serving/*", step_metric="serving/sample_utc")
run.define_metric("serving_available/*", step_metric="serving/sample_utc")
run.define_metric("serving_total/*", step_metric="serving/sample_utc")
# In the existing publisher loop, outside the scrape callback:
run.log(wandb_values(row))
```

Keep W&B credentials on that local publisher. If a separate uploader already
owns the run, feed these rows to that uploader rather than opening a second
writer. Configure the named charts and include the new suite run in the human
report's explicit run selection before dispatch; adding metric keys alone does
not update an already-published W&B report. Synthetic controls need an explicitly
synthetic run and `allow_synthetic=True`; never mix them into real model results.

The future composed caller still owns transport, journal writes, terminal flushing,
raw-log forwarding and W&B/report publication. This module provides the reviewed
observation interface; it does not silently activate those integrations.
