# Capture fetching: CPU profile and preload priorities

Status: measured experiments followed by local harness integration, 2026-09-27.
The conversion and serialization changes are now implemented and tested locally;
no worker/Vercel deployment or model calls. Historical experiment results below
are preserved; integrated acceptance is recorded at the end.

## What was measured

Linux headless Chromium through pinned BrowserGym 0.14.3 / Playwright 1.44.0,
local static fixtures with 1,060 and 21,010 AX nodes. Three warm samples per
configuration. Sequential runs are intentional isolation experiments for CPU
attribution, not a new suite concurrency policy. The fixture serves all requests
locally; these measurements exclude Internet loading and Windows CDP transport.
AX node counts are not token counts.

Instrumented baseline medians for the larger fixture:

| Phase | Wall seconds | Python CPU seconds |
|---|---:|---:|
| Mark/prepare | 0.103 | 0.017 |
| DOM snapshot | 0.727 | 0.552 |
| Full AX extraction | 1.688 | 1.282 |
| Entire native capture, including screenshot | 2.680 | 1.947 |
| Flatten AX | 0.035 | 0.035 |
| Save observation | 0.819 | 0.819 |

Whole-capture renderer CPU was 0.58 seconds and Playwright's Node driver CPU
0.25 seconds. CPU counters are process CPU, not percentages of the whole PC;
children can run concurrently. Nested phases must not be added to their parent.
Instrumentation itself adds overhead. A separate cProfile sample is excluded
from wall-time comparisons. Small-fixture capture was 0.240 seconds and recording
0.055 seconds with the same instrumentation.

The main local bottleneck is Python processing of the returned payload. cProfile
identifies recursive Playwright `from_maybe_impl` copying, connection-side
`_replace_guids_with_channels`, and trace JSON encoding. This is not evidence
that every real website is Python-bound: frame preparation, ongoing navigation,
layout, Windows transport and server loading can dominate other pages.

## Isolated candidates

These were exercised only inside standalone processes under `.local/`; no
installed package or harness source was patched.

| Comparison, large fixture | Baseline median | Candidate median |
|---|---:|---:|
| Entire capture, normal vs one CDP conversion pass bypassed | 2.519 s | 1.931 s |
| Recording same observation, streaming vs bulk JSON encoding | 0.816 s | 0.335 s |
| Raw DOM + AX fetch, sequential vs concurrent requests | 1.306 s | 1.059 s |

The last row is a different, narrower measurement with the conversion bypass
already active; its gain must not be added to the other rows as if measured in
one combined pipeline. Concurrent RPCs retain Python conversion work and are
not an atomic snapshot of a changing page.

The conversion candidate uses private, version-pinned Playwright implementation
calls for four plain-JSON CDP methods only. It avoids generic impl-to-public-API
conversion, not the underlying connection conversion. This is a promising
compatibility adapter experiment, not yet a supported production transport.
An independent repeated comparison measured 2.626 -> 2.126 seconds.

Recording encodes JSON in one operation before writing it through gzip, retaining
compression settings, screenshot encoding and schema. Decompressed JSON bytes
and PNG bytes matched in all tested pairs. The second series measured
0.832 -> 0.335 seconds. Bulk encoding uses extra transient memory; moving it to a
worker also requires immutable ownership and bounded queues. Serialization timing
is CPU-dominated here, so a Python thread alone does not remove GIL contention.

Capture comparisons preserved content, actionable BrowserGym IDs, DOM properties,
relationships and pixels. Large repeated captures sometimes regenerate negative
`InlineTextBox` AX IDs. A separate audit normalizes only those transient IDs and
all their relationships, plus elapsed time; all other recorded fields must match.
All three audited pairs pass, as do three exact same-payload comparisons through
the public conversion function. Dynamic pages, navigation races, iframes and
Windows CDP still require acceptance before runtime promotion.

## Parallelism and loading order

Extra Python threads will not make the recursive CPU work scale across cores.
Independent episodes in separate processes can use more cores. For one episode,
remove duplicate conversion first, then overlap independent browser requests with
bounded concurrency. Avoid replicating a large payload across processes merely
to copy it again. A more direct CDP transport might avoid another conversion but
requires its own transport/session/security compatibility work.

Suggested dependency-driven preload order:

1. Produce a small page orientation: document identity, landmarks, navigation,
   focused controls, visible form controls with labels, and current alerts. Bound
   both depth and breadth. Do not rank using privileged goals or verifier state.
2. While the model generates, prioritize the complete **AX search index** and the
   useful regions around the preview's controls. Global search must either wait
   for complete coverage or explicitly report partial coverage, never silently
   claim a missing match. The earlier Gemini first call was AX search, so loading
   only the visible region would not have satisfied it.
3. Fetch DOM layout/geometry and other expensive derived data when their tools
   need them, with lower-priority prefetch where useful. AX search should not wait
   for unrelated DOM snapshot serialization or screenshot writing.
4. If a request arrives, prioritize its dependencies: an existing target and fresh
   validation for a click; a subtree for local traversal; complete coverage for
   global search; current layout/pixels for a screenshot. Stop sharing one full-
   capture barrier across all tools.

Raw warm CDP `getFullAXTree(depth=2)` took 0.100 seconds but still returned 3,008
nodes on this 21,010-node fixture. Shallow is not necessarily small. That number
excludes BID setup, policy assembly and cold navigation and is not a promised
first-observation latency. The current displayed-node cap does not itself bound
what Chromium returns.

Keep document/version association and action-target freshness checks. Async
requests need navigation invalidation and cannot run mutations halfway through a
capture without an explicit policy. An owner-loop scheduler is needed: the current
synchronous `fill()` still blocks returning a completed model response until the
whole background job ends.

Acceptance for the next implementation should measure first-tool dependency hit
rate and residual wait, foreground/background CPU, complete-vs-partial search
semantics, stale target rejection, and exact delivered observations. A faster
microbenchmark alone does not establish correctness on retail pages.

## Reproduction and evidence

- `.local/capture-fetch-profile-v2/measure_capture.py`, `report.json`, `cprofile.txt`:
  process/phase measurements. Version 1 is retained as a failed experiment: naming
  the driver `profile.py` shadowed Python's module and broke cProfile startup.
- `.local/capture-fetch-candidates-v1/measure_candidates.py`, `report.json`:
  paired capture/recording tests, alternated capture order.
- `.local/capture-fetch-candidates-v1/measure_parallel.py`, `parallel-report.json`:
  raw serial/concurrent RPC and shallow-query samples.
- `.local/capture-fetch-equivalence-v1/measure_equivalence.py`, `audit.py`,
  `report.json`, `audit.json`: retained full observations, exact data audit and
  independent repeated timing series.

Run each measurement process in isolation with:

```sh
LD_LIBRARY_PATH="$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu" \
  .venv/bin/python PATH_TO_DRIVER
```

Choose a fresh output directory before rerunning; historical timing evidence is
not a mutable baseline. All candidate work remains local, with zero paid calls.

## Integrated implementation and acceptance

`intent_browser/cdp_json.py` now scopes the conversion optimization to native
DOM/AX extraction and shallow/static AX queries. Only two heavy plain-JSON CDP
methods bypass the public impl-to-API converter. The installed Playwright version
must be 1.44.0 and the public send method must be unmodified; other versions,
methods, test doubles and instrumentation use public send. Connection dispatch,
owner-thread execution, cancellation and exceptions are unchanged. A failed
command never falls back to sending a second command.

Native BrowserGym extractors operate through a per-call page/context/session
adapter, with no process-global monkeypatch or installed-package edits. A cloned
native `_get_obs` supplies the same adapter on ordinary pipeline fallback; custom
lifecycle callbacks are delegated unchanged. This distinction matters for the
human-handover capture callback, whose own capture already applies the adapter.

`Trace.observation` uses bulk `json.dumps` followed by one text write to the same
gzip writer. It retains schema, JSON defaults, compressed-file names, PNG behavior,
and completion-before-return. Compression bytes can differ due to timestamps and
chunking; **decompressed JSON bytes** are the equality contract. Encoding retains
an extra transient string rather than millions of iterator/write operations.

Actual integrated implementation, three alternated pairs per fixture:

| 21,010-node fixture | Public/old path | Integrated path |
|---|---:|---:|
| Complete capture | 2.702 s | 1.998 s |
| Recording identical observation | 0.839 s | 0.334 s |
| Paired capture + recording total | 3.541 s | 2.329 s |

The total is the median of paired totals, not the sum of phase medians. About
34% lower wall time on this local static fixture. Small-fixture capture is noisy
and does not show a consistent useful gain; do not promise uniform acceleration.
Capture and recording preserve complete observations (except elapsed time and
transient layout IDs), exact pixels, raw JSON bytes and AX text as appropriate.

Evidence:

- `scripts/verify_capture_json.py --output NEW_DIRECTORY`: production-code paired
  parity/performance, exclusive output directory and frozen source map.
- `.local/capture-json-integrated-profile-v1/report.json`: six passing pairs and
  source hashes; `optimized-profile.txt` / `optimized.prof`: separate CPU profile.
- `.local/capture-json-final-unit-tests.log`: 87 tests and 65 subtests, including
  native tools/retry/input-budget regressions, conversion fallback/error handling
  and every observation phase with/without screenshots.
- `.local/capture-json-overlap-acceptance-v2/report.json`: 15 current-source browser
  cases, including fast responses, navigation, custody, stale previews, callback
  failures and HTTP errors. Mock HTTP only, no model calls.
- `.local/capture-json-pipeline-{static,fallback,dense}-v1/report.json`: three
  current-source scripted seven-decision browser cases.
- `.local/capture-json-native-acceptance-v1/report.json`: earlier eight native
  cases (plain, frames, shadow DOM, stalled frames, deadline/cleanup failures),
  pinned to their own source snapshot before the subsequent callback fix.

The first overlap integration suite is retained as a failed development attempt:
`capture_json` incorrectly assumed a saved callback was native `_get_obs` and
raised `KeyError` for the human-capture callback. The helper now only clones the
exact native method and delegates other callbacks; the current v2 suite and a
specific lifecycle-wrapper unit test cover this boundary. No browser action or
paid episode was replayed to conceal that failure.

## What Python still does, and next targets

The new CPU profile still identifies connection-level
`_replace_guids_with_channels` as the largest Python traversal: approximately
1.1 million recursive invocations in one large capture. This is separate from the
removed public API pass. Raw JSON decoding and bulk encoding now mostly run in
CPython's C implementation; gzip compression also runs in native code. Calling
these functions from Python does not imply their heavy loops execute as Python
bytecode. Profile timings are instrumented and should not replace the wall-time
comparison above.

| Responsibility | Needed where? | Direction |
|---|---|---|
| Accessibility semantics, layout, DOM state | Chromium already computes these | Keep authoritative extraction in Chromium |
| CDP object-reference conversion | Playwright's general protocol, not intrinsic to AX JSON | Investigate a narrowly scoped raw-JSON reply path; do not disable conversion globally |
| BrowserGym BID/frame association | Harness must retain it | Keep one indexing pass and immutable per-document state; avoid repeated copying |
| AX search/traversal, changes and delivered context | Harness tool semantics | Reuse the retained index; fetch only required branches where coverage semantics permit |
| Document/custody/target freshness | Harness correctness | Retain these guards; optimization must not substitute stale targets |
| Model request, tool dispatch, grading | Python orchestration is appropriate | Usually small relative to bulk capture; no rewrite justified by this measurement |
| Trace storage | Harness, independent of browser control | Bulk encode now; eventual bounded asynchronous persistence needs explicit ownership/backpressure |

A direct JSON CDP channel could avoid the remaining generic reference conversion
without introducing another language, but it is not implemented here. It would
need the same target/session, navigation, cancellation and Windows-CDP coverage
as the existing path. Do not replace accessibility extraction with DOM text or
page-JavaScript approximations merely to reduce cost.

The next loading change should expose independently ready AX/search/geometry
components and prioritize AX ahead of unrelated DOM/recording work. Keep the
preload/coverage acceptance criteria above; this increment only removes redundant
work and does not claim the universal full-capture barrier is gone.

## Connection-level traversal removal (second increment)

The remaining GUID-to-channel traversal is now bypassed for the same two CDP
methods, scoped to their actual request IDs and callback identities. The adapter
installs temporary hooks on that connection instance, not on the Playwright class.
A context-local tag identifies the intended CDP sender/method. Native sending
still allocates IDs and handles tracing; callback identity is checked after the
synchronous send, including the case where nested trace messages allocated other
IDs. Normal-success replies retain the original JSON object and complete the
original future. Every other message goes to the original dispatcher.

In particular, browser object creation/events, non-capture replies, protocol
errors, cancelled futures, closed connections and unexpected reply shapes retain
native dispatch. Overlapping requests reference-count the scoped hooks, and the
last completion/error/cancellation restores the original instance attributes.
Late replies after that point use ordinary dispatch. Nothing retries a command.
Unreviewed versions and pre-instrumented connections keep the previous path.

A real-browser activation test is important here: the first implementation assumed
an outer `value` field, whereas the pinned Node CDPSession dispatcher uses `result`.
Its conservative guard fell back to native conversion, so functional checks passed
without removing the cost. The corrected v2 acceptance explicitly counts large
reply traversals: public=2, previous conversion-only=2, new=0. Ordinary handles,
fill actions and a subsequent valid capture after a real CDP error still work.
Historical direct-v1 artifacts are retained as this inactive-fast-path experiment;
they do not demonstrate the traversal removal.

Reproduce activation with `scripts/verify_cdp_json_dispatch.py --output NEW_DIR`.
The three-way performance driver now compares public, previous conversion-only,
and current transport in rotating order. Its separate CPU profile also asserts
that large-payload recursion has not silently returned. No new model calls or
worker/Vercel publication is part of this increment.

Second-increment results (current-source v2, three rotations on 21,010 AX nodes):

| Measurement | Previous conversion-only | Both traversals bypassed |
|---|---:|---:|
| Complete capture median | 1.953 s | 1.350 s |
| Python CPU during capture median | 1.233 s | 0.569 s |
| Capture + bulk recording, median of paired totals | 2.304 s | 1.701 s |

Capture is about 31% faster than the prior implementation, with about 54% less
Python CPU during capture. Compared with public conversion plus the old streaming
recorder measured in this same experiment, total time is 3.353 -> 1.701 seconds.
This remains a warm local fixture measurement, not a real-web guarantee. No AX,
DOM, geometry, screenshot or recording content was omitted. The small fixture is
still dominated by other costs.

The optimized CPU profile records 60 reference-conversion calls for ordinary small
protocol messages, versus approximately 1.1 million previously. Large AX/DOM
reply traversal is absent, independently checked by the activation driver.
Remaining costs include Chromium/transport waiting, JSON decoding, DOM-property
processing and compression. Some execute in native code despite their Python API;
profile timing is instrumented, not an additive wall-time estimate.

Current acceptance: 97 unit tests plus 65 subtests; eight native browser cases;
15 dynamic-overlap browser cases; real-browser activation/error/ordinary-handle
checks; six three-way capture/recording comparisons. All current v2 browser and
performance reports match the same complete Python source map. No paid calls.

Exact evidence:

- `.local/capture-json-direct-final-unit-v3.log`
- `.local/capture-json-direct-native-v2/report.json`
- `.local/capture-json-direct-overlap-v2/report.json`
- `.local/capture-json-dispatch-proof-v2/report.json`
- `.local/capture-json-direct-profile-v2/{report,acceptance,reference-scan-count}.json`
- `.local/capture-json-direct-profile-v2/optimized-profile.txt`
