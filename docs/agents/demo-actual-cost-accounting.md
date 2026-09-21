# Deployment actual-cost accounting

The demo now counts provider-reported charges instead of permanently accumulating
worst-case reservations. This applies to client demo requests, remote manual Ask,
and worker task requests. The existing $1 daily limit and 100-request daily limit
remain unchanged. The separate local benchmark ledgers are unaffected.

Before dispatch, a temporary maximum-cost allowance prevents concurrent requests
from collectively crossing the cap. A saved provider response settles that exact
attempt at its actual nonnegative `usage.cost`, including parser failures and
HTTP errors that report a cost. Unknown/transport-failed requests retain their
allowance; they are not silently free. Known pre-dispatch cancellation releases
its allowance. Abandoned allowances require evidence-based reconciliation.

`deploy/daylight/lib/budget.mjs` owns the shared daily v2 ledger. Each permit has a
unique ID/date; compare-and-swap retries apply only to local accounting, never
inference or browser actions. Settlement is idempotent, conflicting duplicate
settlements are rejected, and reported costs above the bound are recorded in full
before further requests are stopped. Late settlement is attributed to the permit's
original UTC date. Requests per day remain a separate guard.

The Python worker preserves exact request/response transport first, then calls
the authenticated `settle` endpoint, before returning an action. Settlement binds
the worker lease, request index, fingerprint and issued receipt; terminal jobs may
accept a late cost without becoming runnable again. If accounting fails, no action
is delivered and raw evidence remains. Budget rejection now explains spent versus
outstanding amounts instead of only reporting HTTP 429.

Original response bodies and traces are unchanged. v2's compatibility
`reserved_usd` field means actual charges plus outstanding liabilities. An old
frontend that tries to increment this field without a matching attempt is rejected
by the PC service; it cannot silently bypass the new ledger during rollout.

## Historical correction

2026-09-21 had ten legacy permits totaling $0.9937515 but saved reported charges
of $0.02947928: nine manual Ask calls ($0.02760924) plus one worker call
($0.00187004). Complete cumulative receipt order, total/count equality, unique
response IDs and request fingerprints were checked. Failed permit requests did
not dispatch and were not included. Evidence: `.local/budget-actual-v2/`.

`scripts/reconcile_demo_budget.mjs` validates an operator-created evidence file,
and optionally applies it to a paused SQLite service. It requires a matching raw
ledger hash, every legacy permit, valid bounded charges, unique responses and
no active worker/Ask. It retains the original aggregate inside the new ledger.
Partial/unknown evidence does not qualify; old ledgers otherwise remain unresolved.
This is a correction from saved charges, not a budget reset or increased cap.

## Validation and release

131 Node tests, 17 Python worker tests; no paid inference. Focused checks cover
parallel reservations, settlement races, duplicate response/cost rejection,
unknown liability, midnight settlement, daily call cap, unsent cancellation,
legacy migration omissions, late job settlement, and stale deployment writers.
Real local scripted Prislyktan positive/negative publication checks pass. Policy,
website, task and grader sources are unchanged; only team_worker.py changes in
Python. The new certificate directory retains original source acceptance plus
this explicit transport amendment; container certification accepts 203 expanded
and six Prislyktan tasks. Saved acceptance is not a new autonomous model result.

Images are derived from the installed standard images using the frozen delta
context in `.local/budget-actual-v2/image-context`. Append
`deploy/control/actual-cost.override.yaml` to the existing compose configuration,
set `STANDARD_WORKER_CERTIFICATES` to the new reviewed directory, and retain
existing volume mounts. Check there are no running jobs/Ask, back up SQLite,
reconcile while stopped, recreate control and its worker (shared network namespace),
then verify capabilities before publishing the Vercel change. Do not roll back to
an old ledger writer after v2 writes have begun. No automatic task reruns.
