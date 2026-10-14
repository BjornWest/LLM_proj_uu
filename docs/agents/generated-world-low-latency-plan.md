# Generated-world low-latency harness: implementation plan

Draft by Claude Code, 2026-10-14, for review with Bjorn before implementation.
Goal brief: [generated-world-low-latency-goal.md](generated-world-low-latency-goal.md).
Work happens on branch `claude/generated-world-low-latency-20261014` (from `main`
`cd96b17`). No model or cloud runs are part of this plan; all timings come from
scripted episodes tagged `scripted`.

## 1. Where the time goes today

The slow Vast.ai run on 2026-10-14 (case B14, Qwen3.8-27B-FP8 on vLLM, RTX PRO
6000, generated-world `qwen-*` suite) recorded `runtime_selection.selected=native`
(`reason=caller_configuration`), fact recording on, shared Chromium on, screenshots
on and synchronous recording. Over 114 turns, harness time from model response to
next request (median **6.94 s**) exceeded model request time (median 4.18 s):

| Segment per turn | Median | Mean |
|---|---:|---:|
| Response to first tool (a full "batch guard" capture before every tool) | 2.10 s | 2.75 s |
| Decision observation (a synchronous full capture, no overlap) | 2.09 s | 2.74 s |
| Tool execution (click mean 4.57 s, goto 3.96 s; AX tools 0.02 s) | 0.04 s | 1.15 s |
| Gaps between batched tools | 0 | 0.55 s |

Roughly 2.4 full captures per turn, each carrying the fact provider's extra browser
work. Each click paid the BrowserGym task's 1000 ms Playwright `slow_mo`, a fixed
0.5 s `pre_observation_delay` and another full `_get_obs` (2.0–2.65 s, with two
`DOMSnapshot.captureSnapshot` calls, the full AX tree and a screenshot). The remote
host was about 1.6–2× slower than local for the same scripted actions (not a
controlled comparison). Evidence:
`.local/human-reports/qwen-vast-private4-live-20261013-v1/` and the B14 trace under
`.local/coordination/openrouter-qwen-suite-20261013-v1/.../florida-live-v1/`.

The older reference points are much lower. The 21k-node targeted-capture fixture
measured guard plus post-action observation at 0.051 s versus 4.0 s for full checks.
The Gemini real-web trial had a median post-response wait of 0.154 s with background
capture overlapping all 20 requests. The September generated-storefront profile
measured a 0.63 s model-free cycle once the fixed wait was removed.

## 2. Why the newer harness does not use the low-latency path

| Blocker | Location |
|---|---|
| Every generated-world case function passes `observation_pipeline='native'` and refuses overrides | `environments/website_world/*_execution.py` (13 modules), e.g. `catalog_compare_review_execution.py:443,626` |
| The recording wrapper forces `observation_pipeline=None`; the runner rejects a fact capture observer with any pipeline | `training/browser_training/native_suite_recording.py:80,192`; `intent_browser/runner.py:211` |
| `auto` selection requires the human-handover live-web profile; dynamic preview requires handover plus stable frames | `intent_browser/runtime_defaults.py:24-27`; `runner.py:107-116,140` |
| The preview, targeted guard and deferred capture are implemented on `HumanBrowser` (tab custody) | `dynamic_preview.py`, `targeted_guard.py`, `human_browser.py` |
| No generated-world adapter declares dynamic preview or targeted observations | `website_world/generation.py:528` declares only `native_full_only` |
| Qwen backends declare no background completion and require the browser thread (SIGALRM watchdog; page snapshot around the capacity wait) | `scripts/qwen_suite_runtime.py:400`, `scripts/openrouter_qwen_runtime.py:131,179`, `scripts/comparison_suite.py:908-923` |
| BrowserGym's task default `slow_mo=1000` and `pre_observation_delay=0.5` are never overridden for generated worlds (shared Chromium forwards `slow_mo` to the pool server) | `connected_world_task.py:111`; `browsergym/core/task.py:25`, `env.py:80` |
| Suite runner options force `trace_screenshots=True`, `async_recording=False` | `scripts/comparison_suite.py:940` |

The generated-world graders grade from chat answers, world-side journals, storage
state and order ledgers; none consumes complete transition observations (checked in
`automatic_grading.py`, `connected_world_task.py`, `graded_world_task.py` and the
`*_grading.py` modules). Deferred post-action observations do not remove grading evidence.

## 3. Target decision cycle

After the final action of a batch returns:

1. **Readiness**: wait for actual application readiness, not a fixed sleep (§4 P1).
2. **Decision observation**: a cheap shallow preview (or the reused full capture,
   see open question Q1), then dispatch inference.
3. **Background full capture**: one full native capture on the browser-owner thread
   while the request is in flight. It feeds AX search/read/changes, target guards and
   fact recording. The only post-inference wait is for this capture if it has not
   finished.
4. **Per action**: a targeted main-document check (custody, document, target DOM
   identity, AX semantics, ancestry); no full pre-action capture. AX query tools use
   the captured snapshot. Intermediate batch actions keep a full post-action capture
   (recorded as an exception). The final action's post-capture is deferred into the
   next cycle.
5. **Recording**: fact joins and trace serialization run behind a bounded queue.
   Gaps are recorded; they never block actions.

Expected normal cycle: one preview plus one full capture, zero full captures for
`ax_search`/`ax_read`, and no 1 s slow-motion or 0.5 s sleep. Exceptions (startup,
intermediate batch actions, invalidations, frame targets, explicit visual/data
tools) are recorded per event.

## 4. Phases

Each phase ends with focused tests and a scripted timing run against the P0
baseline. Commits stay on the side branch; one Codex (Astra) review covers the
batch before handoff.

### P0 — Scripted timing harness and baseline

- Add a scripted latency driver that runs real generated-world cases through the
  same case callables and `run_episode` as `scripts/comparison_suite.py`, with the
  shared Chromium pool, the fact recording package, attached automatic grading and
  trace-viewer projection. The backend is a background-capable `MockTransport`
  completion backend with a configurable simulated inference delay (0, 2 and 5 s)
  replaying a fixed journey: `ax_search`, `ax_read`, click, goto, `select_option`,
  fill, a fill+press batch, back, and the final answer. Episodes are tagged `scripted`.
  I will first check whether `comparison_suite.py`'s scripted mode (`scripted_journey`)
  can carry multi-turn tool journeys; if it can, use it directly.
- Per cycle it reports: response to first tool, per-tool targeted/full guard time,
  action execution, readiness, preview, full capture, residual post-inference wait,
  fact recording cost (browser-side and join/write), trace write time, and the
  count of full captures by reason. It reuses `debug_timings` and
  `env-step-telemetry`; no extra browser probes.
- Baseline A reproduces the Florida configuration locally: native capture, fact
  recording, screenshots on, synchronous recording, `slow_mo=1000`, 0.5 s delay.
  Run once in isolation (sequential, to separate component timings from contention;
  this is the CLAUDE.md isolation exception) and once at 4 concurrent episodes,
  matching the live suite.

### P1 — Pacing and readiness

- Set `slow_mo=0` for generated-world environment construction
  (`ConnectedWorldTask.make_env` and the website_world task env), recorded in metadata.
- Replace the fixed 0.5 s with a harness-owned readiness check for generated worlds:
  no in-flight same-origin fetch/XHR started by the page, a short DOM mutation quiet
  period (about 50 ms) and two animation frames, with a 2 s deadline. A timeout keeps
  the existing "effects uncertain; inspect before acting" feedback and never replays
  the action. Readiness time and outcome are recorded per action.
  `intent_browser/readiness.py` already has the mutation and animation-frame parts.
- Optional follow-up for the Website owner: an explicit application signal around
  `ensureQuote`/`ensureProduct`/render (`__intentReadinessV1.app.begin/end`). This is
  not required for P1.

### P2 — Fast capture without human handover

- Add an agent-only custody browser: the stable-frame capture, document identity,
  guard deadlines and capture retry logic of `HumanBrowser`, with all tabs
  agent-controlled. It follows BrowserGym's active page the way native mode does and
  has no handover/tab tools, human chat or `proceed_action`. The policy tool schema
  is unchanged.
- In `runner.py`, separate the capture/guard provider (`custody`) from the
  policy-visible handover features, which stay keyed on `human_browser`. Without
  handover, content agreement stays as native today (document plus target
  signature), not full AX digest equality.
- `runtime_defaults` v2 (`browser-runtime-defaults-v2`): a second eligibility branch
  for generated worlds, gated on an explicit adapter declaration, a certified
  background backend, no helpers and incremental AX. Selection and every fallback
  reason go into `runtime_selection`. `native` and explicit configurations keep their
  current meaning.
- Generated-world adapters (`NativeWorldTask`, `ComparisonSkuTask`) declare the
  capabilities. Case functions and `comparison_suite.py` take the observation mode
  from the caller spec instead of hard-coding `native`. New suites default to
  `auto`; existing frozen specs and pinned releases stay as they are.
- `watch_browser_steps`' instance `env.step` override must move to a supported hook,
  because the pipeline rejects instance overrides.

### P3 — Background-capable suite backends

- Qwen private/hosted backends: replace the SIGALRM watchdog with a thread-safe
  deadline (client timeout plus owner-side cancellation that closes the request).
- The capacity-wait freshness check currently evaluates the page from inside the
  backend. Replace it with an owner-thread mailbox: while `pipeline.complete` waits
  for the model future, the browser thread services small queued browser calls. The
  "do not dispatch a stale request" guarantee is kept without Playwright leaving
  its thread. Then declare `supports_background_completion=True` with tests.
- MiMo's `ChatCompletionsBackend` is already background-capable. Its request hooks
  (`source_guard`, `admission.before_dispatch`) get a thread-safety check.

### P4 — Fact recording on the shared full capture

- Replace the per-capture provider bracket (5–6 `page.evaluate` calls, plus
  `DOM.getDocument`, `DOM.describeNode`, `Page.getFrameTree` and a second
  `DOMSnapshot`) with one probe evaluation inside the native capture's marked
  window. It returns the renderer registrations keyed by BrowserGym `bid` with
  text-run offsets, plus a document mutation revision. A cheap revision read after
  extraction attests that nothing changed.
- Normalize against that capture's own DOMSnapshot (`dom_object`: backend node IDs,
  text nodes, input values) and AX tree. There is no extra AX, DOM or snapshot request.
- Run the join, serialization and artifact writes in a bounded background worker.
  Records carry the capture serial and snapshot ID, so delayed processing cannot
  attribute newer page state to an older observation. When the worker falls behind,
  it records a gap or unknown mapping instead of blocking.
- Preview spans join to the validated full capture: preview nodes are proven equal by
  backend node ID and semantics before actions run. Otherwise they are recorded as
  unknown. A deferred post-action capture records "deferred; covered by next decision
  capture". Delivery acknowledgement stays exact and separate from captured content.
- This is a new versioned recording package with its own pins. The old package stays
  available for pinned suites. Enabled/actual state, pins and failures are recorded,
  as `CLAUDE.md` requires.

### P5 — Trace persistence and screenshots

- Automatic screenshots default off on the generated fast path, behind a spec switch.
  The explicit screenshot tool is unchanged.
- Suites use `async_recording=True`. Move the foreground `json.dumps` of full
  observations (multi-MB with DOM snapshots) and the per-event flushes behind the
  recorder thread, with bounded backpressure and flush barriers before grading and
  at finish. Policy-delivery `.txt` artifacts stay synchronous; exposure graders
  read them immediately.

### P6 — Acceptance and timing report

- Timing matrix: baseline A, after P1, after P2+P3, and final with fact recording
  on and off. Simulated inference of 0, 2 and 5 s; isolated and 4-concurrent runs.
  All scripted. Results are wall-clock seconds with per-component medians, plus
  capture counts by reason and fallback reasons.
- Functional regressions: the targeted-action browser suite (17 cases), the
  dynamic-overlap suite, fact provenance and capture-boundary tests, and
  generated-world scripted positive/negative controls through the suite's
  automatic grading and viewer projection.
- Write-up in `docs/agents/`, then a Codex (Astra) review of the commit batch, then
  a handoff to Harness for dev integration. Evaluation decides prod promotion.

Indicative targets (not an SLA; the brief states none):
- Response-to-next-request harness time per click cycle drops from the B14 median of
  6.94 s to under 1 s locally with simulated inference of 2 s or more.
- One full capture per normal cycle.
- Median residual post-inference wait under 0.2 s when inference outlasts the full
  capture.

## 5. Decisions (Bjorn, 2026-10-14)

1. **Decision observation:** what the model sees is a separate setting, not part of
   this optimization. Keep the token-budget overview (`ax_overview_tokens`, currently
   1,000) as the context policy; drop the depth-2/64-node preview as the default.
   The capture should extract and process only what is needed to fill the budget,
   as early as possible, and do everything else (DOM snapshot, full index, facts,
   screenshots) in the background. P0 benchmarks extraction/processing strategies
   for x tokens on real generated pages. Later turns' change reports still need the
   state of previously shown (possibly deep) nodes.
2. **Ownership:** work on the side branch; Bjorn contacts the owning agents when it
   is ready.
3. **Readiness:** harness-side. Note: the online tests do not have this either; they
   inherit `slow_mo=1000` and the fixed 0.5 s (no `observation_readiness` events in
   the Gemini trace). Build it generically, enable for generated worlds first.
4. **Stale pages during inference:** never interrupt or withhold a request. Remove the
   page snapshot from the Qwen backend; the pipeline validates after completion and
   tells the model. B14's capacity permits waited at most 0.6 ms over 115 requests,
   so there was no real queueing. The case is a page changing without the agent
   (e.g. a late quote render).
