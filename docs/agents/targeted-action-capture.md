# Targeted action checks and deferred observation

This opt-in path removes the full pre-action guard capture and full final-action post-capture from the dynamic-preview loop. It is implemented locally; no new paid episode or deployment is claimed.

## Lifecycle

1. After pacing and human-message handling, capture a fresh bounded main-document AX preview with usable viewport BIDs.
2. Start inference and collect the full native observation concurrently on the browser-owner thread. Queries still receive that full index. Preview identities must agree with it before dispatch.
3. Immediately before a supported main-document action, check browser custody, document identity, the selected element's DOM identity/BID, current AX semantics and ancestor identity/semantics. This uses a partial AX lookup, not another full DOM/AX extraction.
4. Execute once. Keep native action results, errors, browser events and task validation. For the last browser action in the batch, record execution metadata with explicit `coverage: partial` and `deferred: true`; do not claim a new full page snapshot or infer removals from omitted content.
5. The next request gets a fresh shallow preview. Full extraction again overlaps inference.

The prior fixed native settling delay is unchanged in this increment. This avoids conflating capture savings with readiness-policy changes.

## Scope and limitations

This is a target-consistency guard, not proof that the whole page is unchanged or that an action is authorized. Prices, terms and other content outside the chosen element's ancestry are not rechecked. Meaningful target labels/states and contextual ancestor labels are checked; unrelated news updates do not veto the action.

Intermediate actions in a multi-call batch retain full post-action observations so later calls can use the updated state. Child-frame targets and explicit `proceed_action` confirmations retain the existing full guard. Custody, document and target checks remain immediately before dispatch; no web automation check can make that check and a later page action atomic.

The mode requires dynamic preview, automatic screenshots disabled and an explicitly background-capable backend. Task adapters must declare support before receiving deferred observations. The open-internet adapter supports it; benchmark adapters have not been promoted. Existing defaults remain unchanged.

```python
ObservationPipelineConfig(
    (), full_capture_only=True, dynamic_preview=True,
    trace_screenshots=False, targeted_actions=True,
)
```

Use the existing human-handover/stable-frame native-tool profile and pass `trace_screenshots=False` to the runner. The configuration is recorded in trace metadata. `targeted_action_guard` events identify the live check scope; `post_action_capture_deferred` explicitly distinguishes metadata from a full observation. The retained pre-action full snapshot is historical, not relabeled as freshly captured.

## Offline acceptance

Real Chromium uses scripted HTTPX completions; there are no paid model calls. The acceptance suite covers ordinary clicks, unrelated updates, changed labels, disabled/replaced/moved elements, BID changes/duplicates, navigation and human custody races, iframe fallback, fill/press batching, fresh context after deferral/pacing, and an actual action timeout without replay. Raw requests and delivered observation provenance are retained; evaluation precedes close.

A deeper preview uncovered native input/shadow-tree ID incompatibility. Preview marking now skips closed/browser-internal shadow roots and ignored AX nodes, preserving open-shadow controls. Tests compare every assigned preview BID with the following native observation.

Structural ancestors may appear as `generic` while BrowserGym's temporary markers are present and as ignored `none` after cleanup. The targeted comparison preserves their DOM identity without treating that marker-induced representation change as a changed product or control. Named semantic ancestors remain checked.

Validation results:

- 17 targeted-action real-browser cases pass: `.local/targeted-actions-acceptance-v7/report.json`.
- 18 existing dynamic-overlap browser cases pass: `.local/dynamic-overlap-targeted-regression-v1/report.json`. These exercise the unchanged default path; the final stricter named-ancestor comparison is exercised in the targeted suite.
- 19 preview-ID lifecycle checks pass: `.local/preview-bids-shadow-acceptance-v2/report.json`.
- 54 focused Python tests and 12 subtests pass (targeted guard, dynamic preview, observation pipeline, batch guard, action-error feedback, frame capture, screenshots).
- Six isolated large-page timing runs pass with one recorded effect each, zero action errors and identical source fingerprints. No paid calls.

Earlier failed development artifacts remain intact. They distinguish the preview-ID bug, structural-marker mismatch, empty partial-tree feedback integration, and a cross-origin callback mistake in the test fixture.

## Measured latency

The fixture contains **21,022 AX nodes**, including 3,000 product articles and an iframe. Three fresh runs per mode, sequential to avoid cross-browser timing interference; automatic screenshots/video off and asynchronous recording on. Each episode makes one scripted click. Both modes retain native readiness and validation. Medians:

| Measurement | Previous full checks | Targeted/deferred |
|---|---:|---:|
| Pre-action observation/check | 1.905 s | 0.034 s |
| Post-action observation/metadata | 2.110 s | 0.016 s |
| Combined guard + post-observation, sum of medians | 4.016 s | 0.051 s |
| Entire browser step, including action and settling | 3.690 s | 1.583 s |
| Full native captures, including startup/background | 5 | 3 |
| Sum of full native capture wall time | 8.745 s | 4.689 s |
| Reset start to cleanup start | 17.142 s | 11.248 s |

The two formerly full serial checks cost about **3.97 seconds less per tested action**. Whole one-click episode wall time fell about **34%**; this includes startup, recording, context work and mock transport overhead. It is not a real-model throughput measurement or a prediction for all websites. The small sample establishes the removed work and approximate local benefit, not a performance distribution.

Background full capture still runs, and intermediate batch actions still capture fully. Event and phase durations are nested: do not add browser-step duration to its post-observation subphase. No screenshot savings are included; both modes already had screenshots disabled.

Machine evidence: `.local/targeted-actions-timing-v1/timing.json`, with per-run traces and source hashes. Reproduce with `scripts/verify_targeted_actions.py --case baseline` and `--case click`, each with `--products 3000 --workers 1 --output <new-directory>`; run three of each sequentially. Functional acceptance runs the same script without `--case`, using bounded parallelism by default.


## Subsequent live trial

The [20-turn Gemini trial](gemini-targeted-capture-benchmark.md) stopped after 16 responses with a post-click DOM-wait/event-pump exception. Target probes and removal of full pre-action captures worked, but this is not clean live acceptance. Preserve the opt-in status while investigating that boundary offline.
