# BrowserGym observation latency investigation

2026-09-21. Standalone profiling only: no inference, shared-runtime changes, installed-package edits, or modifications to historical traces.

## Finding

Page size alone does not explain the observed ten-second pause. BrowserGym 0.14.3 waits for IntersectionObserver visibility callbacks **separately in each frame**, up to approximately one second per frame. Those waits accumulate. A two-phase experimental marker starts every frame's ordinary marking first, then collects their results; it retains the timeout and warnings rather than dropping frames or cutting page content.

| Controlled capture | Original sequential waits | Concurrent waits prototype |
| --- | --- | --- |
| Main page + six visible frames | 567–619 ms | 318–337 ms |
| Main page + six hidden frames | 568–607 ms | 314–334 ms |
| Six deliberately suppressed frame callbacks | 6,493–6,547 ms | 1,292–1,323 ms |

These are two captures per variant in alternating order, from separate browser processes per fixture. They are diagnostic measurements, not a statistically established performance benchmark. In all three fixtures, the first four captures had identical extracted AX semantic fields, per-frame element IDs/visibility values, document counts, pending counts and warning counts. The stalled fixture retained all six warnings and the same unknown/default visibility values: faster extraction does **not** establish that visibility became correct.

Checker evidence: `.local/coordination/observation-latency/controlled-comparison-v1.json`. Profiler: `data/curation/observation_latency/profile.py`, SHA256 `777266365ce69f9fad6ab40f9fc762d7fe3f91f0527e855b55121ccabfb6dd6f`. Installed upstream marker SHA256 `6ecfbba89d756c37874bdf692e4bf24126459ab79f9120c1f053305b7ba2978a`.

## Original run and uncertainty

The interrupted episode `20260921T180351Z-515f0b2a` has a decision capture of 10.354 seconds, repeated `Frame marking: not all elements have been visited by the intersection_observer after 1000 ms` warnings, and six to eight DOM documents in adjacent saved observations. The warning is visibility marking, not a measurement of page rendering or AX extraction itself. Its original logs do not identify individual frames, pending elements or extraction phases, so we cannot attribute the entire pause or identify the exact callback failure after the fact.

The saved page includes consent/ad/tracking frames; their presence makes cumulative waits plausible. This is an inference, not proof that any specific tracker caused the delay. Controlled hidden, off-screen, empty and detached-element examples did not naturally reproduce the missing callbacks. The artificial stalled-callback fixture tests the wait mechanism, not PriceRunner's exact failure.

Fresh visible-browser PriceRunner search-page captures took 658–801 ms with the original sequential marker and had no warnings. They were new sessions, not the original post-consent state. A headless visit received **Åtkomst nekad**; its faster capture is not a valid performance comparison of the real results page. A 3,000-paragraph local page captured in 809–986 ms, also without warnings.

## Separate findings

- **Background-tab screenshots can stall.** Two initial background-tab diagnostics were manually interrupted while blocked in BrowserGym's CDP `Page.captureScreenshot`. A bounded repeat completed its first screenshot in 3.517 seconds, then was still in its second screenshot when the ten-second whole-process limit ended the experiment. Marking, DOM and AX phases finished promptly. Evidence: `background-bounded-v2/phases.jsonl` and sibling `.exit.txt` (124). This is separate from visibility warnings. Do not assume all capture latency is AX or silently omit screenshots.
- **Open-internet mode inherits `slow_mo=1000`, despite CLI metadata saying 250.** Its `OpenWebTask` inherits the upstream task default and `make_env` does not override it. The historical record remains unchanged. A controlled `slow_mo=1000` extraction did not reproduce the multi-second observation stall, so this is a setup/metadata issue and potential action latency, not the established cause of that stall.
- A deliberately uncommitted iframe navigation also blocked frame evaluation in a separate exploratory probe. It was interrupted; no completed comparison was produced. A Python/JS observer timeout is not a general timeout on frame execution-context acquisition or CDP transport.

## Recommended runtime increment

1. Promote a **version-pinned, opt-in two-phase marker** after checking cross-origin/nested frames, frame detach/navigation, shadow DOM, exception cleanup and shared-runner integration. Keep parent-before-child BID assignment; collect original visibility results and warnings. Preserve all page content. The current standalone prototype is not production ready and has not changed live behavior.
2. Record separate mark/frame, DOM, AX, screenshot and total timings. Include pending count and frame identity in diagnostics. This lets the next real occurrence distinguish callback delay from navigation/CDP stalls without another inference run solely for debugging.
3. Handle screenshot availability explicitly for background tabs. An automatic focus change may alter BrowserGym's active-page tracking and cannot be introduced silently. A bounded capture failure must not deliver an old screenshot as current.
4. Make the new open-internet mode's intentional action delay explicit and log the actual value. Preserve historical benchmark settings.

The prototype overlaps visibility waits; it does not solve blocked execution contexts, screenshot stalls, or guarantee a globally bounded capture time. Production acceptance and a new supervised live run remain separate from this investigation.

## Reproduce

Use a fresh output directory and an outer process deadline. This exercises controlled local content only:

```bash
timeout --kill-after=5s 45s env \
  LD_LIBRARY_PATH=.local/system-libs/usr/lib/x86_64-linux-gnu \
  .venv/bin/python data/curation/observation_latency/profile.py \
  --case stalled --output .local/observation-latency-new
```

Other cases: `visible`, `hidden`, `dense`, `offscreen`, `empty`. `--headful --background` specifically investigates background-tab behavior; `--no-screenshot` isolates text extraction. `live --url URL` is a real public-site visit and may encounter different content or bot blocking. No model is invoked. The profiler uses Playwright plus installed BrowserGym extractors, not a complete BrowserGym episode. Phase events are flushed before/after each stage so interrupted experiments retain their last stage.

The earlier `hidden-no-wait` experiment is retained in source/evidence but is **not** the recommended candidate. Earlier reports keyed visibility rows by URL and could overwrite duplicate `about:blank` entries; final v2 comparisons use a list preserving every frame. Historical reports are untouched.
