# Nonblocking browser feedback and buffered timing diagnostics

Implemented locally on 2026-09-28; offline browser acceptance only. No paid model episode was started for this increment.

## What changed

`BrowserEvents.drain()` now reads only events already delivered into the Python buffer. It does not enumerate browser frames, evaluate JavaScript, or wait for pending bindings. DOM observers continue pushing events through the existing Playwright binding. Events arriving later are eligible for a subsequent feedback update; delivered events survive navigation and frame removal.

Previously every drain checked and flushed every live frame synchronously. In the most recent Gemini trial, one before-request feedback phase took 19.733 seconds with a frame-flush warning. That trace does not identify the individual offending frame/RPC. Removing the flush removes this dependency from feedback delivery; it does not establish a speedup for unrelated capture, navigation or inference.

Observer installation on existing documents and CDP dialog observation use bounded asynchronous work on the existing Playwright owner loop: four concurrent installs, at most 128 pending, a 500 ms operation timeout. Future documents receive the existing context init script. Installation failures are capture warnings, never action retries. Context shutdown cancels outstanding installs without waiting for a hung frame. Explicit standalone collector cleanup still closes installed observers.

The DOM producer now renews its rate limit without a flush: up to 64 events per 250 ms window, at most 64 pending bindings per document. Overflow emits an asynchronous gap notice; Python still caps each delivery buffer at 64 events and reports omissions. This is best-effort public feedback, not an exhaustive event journal or verifier.

Page/frame identity and document sequence are retained in raw evidence. Delivery-window labels describe when Python received the event, not which action caused it. The policy presentation explicitly warns about delayed events. Current tab custody filters continue to exclude non-agent feedback. Page observers/listeners can be installed in other tabs so subsequent adoption does not require a synchronous sweep; events are filtered before retention and again before delivery.

### Delivery limits

- There is no guarantee that all events caused by an action appear in its immediate tool result.
- Bindings are processed when the Playwright owner loop runs. A blocking model request without concurrent browser work can delay delivery until subsequent browser processing.
- Events not received before document/context destruction can be lost. Terminal completion does not force a final frame flush.
- This change does not repair the separate post-click event-pump `AttributeError` from the last live trial. Debug mode now preserves exception stack locations to make the next such failure diagnosable.

## Enable debug mode

Use either the explicit episode argument:

```python
run_episode(..., debug_timings=True)
```

or export the process setting before launching:

```bash
export HARNESS_DEBUG_TIMINGS=1
```

The default is off. An explicit `False` overrides the environment. Environment values must be `0` or `1`; a value merely stored in an arbitrary dotenv file is not automatically exported by the runner.

The selected mode is recorded in trace metadata. When enabled, `debug-timings.json` is written after episode completion/cleanup, including normal exception handling. The buffer holds at most 50,000 records and reports additional dropped records. A hard process kill can lose this diagnostic buffer; ordinary lifecycle/trace recording is unchanged.

Recorded spans cover existing capture/frame phase timings, observer installation queue/operation time, feedback drains and formatting, preview formatting, prompt construction, input-token counting, completion/capture barriers, browser steps, observation serialization/enqueue, lifecycle/step writes and cleanup. Exception records contain type and file/line/function stack locations, without locals or exception messages. Timing records do not enter model context. Existing lifecycle timestamps and `recording.json` still provide the complementary request/background-writer evidence.

Debug logging adds no browser queries and no per-record disk writes. It does allocate bounded records and read the clock; its overhead is measurable, not zero. Existing lifecycle logging remains synchronous as before.

Summarize an existing trace:

```bash
.venv/bin/python scripts/summarize_debug_timings.py PATH_TO_TRACE
# Machine-readable summary:
.venv/bin/python scripts/summarize_debug_timings.py PATH_TO_TRACE --json
```

Spans can nest and overlap. Their sums are **not** an exclusive episode wall-time breakdown. Mirrored lifecycle spans use the existing reported duration and the time at which the lifecycle event was emitted. Background write timings remain in `recording.json`.

## Offline acceptance

Current-source evidence: `.local/nonblocking-feedback-final/validation.json`; suite reports under `core/`, `targeted/` and `boundaries/`. All source hashes in all three suite reports match the reviewed runtime. All 37 focused unit tests (9 subtests) and 36 browser cases pass. The 17 targeted-action cases run with timing diagnostics enabled and retain zero dropped timing records. Debug on/off preserves exact scripted model requests; errors retain stack locations without exception text.

| Controlled measurement | Result |
|---|---:|
| Old serial flush, iframe busy for 500 ms, median of 3 | 456.057 ms |
| New buffer drain during the same busy condition, median of 3 | 0.016 ms |
| Debug disabled: median 100-turn synthetic recording loop | 76.942 ms |
| Debug enabled: median 100-turn synthetic recording loop | 80.426 ms |
| Added debug cost per synthetic turn, median difference | 0.035 ms |

The recording A/B alternates four samples per mode, serializing a 1,000-node synthetic observation plus 20 events and four lifecycle phases per turn. It includes writer admission/backpressure; shutdown/file flush is measured separately. These are offline measurements, not a prediction of live-model wall-time improvement. The busy-frame test also confirms the browser remains usable after the stall resolves.

Browser acceptance covers delayed delivery without duplicates, active-tab adoption and custody filtering, autonomous quota renewal/overflow reporting, bounded initial installation, cancellation at close, hidden/password exclusion, dialog auto-dismiss behavior, navigation/frame destruction, exact policy evidence, full-capture fallback and existing action-guard boundaries. No asynchronous unhandled-task warnings were found in the final logs. No model/network-provider calls were made.

Reproduce:

```bash
.venv/bin/python -m pytest -q tests/test_debug_timings.py tests/test_core_feedback_runner.py \
  tests/test_feedback_presentation.py tests/test_execution_feedback.py \
  tests/test_action_error_feedback.py tests/test_async_recording.py tests/test_targeted_guard.py
.venv/bin/python scripts/verify_nonblocking_feedback.py --output NEW_DIRECTORY
.venv/bin/python scripts/verify_core_browser_feedback.py --output ANOTHER_NEW_DIRECTORY
LD_LIBRARY_PATH="$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu" HARNESS_DEBUG_TIMINGS=1 \
  .venv/bin/python scripts/verify_targeted_actions.py --workers 2 --output THIRD_NEW_DIRECTORY
```

Independent boundary cases run with two browser workers. The intentional stall comparison and debug-overhead A/B run sequentially to avoid cross-case CPU contention. The legacy feedback suite uses sequential cases in one browser process, with separate contexts, including a cross-context isolation check.
