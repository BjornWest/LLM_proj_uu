# Repeatable local browser reproductions

Eight fresh scripted browser runs reproduced both known failures twice, and
both corresponding controls succeeded twice. All 72 baseline assertions passed;
a separate saved-evidence audit also passed for all eight traces. No model or
search API calls were made. This establishes repeatable bug evidence, not a fix
or a model pass rate.

| Case | Scripted sequence | Observed in both repetitions |
| --- | --- | --- |
| Expired notification target | Add one laptop/warranty pair; take Close ID from the exact supplied observation; wait 10 seconds; click that ID | The target was present before the wait and absent afterward. Exactly one missing-element error; one pair remains in the cart; zero checkouts. |
| Observation refresh control | Same addition and wait; `noop()` lets the existing runner capture a new observation; open cart; checkout | New observation has no Close notification. One authorized checkout, no browser action errors. |
| Blur/save collision | Fill workspace name; click the safe save button directly | No browser action error, but server receives only the name input during that click; zero commits; task incomplete. |
| Separate blur/save control | Fill name; Tab from name; Tab from readonly owner; click safe save | Name input precedes exactly one safe commit; authorized completion, no browser action errors. |

Every run uses a fresh browser environment; all four Chaos sessions are distinct
and have one mount each. The scripted terminal message is fixed test scaffolding,
including in deliberately incomplete cases. It does not claim the task completed.
All traces remain privileged scripted development evidence and training-ineligible.

## What this establishes

The notification experiment confirms that an ID genuinely delivered to the agent
can expire during an added wait. It selects the ID before waiting, rather than
finding a fresh DOM target afterward. The unchanged fixture removes notifications
on its own timer; the driver does not delete or replace elements.

The control changes both observation timing and the subsequent action selection:
it supplies a new observation, then the script selects the persistent cart link.
It demonstrates a workable control path, not that refreshing alone will fix the
model's repeated-add behavior. The extra `noop()` is a visible scripted control;
it is not a production pacing implementation. The 10-second delay uses
`page.wait_for_timeout` to pump browser events, rather than invoking the paid
wrapper or a fake inference request.

The Chaos result no longer depends on interpreting a model trace: prescribed
fill-and-click actions reproduce the missing commit on two newly generated task
instances. Read-only server snapshots show no input before blur; the input then
arrives within the save click's tool interval. Final server events still contain
no commit. The installed frontend's shared in-flight guard remains the supported
cause; this test does not instrument that particular JavaScript branch. The
control flushes blur from both the editable name and readonly owner field, as the
existing verifier script does. It performs only one save click.

The scripts preserve raw outcomes and do not repair or automatically retry an
action. The original runner, backend, graders and fixture sources were unchanged
throughout the suite. Passing this baseline suite means it detected the known
failure behaviors; a future repair should change these expectations under a new
source revision and preserve this report.

## Reproduce and audit

Run from `/home/bjorn/code/LLM_proj_uu`, with the existing local Tricky build and
Chaos server available:

```bash
.venv/bin/python data/curation/reproduce_browser_issues.py --repeat 2 --chaos-base-url http://localhost:45379
```

The command writes a new timestamped report under
`data/curation/browser-reproductions/` and normal traces under `runs/`.
`--case stale-close`, `--case refresh-after-wait`, `--case blur-and-save`, or
`--case separate-blur-save` narrows the run. No credentials are needed. A
precondition failure or changed behavior produces a nonzero result and retains
the evidence. This is a timing-sensitive browser test: two repetitions establish
observed repeatability here, not determinism on every host.

Review the saved evidence without a browser or model:

```bash
.venv/bin/python data/curation/audit_browser_reproductions.py data/curation/browser-reproductions/20260914T231919Z-ffb41302/report.json
```

The audit checks artifact hashes, exact supplied Close IDs, action sequences and
errors, server event ordering, checkout counts, distinct sessions, authorization,
and evaluation before browser close. It checks raw evidence instead of trusting
the report's `passed` field. Original hashes remain historical provenance; it does
not require the current checkout to match historical runtime source.

## Evidence

- Suite: `data/curation/browser-reproductions/20260914T231919Z-ffb41302/report.json`.
- Saved audit: same directory, `saved-evidence-audit.json`.
- Runner SHA256: `4f33bb79c759de46ce45b5cdbf41ab3fc565f569017144022bc685f35f6838c8`.
- Chaos installed CLI SHA256: `0271f4aba16401862247244be943194d96c2e5902529a8e3a9a7547b586352b1`.
- Each trace retains exact observations/actions, screenshots, video, final
  evaluation, fixture provenance, and journal or server event evidence.
- The suite fingerprints its own driver and shared Python sources and checks
  they remain unchanged. Raw build records retain Tricky fixture provenance.
- BrowserGym 0.14.3, Playwright 1.44.0; headless, Tricky adapter slow_mo 100,
  Chaos slow_mo 250; maximum eight scripted steps per run.

| Case | First trace | Second trace |
| --- | --- | --- |
| Expired Close | [20260914T231919Z-c6fefc34](http://localhost:8878/#22e1d73d9d5fea67c24d) | [20260914T232002Z-24f0d5fb](http://localhost:8878/#efa5bbc75622766e7209) |
| Fresh observation control | [20260914T231935Z-d9ba7a69](http://localhost:8878/#2cf4b2fb8996356267b3) | [20260914T232017Z-c4dfd1a0](http://localhost:8878/#94f0b5940ad85f93c088) |
| Dropped save | [20260914T231952Z-889622b5](http://localhost:8878/#0259501dfe441c4347f0) | [20260914T232035Z-a56b5711](http://localhost:8878/#7481edf62aa5d9087b2f) |
| Separate blur control | [20260914T231956Z-b4332f25](http://localhost:8878/#e1f0b5c94610151bf607) | [20260914T232038Z-0544d61b](http://localhost:8878/#9e4f66eb6b1da732d061) |

## Next shared implementation work

The harness agent owns a pacing hook before fresh observation capture and prompt
construction, with distinct wait/request timing. Its acceptance tests should
establish ordering: wait, fresh observation, exact prompt, fingerprint check and
reservation, one dispatch. Errors and request attribution must survive; no
invisible policy-action retries or privileged grader data in prompts.

The environment agent owns a separately versioned Chaos form repair. Its target
is that the direct fill-then-save sequence records the correct input before
exactly one commit, without requiring a second policy click. Revalidate the
relevant graders against the changed fixture; do not rewrite historical runs.

Curation owns these reproductions, saved-evidence checks, and a newly frozen
wrapper/cohort after the shared fix. No new model run is necessary to implement
or check the first repairs. Existing calibration reservations remain unchanged
at $0.64922375 of the $3 authorization.
