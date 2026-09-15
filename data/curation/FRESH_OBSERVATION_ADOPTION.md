# Offline adoption of fresh decision observations

The offline profile is now frozen against shared runtime `f0e4ff0`; live execution
remains disabled. The current wrapper, pacing and exposure checks pass: **33 tests
and 11 subtests**. All 23 saved scripted cases have matching artifact hashes; the
16 Chaos contracts and five Tricky exposure/receipt cases replay successfully.

The new wrapper is `data/curation/prepare_fresh_pilot.py`, with tests in
`data/curation/test_fresh_pilot.py`. Eighteen wrapper tests and three subtests pass. The earlier adoption was also
tested against an isolated copy of runtime `e91d6db`: 26 tests and five subtests
total. That earlier record retains its original wrapper hashes; the new freeze
evidence is recorded separately.
These checks use HTTPX MockTransport and fake environments/clocks. No browser,
model or search calls were made, and no real budget ledger was written.

The CLI has no live option and does not load credentials. It prepares an
offline-only profile, with no selected benchmark case or training eligibility.
This is adoption of the runner contract, not a newly authorized model cohort.

## New wrapper behavior

`run_episode(..., before_observation=backend.wait_until_ready)` is the intended
call site, exercised by the tests. The readiness hook:

- Reads the persistent ledger under a nonblocking lock, releasing it before any
  sleep. It rechecks after each wait and never reserves or dispatches.
- Carries the parent ledger's deadline into a new ledger and preserves deadlines
  across restarts and episodes. Offline tests inject their own synthetic start.
- Returns a single-use readiness record tied to the ledger content and episode.
  The runner keeps it out of policy messages.

After the runner captures its decision observation and constructs the prompt,
`complete` reacquires the nonblocking lock, checks the readiness record, validates
sources, reserves once and dispatches once. Changed state, a new deadline, a
missing hook, a different episode or lock contention rejects the prompt; it does
not wait again. Validation failure consumes no reservation. A dispatched failure
keeps its reservation and blocks automatic continuation/restart. Retry-After is
recorded conservatively but never causes a retry.

The cumulative parent is `routed-pilot-token-v1/budget.json`: $0.64922375 reserved,
including prior calibration and routing-test reservations. The existing cap is
$3; the unchanged request reservation is $0.014048, including Cloudflare's $4/M
output cap. Paid Daylight budgets remain separate. No refunds or negative
reservation credits are accepted. New synthetic test ledgers exist only in
self-cleaning temporary directories.

Routing and prompt settings stay Qwen `qwen/qwen3.8-27b`, the seven-provider list,
top-level session ID equal to episode ID, 512 output tokens, temperature zero,
reasoning off, 12 steps, no search or cache padding. Exact requests, responses,
resolved routing, usage and unknown costs are retained. Timing distinguishes the
HTTPX request-hook entry, response-header hook, and backend attempt end; these
are not claimed to be socket-write or raw response-body completion timestamps.

## Tests and evidence

```bash
.venv/bin/python -m pytest -q data/curation/test_fresh_pilot.py
.venv/bin/python data/curation/prepare_fresh_pilot.py
```

The tests cover actual runner integration and fresh versus transition artifact
references; exact delivered-message hashes; hook-diagnostic exclusion; one request
per reservation; session isolation; inherited/cross-restart pacing; no extra wait
or send after readiness changes; source changes after waiting; exhausted budgets;
429/timeout/error evidence; and preservation of null current-request attribution
when rejection follows a previous successful call.

The profile command verifies harness validation source and artifact hashes, the
curation wrapper/test files, the scoped project import closure, dependency
versions, BrowserGym extraction implementations, and historical funding evidence.
An existing profile is never silently replaced. Environment adapters remain a
separate prerequisite because no scenario is selected.

Saved isolated-runtime test evidence:
`data/curation/fresh-observation-offline-v1/stable-runtime-tests.json`.
The runtime snapshot under `.local/curation-pacing-e91d6db/` contains exact Python
files obtained from that Git revision. It avoids testing the handed-off contract
against concurrent working-tree changes. No shared source was reverted or edited.

## Current freeze and evidence

Profile: `data/curation/fresh-observation-offline-v1/profile.json`.
SHA256: `79b9803e61f5ad00948dc703b1922e9ce8f7a4667130869f798400d911a0e962`.
Shared runtime: `f0e4ff0c4be504d09b2af4b5a3a735de35307c87`.
Readiness reference: `.local/preflight/harness-exposure-v2-readiness.json`.
Current check record: `fresh-observation-offline-v1/f0e4ff0-freeze-review.json`.

The freeze command now rechecks the complete readiness source map, both pacing
and exposure validation files, all referenced artifact hashes, current runtime
provenance for the Chaos executions, unique Chaos sessions, and saved grader
results. It reruns the Tricky acknowledgment and receipt audit, preserving null
exposure semantics, and replays all 16 Chaos contracts. This is read-only review
of the newly supplied browser evidence, not another browser execution or a claim
about a currently listening process. A future live cohort still needs a selected
case and its live environment preflight.

The new Tricky contract is `policy-input-ack-v2` / verifier version 2. Exposure
requires the inserted warranty in the selected decision observation, retained
messages matching that observation, and backend completion before the first
checkout. Failed or unmatched attempts preserve unknown exposure; capture and
HTTP dispatch are not treated as completion acknowledgment. DEV-W01 avoidance
remains null because the warranty is authorized.

Run the focused checks and recheck the frozen profile:

```bash
.venv/bin/python -m pytest -q data/curation/test_fresh_pilot.py tests/test_runner_pacing.py tests/test_policy_exposure.py
.venv/bin/python data/curation/prepare_fresh_pilot.py
```

The earlier freeze refusal is retained in `adoption-status.json`; its pending
status describes that earlier attempt, before the renewed source validation.
No prior profile existed, so this is the first successful freeze in this
protocol directory. Historical calibration profiles, labels and ledger totals
remain unchanged. There is still no real `budget.json` in this new directory.

Remaining limits: Chaos's blur/in-flight guard and seeded arithmetic bugs are
unfixed. The verifier driver explicitly separates blur with Tab; its successful
cases do not establish that a direct model save click will work. Transient
controls can still expire during inference. The profile selects no benchmark
case, leaves training/curation readiness false, and provides no live CLI option.
