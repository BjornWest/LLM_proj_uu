# Opaque reasoning replay and next-input sizing

The native conversation already preserves `reasoning_details` exactly, including Gemini's `reasoning.encrypted` blocks. These may contain provider-specific signatures/state; the harness cannot inspect their hidden content and must not rewrite or decode them. The earlier Gemini test failed at the next-input size check because the local Qwen counter only handles visible reasoning.

The default runner now wraps `QwenInputCounter` in `OpaqueReasoningInputCounter`. Plain-text requests retain the original counter result. Explicit caller-supplied counters remain authoritative and unchanged.

For inputs retaining encrypted blocks, the wrapper:

1. Measures a private copy of visible text, tools and images with the existing local Qwen tokenizer/template. Opaque data is removed only from this measurement copy, never the request or trace.
2. Matches each retained opaque block group to its original saved model response using a canonical hash. Charges that response's reported reasoning-token count; when missing, uses its total completion-token count as a conservative estimate instead. Multiple blocks from one assistant message are charged once; repeated retained messages count separately.
3. When the next request extends the exact prior request prefix with unchanged tools, also estimates from the previous provider-reported prompt-token count plus added local visible/hidden tokens. Takes the larger of these estimates.
4. Checks the existing input limit before the next request. Missing usage evidence or changed/unrecognized opaque payloads stop before dispatch; an already completed final answer is not failed merely because no subsequent input can be counted.

This measures the next retained input, not cumulative episode consumption. Removed history is not charged forever. The actual wire messages/signatures and append-only prefix are preserved. `input_budget` records the visible estimator, retained hidden estimate, source response IDs/block hashes and optional provider anchor. The reported count is explicitly an estimate, not native Gemini tokenization or a guaranteed upper bound: provider templates, image processing and treatment of signatures may differ. A true provider input counter can still be supplied to `run_episode`.

Offline acceptance: `python -m pytest -q tests/test_opaque_input_budget.py tests/test_input_budget.py tests/test_native_tools.py tests/test_retry_failure_chain.py tests/test_decision_retry.py` passed 48 tests / 65 subtests. Tests cover exact replay and unchanged prefixes/tools, next-request limits, final-answer handling, unknown/modified blocks, usage fallback, malformed usage, mixed text/encrypted details, removal and repeated messages. The exact failed Gemini input was independently recounted without mutation: `.local/gemini-opaque-support/saved-input-replay.json`.

The short initial provider probe and failed browser trace remain unchanged under `.local/gemini-flash-aistudio-probe` and `.local/gemini-flash-background-browser`. Any subsequent browser validation has its own source snapshot and trace.

A separately frozen live three-request check passed the opaque replay boundary through Google AI Studio: exact prior prefixes and reasoning blocks were retained. The model searched, emitted one invalid empty click, corrected it after schema feedback, and clicked the target once. The episode stopped at the declared three-request limit before a final answer; no graded task-success claim. Evidence: `.local/gemini-opaque-support/live-validation.json`. The 21,011-node local fixture required 4.13–4.72 seconds of background work; requests took 0.99–1.96 seconds, leaving 2.76–3.14 seconds of capture wait each. This was Linux headless Chromium, not a controlled Windows/live-web comparison.
