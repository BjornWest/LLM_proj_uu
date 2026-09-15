# Team interface to the actual BrowserGym harness

Open **https://browseragent.vercel.app/harness** with your existing invitation.
Jobs run on the PC's Python/Chromium worker, calling the existing `run_episode`,
observation adapter, action parser, model backend and task verifier. The older
browser-side demo remains separate at `/`.

Choose study rooms or the repaired Chaos newsletter task. Watch actual browser
screenshots and actions; select a step to read its exact decision observation
and attach feedback. Completion, authorization and safe success include unknown
values. Download the original trace ZIP, including exact requests/responses,
observations, screenshots, lifecycle and verifier evidence. Extract it beside
local runs to view it using `common_agent_util`.

Invitations see their own jobs and artifacts. Feedback records the episode,
step, artifact names and runtime version; it never enters policy inputs or
changes verifier labels. The model receives AX text, not screenshots. Search is
disabled. Study-room custom requests work in live mode, but only the exact
example has a deterministic verifier; other goals show unknown verification.
Chaos uses its fixed trusted goal and current build certificate. Rehearsals use
explicitly scripted decisions and fixed goals, with no model calls.

## Configuration and running

Add `HARNESS_WORKER_TOKEN` from ignored `.local/team-worker/vercel.env` to Vercel
Production and redeploy. This is the only additional Vercel secret. The existing
invitation login and Private Blob connection remain in use. Machine endpoints
require that token; human endpoints still require an invitation session.

Dedicated local settings already exist in `.local/team-worker/worker.env`.
For a new workstation, generate them with:

```bash
.venv/bin/python scripts/setup_team_worker.py --url https://browseragent.vercel.app
```

This refuses existing configuration. Edit existing files locally instead of
regenerating credentials. Only the dedicated demo key and model/provider
settings are copied; HF, Verda, Parallel and calibration secrets are excluded.
Never paste either environment file into chat or commit it.

See [container instructions](deploy/worker/README.md). The reviewed Chaos copy
is already exported to `.local/team-worker/chaos`; do not export over it.

```bash
docker compose -f deploy/worker/compose.yaml -f deploy/worker/compose.chaos.yaml up -d --build
docker compose -f deploy/worker/compose.yaml -f deploy/worker/compose.chaos.yaml logs --tail 50 worker
```

The non-root worker needs no GPU or inbound ports. Persistent `worker-data`
contains originals in `/data/runs` and publication records in `/data/jobs`.
The separate Chaos bind mount stores isolated fixture state. Do not use
`down -v`, which deletes retained worker data. `HARNESS_MODE=live` uses the model;
`rehearsal` uses scripted decisions. Recreate the container after env changes.

For direct WSL use, stop the container first, set `HARNESS_CHAOS_BUILD` to the
local copied build, then run:

```bash
.venv/bin/python -m intent_browser.team_worker --env-file .local/team-worker/worker.env
```

The same image, protocol and backed-up volume can move to a CPU server later.
Moving hosts is a new runtime provenance boundary, even with identical sources.

## Lifecycle, costs and limitations

One worker processes one episode at a time. Queued jobs wait while it is offline.
An active job with no contact for two minutes is interrupted, never automatically
replayed. Local originals survive failed cloud publication. In-flight actions
cannot be undone by disconnection. Closing the viewing tab does not stop the
worker; the PC must remain awake with Docker running.

Live requests share the existing demo's daily reservation ledger and
`DEMO_DAILY_BUDGET_USD` / `DEMO_DAILY_CALL_LIMIT`, plus the dedicated key's
OpenRouter cap. Each job has at most 12 requests and 512 output tokens per call.
Failures/unknown costs retain their reservations; inference is never retried
automatically. One routing session ID per episode uses the configured allowlist.
Reported costs, unknown attempts and cost/provider alerts remain separate.
Pacing precedes fresh observation; leases are rechecked before inference and
before returning an action to the runner.

The small control plane retains 100 jobs and 50 notes per job, with no automatic
deletion or administrator archive UI. Artifact uploads are bounded; original
archive parts stream on download. Screenshots update after completed steps.
Rich sidebar chat, browser takeover, simultaneous workers and more benchmark
selectors are subsequent work.

## Validation

```bash
.venv/bin/python -m pytest -q tests/test_team_worker.py
cd deploy/daylight
npm run build
npm test
cd ../..
.venv/bin/python -m scripts.smoke_team_worker --chaos-build .local/chaos-fifo-xor32-v2
```

Actual worker/BrowserGym integration passes 101 checks for both tasks: independent
verification, original archive bytes, step feedback, evaluation before close and
cross-invitation denial. The container also passes with external networking
disabled, random credentials and zero model calls. Current image/source evidence
is in `.local/team-worker/container-final-11dca758/`. Historical reports remain
unchanged. These are transport/harness tests, not model-performance results;
training eligibility and calibration profiles/budgets are unchanged.
