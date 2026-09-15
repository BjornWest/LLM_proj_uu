# PC-hosted BrowserGym worker

This container runs the repository's Python harness and headless Chromium on your
PC. It polls the private Vercel deployment for work and sends back episode updates
and artifacts. Vercel supplies the shared interface; it does not execute
BrowserGym. There are no inbound ports, router changes, browser windows, or GPU
requirements. One worker processes one episode at a time.

The same image, environment file and durable data volume can later move to a
Linux server without changing the frontend protocol. The PC must remain awake
and Docker Desktop must be running for teammates to start work.

## Setup on this workstation

Docker Desktop's WSL integration is enabled on this workstation; Docker 25.0.3
and Compose 2.24.6 were checked. On a new workstation, enable Settings →
Resources → WSL Integration for the Ubuntu distro, then reopen the shell.
Both commands must work before proceeding:

```bash
docker version
docker compose version
```

The dedicated configuration already exists on Bjorn's workstation. On a new
workstation, generate it from the repository root:

```bash
.venv/bin/python scripts/setup_team_worker.py --url https://browseragent.vercel.app
```

Edit that file locally; do not copy the project's full `.env`. It needs:

```dotenv
HARNESS_URL=https://your-production-project.vercel.app
HARNESS_WORKER_TOKEN=replace-with-the-server-worker-token
HARNESS_MODE=rehearsal
HARNESS_POLL_SECONDS=5
MODEL_NAME=qwen/qwen3.8-27b
OPENROUTER_PROVIDERS=chutes,dekallm,phala,parasail,akashml,ionstream,cloudflare
OPENROUTER_MAX_TOKENS=4096
```

`HARNESS_URL` is the deployment origin, without `/login` or another page path.
Use the same worker token configured on Vercel, never an invitation code. That
token authenticates the worker and must stay out of frontend code and shared
screenshots. See the shared-harness setup guide for the server-side configuration.

Start with `HARNESS_MODE=rehearsal`: it exercises the actual BrowserGym/action/
trace path with scripted decisions and makes no inference calls. For model
episodes, explicitly set `HARNESS_MODE=live` and add the existing dedicated demo
key as `DAYLIGHT_OPENROUTER_API_KEY`. Keep the demo's key and spending limit
separate from calibration credentials. No Parallel key is needed for these
controlled tasks.

Build and start from the repository root:

```bash
docker compose -f deploy/worker/compose.yaml build
docker compose -f deploy/worker/compose.yaml up -d
docker compose -f deploy/worker/compose.yaml logs --tail 100 -f worker
```

The first build downloads Python/Node base images, Python packages, Chromium and
its system libraries; expect several hundred MB or more. The image installs
Chromium only, not Firefox or WebKit. Credentials are supplied when the container
starts and are never build arguments or image layers. Avoid pasting expanded
`docker compose config` output into chats: it can contain env-file secrets.

After editing the dedicated environment file, recreate the worker so it receives
the new values:

```bash
docker compose -f deploy/worker/compose.yaml up -d --force-recreate
```

## Storage, stopping, and moving hosts

The named `worker-data` volume is mounted at `/data`, owned by the runtime's
non-root UID/GID `10001:10001`. Local traces and worker state survive container
replacement and `docker compose down`. Review notes do not rewrite those traces.
Do not use `down -v` unless you intend to delete the retained data.

```bash
docker compose -f deploy/worker/compose.yaml stop
docker compose -f deploy/worker/compose.yaml start
```

To move to a server, build or transfer this image, securely supply the dedicated
environment file, and back up/restore the named volume. Run one worker against
this data directory; do not share its writable files between machines. Keep the
worker token and demo key server-side. Switching machines is a new runtime
provenance boundary, even when source files are identical.

## Optional certified Chaos fixture

Study-room assets are included in the image. Chaos is deliberately **not** fetched
with `npx` or bundled from `.local` during a build. Export the already reviewed
local build into a new directory:

```bash
python3 deploy/worker/export_chaos.py \
  --source .local/chaos-fifo-xor32-v2 \
  --output .local/team-worker/chaos
```

The exporter checks the source manifest, preserves exact package/dist bytes,
materializes cached dependency symlinks, and verifies the resulting bytes and
unchanged source. It excludes old state, process IDs, server logs and sessions.
It refuses existing or dangling output paths, escaping dependency links and
directory cycles. It makes no download or certificate changes. A failed partial
export is left for inspection and also cannot be overwritten automatically.
`export-report.json` records the copy; it is not browser-readiness evidence.

Give the **exported copy only** to the container's runtime user, then start the
worker with the optional override. The one-time `chown` runs as root inside a
short-lived container and changes ownership only under the new Chaos bind mount;
the normal worker remains non-root:

```bash
docker compose -f deploy/worker/compose.yaml -f deploy/worker/compose.chaos.yaml \
  run --rm --no-deps --user 0 --entrypoint chown worker -R 10001:10001 /data/chaos
docker compose -f deploy/worker/compose.yaml -f deploy/worker/compose.chaos.yaml \
  up -d
```

The override mounts `.local/team-worker/chaos` at `/data/chaos` and sets
`HARNESS_CHAOS_BUILD=/data/chaos`. The worker starts this local copy with Node;
the certificate is checked before a Chaos episode proceeds. No additional host
port is opened. Keep the override on subsequent Compose commands while using
Chaos. Never mount the original running build, the full repository, `.env`, or
the npm cache into the worker.

The bind explicitly uses `rprivate` propagation. This Docker Desktop/WSL setup
rejected Compose's implicit propagation with a "not a shared mount" error;
the explicit private setting starts correctly without changing host mounts.

Until the exported copy passes readiness in the actual container, use the
study-room task. Successful copying or image construction does not establish
Chaos browser readiness. Relocation gets new process/session/runtime provenance;
the original certificate and historical traces are left unchanged.

## Version and validation boundaries

`requirements.txt` pins direct dependencies to the local harness, including
BrowserGym core `0.14.3` and Playwright `1.44.0`. The matching Playwright installer
downloads its own Chromium revision. Python is `3.12` on Debian Bookworm, and
Node is from the `22-bookworm-slim` image. Direct package/browser versions are
pinned; base-image patch levels and transitive dependencies are not a complete
reproducible lock. Saved episode provenance identifies the actual runtime.

Upstream's [Playwright Docker guide](https://playwright.dev/python/docs/docker)
documents matching the browser and Python package versions, installing system
dependencies, and using an init process. The checked local Playwright 1.44
dependency table supports Debian 12. This image uses that Chromium-only path,
an init process and a private 1 GB shared-memory segment. It runs as a non-root
user with no added capabilities. This is a local-fixture development worker;
the container is not a certification for browsing arbitrary hostile websites.

**Container build/run status:** the image builds on Docker Desktop/WSL, and
Compose validates with a dedicated dummy environment file. A network-disabled
container ran the existing BrowserGym smoke task as UID `10001` with the same
capability restrictions as Compose: three scripted decisions, zero action
errors, saved screenshots/observations and a nonempty video. No model request
was made. The installed browser is Chromium `125.0.6422.26` (revision `1117`),
and Node is `22.23.2`. Runtime inspection confirmed that excluded credential,
cache, research and historical-run paths are absent and `/data` is writable.

The basic smoke record is `.local/team-worker/container-smoke-report.json`; its
artifacts and image ID describe the build at that point. A subsequent container
integration also ran the actual worker against an isolated local HTTP broker,
with study-room and certified Chaos confirmshaming episodes: **101 checks pass**.
Both independently verified safe successes, remote images/decision text,
step-linked feedback, exact trace-download bytes, evaluation-before-close and
cross-invitation access denial were checked. Feedback remained outside policy
inputs. The container had no external network or real credentials and made zero
model calls.

The final integration record is
`.local/team-worker/container-final-11dca758/report.json`; the adjacent
`container-validation.json` records image/source boundaries and confirms the
tested sources remained current after the run. Its image ID is
`sha256:b55971af62447ad5d2cc4f3772b8652835684c2d0ed981647ca08ee45276c201`.
The earlier `.local/team-worker/container-integration-cb5fab49/report.json`
remains unchanged as historical evidence. This establishes
container worker/browser/local-broker integration, not access to the deployed
Vercel project. After changing the shared worker source, rebuild the image before
deploying it; the dependency/browser layers are cached.

To repeat only the offline browser check in the current image:

```bash
docker run --rm --init --network none --shm-size 1g \
  --cap-drop ALL --security-opt no-new-privileges:true \
  intent-browser-worker:local \
  python -m intent_browser.cli smoke --no-preview --output /data/smoke --video
```

That disposable invocation deletes its local artifacts when it exits. The
regular Compose worker uses the persistent volume described above.
