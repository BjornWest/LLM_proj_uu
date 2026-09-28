# Gemini targeted capture: 20-turn live trial

One user-authorized episode ran against real Prisjakt pages on 2026-09-28 local time. It stopped with a harness exception after the **16th model response**, before reaching the 20-turn limit. No rerun or action replay occurred. The research task was unfinished; completion, authorization and safe success remain unknown.

[Open trace](http://localhost:8878/#4cc7ef865accad3f671d). Frozen source, plan, raw requests/responses, cost ledger and timing analysis: `.local/gemini-combined-targeted-20-v1/`. Exact trace: `runs/20260927T233505Z-4befac6e` under that directory. Source hashes remained unchanged throughout.

## Configuration

Same task as the preceding 80-turn run: compare black Sony WH-1000XM5 headphones at three retailers delivering to Malmö, with price/shipping/availability evidence; no purchases, cart additions or accounts. Same Gemini fixed-overview compatibility tool variant, `google/gemini-3.8-flash`, Google AI Studio only, 16,384 maximum output tokens, 100,000 estimated input-token ceiling, fresh Windows Chrome/CDP context, diagnostic capture mode and human handover available.

Changes: current frozen runtime with `targeted_actions=True`, 20-turn maximum. Automatic screenshots and video disabled; asynchronous recording on; explicit screenshot tool still available. The model requested one screenshot (two derived PNG artifacts, zero automatic observation screenshots). This run is a new trajectory, not matched action playback of the prior run.

## Wall time

Whole recorded episode, including setup and cleanup: **104.542 seconds**. All 16 requests overlapped full background extraction.

| Exclusive wall-time category | Seconds | Share |
|---|---:|---:|
| Model request in flight | 20.861 | 20.0% |
| Waiting after model response for capture/validation barrier | 23.673 | 22.6% |
| Other harness work | 60.008 | 57.4% |
| Total | 104.542 | 100% |

Request flight includes provider queueing, network, prefill, decoding and small local backend accounting; it is **not decode-only time**. Thus the harness had no model request in flight for **83.680 seconds (80.0%)**. Background work performed during request flight is already inside the first row and must not be added again.

| Per-request/capture measurement | Median | Maximum |
|---|---:|---:|
| Model request flight | 1.256 s | 1.752 s |
| Full background prefetch | 2.963 s | 4.604 s |
| Post-response wait | 1.646 s | 3.428 s |
| Shallow preview | 0.214 s | 0.549 s |
| Targeted element check (5 probes) | 0.066 s | 0.107 s |

The retained full background snapshots range from 736 to 5,450 AX nodes (median 2,143). These node counts describe page structure, not model tokens.

## What improved, and what remains slow

**No full pre-action guard captures occurred.** All five main-document element probes used targeted checks, taking only **0.363 seconds combined**. Three successful final-action post-captures were deferred. The final failed action never produced its deferred observation.

There were 19 full native captures: 16 background, two startup, and one intermediate capture inside the fill/press batch. That intermediate capture took **6.259 seconds**; retaining it ensures later actions in the same batch have updated state.

The other-harness bucket includes a conspicuous **19.733-second feedback collection before turn 8**. The saved update reports `frame_flush_unavailable`; the collector's drain path synchronously evaluates live frames. The timer includes drain and feedback presentation, without individual-frame timings, so attributing the entire stall to a particular advertising frame would exceed the evidence. This is a separate path from the optimized AX capture.

Other recorded nested components: shallow decision capture 4.125 seconds; completed BrowserGym action execution 1.339 seconds; settling 4.273 seconds; validation 0.071 seconds; post-action observation 6.656 seconds (including the intermediate capture). These are not additional rows to sum on top of the exclusive table. The final interrupted action does not have complete BrowserGym phase timings.

The asynchronous recorder peaked at one queued job / 4.60 MB accounted payload, with only **0.000017 seconds** of queue backpressure. This does not exclude foreground serialization/context costs, but the disk writer queue was not the large observed wait.

This sample **does not establish better end-to-end throughput**. It averaged 6.53 seconds per response versus 5.11 in the earlier 80-turn run, but task progress, pages, screenshot use and the feedback outlier differ. It does establish that the targeted path removed the serial full pre-action captures. Fast Gemini responses still outpace full background capture.

## Failure evidence

Turn 16 proposed a valid `click(bid='467')`. Its live target identity/semantics check passed. Native action code returned with no action error; then the best-effort one-second DOM load wait expired. Immediately afterward, `sync/context_event_pump` raised:

```text
AttributeError: 'str' object has no attribute 'get'
```

The event pump invokes `BrowserContext.cookies()` to service queued browser events. Nearby route-handler logs contain capture-deadline exceptions. The primary exception's full Python traceback was not retained, so the exact mechanism and causal relationship remain unproven. This is a post-action harness/transport failure, not malformed model output; it did not occur in the targeted AX comparison. No final full/deferred observation was published, and the trace correctly warns that the dispatched action may have changed the site. Do not replay it automatically.

Evaluation preceded cleanup; cleanup completed without a recorded cleanup error. An offline reproduction of the DOM-wait/event-pump boundary is needed before another reliability claim. The run provides timing evidence but is not a clean 20-turn acceptance pass.

## Billing and review scope

All 16 responses report **Google AI Studio**. Actual cost: **$0.095294175**, with no unknown-cost responses. The prior capped ledger was unchanged; this episode had finite user authorization.

Final request input: **27,000 provider-reported Gemini tokens**. Total generated output: 1,073 tokens, including 692 reasoning tokens. Reported aggregate input/cache counters imply 57.6% cached; these billing counters are not context size. No final answer was produced.

Read-only analysis: `review.py`, `latency-breakdown.py`, `wall-time.py`, `findings.json` and a single-episode triage export. Original raw artifacts and null verdicts are unchanged. The curation tool path is currently being migrated, so the triage exporter was copied from Git HEAD into ignored `analysis-tools/` with commit/hash provenance; no tracked curation files were restored.
