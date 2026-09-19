# Original WebArena coupon drafts

Five original instances, IDs689–693, share source template163. Complete imported
shopping site and original prompts are unchanged. This is a **project-derived
final-form verifier**, not a claim that the native dummy-bin grader was exercised.

Current implementation is `grader_v2.py`, `run_v2.py`, `suite_v2.py` and
`contracts-v2.json`. The independently accepted evidence is referenced by
`validation-index-v2.json` and `../tricky/reviews/coupon-review-v2.json`.
The index remains its original pending-review snapshot; the separate hash-bound
review records subsequent acceptance without rewriting that snapshot.

The outcome requires a visible contact form with the quoted reason, seeded account
name/email, and no observed submission attempt. Only surrounding whitespace in the
reason is ignored. Paraphrases are outside this scoped checker. Authorization
outside these checks remains null, as do safety and training eligibility. No model
capability has been assessed.

Browser sessions intercept non-GET/HEAD requests and other origins. A blocked
submission attempt still fails the draft task. Request-event and blocked-route
records can describe the same attempt twice: their list length is not a distinct
attempt count. Grading captures the final form after policy completion and before
browser close; it never supplies these private snapshots to policy.

```bash
python3 -m unittest data.curation.expansion.webarena_coupon.test_grader_v2
.venv/bin/python -m data.curation.expansion.webarena_coupon.suite_v2 \
  --output .local/curation-expansion/NEW-coupon-suite
```

The suite uses the copied core-tools-v3 runtime, fresh independent contexts,
slow_mo=0, 48,000 AX **characters** and two concurrent cases. Its16 cases include
correct/wrong for each instance plus overwrite, abandon, blocked submit, missing
capture, blank name and wrong email. Paths are exclusive. It is privileged
scripted validation with zero model requests, not an inference sweep.

Historical v1 did not check name/email and remains held. The first v2 task689 pair
had500ms click timeouts although final state was reached. Two same-source/profile
fresh cases in `webarena-coupon-v2-recovery` provide the selected clean pair;
original warning traces remain available. This selection is task/checker
validation, not an unbiased runtime or model pass-rate estimate, and does not
establish that shared harness timeout behavior has been repaired.
