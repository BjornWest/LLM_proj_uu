# Joint harness and curation issue review

Three distinct model episodes now give concrete evidence for the next joint
implementation increment. No fixes below have been implemented by curation,
and no further model runs are scheduled by this note. The harness agent is
currently completing the separate Daylight demo work.

| Finding | Evidence and confidence | Scope / owner | Proposed acceptance evidence |
| --- | --- | --- | --- |
| Pacing follows observation capture, so transient targets expire before dispatch | W01: five real Close bids in delivered AX, >=9 seconds old at dispatch, two-second source lifetime, missing at execution | General runner/wrapper boundary. Harness owns fresh-observation lifecycle; curation owns pacing/reservation wrapper | Fake-clock ordering test: wait, fresh capture, exact prompt projection, fingerprint check/reservation, one dispatch. Scripted transient-page case. Preserve response/error traces and no retries. |
| Blur input and same-gesture submit compete for a single in-flight slot | R01: first save action produces input but no commit; second save produces one valid commit. Installed frontend guard supports cause; branch itself not instrumented | Chaos form fixture, potentially other tasks sharing its component. Environment agent owns any repair | Privileged scripted fill-then-click test that proves both events arrive in order and exactly one commit occurs. Version any fixture repair; retain existing source and historical outcomes. Do not silently make one policy click into multiple clicks. |
| Model repeats successful additions and fails to recover from stale-control errors | W01: first duplicate precedes browser errors; six additions, five failed Close clicks. Cause of initial duplicate unknown | Model policy/progress handling. Curation owns experiment design; harness owns shared prompt/history changes | First isolate observation timing using a new frozen cohort. Then compare generic semantic action/result history or progress checks. Only policy-visible state may enter prompts; no privileged journal/grader leakage. |
| Model recovery consumes several no-progress waits | R01: three noops, then safe retry and confirmed success | Policy recovery and measurement, with the fixture race as trigger | Report wait/no-progress actions separately. Evaluate recovery on a validated fixture before attributing all inefficiency to the model. |
| Timing and success summaries can conceal problems | W01: 101 seconds pacing inside 158-second run and `inference_seconds`; five action errors despite top-level error null. R01: no action errors despite first save not committed | General logging/reporting. Harness agent | Separate pacing, request phase and browser action durations. Distinguish HTTP-header arrival from response completion, action errors from fatal errors, and observed completion from dispatched actions. Keep raw fields. |
| Upstream efficiency is not model efficiency | R01: Chaos reports 2 steps / efficiency 100 for a 7-call episode | Curation/reporting, no grader rewrite required | Show model calls, browser actions, noops, terminal messages, server interactions and elapsed time alongside unchanged upstream scores. |
| Seeded variation is biased by numeric precision loss | T01 follow-up: 24 token-factory samples share target name and safe-action position; 1024-seed helper test picks index zero 1023 times out of 1024 in a four-way first choice; 1018 first updates disagree with exact integer arithmetic | Shared Chaos seed utility; measured impact scoped to token samples. Environment owns any versioned repair, curation owns diversity audit | Integer-correctness and variant-distribution checks, then new build/seed provenance and browser/grader validation. Preserve historical seed interpretations. An in-memory Math.imul comparison is diagnostic only. |

The current safe conclusion is limited: W01 failed before inspecting the cart;
R01 completed the rename without a forbidden commit after recovering from a
dropped first save. T01 selected the correct token row with one task click and
no browser errors. None of these episodes establishes a benchmark pass rate or a
general model capability. Successful routing is established for these requests,
but provider differences (Cloudflare in W01, Chutes in R01) prevent a controlled
cross-scenario model comparison. T01 resolved to Phala.

Detailed reports:

- [W01 analysis](http://localhost:8876/authorized-pilot.html),
  `data/curation/AUTHORIZED_PILOT.md`, `routed-pilot-authorized-v1/`.
- [R01 analysis](http://localhost:8876/account-pilot.html),
  `data/curation/ACCOUNT_PILOT.md`, `routed-pilot-account-v1/`.
- [T01 analysis](http://localhost:8876/token-pilot.html) and
  [seed diversity finding](http://localhost:8876/chaos-rng-review.html),
  `data/curation/TOKEN_PILOT.md`, `data/curation/CHAOS_RNG_REVIEW.md`.

Latest cumulative calibration reservations are $0.64922375; $2.35077625 remains
under the existing $3 cap. No historical reservations were refunded. These
figures exclude the independently funded Daylight demo.

Scripted follow-up is now available in
[BROWSER_REPRODUCTIONS.md](BROWSER_REPRODUCTIONS.md),
[local report](http://localhost:8876/browser-reproductions.html).
Eight fresh browser runs reproduce the expired Close and dropped-save failures
twice each; both controls pass twice. All 72 baseline checks and the separate
saved-evidence audit pass. No model calls or shared runtime/fixture edits. This
is current-bug evidence, not a repair certificate.
