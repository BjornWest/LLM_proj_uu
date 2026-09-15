# Review of proposed decision-observation hook

Read `HARNESS_ISSUE_REVIEW.md` and
`.local/preflight/harness-issue-review.json` on 2026-09-15. The independent W01,
R01 and RNG findings agree with the curation evidence. No further model cohort,
fixture repair or change to historical labels is implied by this review.

The proposed sequence is appropriate: readiness/pacing, fresh observation,
exact prompt construction, source validation and reservation, then a single
request. Retain both the original post-action observation and the separate
observation used for the decision. A pinned BrowserGym 0.14.3 `_get_obs()` adapter
avoids adding a fake action. Its extraction marks DOM elements and captures page
state; describe it as observation extraction, not a completely side-effect-free
operation. Preserve last-action errors and distinguish extraction failures from
model request failures. Controls can still expire during inference.

A concrete Tricky compatibility issue needs handling before a new model cohort:
`TrickyTask.after_step` currently reads `observation-{index:03d}.txt` and passes
that text to `snapshot`, which latches `warranty_delivered` when the warranty name
occurs before a checkout. This is the transition observation, not the proposed
fresh decision observation. After the hook change the two can differ. DEV-W01
inherits this exposure tracking. The implementation must keep state/journal
capture separate from recording the exact policy-delivered text. Do not promote
an undelivered transition observation to exposure; do not miss content appearing
only in the new decision observation. Define separately capture, constructed
prompt and actual request delivery evidence, including failed dispatches.

Acceptance cases to add to the harness-owned tests:

- Transition contains warranty, decision observation does not: that transition
  alone cannot establish exposure.
- Transition lacks warranty, decision observation contains it before checkout:
  exposure can be established using the chosen delivery evidence contract.
- Construction or dispatch fails: retain the observation and request evidence,
  but do not silently treat prompt construction as confirmed model delivery.
- A prior valid exposure remains recorded; a post-checkout observation cannot
  establish first exposure before that checkout.

The curation baseline already supplies eight fresh browser traces: two expired
Close failures, two direct-save dropped commits, and two of each successful
scripted control. See `BROWSER_REPRODUCTIONS.md`. It does not prove the newly
proposed hook works, and the Chaos in-flight guard branch remains uninstrumented.
The new hook needs its own source-pinned fake-clock and fresh-browser checks.

At inspection, `intent_browser/runner.py`, `intent_browser/trace.py`, and the new
`intent_browser/observation.py` were actively changing. This note is a design and
compatibility review, not approval of an immutable implementation. The concrete
exposure gap was queued to the harness agent. No shared files, historical
profiles, budgets or raw episodes were changed; no browser/model calls were made.
