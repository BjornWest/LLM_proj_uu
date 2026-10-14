# Current browser runtime defaults

Version: `browser-runtime-defaults-v2` (v2 adds the generated-world branch below; the live-web branch is unchanged from v1). This selects capture behavior separately from the policy toolset (`core-tools-v12-ax-reuse`). Implemented and validated locally; this document does not certify deployed workers or unreviewed task adapters.

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

## Generated-world agent custody (v2)

Without the human-handover profile, `auto` now has a second reviewed branch for
generated worlds. It requires all of:

- An adapter that explicitly declares `supports_agent_fast_capture = True`, plus
  `supports_observation_pipeline`, `supports_dynamic_preview` and
  `supports_targeted_observations`. Declare it only when the grader does not
  consume complete transition observations (generated-world graders read chat
  answers, journals, storage state and ledgers).
- No open-internet tools, no helper runtime, incremental AX and native tools.
- A backend class that itself declares background completion and does not need
  the browser thread.

Otherwise selection stays native; `runtime_selection.reason` names the first
missing requirement (`requires_live_web_tab_tracking` when the adapter does not
declare agent fast capture). Explicit `native`, `None` and concrete
configurations are unchanged. Selected names: `agent_budgeted_targeted`, or
`agent_budgeted_full_post_action` when automatic screenshots are requested.

The selected configuration adds `agent_custody=True` and
`decision_capture='budgeted_overview'`:

- Agent-only custody (`agent_browser.py`): HumanBrowser's owner-thread
  deadlines, stable-frame projection and capture retries, every tab agent-owned,
  native active-page following. No handover/tab tools, human chat,
  `proceed_action` or full-content agreement are added; the policy tool schema is
  unchanged.
- Decision observation: one unmarked merged AX read. The context shown is the
  profile's normal token-budgeted overview (`ax_overview_tokens`), not a shallow
  preview. BIDs come from earlier DOM snapshots of the same document; first-seen
  elements in overview breadth-first order get native-compatible BIDs.
- Background capture while the request is in flight: BrowserGym marking (BID
  assignment), DOMSnapshot, unmarking, then an unmarked AX read. It becomes the
  AX index for search/read, targeted guards and fact recording. Validation after
  completion requires the same document/custody and an unchanged public revision
  or identical AX; otherwise the decision is invalidated and the model is told.
- Every index uses unmarked AX trees, so the empty structural nodes that marking
  makes visible (for example an empty paragraph or `rowgroup`) are absent.
- Readiness (`page_settle.js`): after an action, wait for no in-flight
  fetch/XHR, a 60 ms DOM quiet period and two animation frames (2 s deadline)
  instead of BrowserGym's fixed 0.5 s sleep. A timeout keeps the "effects
  uncertain; inspect before acting" feedback; nothing is replayed. BrowserGym's
  1000 ms Playwright `slow_mo` is set to 0 for these environments.
- Fact recording, when enabled with the pipeline recording package, runs one
  private probe inside the background capture's revision bracket and normalizes
  against that capture's own DOMSnapshot/AX (no attestations, `DOM.getDocument`,
  `describeNode` or second DOMSnapshot). The decision overview's fact output is
  re-bound to the validated background capture before acknowledgment.

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
