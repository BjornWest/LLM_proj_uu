# Open-web capture count and inference overlap

2026-09-27, `OPEN-WEB-CAPTURE-EFFICIENCY-20260927`. Saved-run investigation plus a
bounded immutable-calculation guard fix. No new model episode or public-site call.

## Observed run

Frozen Windows v3 episode:
`.local/real-web-prisjakt-windows-v3/runs/20260927T154328Z-4f1b1ea9`.
35 decisions, each proposing one tool; all report `overlapped: false`.
Original outcome remains interrupted/unknown, not a success/failure reinterpretation.

| Native capture association | Count | Successful capture time summed |
| --- | ---: | ---: |
| Before model request | 35 | 121.405 s |
| Post-response, before tool dispatch | 15 | 52.286 s |
| During tool execution / resulting observation | 8 (one error) | 17.564 s |
| No associated step phase | 2 | 3.490 s |

59 successful captures: median 3.455 s; max 5.685 s. The 35 row-level
`observation_capture_seconds` values total 173.997 s and include batch guard
capture fields. These measurements are nested: **do not add row totals to native
phase totals**. They also do not quantify CPU time or expected end-to-end savings.

Of the 15 dispatch captures: six run_python, four click, two goto, one fill, one
press, one extract_page. The six run_python captures total **22.920 s**. They read
immutable saved dataset `data1`; recapturing the website cannot improve those
inputs. This is avoidable work, not evidence of slow Python or decoding.

Exact saved-file hashes, per-tool aggregation and reproducible audit script:
`.local/open-web-capture-efficiency-v1/{saved-audit.json,audit.py}`. All seven
artifact hashes in Curation's saved review were independently checked. The skill's
old `data.curation.trace_triage` package is absent from the current checkout;
this audit directly reads retained JSONL rather than creating a new triage export.

## Why overlap was inactive

This is an explicit profile boundary, not failed background execution:

1. Open-internet and human-handover paths require `full_capture_only=True`.
2. `ObservationPipeline.stamp()` returns None in that mode.
3. Native capture clears `pending`; there is no shallow preview awaiting completion.
4. `complete()` overlaps only if a backend opts into background completion AND
   `pending` exists. Hence this run cannot overlap, regardless of decoding time.

The earlier progressive implementation is qualified only for explicitly declared,
script-disabled, single-document pages with stable revisions. It does not establish
shallow/full parity on dynamic retail sites with live subframes. The native path
still performs marking, DOM, AX, metadata/pixels and cleanup before dispatch.

## Implemented first correction

The batch runner now avoids a new browser extraction for `run_python` when a
DataSession exists. It records `immutable_data_query` and explicitly labels reuse
of the existing observation. Dataset byte hashes and sandbox restrictions remain
in DataSession. Model input, tool schemas and inference routing are unchanged.

All current document, target-tab, human custody and pending-human-message checks
remain. A navigation or handover during inference still rejects the proposal.
A subsequent click in the SAME batch still refreshes and checks its target.
`extract_page`, screenshot, browser actions and next-decision refreshes are not
changed. No automatic action replay or mutation retry was introduced.

Acceptance: `.local/open-web-capture-efficiency-v1/browser-final/report.json`:
six independent, local real-browser cases, bounded concurrency three. Literal
Python, extract-then-Python and Python-then-click prove capture counts/order;
standalone extraction still captures; replaced document and human ownership both
reject before execution. HTTP responses and Python sandbox output are **scripted**;
this tests runner control flow, not model ability or Python performance.
20 batch/data/native-tool unit tests pass, including immutable artifact rejection.
The first fixture launch lacked a multimodal capability declaration and failed
before browser creation; retained under `browser/`. The corrected fixture declares
it explicitly, matching the production profile's image capability requirement.

This establishes removal of six avoidable extraction *sites* from a comparable
trajectory. It does not claim a measured 22.920 s speedup of the historical run;
that run was not replayed.

## Remaining work / proposed boundary

- There is still a full capture before each decision, including after calculation.
  Stopping automatic page updates across calculation turns needs an explicit
  deferred-refresh contract; don't silently label old state current.
- Post-action observation followed by next-decision observation can repeat work.
  Reuse needs a reliable freshness check covering semantic/value/visibility changes,
  not just unchanged URL or document identity. Pacing and human input can make the
  second observation necessary. Existing transition/verifier evidence must survive.
- General open-web overlap needs its own opt-in path and qualification: bounded
  initial preview, owner-thread background full capture while inference runs on a
  backend-capable thread, retained response on capture failure, and dispatch barrier.
  Check main document, captured target's frame, custody, and preview/full evidence
  before actions. Track changed/excluded frames honestly; don't claim foreground
  equivalence from main-document identity alone.
- An overlapped snapshot can itself become stale during decoding. Keeping the
  existing post-inference full guard would preserve safety but cap the latency
  benefit. Replacing it requires separately validated change detection (including
  form values, focus/visibility and subframes), with native fallback when uncertain.

Recommended next offline experiment: dynamic main document plus same-/cross-origin
frames, delayed mock completion, and changes before/during/after background capture.
Measure capture counts and dispatch critical-path time separately. Include fast
model completion, target-frame replacement, human custody change and capture error.
Do not switch existing real-web profiles or claim decoding overlap based on the
static/generated-site experiment alone.
