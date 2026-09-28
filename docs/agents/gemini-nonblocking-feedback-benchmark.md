# Gemini nonblocking-feedback trial: 20 turns

One newly authorized, isolated real-web episode completed **20 model turns without a harness exception or action error**. It stopped at the chosen turn limit, not at task completion. Total recorded episode wall time: **78.900 seconds**. Reported inference cost: **$0.13724295**, all 20 responses from Google AI Studio, no unknown-cost attempts or automatic episode restart.

[Open trace](http://localhost:8878/#d6758e5a51c8bc8b2280). Original trace: `/home/bjorn/code/LLM_proj_uu/.local/gemini-combined-feedback-20-v1/runs/20260928T084751Z-341ff855`. Frozen source, plan, actual-cost ledger and read-only analyses: `.local/gemini-combined-feedback-20-v1`.

## Configuration and scope

Same Sony WH-1000XM5 black headphone comparison task as the prior targeted-capture trial: research three retailers delivering to Malmö, verify prices/shipping/availability, no cart, purchase, account or personal information. Same Gemini `google/gemini-3.8-flash` fixed-overview compatibility variant; Google AI Studio only, no Vertex/fallback, 16,384 output-token maximum, 100,000 estimated next-input ceiling, 20-turn cap, fresh Windows Chrome/CDP context, configured background/no-focus layout, human handover available, diagnostic capture mode. No helpers or separate search API.

Runtime changes relative to the last trial are limited to the six files listed in `source-delta.json`: push-only browser feedback, delivery wording and buffered timing instrumentation. Current source matched the completed offline acceptance before freezing. Frozen files remained unchanged through the run. Automatic screenshots/video remain disabled; explicit screenshots remain available but were not requested. HAR and asynchronous trace recording remain enabled. The new cost ledger does not modify historical capped cohorts.

## Exclusive wall-time breakdown

| Category | Seconds | Share |
|---|---:|---:|
| Startup before first request | 18.353 | 23.3% |
| Model request in flight | 26.244 | 33.3% |
| Waiting after model response for capture/validation | 9.676 | 12.3% |
| Other work during the active loop | 24.321 | 30.8% |
| Evaluation and cleanup | 0.305 | 0.4% |
| Total | 78.900 | 100.0% |

The earlier three-category convention reports **42.979 seconds / 54.5%** as other harness work. Splitting startup and cleanup out, as above, shows that **18.353 seconds** happened before the first model request; this is not a delay repeated on every turn. Environment reset itself took 17.560 seconds, including browser/chat setup and initial page capture.

Request flight includes network, provider queueing, prefill, generation and small local wrapper work; it is not decode-only time. Full capture overlapped **all 20 requests**. No model request was in flight for 52.656 seconds of the whole episode, including startup. The median full background prefetch was 1.353 seconds; median request flight was 1.202 seconds. Median post-response capture/barrier wait was **0.154 seconds**, maximum 2.129 seconds.

## Feedback result

| Measurement | Result |
|---|---:|
| Before-request feedback, all 20 turns combined | 3.351 ms |
| Slowest before-request feedback update | 1.102 ms |
| Buffer drain, all 28 calls combined | 0.531 ms |
| Slowest buffer drain | 0.0368 ms |
| Browser events received | 142 |
| Observer-install errors | 0 |
| Debug records retained / dropped | 8,598 / 0 |

The earlier **19.733-second** before-request feedback stall did not recur. Raw events and selected feedback updates are retained, including asynchronous navigation and text changes delivered in later turns. Two bounded producer gap notices were recorded: this remains best-effort feedback, not an exhaustive event journal. Zero observer-install errors does not prove every page event was captured.

## Remaining serial work

The timing scaffold makes several costs visible without adding browser probes:

- **9.949 seconds** elapsed from completed model/capture barriers to the first tool starting, across 20 turns (median 0.499 seconds). This interval includes policy bookkeeping, AX preparation and browser identity/custody checks; it is not a single fixed sleep.
- Across the entire run there were **146 identity-session detach operations**, totaling **5.771 seconds**, plus session creation/frame-tree/document checks. Some overlap other phases, so this total must not be added to the exclusive table. A sampled `ax_search` decision (zero-based turn 10) made five identity checks before dispatch; several detaches each took about 44 ms. Reusing/checking identity less redundantly is a concrete next investigation, not a fix made during this run.
- The shallow preview cost 4.353 seconds total. Four actual browser actions cost 7.752 seconds inside `env.step`, including settling and one intermediate fill/press capture. These are nested diagnostics, not additional exclusive categories.
- The native full-capture count was 23: two startup, 20 background, one intermediate batch capture. **No full pre-action guard captures** occurred. Three final-action observations were deferred. Three element-target probes totaled 0.161 seconds; URL navigation did not require an element probe.
- Background recording queue backpressure totaled only 0.000019 seconds. Foreground observation serialization is recorded separately; the recorder queue was not a substantial wait.

## What the agent did

The agent inspected the consent UI, clicked a consent control, found the search box, issued a fill/Enter batch, searched and traversed the result tree, used `goto` to open a product URL, then explored color/price-related AX regions. It proposed 21 tool calls across 20 model responses: eight `ax_search`, nine `ax_read`, one click, one fill, one press and one URL navigation. Document-change batch boundaries were recorded normally; there were no tool-format errors, action errors or technical failures.

It had not produced the requested three-retailer comparison when the 20-turn test ended. Completion, authorization and safe-success labels remain null. This was a latency/reliability probe, not a benchmark success claim.

Final request input was **22,847 provider-reported Gemini tokens**. Total generated output was 1,887 tokens, including 1,310 reported reasoning tokens. Aggregate reported cache fraction was 38.2%; that aggregate is a billing diagnostic, not context size. The model did not request a screenshot.

## Comparison limits and evidence

The previous trial stopped with a harness error after 16 responses in 104.542 seconds. This one reached 20 responses in 78.900 seconds: 3.945 versus 6.534 seconds per response including setup/cleanup. This is encouraging, but different live page states, advertisements and model actions mean it is not a controlled speedup estimate. Background capture was also faster on this trajectory, which cannot be assigned wholly to the feedback change.

The separate prior event-pump crash did not recur; one clean run does not prove that unmodified boundary is repaired. Original traces/evaluations remain unchanged. Saved evidence includes `review.json`, `wall-time.json`, `debug-review.json`, `latency-breakdown.json`, `debug-summary.json`, a bounded single-run triage export and the raw `debug-timings.json`. The debug spans can nest and overlap and must not be summed indiscriminately.
