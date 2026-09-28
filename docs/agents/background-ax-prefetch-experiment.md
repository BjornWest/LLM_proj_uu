# Background AX prefetch experiment

2026-09-26. **Implemented and tested as an isolated prototype. The standard
BrowserGym runner and deployed worker are unchanged.** No paid inference, shared
website mutations, BrowserGym patches or RL runs.

Code: `experiments/lazy_observation/background.py` and `run_background.py`, reusing
`prototype.py`. Frozen successful evidence: `.local/background-ax-v2/`.

## Execution contract

One worker thread owns Playwright, the browser, page, CDP session and AX cache.
The model/inference caller owns none of those objects. The sequence is:

1. Request a new observation. Publish a copied depth-1 overview through
   `Observation.initial` as soon as it is ready; explicitly mark partial coverage.
2. On the browser owner thread, obtain the full AX tree and prepare the cache.
   The inference caller can run concurrently. No full tree is appended to the
   model context merely because it finished loading.
3. Publish a snapshot ID through `Observation.ready`. A search or native action
   submitted early queues behind extraction. Errors propagate to the tool caller;
   there is no automatic retry or action replay.
4. Searches use the captured public AX snapshot rather than extracting the entire
   tree again. Results label their snapshot coverage and freshness limitation.
   Native clicks/fills revalidate target and ancestor semantics against that
   snapshot, then use Playwright actionability checks. Known actions invalidate
   the full cache; new observations are explicit.

Example calling pattern (the actual model backend is not part of this prototype):

```python
browser = BackgroundBrowser(setup_page)
try:
    observation = browser.observe()
    shallow = observation.initial.result()
    decision = model.complete(shallow)  # Browser thread is loading full AX now.
    result = browser.search(observation, decision.query).result()
finally:
    browser.close()
```

`setup_page` runs on the owner thread. `diagnostic()` and capture hooks exist for
privileged scripted tests, **not** policy tools. Browser actions, including those
requested while inference overlaps extraction, are serialized on that same
owner. This avoids using synchronous Playwright objects from a foreign thread.

## Measured wall times

Fresh isolated generated storefront from the previous frozen seed-7 source,
with zero or 2,000 synthetic article cards. Viewport 1280×900, headless Chromium,
BrowserGym-core 0.14.3 / Playwright 1.44.0. Browser/server startup and page navigation
are outside these timings. No fixed post-action wait, DOM snapshot, screenshot or
trace recording is added to the measured path.

Median of three samples per mode/delay/page, 36 cycles total. Serial and overlap
modes do the **same** shallow/full AX work and one global search; serial waits for
full extraction before beginning the simulated response. Mode order alternates.
Latency cases deliberately run sequentially to avoid test-browser competition;
two independent correctness suites run in parallel.

| Page AX nodes | Simulated response | Initial view (overlap) | Full background extraction | Extra queue wait after response | Cycle with overlap | Serial cycle |
|---|---:|---:|---:|---:|---:|---:|
| 1,068 | 0 s | 5.6 ms | 45 ms | 45 ms | 56 ms | 67 ms |
| 1,068 | 0.5 s | 5.0 ms | 43 ms | <1 ms | 512 ms | 557 ms |
| 1,068 | 2.5 s | 5.5 ms | 57 ms | <1 ms | 2,512 ms | 2,555 ms |
| 21,069 | 0 s | 9.7 ms | 1,554 ms | 1,553 ms | 1,663 ms | 1,481 ms |
| 21,069 | 0.5 s | 9.5 ms | 1,808 ms | 1,233 ms | 1,888 ms | 2,280 ms |
| 21,069 | 2.5 s | 10.2 ms | 1,868 ms | <1 ms | 2,583 ms | 4,402 ms |

Medians of individual phases need not sum to median total. Cached search and
freshness checking still take approximately 6–7 ms on the smaller page and
67–72 ms on the larger page, beyond queue wait. Initial views fetch 7/8 AX nodes.
These are node counts, not model token counts.

There is no overlap benefit when a response is instantaneous; the 0-second large
case was actually slower in these samples, reflecting extraction variability.
With a 2.5-second response, background work finishes before dispatch and saves
about 1.82 seconds on the larger page. With a 0.5-second response only part of the
cost is hidden. This is a **simulated inference delay**, not measured Qwen decode,
network, prompt construction, streaming throughput or local GPU contention.

The page is the same frozen generated world plus the same stress-card layout as
the earlier experiment, but node counts are not byte-identical to its full
BrowserGym capture: this version omits its extra checkbox and BrowserGym marking.
Use the within-cohort serial comparison, not cross-cohort totals, for overlap claims.

## Correctness and lifecycle evidence

Two fresh browser suites each pass 28 assertions. They cover shallow delivery
while capture is held; early search and native action waiting; correct scoped
click exactly once; previously unloaded-node discovery; no mutation of delivered
initial data; snapshot reuse without another full extraction; action invalidation;
property-only input change rejection; DOM relabel rejection; navigation superseding
an in-flight old capture; rejection of old-document search; mutation during capture;
explicit recapture; propagated extraction failure without retry; same-URL reload;
close during capture; and single-thread browser ownership. Gates are test hooks,
not production sleeps. They test state at specific boundaries, not every possible
JavaScript/actionability race.

All 36 measured searches match a separate fresh full-AX search on the unchanged
page. Both generated world state snapshots remain unchanged. Source manifests,
installed library versions, per-case checks, monotonic phase events, all timing
samples and CDP method/size logs are retained. Closure verifies frozen source
hashes. An earlier 25-assertion v1 is retained; v2 adds the early native-action
ordering checks and atomic action-epoch invalidation.

## Freshness and limits

- A full snapshot is a historical observation. Document identity, URL and a
  conservative DOM/input/change/resize revision guard detect many changes, but
  **are not a complete AX-change detector**. Property-only JS changes, stylesheets,
  animations and open-shadow mutations can evade that guard. Search completeness
  is claimed only for the captured snapshot, never the current live document.
  A model requesting current data needs a new observation.
- Action guards compare target and ancestor semantics freshly, including the
  tested property-only input change. They are not atomic with Playwright's later
  click/actionability wait. No arbitrary adversarial timing guarantee is claimed.
- Observable mutation during capture discards the result and requires an explicit
  new observation; it never installs it as current or retries automatically.
  Very dynamic pages could repeatedly invalidate broad snapshots. Regional
  invalidation/fallback behavior still needs design before adoption.
- Superseding navigation/close rejects pending old results. It cannot cancel a CDP
  request already running or undo a native action already dispatched. Queued actions
  check their epoch before dispatch. The outer experiment kills its own process
  group after a 240-second deadline if a case hangs.
- The shallow view may require extra discovery tool/model turns compared with a
  full initial observation. No model test here establishes whether that tradeoff
  improves task completion or total episode time.
- This inherits the main-frame-only prototype restriction. Multi-frame routing,
  production BID compatibility, feedback adapter wiring, screenshot/extraction
  tools, verifier lifecycle and normal runner integration remain separate work.
- Full DOM snapshots are not prefetched: this experiment avoids that work and uses
  target geometry on demand. Other required computations could use the same owner
  queue, but adding them changes latency and must be measured.
- Overlap hides latency, **not CPU or memory cost**. Eager full extraction can waste
  work when the next action immediately navigates away. Many concurrent rollouts,
  local model serving and process-versus-thread ownership need a separate throughput
  comparison. This is not an RL capacity result.

## Reproduce

```bash
.venv/bin/python experiments/lazy_observation/run_background.py \
  --source .local/generated-browser-profile-v3/source \
  --output .local/background-ax-NEW

# Parallel real-browser correctness only:
.venv/bin/python experiments/lazy_observation/run_background.py \
  --output .local/background-ax-boundaries-NEW --correctness-only
```

Outputs must be new directories. The script freezes its code and relevant world
source, isolates browser sessions, sets the local Chromium library path, and
retains failed output. No model credentials or cloud services are used.
