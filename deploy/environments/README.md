# Portable web environments

The environment runs on the PC or a rollout instance. Vercel, OpenRouter,
Parallel, Blob and the team queue are **not required**. Browsers talk to local
fixture servers; graders and traces stay in the same runtime.

This is packaging and execution infrastructure. It does not yet add manually
clickable dataset iframes to the Vercel workspace.

| Family | Packaged scope |
|---|---|
| Campus | Study rooms, shop and preferences; existing server-state verifier |
| Browser Agent Chaos | Seven reviewed tasks; copied FIFO/xorshift build and existing grader |
| TrickyArena | P07 shopping, P10 privacy, P11 membership, clean/injected conditions |
| Synthetic development | DEV-W01 authorized warranty, with its separate contract |
| MiniWoB | 125 registered BrowserGym tasks and local assets; native rewards, no authorization claim |
| SusBench | IKEA source/callback diagnostic only; full benchmark and transaction verifier unavailable |
| DoomArena | Explicitly not integrated; an attack layer rather than a standalone website |

No package changes historical source files, goals, grades, training eligibility,
or certificates. New executions record a package fingerprint. Full upstream
Tricky sites and full SusBench are not implied by these adapted fixtures.

## Prepare once

Commands run from the repository root. Use existing reviewed local caches:

```bash
.venv/bin/python scripts/prepare_environment_resources.py
.venv/bin/python -m intent_browser.environment_package export \
  --output .local/environment-packages/my-package \
  --fixtures .local/team-worker/fixtures-v1 \
  --chaos .local/chaos-fifo-xor32-v2 \
  --miniwob .local/miniwob-plusplus
```

If the font cache is absent, run `scripts/prepare_environment_resources.py
--fetch` using the project Python **during preparation**. It restores 40 pinned
files (~4.9 MB), including the SIL Open Font License. Changed responses fail
hash verification. Export/startup never download anything. Dataset caches and
BrowserGym/Chromium must likewise be prepared before offline execution.

The package contains copied Python adapters and graders, exact reviewed fixture
assets/private contracts, materialized Chaos Node dependencies, MiniWoB assets
and its adapter, pinned fonts, and a complete size/hash manifest. It excludes
credentials, previous sessions, model weights and run directories. Existing or
dangling output paths are rejected; create a new package for any revision.

The **package is private harness input, not a web root**. It contains privileged
contracts. Only explicit fixture asset routes may be exposed to a browser.

## Container execution without internet

```bash
docker build --pull=false -f deploy/environments/Dockerfile \
  -t intent-browser-environments:local .
```

The default base is the already prepared `intent-browser-worker:hosted-v1`
image, including Python 3.12, Node, BrowserGym and Chromium. The small environment
image installs nothing. If the base is missing, prepare it using
`deploy/worker/Dockerfile` while networking is available, or transfer it with
Docker save/load. Keep the tested image ID with the package acceptance record.

Set `ENVIRONMENT_PACKAGE` and `ENVIRONMENT_OUTPUT` to absolute paths. Output must
be a writable **parent** directory for UID 10001; each run uses a new subdirectory.
The package is read-only.

```bash
docker compose -f deploy/environments/compose.yaml run --rm environments

# Positive scripted episodes across the supported fixture families:
docker compose -f deploy/environments/compose.yaml run --rm --entrypoint python \
  environments /package/runtime/scripts/verify_environment_package.py \
  --package /package --output /output/positive

# Optional broad MiniWoB load/observation check (not solving all tasks):
docker compose -f deploy/environments/compose.yaml run --rm --entrypoint python \
  environments /package/runtime/scripts/verify_environment_package.py \
  --package /package --output /output/miniwob-load --miniwob-load-all
```

Compose uses `network_mode: none`; loopback inside the container still works.
It has a read-only root filesystem, a writable temporary directory, no Vercel
credentials, no published ports, and no connection to the running team worker.
Negative acceptance uses `--negative --task TASK_ID` for the reviewed Chaos and
Tricky/DEV-W01 selectors. Diagnostic drivers are privileged scripts, not agents.

For transfer, copy the package and save/load the tested image:

```bash
docker save -o environments-image.tar intent-browser-environments:local
# On the other machine, after transferring these files:
docker load -i environments-image.tar
```

No repository checkout or original absolute source path is needed at runtime.
Image/CPU architecture must match the destination. Model weights/runtime are a
separate preparation concern; GPU access is not required by these websites.

## Use the same harness with a model backend

Run a new Python process with `PYTHONPATH=/absolute/package/runtime` and
`PYTHONDONTWRITEBYTECODE=1`. Use the package's code, not another checkout's
adapter revision. Supply any backend implementing the existing `complete`
interface:

```python
from intent_browser.environment_runtime import EnvironmentRuntime

with EnvironmentRuntime('/package', '/output/new-rollout') as runtime:
    with runtime.session('tricky-p07-clean') as session:
        directory, result = session.run(backend, max_steps=12, seed=42)
```

`session.run` uses the existing runner, exact task goal, observation adapter,
action parser, trace logger and independent verifier. It refreshes observations
after the backend's optional readiness/pacing hook. This also handles controls
rendered during initialization after the first reset observation. Evaluation
happens before the browser closes. The caller owns the backend's lifecycle.

Use one synchronous session per process; multiple rollout processes get separate
state/output directories. A local model can run in the same network namespace,
or use an isolated internal container network for environment/model containers.
That requires local network traffic, but no internet traffic. Do not enable
hosted inference or search when claiming an offline rollout.

## Evidence and limitations

Each episode keeps normal raw traces and `package-network.json`, including
fixture requests and external font URLs fulfilled from bundled bytes. This is
not a live font fetch. The original Chaos CSS remains unchanged; the added font
cache is a new, fingerprinted rendering dependency. Do not infer pixel parity
with older traces that may have used a fallback font.

The browser guard preserves existing stricter fixture route checks. Container
network isolation supplies the stronger no-internet boundary, including Node
and browser background traffic. Browsing and grading require no publication.
Traces can be uploaded later by the separate trace-library tooling.

Consult `config/environment_package_validation.json` for the exact tested
package/image and retained reports. Native MiniWoB success remains separate
from unknown authorization; IKEA radio callbacks remain separate from purchases.
Interrupted/failed episodes retain their errors, not invented success labels.
