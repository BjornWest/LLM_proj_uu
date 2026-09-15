# External objectives and verifiers in the team harness

Deployed on 2026-09-15 at https://browseragent.vercel.app/harness from
commit `bb0e787`. All fifteen task choices are advertised by the live PC
worker. This is an end-to-end worker integration, not just static page hosting.

The private dispatch registry at `config/team_tasks.json` adds fourteen
conditions alongside the existing study-room demo:

- Seven reviewed Chaos tasks, using a fresh generated objective per session.
- Tricky P07 shopping, P10 privacy/cancellation and P11 music membership, each
  in clean and injected conditions with identical paired trusted goals.
- DEV-W01, a separately identified synthetic authorized-warranty task.

The Vercel broker projects only task display fields and an immutable revision.
The worker checks the requested revision, constructs the existing adapter,
initializes the fresh environment, runs the existing BrowserGym loop, evaluates
before close, and publishes the original evidence/archive. Fixed goals cannot
be changed by submitting another goal. Generated Chaos goals start as pending;
the actual reset observation's resolved goal becomes the immutable displayed
job objective. No sample target is substituted for the session's descriptor.

Tricky retains its exact adapter routes, journal, hydration, reset, exposure
and verifier hooks. In particular, the publication wrapper does not shadow the
adapter's stricter route handler with a general origin-only network rule.
The underlying host adapters, runner and reviewed builds are unchanged.

## Portable packaging

`deploy/worker/prepare_tasks.py` builds the registry from the private curation
catalog and exports reviewed fixtures without downloads or overwrites:

```bash
# These commands require fresh output paths; review a new registry before
# deliberately replacing the checked-in configuration in a later revision.
.venv/bin/python deploy/worker/prepare_tasks.py registry --output /tmp/new-team-tasks.json
.venv/bin/python deploy/worker/prepare_tasks.py export --output /tmp/new-team-fixtures
```

The current export is `.local/team-worker/fixtures-v1`: 77 exact asset,
build-manifest, catalog, task-manifest and contract files. It contains no
running session state. Its `package.json` binds it to the registry hash.
Private task/grader inputs are mounted only into the worker, never copied to
the Vercel public directory. The original full trajectory may retain grader
evidence for authenticated review, separately from policy messages.

The optional `deploy/worker/compose.fixtures.yaml` mounts this export read-only
and sets `HARNESS_FIXTURES_DIR`. The existing optional Chaos mount remains a
separate copied process/state directory. Each Tricky episode constructs its
own isolated server and journal. These websites are initially worker-hosted;
Vercel provides selection, viewing, results and downloads. Relocating page
assets to Vercel requires a later version and semantic parity tests.

New task capabilities are advertised only when the local package and verifier
sources pass checks. Ordinary rehearsal mode still advertises only the two
installed example policies. The acceptance script's explicit privileged
drivers are not exposed as a general policy or queued code-execution option.

## Acceptance and rollout

Focused checks:

```bash
.venv/bin/python -m pytest -q tests/test_hosted_tasks.py tests/test_team_worker.py
cd deploy/daylight
npm test
```

Scripted transport/semantic checks use a separately exported Chaos copy and a
fresh output directory:

```bash
.venv/bin/python -m scripts.verify_hosted_worker \
  --fixtures .local/team-worker/fixtures-v1 \
  --chaos-build .local/team-worker/chaos-hosted-acceptance-v1 \
  --output /tmp/new-hosted-worker-validation
```

Each of fourteen conditions runs a positive and a negative script through the
real worker and authenticated local HTTP broker. Checks include expected safe
success, fixed/generated objective identity, revision, original ZIP bytes,
screenshots, decision text and grading before close. The scripts reuse existing
privileged verifier-test drivers and make zero model requests. They validate
the transport and selected contracts, not learned behavior or all possible
failure cases. Duplicate-warranty and historical-effect regression coverage
remains explicitly distinct from this initial positive/negative pair.

First local acceptance: `.local/team-worker/hosted-acceptance-v1/report.json`,
28 cases and 364 checks passed. The candidate image is separately tagged
`intent-browser-worker:hosted-v1`; a network-disabled container suite runs the
same scenarios with a different isolated Chaos copy. All 28 container cases
and 364 checks passed too; evidence is under
`.local/team-worker/hosted-container-acceptance-v1/`. Completion, authorization,
safe-success and exposure outcomes match. Two negative Chaos cases retain
different generated record IDs in their forbidden-action evidence; these are
fresh variants, not identical session descriptors. Neither these local
results nor an image build imply production readiness.

Before rollout, coordinate the backend and UX commits, verify the candidate
container results, and wait for the current production job to finish. Preserve
the data volume, then switch to the reviewed image/fixture mount and verify
authenticated configuration and trace retrieval on the deployment. Do not
restart the host curation server or alter its frozen build. Team runs continue
using the dedicated Daylight key and demo ledger, separate from curation funds.
No new paid test is required by this acceptance procedure.

## Production rollout evidence

The coordinated release passed 49 read-only production checks: all fifteen
capabilities available, exact task revisions/goals, private registry fields
excluded, five UI assets matching the committed build, and historical ZIPs
retained byte-for-byte. Chromium loaded the production UI, switched task
selection and entered replay with no writes or JavaScript errors. The worker
was idle when switched; its data volume and two existing runs were preserved.
The active curation sweep's 103 pinned files still match.

`config/hosted_worker_rollout.json` records this separate deployment evidence.
No new agent episodes or inference calls were made on production for this
check. The 28 local and 28 container scripted episodes remain the execution
evidence for the fourteen external conditions; this does not claim that each
condition has completed a production model run. The earlier candidate
validation record remains unchanged.
