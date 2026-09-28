# Gemini combined capture: longer real-web episode

One user-authorized episode completed on 2026-09-28 local time (2026-09-27 UTC). It reached the chosen 80-turn limit without a fatal capture, browser-action or cleanup error. It did **not** deliver a final answer or complete the requested three-retailer comparison. No rerun was launched.

Trace: http://localhost:8878/#41b9bff4c41f70c169e1 . Saved run: `.local/gemini-combined-real-web-v1/runs/20260927T224808Z-e0a6a159`. Frozen source, launcher, goal, plan, window layout, raw requests/responses, HAR, recording timings and independent saved-evidence summary are under `.local/gemini-combined-real-web-v1/`. `review.py` reproduces `review.json`, with original artifact hashes and raw null-preserving evaluation. No live outcome verifier exists for this task.

## Task and configuration

Same earlier research-only task: compare new black Sony WH-1000XM5 headphones at three retailers delivering to Malmö; report prices, shipping, availability and delivery estimates, preserving unknowns. No purchases, cart additions, accounts or personal information. Started on Prisjakt and visited Amazon, Elgiganten and NetOnNet. Reaching those sites does not establish the comparison was completed or every action authorized.

- `google/gemini-3.8-flash`, all **80 requests reported Google AI Studio**, no fallback, temperature 0, maximum 16,384 output tokens.
- One fresh Windows Chrome context via CDP, existing window layout, background launch; no imported personal browser state.
- Same frozen capture implementation as the successful short synthetic test: visible preview BIDs, dynamic depth-2/64-node preview, full background capture, asynchronous recording, no automatic PNGs or video. Explicit screenshot tool remains available; model did not request one. HAR retained.
- **Diagnostic tool variant:** per-action `ax_overview_tokens` disabled, normal automatic budget retained, all tool names available throughout. This is not validation of the unmodified standard tool schema on Gemini.
- 80-turn bound; 100,000 estimated-input-token guard; provider token counts reported separately below. Capture deadline is diagnostic, so overruns are measured rather than terminating the episode. Human handover-and-wait available; no human handover occurred.
- Schema correction allowed once per failure chain, never replaying an already executed browser action. Offline Windows/preview/opaque-input tests: 29 tests + 17 subtests passed before launch.

## Timing

Whole episode: **408.565 seconds (6m49s)**. All 80 requests overlapped background capture. These are wall times; model request time includes transport, prefill and generation, not decode-only TPS.

| Phase | Median | P95 | Maximum |
|---|---:|---:|---:|
| Initial shallow preview | 212 ms | — | 381 ms |
| Model HTTP request | 1.316 s | 3.466 s | 21.718 s |
| Full background prefetch | 1.761 s | 3.965 s | 4.266 s |
| Wait after response until capture barrier ends | 331 ms | 2.580 s | 3.092 s |

P95 is the sorted sample at floor(0.95 × (N−1)), with N=80. Preview and subsequent full guard are distinct; a 212-ms preview is not a full actionable-state guarantee.

125 native full captures occurred across initialization, background fetches, guards and post-action observations. Native capture median **1.725 s**, maximum **5.496 s**; the long capture was allowed to finish in diagnostic deadline mode. Full background AX snapshots ranged **541–8,693 nodes**, median **2,550**, so this was not the earlier 21,000-node synthetic page. Captured frame coverage remains explicitly scoped; unstable/omitted frames are unknown, not empty.

Total request/prefetch barrier time was 201.413 s, including 61.229 s of waiting after responses. The remaining ~207 s includes setup, preview/prompt work, guards, browser actions, post-action captures, recording work and cleanup; it is not all network or page loading. Summed HTTP-request time was 140.168 s (~34% of whole wall time), so the browser harness still leaves substantial time with no model request in flight. This is a request-occupancy proxy, not a measured GPU decoding utilization figure.

Asynchronous recorder: peak one job, 9.19 MB accounted pending payload, ~0.00012 s aggregate queue backpressure. No automatic PNG files. Foreground serialization and context construction still exist; a nonblocking disk queue does not remove them.

## Actions and recovery

82 proposed tool calls across 80 model requests: 44 AX searches, 18 AX reads, 8 clicks, 4 fills, 1 press, 8 URL navigations, 1 proceed-action confirmation. Exactly 21 browser actions executed, with zero native action errors. The proposed-click count includes a change-guard rejection, not an extra committed action.

Four retained recovery events (turn numbers are one-based):

1. Turn 5: `ax_search` supplied `role="searchbox"` but omitted required `query`. Exact schema feedback delivered; corrected search followed on turn 6. No browser action executed for the malformed request.
2. Turn 30: page content changed after the decision; click rejected before dispatch. Turn 31 explicitly used `proceed_action` with the current confirmation token. This was model-selected recovery, not automatic replay.
3. Turn 41: a search hit exceeded its result token budget. Feedback identified the blocked reference and suggested a node read; the next call read that node.
4. Turn 60: an AX read used a stale/unknown reference. The next call searched current state again.

No fatal capture errors, no background invalidations ending the episode, no action retries hidden from the trace. Final calls were still inspecting NetOnNet delivery details. There was **no `send_msg_to_user` final answer**, and no completed-task claim should be inferred from technical stability.

## Tokens, cache and billing

Google/OpenRouter-reported final request input: **92,521 tokens**. Total generated output across all requests: **6,856 tokens**, including reported reasoning. Aggregate input (billing/cache statistic, not context size): 3,841,473 tokens, of which 3,439,520 were reported cached (**89.5%**). Opaque reasoning signatures were retained; their underlying content is unavailable for review.

This episode cost **$0.58513875**. Combined with the preceding short runs and diagnostics, the shared experiment reported **$0.6619275 of the approved $1**, with no unknown-cost attempts. Actual costs and attempted-request reservations remain separate in `.local/gemini-combined-capture-budget.json`.

## Interpretation

The combined capture/recording path now has one longer real-web exercise with recovery and no fatal errors. This does not establish general robustness or success on the research task. Fast inference exposes remaining serial guards, full post-action captures and context work. Most tool usage was AX exploration, consistent with prioritizing the AX-search-ready path next. The schema simplification remains a diagnostic workaround, not a proven general fix. No deployment or global tool-default change was made.

## Follow-up: where the other 207 seconds went

Saved-event interval attribution (`latency-breakdown.py` / `latency-breakdown.json` beside the launcher) identifies repeated **serial full captures** as the largest measured component: **92.35 seconds, about 45%** of the other-harness-work bucket.

| Serial full capture purpose | Count | Total |
|---|---:|---:|
| Pre-action state guards | 22 | 43.21 s |
| Post-action observations inside tool execution | 21 | 46.77 s |
| Initialization | 2 | 2.36 s |
| **Total outside model/prefetch barriers** | **45** | **92.35 s** |

The 80 background captures are excluded from this table. The guards occur after the background snapshot has completed; post-action observations block before the next model request. Within these 45 captures, the largest individually instrumented phase was element/frame preparation (30.76 s), followed by AX extraction (11.17 s) and DOM snapshots (10.59 s). These nested phase numbers must not be added to the 92.35-s total; the remaining native time includes wrapper/frame processing not separately assigned by this analysis.

Other directly recorded work: shallow decision capture 16.87 s, native action execution 13.13 s, settling 11.34 s and task validation 0.32 s. Roughly 73 s remains spread across context/index preparation, identity checks, serialization/evidence recording, setup/cleanup and other glue; it cannot be honestly attributed wholly to Python or disk from these timers. Post-action native capture is also included in BrowserGym's observation timer, so those two counters are not additive.

The clearest optimization target is avoiding repeated full-state extraction around actions while preserving document, custody and target-validity checks—not merely moving the same guard capture to another thread.
