# Integrated readiness and background AX: opt-in experiment

2026-09-26. **Implemented locally, not enabled in the normal BrowserGym runner,
RL rollout worker or deployed demo.** This integrates the prior prototypes on one
Playwright-owning thread. No inference, paid calls, shared website changes or
generated-world source edits.

Code: `experiments/observation_pipeline/{pipeline.py,revision.js,check.py,performance.py}`.
Frozen successful evidence: `.local/integrated-observation-v5/` (including exact
Python/JS and procedural-commerce source closure under `source/`). Earlier v1–v4
artifacts remain distinct.

## Execution order

1. Validate the supplied observation and target against the current document.
2. Arm a public readiness contract, execute the native action once, then await
   its result. Pending/failed readiness returns an explicit receipt without a
   new ready observation; it never replays the action.
3. If navigation replaced the document, discard the old readiness ticket and
   establish the destination's public readiness. A same-URL reload still gets
   a new document identity. Destination headers, not a historically visited URL,
   determine its cache eligibility.
4. Publish the shallow observation as an immutable copy. Continue full AX capture
   on the browser owner thread while the caller may begin model inference.
5. A queued search/action waits for the full tree. Before consumption, check
   document identity, epoch and public revision state; changed observations are
   rejected. Target/ancestor semantics are rechecked before a mutating action.

`IntegratedBrowser.step()` returns a future containing a readiness/action receipt
and an `Observation`. The caller waits for `observation.initial`, not `.ready`,
before starting inference. Tool requests serialize behind the pending capture.
Diagnostics are privileged test helpers, not exposed policy tools.

```python
browser = IntegratedBrowser(setup, static_origins=runtime.origins.values())
try:
    observation = browser.observe()
    initial = observation.initial.result()
    # Begin inference here. Full AX continues on its owner thread.
    found = browser.search(observation, 'Search the store', role='searchbox').result()
    transition = browser.step(observation, found['items'][0]['ref'],
                              operation='fill', text='shoe').result()
    if transition['observation'] is not None:
        initial = transition['observation'].initial.result()
finally:
    browser.close()
```

## Fast-cache qualification and limitations

The inspected generated commerce pages are server-rendered and send a no-script
CSP. This experiment permits avoiding a second full AX read **only** when:

- the host explicitly lists the origin in `static_origins`;
- the current response's effective script directives are exactly `'none'`, with
  no permissive script element/attribute override;
- the document/assets/fonts are loaded, and there are no running animations or
  detected unsupported structures;
- the cached document/revision/style/media signature still matches.

Other pages retain the strict full-AX equality check. A script-enabled application
does not become cache-safe merely by supplying one lifecycle completion signal.
Its asynchronous work can still use readiness signals; freshness remains strict.

The tracker observes DOM mutations, native control/focus/pointer/scroll events,
asset/font events, direct form-property assignments and CSSOM edits. It also
compares stylesheet contents and media-query matches: prototype setter wrapping
alone missed native `rule.style.display` writes in Chromium. Style signatures are
private runtime metadata, not repeated model input. Shadows, unreadable style
rules, frames, active media/canvas and several autonomous-rendering elements
conservatively disqualify cache reuse. This is an explicit supported-site contract,
not a universal detector for every possible browser/AX change.

There is no frozen-time guarantee after validation. A foreground reader also sees
only a snapshot; later changes can make its results stale. Known changes must not
silently reinterpret old references. Mid-capture changes discard the observation
rather than editing already-delivered messages. Explicit fresh observation is the
recovery path. No hidden retries of browser mutations.

The default destination contract establishes the presence of the document body
after DOMContentLoaded and render-frame checks. That is appropriate to the tested
server-rendered fixture; it is **not** proof that arbitrary client-side hydration
or business operations finished. Such pages need an appropriate public document
contract and lifecycle signal. Multi-frame and popup integration remains outside
this prototype; existing frame guards reject unsupported documents.

## Screenshot-only work

Screenshot requests use the visual gate from `experiments/readiness/visual.py`:
image decoding, document font loading, finite animations and sampled region layout,
with identity/signature checks across capture. Normal AX actions do not run it.

The integrated caller opts into retaining a requested screenshot even when its
readiness is unknown/pending/failed, with that status preserved. This makes canvas
and other unsupported visuals inspectable without claiming they are stable.
Screenshot capture leaves the caret unchanged: Playwright's default caret hiding
temporarily injected CSS and falsely looked like a page change to the tracker.
These are sampled region guarantees, not complete pixel invariance or task grading.

## Acceptance

**58 integrated checks pass:** 33 boundary checks, 12 actual generated-world checks,
13 dense generated-world checks. Independent cases run with at most two concurrent
browser processes, each with its own runtime/ports/state. This is concurrency
correctness coverage, not RL throughput or CPU-capacity certification.

- No full AX rereads for repeated cached searches on an eligible document.
- Value/checkbox/CSS/focus/media changes invalidate old observations, with exact
  full-AX equality after explicit recovery.
- Link/form navigation and same-URL reload; changed/missing response policy
  cannot inherit old eligibility.
- Delayed async completion, timeout with eventual completion, exactly one native
  action and no replay; unknown apps use strict validation.
- Shallow publication precedes full completion; early search queues correctly.
- On-demand ready and uncertain screenshots remain honestly labeled.
- Real generated storefront: fill search, submit search, gallery radio/CSS change,
  add to cart and open cart. One cart quantity, no order; other retailers unchanged.
- Exact foreground equality after every inspected transition. The density case
  adds 2,000 synthetic article cards to the real product page: **20,955 nodes**
  initially, **20,957 after filling**. The cards are stress instrumentation, not
  claimed native generated content.

Additional regressions retain 49 strict-AX/visual checks and 56 historical background
checks. Current artifacts identify their own source closure; old speed evidence is
not relabeled as measurements of this stronger path.

## Isolated wall times

Three repeats per mode/size, alternating mode order; intentionally sequential
for latency isolation. **500 ms simulated inference**, no actual model requests.
Both pages are generated storefronts; the larger adds 2,000 stress cards. Recording,
normal runner prompt construction and grading are outside these timings.

| AX nodes | Mode | Initial view | Full prefetch | Search + validation | Complete cycle |
| ---: | --- | ---: | ---: | ---: | ---: |
| 1,068 | Strict foreground reference | 26 ms | 45 ms | 61 ms | 642 ms |
| 1,068 | Cached, sequential inference | 26 ms | 40 ms | 8 ms | 577 ms |
| 1,068 | Cached, overlapping inference | 32 ms | 42 ms | 8 ms | 540 ms |
| 21,069 | Strict foreground reference | 57 ms | 1,943 ms | 1,974 ms | 4,475 ms |
| 21,069 | Cached, sequential inference | 55 ms | 2,003 ms | 69 ms | 2,619 ms |
| 21,069 | Cached, overlapping inference | 57 ms | 1,939 ms | 68 ms | 2,063 ms |

Strict reference includes a deliberate second full read at search. Therefore use
**cached sequential versus cached overlap** to isolate the overlap benefit; do not
attribute the entire difference versus strict mode to background execution.
On the large page 500 ms does not hide the whole extraction: queued search still
waited a median 1,437 ms. Phase medians need not sum to total medians. All 18 timed
cycles matched an independent foreground tree outside the measured interval and
left the private world state unchanged.

## Reproduction and promotion boundary

```bash
LD_LIBRARY_PATH="$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu" \
  .venv/bin/python experiments/observation_pipeline/check.py \
  --output .local/integrated-observation-NEW

LD_LIBRARY_PATH="$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu" \
  .venv/bin/python .local/integrated-observation-NEW/source/experiments/observation_pipeline/performance.py \
  --output .local/integrated-observation-NEW/performance
```

Use a fresh output directory; raw evidence is never overwritten. Before a normal
runner rollout, bridge this experimental reader to the existing BID/AX context
tools, feedback, native tool batching, recording and verifier lifecycle, preserving
their contracts. The current experiment has its own experimental references and
does **not** imply those production adapters already consume it. Keep the strict
reference available, retain source-pinned supported-site profiles, and validate
any new scripted generated-world family before permitting cheap cache reuse.

The assisted-trajectory editor remains a separate subsequent feature described in
[assisted trajectory repair](assisted-trajectory-repair.md).

## Normal runner bridge (2026-09-26)

The subsequent opt-in bridge is now documented in
[browsergym-observation-integration.md](browsergym-observation-integration.md).
It preserves native BrowserGym BIDs and existing context tools, and has its own
actual-runner acceptance under `.local/runner-pipeline-v7/`. The timings above
remain experimental-reader measurements; they are not relabeled as runner timings.
The bridge does not change deployment/defaults, and open-web use explicitly selects
native full capture without a background-performance claim.
