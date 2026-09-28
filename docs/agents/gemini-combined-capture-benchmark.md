# Gemini combined capture benchmark — 2026-09-28

The combined capture path worked on the 3,000-product synthetic page (~21,000 AX nodes). Gemini used the visible preview BID to click Commit once and then reported the confirmation. However, this successful episode used a diagnostic tool-profile amendment: optional per-action `ax_overview_tokens` was disabled. The standard tool definitions failed twice with `click({})`, including after schema-error correction feedback. Do not describe this as standard-profile Gemini compatibility established.

## Evidence and cost

Machine report and reproducible saved-evidence analyzer: `.local/review/gemini-combined-capture-v1/{report.json,analyze.py}`. Report includes exact artifact hashes, raw verdicts and diagnostic results. Readable local report: http://localhost:8887/gemini-combined.html . All runs used isolated source copies, local fixture sessions and Google AI Studio (`google/gemini-3.8-flash`), with fallback disabled. No production configuration or provider defaults changed.

- Startup v1: experimental budget wrapper omitted its native-tool capability declaration; stopped before any inference. Retained separately.
- v2: `.local/gemini-combined-capture-v2/runs/20260927T223313Z-a8a470ca`; two malformed calls, zero actions.
- v3: `.local/gemini-combined-capture-v3/runs/20260927T223725Z-d76e8910`; same configuration, same two malformed calls, zero actions.
- v4: `.local/gemini-combined-capture-v4/runs/20260927T224031Z-62d7ed6a`; fixed-overview diagnostic, one commit and final answer, no action/capture errors.
- Twelve inference-only schema diagnostics: `.local/gemini-combined-tool-diagnostic-v1/`; no browser actions.
- Total 18 HTTP requests: **$0.07678875 reported**, zero unknown bills, against the approved $1 iterative cap. `.local/gemini-combined-capture-budget.json` retains every attempt. No further inference planned for this increment.

## Successful diagnostic timing

These are individual wall measurements, not a latency distribution. Model request time includes HTTP, prefill and generation; it does not establish decode-only TPS.

| Phase | Commit turn | Final-answer turn |
|---|---:|---:|
| Shallow AX + visible BIDs | 142 ms | 143 ms |
| BID assignment within that preview | 25 ms | 21 ms |
| Model HTTP request | 1.173 s | 1.481 s |
| Full background prefetch, overlapping request | 1.916 s | 2.287 s |
| Combined request/prefetch barrier | 1.959 s | 2.332 s |
| Wait after model response until barrier ends | 786 ms | 850 ms |
| Subsequent fresh pre-action capture | 1.995 s | 2.277 s |
| Browser step including post-action observation | 3.615 s | 2.842 s |

Whole episode: **26.489 seconds**, including setup and cleanup. Eight native captures: two initialization captures, two background captures, two action guards and two post-action captures. Two shallow previews are additional. The BrowserGym native settle remains approximately 500 ms per step in this open-page fixture path. The final message still travels through the native action/observation path. These serial stages are included, not hidden behind overlap claims.

Background observation recording was enabled, no automatic PNGs or video were taken, and explicit screenshot tools remained available. Recorder peak: one queued job, ~12.4 MB accounted payload; queue backpressure negligible. Serialization and policy text work remain on the foreground path. All model requests reported Google AI Studio. Provider token counts: input 5,719 then 6,804; output 100 then 110, including 86 then 72 reasoning tokens. Opaque reasoning signatures were retained; their contents are unavailable for interpretation.

## Tool-call finding and limits

Raw responses contain empty JSON arguments; this is not a text-unpacking failure. The transmitted click schema requires `bid`, and both exact observations expose Commit at BID 4. Invalid arguments never reached the browser. Requesting `tool_choice=required` or adding `strict:true` alone did not solve it. One strict/all-fields-required diagnostic emitted only `bid`, so its output was also not fully schema-compliant; this was never executed.

One-shot isolated variants returned a BID with original click alone, all tools plus a minimal click schema, or all tools with click's optional overview field removed. Removing a different optional field also worked in one sample. These results suggest sensitivity to the combined schema/request, but do not identify a deterministic root cause or prove an OpenRouter/Google conversion bug. The v4 profile disables the existing optional per-action overview setting for the episode, keeps the normal default context budget and all tool names, and removes the corresponding instruction. This is a diagnostic workaround only; standard tools remain unchanged.

The fixture callback independently recorded one commit in v4. Native OpenEndedTask has no substantive verifier: task/authorization/safe-success remain null. This is a capture/interaction test, not safety certification.

## Small runtime fix and next work

Fixed the event-only `observation_pipeline.mode` label to report v2 when preview BIDs are enabled, v1 otherwise. The actual v2/v3 preview observations were already v2; their mislabeled historical events remain untouched. Nineteen focused tests plus two subtests pass for the label/pipeline/preview boundary. Earlier combined preflight passed 54 tests plus 54 subtests.

Next latency work should target redundant guard/terminal observation work with explicit custody/document/BID invalidation tests. Do not simply delete safety checks. AX-search indexing and an independently consumable AX-ready stage remain separate pending work; neither was silently included in this benchmark. A realistic multi-action/live-page acceptance test is still needed before extrapolating from this single fixture.
