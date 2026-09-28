# Background observation recording

`run_episode` now defaults to `async_recording=True`. Set it to `False` for a
synchronous comparison. Root and helper episodes inherit the selected option.
Standalone `Trace` remains synchronous for compatibility; use
`Trace(..., async_recording=True)` explicitly outside the runner.

Observation JSON is serialized on the caller thread to freeze nested mutable
browser state. Screenshot pixels are copied before submission. The writer never
uses Playwright or reads the original observation. The small AX text file remains
synchronous because exposure graders consume it immediately. PNG encoding and
saving, gzip compression and raw-file writing happen in one ordered worker thread
per trace. This overlaps browser capture/decoding; it does not eliminate CPU work
or all Python GIL contention.

The queue allows up to eight pending observations and 128 MiB of accounted
immutable payload/pixel buffers, including the active job. Queue bookkeeping uses
Python string allocation size plus pixel bytes; this is not an RSS ceiling or an
estimate of the complete live observation. A saturated queue waits for its oldest
job. A single oversized item drains the queue and writes synchronously. There is
no silent drop or unlimited backlog. The caller-side current snapshot/serialized
payload and compression buffers add to memory usage.

Raw/PNG files are published using temporary files and atomic replacement. AX text
is available when `observation()` returns; raw/image references can be pending.
`flush_observations()` is the explicit barrier for immediate raw/image readers.
`finish()` drains the queue before publishing episode completion, shuts down the
worker and saves `recording.json` with queue/writer timings. Write failures
propagate and mark `trace_complete:false` and `recording_error`; outcome grading
is not silently reclassified. Abrupt process termination can lose pending writes;
this is not a durable external queue.

The team publisher exposes only the prefix of steps whose referenced media/text
are present, then catches up on its next poll. It does not block inference to wait
for media. Existing explicit screenshot tools remain synchronous when the model
needs image bytes. Video is a separate feature.

## Acceptance and timing

- Seven writer/publication tests cover queued mutation isolation, immediate AX
  text, complete finish across phases, FIFO ordering, backlog/oversized handling,
  atomic failures and pending-image publication.
- Final focused acceptance: 68 tests / 10 subtests pass. One unrelated worker
  test was deselected after confirming it still expects the former 4096 output
  default while the existing backend now defaults to 16384. The initial broad
  run retained that failure; it was not changed as part of recording work.
- `.local/async-recording-browser-v1/report.json`: seven scripted browser cases
  pass with background recording, automatic screenshots on/off, native/static/
  dynamic pipelines, exact saved artifacts and explicit screenshot delivery.
  No model calls.
- `.local/recording-overlap-prisjakt-v1/report.json`: current live Prisjakt homepage,
  5381 AX nodes/four captured DOM documents. Forty captures: two blocks of five
  per mode, reversed mode order. No pauses or inference between captures.
  Sequential performance isolation; GC only between blocks. Initial navigation
  and five-second settling excluded. Final queue drain included in throughput.

| Mode | Synchronous wall/capture | Background wall/capture | Foreground recording, sync → background |
|---|---:|---:|---:|
| No screenshots | 0.784 s | 0.641 s | 152 ms → 26 ms |
| Screenshots | 0.854 s | 0.749 s | 189 ms → 27 ms |

Wall/capture divides total block wall time (including flattening, final flush and
loop overhead) by captures; recording columns are medians. Recording overlapped
a later capture for all eight eligible writes in each background mode, zero in
synchronous controls. Last writes have no next capture and are drained explicitly
(127 ms without screenshots, 160–162 ms with). Actual backlog stayed at one job;
accounted payload peaks were about 4.4/7.1 MB. This establishes loaded-homepage
capture overlap, not Windows-CDP, navigation or full-episode speed. Live content
may vary; artifact completeness and source fingerprints were checked.

Reproduce in a fresh directory:

```bash
LD_LIBRARY_PATH="$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu" \
  .venv/bin/python scripts/benchmark_recording_overlap.py \
  --output .local/recording-overlap-prisjakt-NEW
```

Local implementation only; no production worker/container restart or deployment.
