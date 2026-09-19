# Expanded tasks in the team worker

This increment connects the private 203-task registry to the same task factory
used by local validation. The public catalog contains objectives and attribution;
it does not contain private grading inputs. Availability requires an exact task
revision advertised by a live, locally certified worker. Catalog presence alone
never enables execution.

## Runtime boundaries

- The existing 14 externally sourced tasks retain their certified runtime. New
  `tricky:*` and `webarena:*` jobs execute in an isolated source process, packaged
  by `scripts/package_expanded_worker.py` and built with
  `deploy/worker/Dockerfile.expanded`.
- `data.curation.worker_integration.tasks.make_task` is the shared setup/grading
  entrypoint. `intent_browser.expanded_tasks.runner_options` selects the same
  native tool profile and each binding's goal, terminal instruction, context
  bound and step limit. No model calls are made by integration checks.
- Dedicated WebArena shopping/forum clones are leased through
  `scripts/worker_site_service.py`. They are separate from manual browsing and
  shared research instances. Release resets the complete application/database;
  failed reset quarantines the slot. Service authentication and proxy credentials
  are never policy inputs.
- Browser and private HTTP reads use the same lease and canonical origin.
  Private state operations are fixed per contract; no arbitrary SQL, URL fetch
  or caller-selected baseline is exposed.
- Native WebArena HAR evaluation runs in a separate pinned dependency environment
  **after browser close**. `finalize_task_run` records an exclusive authoritative
  result before trace ZIP/terminal publication. Earlier runtime evaluations remain
  unchanged. Grading failures retain unknown safety; they do not fall back to a
  claimed success.
- Task-specific execution ceilings apply to expanded tasks only. Reservations use
  the complete serialized request (including native schemas/history), with the
  actual output ceiling. Existing shared budget limits remain in force.

## Acceptance and current limits

Local dispatcher checks cover positive/negative Tricky runs, full ZIP membership
and byte equality, and a simulated transport failure with unknown safety.
Dedicated lease tests cover browser/private HTTP access, identity, reset and
credential absence. Curation validates representative task families, not 203 new
model episodes. This is development integration, not a benchmark score or training
readiness claim.

Cold WebArena navigation can exceed five seconds after the click has taken effect.
A controlled six-second native navigation test verifies an explicit 30-second
action deadline completes with one click; the old five-second case remains a
recorded timeout. The new deadline is selected in a new certificate/profile, with
no automatic replay, force click or hidden warm-up.

Magento controls may appear before their JavaScript handlers become effective.
The retained wishlist negative control succeeds with an ordinary recorded `noop`
while delivered AX reports busy. A separate worker page-size control changed the
select but did not navigate or change the table, even after one recorded wait;
that check remains a failure. These observations do not justify silently retrying
mutating actions or claiming that all readiness problems are solved.

## Reproducible entrypoints

- `scripts/verify_expanded_navigation.py`: offline two-deadline browser boundary.
- `scripts/verify_expanded_worker.py`: actual worker dispatcher and portable
  archive checks with trusted scripted transport; supports explicit failure mode
  and dedicated WebArena service arguments. Never reads real model credentials.
- `data/curation/worker_integration/verify_tricky.py` and `verify_webarena.py`:
  shared adapter family checks. Preserve historical outputs; use a new directory
  for every run/amendment.
- `tests/test_expanded_tasks.py`, `test_task_finalization.py`, `test_worker_sites.py`
  and `test_team_worker.py`: registry/certificate, finalization, proxy and broker
  boundaries. Daylight broker checks are in `deploy/daylight/tests/harness.test.mjs`.

Deployment remains a separate acceptance step. Do not restart manual clones,
reuse a manual lease, replace historical certificates, or advertise expanded IDs
before a certificate and the corresponding container checks are complete.
