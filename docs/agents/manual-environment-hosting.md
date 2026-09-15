# Manual access to packaged environments

Status: implemented and locally validated; production acceptance is recorded in
`config/manual_environment_validation.json` after the coordinated release.

## What runs where

Vercel serves the authenticated workspace and proxies `/api/manual/*` to the PC
control service. The control service launches a separate headless BrowserGym
process per manual session, using the immutable portable environment package.
The browser receives screenshots and sends bounded native pointer/keyboard
commands. Dataset JavaScript and private grader state are not served under the
Vercel application origin. No model is involved in manual exploration.

The existing Watch path still creates a fresh model job on the worker. Campus
Ask retains its existing browser-side action loop. Manual exploration does not
hand its current browser state to either model runtime.

The same environment package can move to another Docker host with its local
assets, runtime and graders. The manual control service is an optional UI bridge;
local rollouts need neither Vercel, Cloudflare nor a per-action network service.
The package was tested with the container network disabled. The deployed bridge
has network access to answer authenticated requests; do not describe that
service as an OS-level network sandbox.

## Scope and important limits

- The registry exposes 14 existing variants: seven Chaos tasks, clean/injected
  P07 shopping, P10 privacy and P11 membership, plus separate DEV-W01 warranty.
  They are task fixtures, not the complete upstream benchmarks.
- Health navigation beyond the supported home/appointment routes can stop the
  session with a scope error. In particular, My Profile is outside the P10
  contract. Scheduling has no complete doctor catalog. Music is a membership
  fixture, not a full music/audio service. These limitations are not hidden by
  changing the underlying pages or expanding verifier claims.
- WorkArena remains an external ServiceNow research integration, not in this
  production catalog. MiniWoB and IKEA remain available through their existing
  local package interfaces; this release does not add them to the workspace.
- Two concurrent manual browsers across the service; one active session per
  invitation owner. Idle sessions close after five minutes; total session time
  is fifteen minutes; at most 100 native actions and 300 captured frames.
- Click coordinates must fit the presented screenshot. Keys use an explicit
  allowlist; inserted text is at most 1000 characters; scroll distances are at
  most 500 pixels per axis. No URL, JavaScript or arbitrary Python tool is exposed.
- Frames update after an action or explicit refresh. This is not continuous video.
  A current frame ID does not prove the underlying page has not animated since
  capture. Native navigation/control errors are retained without action replay.
- A hard process/host crash can leave a partial trace without a finished ZIP.
  The durable command record and files remain on the PC; the UI reports an
  interrupted session, not success. Completed sessions have authenticated ZIP
  downloads. A universal external/local trace importer remains separate work.

## Ownership, actions and evidence

Vercel derives the owner from the invitation cookie; body-supplied owners are
ignored. Manual RPC uses the separate control token, never the worker token.
Browser processes receive an explicit minimal environment with no model,
invitation or control credentials. Commands and acknowledgments use separate
private file descriptors; stdin is `/dev/null` so dataset CLIs cannot consume or
alter the browser command stream.

A command UUID and frame version are durably claimed before exactly one browser
dispatch. Concurrent requests, a stale frame or reuse of an ID for a different
payload are rejected. Repeating an acknowledged UUID returns recorded state
without another action. Unknown attempts are never replayed automatically. A
new service process marks previous unfinished sessions interrupted on discovery.

Trace metadata distinguishes `human` from `scripted_validation`. Native action
attempts, screenshots, raw DOM/AX, lifecycle, task state and driver/package
fingerprints are retained. An action already completed is written before a
later privileged state-capture error can stop the driver. No fake model requests,
noops or policy-input acknowledgments are fabricated.

`evaluation` and aggregate `success` stay null. Existing task graders run before
browser close only as `reference_evaluation`: the selected fixture goal was not
an independently authorized human-intent contract. Model AX exposure/avoidance
remain null because screenshot delivery does not establish model AX delivery.
The workspace marks manual sessions **Not graded**, even when an individual
reference diagnostic is true or false. Original grader artifacts are retained.

## Runtime setup and moving it

Use the existing PC SQLite/control service and the same verified package. Add
`deploy/control/manual.override.yaml` to the established Compose command, setting
`ENVIRONMENT_PACKAGE` to its absolute directory. The override mounts `/package`
read-only and adds the persistent `worker_manual-data` volume, writable tmpfs and
Chromium shared memory. It runs as UID 10001 with a read-only root filesystem.

Do not rebuild or overwrite the immutable package for this feature. Moving to a
GPU host means copying that package and persistent data, rebuilding the small
control image on the installed browser runtime and updating the control URL.
The model worker, model key and rollout configuration remain separate.

Before replacing the PC control container, verify there is no active worker job
or manual session. The worker shares its network namespace and must be recreated
after a control-container replacement; preserve its existing image and volumes.
The temporary tunnel process can remain connected to localhost:8894. Never run
`docker compose down -v` or reimport the historical database over live state.

## Reproducible validation

Run from repository root, with the already installed host browser libraries:

```sh
python3 scripts/test_manual_environment.py
npm --prefix deploy/daylight test
PLAYWRIGHT_BROWSERS_PATH="$HOME/.cache/ms-playwright" \
LD_LIBRARY_PATH="$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu" \
node scripts/verify_manual_sites.mjs .local/manual-sites/NEW-host-run
PLAYWRIGHT_BROWSERS_PATH="$HOME/.cache/ms-playwright" \
LD_LIBRARY_PATH="$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu" \
node scripts/verify_manual_boundaries.mjs .local/manual-sites/NEW-boundaries
.venv/bin/python scripts/smoke_manual_workspace_live.py
```

Each validation output must be a new path. The browser suite selects controls
from privileged saved AX bounding boxes solely for deterministic testing. That
selection is not supplied to users or models and does not show learned autonomy.
It intentionally clicks both authorized and unauthorized reference controls.

`deploy/daylight/tests/manual-server.mjs` provides an isolated actual handler,
SQLite service and native browser for UI checks, with only test invitation
credentials and no inference keys. It must never be used as the production
entrypoint. The test reports distinguish mocked UI checks from actual browser
execution. Earlier failed attempts remain as diagnostic artifacts, not passes.
