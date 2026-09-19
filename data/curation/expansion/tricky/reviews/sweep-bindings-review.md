# Independent sweep invocation review

SWEEP-BINDINGS-01 is closed for the corrected v3 export. This accepts reusable invocation descriptions, **not new execution readiness**. No browser, model, service, or shared-source changes were made by this review.

The v2 audit found two concrete defects: AU01–AU20 declared 28 steps despite their accepted 24-step profile, and six derived WebArena bindings called the copied runtime optional even though their factory modules assert its activation at import. The parent fixed these in v3 and added the independently accepted forum vote task 407.

Evidence:

- [Historical v2 audit](sweep-bindings-v2-final-review.json): 169 tasks / 346 retained native episodes. The two current-file hash differences are the subsequently amended exporter and accepted index; the archived v2 exporter exactly matches its historical pin.
- [Corrected v3 audit](sweep-bindings-v3-review.json): 170 tasks / 351 retained native episodes / 107 referenced hashes / 14 distinct adapter symbols. All references match; no missing task evidence or profile mismatches.
- [Read-only audit program](audit_sweep_bindings_v1.py) checks exact task goals, policy projection, retained first requests, terminal instructions and recorded caps without importing candidate graders.
- [Six regression tests](test_sweep_bindings_review_v1.py) check private-field exclusion, missing-goal rejection, cap and strict-draft version selection, mandatory runtime activation, actual constructor signatures and held-task/readiness boundaries.

All 170 policy projections contain only the task goal and public response-format instruction. Private contract rows, expected answers, evaluation fields and implementation metadata are excluded. All retained terminal instructions appear in exact saved system messages and the goal matches the saved user goal. A null terminal instruction for seven original action tasks intentionally selects the native runner's recorded “Done” default.

The adapter bindings preserve preparation before environment creation, initial capture, post-action state capture and evaluation before close. Tricky adapters own per-episode fixture servers and require their `close()` cleanup. External WebArena adapters still require their pinned factory recipes: appropriate test-account headers, route guards, shared event lists, HAR recording, callbacks and teardown. Read-only WebArena native grading remains a separate post-close HAR replay, not a runtime verifier result. Constructor arguments match the referenced classes, including the two inherited original Tricky classes.

The strict-draft cases select `authored03.native_v2`. The seven derived WebArena bindings require `CURATION_FROZEN_RUNTIME` and the pinned activation helper before any `intent_browser` import. Other historical source maps remain distinct from that optional baseline. Among reviewed episodes, authorization is null in 335 and false in 16; none asserts complete authorization. Unknown safety is not converted into success by the export.

One implementation detail remains for an eventual executor: construct `native_tools_profile(parallel_tool_calls=None, compact_feedback=True, reasoning_replay="preserve")` explicitly. Calling its constructor with defaults produces a different profile; a profile name in a manifest is not itself a constructor call. The current export already keeps every task's execution/model/training/production flags false and requires new source, environment and funding preflight.

Reproduce the regression checks without browser or inference calls:

```bash
python3 -m unittest data.curation.expansion.tricky.reviews.test_sweep_bindings_review_v1 -v
python3 -m data.curation.expansion.tricky.reviews.audit_sweep_bindings_v1 \
  --input .local/curation-expansion/sweep-inputs-170-v3.json \
  --output NEW_REVIEW.json
```
