# Current browser runtime defaults

Version: `browser-runtime-defaults-v1`. This selects capture behavior separately from the policy toolset (`core-tools-v12-ax-reuse`). Implemented and validated locally; this document does not certify deployed workers or unreviewed task adapters.

## Selection

`run_episode` now defaults to `observation_pipeline="auto"`. The selected mode and reason are retained as `runtime_selection` in trace metadata. Selection happens before browser/model work.

The automatic fast path requires all of:

- Live-web human-handover/tab tracking with stable-frame capture and incremental AX.
- No helper-agent runtime; helper browser concurrency is a separate supported mode that retains its existing capture path.
- A backend class that explicitly declares background completion support and does not require the browser-owning thread. Subclasses cannot inherit this declaration accidentally.
- An adapter that explicitly supports the observation pipeline, dynamic decision previews and deferred/targeted post-action observations. An ungraded direct environment without a task adapter can use the same reviewed path.

When compatible, selection matches the recent Gemini trial: a depth-two public preview, at most 64 preview nodes, visible preview BIDs, full AX capture overlapping inference, targeted main-document action checks and deferred final-action observations. Unsupported iframe/target cases retain the existing full-capture fallback. Stable document/custody checks remain in place.

Automatic screenshots default off on this fast path. The explicit screenshot tool remains available and video is independent. Requesting `trace_screenshots=True` keeps preview/background capture but disables deferred post-action capture so complete post-action screenshots remain available.

Other adapters retain complete native observations. This is important for graders that consume complete transition observations; selecting a faster path must not change their evidence contract silently. Unsupported custom BrowserGym overrides remain rejected by the existing pipeline validator rather than being guessed compatible.

Core push-based feedback and asynchronous recording remain the current implementation independently of this selection. Detailed timing is off unless `debug_timings=True` or the process exports `HARNESS_DEBUG_TIMINGS=1`.

## Python and CLI

Existing launchers can adopt automatic selection by omitting their explicit pipeline configuration:

```python
run_episode(..., observation_pipeline="auto")  # also the default
```

An explicitly supplied `ObservationPipelineConfig(...)` remains authoritative. Explicit `None` continues to mean no pipeline; the handover path still requires an appropriate pipeline. No historical experiment source, plan or saved evidence is rewritten.

To use full capture while retaining live-web handover support:

```python
run_episode(..., observation_pipeline="native")
```

The current CLI live-web handover profile enables stable-frame capture and compact tab context. Available controls:

```text
--observation-mode auto       capability-gated default
--observation-mode native     complete native capture
--screenshots                 retain automatic screenshots
--no-screenshots              disable automatic screenshots explicitly
```

Typical supported invocation uses `intent-browser run --open-internet --human-handover --headful --no-subagents` with the user's existing model, URL and goal arguments. Headless benchmark runs and ordinary open-internet mode without tab tracking retain their existing native capture behavior. The old profile factories and explicitly selected configurations remain available for comparisons.

## Evidence and limits

The preceding live test completed 20 Gemini Flash turns without harness/action errors; all 20 requests overlapped capture. Before-request feedback totaled 3.35 ms, maximum 1.10 ms. See [the live report](gemini-nonblocking-feedback-benchmark.md). The Gemini trial used its explicitly selected fixed-overview tool-schema compatibility variant; automatic runtime selection does not change or repair a provider’s tool-schema support. One clean real-web run is sufficient to adopt a reversible default for this reviewed path, not a claim that arbitrary websites cannot expose further bugs. The earlier unrelated event-pump exception remains a known unreproduced boundary; it did not recur in that test.

Offline promotion acceptance is recorded under `.local/runtime-defaults-v1/` (106 tests and 25 subtests): configuration/CLI tests, existing capture/recording/delegation regressions, and the 17-case targeted-action browser suite through automatic selection (with the explicit baseline retained as its control). HTTP model calls in that suite use MockTransport; no paid inference is used. New automatic-mode cases omit the pipeline and screenshot parameters and assert the selected trace metadata.

Future performance tuning is paused. Further adapter adoption is separate work requiring its grading/delivery checks; merely advertising a capability flag is not validation.
