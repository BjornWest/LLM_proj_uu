# Laptop setup: harness and generated worlds on WSL

Setup handoff for a Codex agent on Bjorn's **Ubuntu/WSL laptop**. The goal is
world generation, local browser-agent development and trace viewing. Do not set
up Vercel, its backend, tunnels, imported datasets, training frameworks or model
weights. No local GPU is required for hosted inference. Generating and browsing
worlds needs no API credentials.

Run commands from the repository root unless stated otherwise. Keep the checkout
in the WSL Linux filesystem, e.g. `~/code/LLM_proj_uu`, rather than `/mnt/c/...`.
Create laptop-local resources; do not copy this PC's virtualenv, browser profiles,
Docker volumes, home paths or live-process configuration.

For the Raven side-panel demo only, go to
[Raven demo on the laptop](#raven-demo-on-the-laptop).

## 1. Install the Python/browser dependencies

Read `AGENTS.md`, inspect `git status`, and record `git rev-parse HEAD`. Pull with
`git pull --ff-only` only when clean; never discard laptop edits. This guide
targets committed runtime `27576b1` or a descendant.

Use Python 3.12. On an Ubuntu release providing these packages:

```bash
sudo apt-get update
sudo apt-get install -y git python3.12 python3.12-venv
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
.venv/bin/playwright install chromium
.venv/bin/playwright install-deps chromium
```

The lock already includes `-e .`, installing this checkout in editable mode.
Legacy Python adapters in the lock do not download their websites. Playwright's
system-dependency installer may require sudo. If Python 3.12 is unavailable,
inspect the Ubuntu version before changing system Python; the project supports
>=3.11,<3.14, with 3.12 used on this PC. Keep BrowserGym/Playwright pinned.

Explain the package/browser downloads before starting and follow the user's
download permissions. Node.js is unnecessary for this baseline. Docker is needed
only for the agent's isolated Python calculation tool, described below.

Initial **scripted, offline** browser check:

```bash
.venv/bin/intent-browser smoke --headless --no-preview
```

This tests browser/action/trace plumbing on a built-in page, with no model calls.
It does not certify the full current toolset or world grading. Start headless to
avoid stealing focus; native browser windows are optional.

## 2. Install tokenizer assets, not model weights

The standard harness needs both `tokenizer.json` and adjacent
`chat_template.jinja` for AX/request token budgeting, even with hosted inference.
Local estimates are not an exact promise about provider billing.

Either copy those two non-secret files from this PC's
`training/.cache/qwen38-tokenizer/`, or download only the pinned files below
(roughly 13 MB total). They are public; no HF token or full model snapshot is
required. Pins also appear in `training/research/tokenization-validation.json`.

```bash
.venv/bin/python - <<'PY'
import hashlib
from pathlib import Path
from urllib.request import urlopen

revision = '1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0'
base = f'https://huggingface.co/Qwen/Qwen3.8-27B/resolve/{revision}/'
expected = {
    'tokenizer.json': '0997f410c57a1f4e53b09e4be8f4a172d90edd9564368fb0847030937229b9f3',
    'chat_template.jinja': 'c3cf9e34abf4f9e36c2d72165aa9c132d3e2a725b6c2586aaa3a8af9d7a81041',
}
root = Path('training/.cache/qwen38-tokenizer')
root.mkdir(parents=True, exist_ok=True)
for name, digest in expected.items():
    path = root / name
    if path.exists():
        content = path.read_bytes()
    else:
        with urlopen(base + name, timeout=60) as response:
            content = response.read()
    assert hashlib.sha256(content).hexdigest() == digest, f'Hash mismatch: {name}'
    if not path.exists():
        with path.open('xb') as stream:
            stream.write(content)
    print(name, 'verified')
PY
```

For a different location, **export** `HARNESS_AX_TOKENIZER=/absolute/path/tokenizer.json`
before invoking the CLI. Profile selection happens before `--env-file` loading,
so putting this override only in `.env` is insufficient. The default path needs
no override. Do not silently substitute another tokenizer if retrieval fails.

```bash
.venv/bin/python - <<'PY'
from intent_browser.standard_profile import standard_profile, tokenizer_path
from intent_browser.input_budget import QwenInputCounter
print('Profile:', standard_profile().name)
print('Counter:', QwenInputCounter(tokenizer_path()).provenance['method'])
PY
```

## 3. Configure credentials locally

World generation, manual browsing and scripted checks require **no API key**.
For later authorized model runs, create `.env` without overwriting an existing
file, run `chmod 600 .env`, and have Bjorn enter the key privately. Never print,
commit or paste secret values. Minimal contents:

```dotenv
MODEL_BASE_URL=https://openrouter.ai/api/v1
MODEL_NAME=qwen/qwen3.8-27b
OPENROUTER_API_KEY=REPLACE_LOCALLY
OPENROUTER_PROVIDERS=akashml,chutes,phala,parasail,ionstream,cloudflare
OPENROUTER_MAX_TOKENS=16384
```

- Pass **both** `--env-file .env --api-key-env OPENROUTER_API_KEY`. The CLI's
  default key name is `MODEL_API_KEY`. Dotenv does not override existing shell
  variables; check for stale exported settings without displaying secret values.
- Leave `OPENROUTER_PRESET` **unset**, including in the shell. Use a model slug
  with the provider list. Current defaults prefer AkashML with capacity fallbacks
  and exclude DekaLLM. Session IDs are retained; provider fallback does not
  guarantee cache continuity. Reasoning is enabled; 16384 includes reasoning and
  final output.
- `PARALLEL_API_KEY` is optional, unnecessary here. Keep `--search disabled`;
  generated worlds have their own website search index.
- `DAYLIGHT_*`, `HARNESS_WORKER_TOKEN`, Blob/control/tunnel credentials,
  `VERDA_*` and `HF_TOKEN` are unnecessary. `.env.example` includes optional
  legacy/deployment entries; do not treat all of them as requirements.
- Optional **exported** settings: `HARNESS_PYTHON_IMAGE` selects the sandbox image;
  `HARNESS_DEBUG_TIMINGS=1` enables diagnostics. Leave timing off unless needed.
- Custom Python launchers must call `load_dotenv('.env', override=False)` or
  receive exported settings. Importing the backend does not load `.env`.

Setup does not authorize paid tests. Follow `AGENTS.md`: an agreed finite episode
list authorizes those runs; report actual charges and surprises. Ask for a cap
for open-ended unsupervised experimentation.

## 4. Enable the isolated Python tool

Enable Docker Desktop integration for this laptop's Ubuntu WSL distro and check
access from WSL. The image build may download its base image; no GPU is needed.

```bash
docker version
docker build -f deploy/python/Dockerfile -t intent-browser-python:stdlib-v1 .
docker image inspect intent-browser-python:stdlib-v1 --format '{{.Id}}'
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --entrypoint python3 \
  intent-browser-python:stdlib-v1 -I -S -u -c 'print(sum([1, 2, 3]))'
```

The actual harness applies its own sandbox/resource restrictions. Record the
image ID. Runtime never automatically pulls a missing image or substitutes host
Python. Without Docker, world browsing still works; a custom launcher can use
`standard_profile(data_tools=False)`, explicitly labeled as a reduced toolset.

## 5. Generate and browse a fresh world

Old `.local/coordination/.../product-pin-v*` paths are ignored desktop fixtures,
not clone contents. Their source pins may also be stale. Generate fresh inputs
using committed modules, fixed seeds and bundled offline geography. Do not
resample until a task happens to have a successful answer.

```bash
.venv/bin/python - <<'PY'
import hashlib
import json
import subprocess
from pathlib import Path
from environments.product_world.scenario import generate_scenario

root = Path('.local/laptop-world/pin-v1')
root.mkdir(parents=True, exist_ok=False)  # choose a new directory on a rerun
scenario = generate_scenario(
    task_options={'seed': 0, 'family': 'footwear', 'query': 'cheapest',
                  'destination_city': 'random', 'destination_country': 'SE',
                  'memory': 'none', 'hidden': 'none'},
    world_options={'seed': 42, 'store_count': 6, 'models_per_store': 5},
    location_options={},
)
payload = json.dumps(scenario, ensure_ascii=False, indent=2).encode('utf-8')
(root / 'scenario.private.json').write_bytes(payload)
sources = sorted(Path('environments/product_world').glob('*.py'))
pins = {
    'file_sha256': {'scenario.private.json': hashlib.sha256(payload).hexdigest()},
    'source_sha256': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
    'checkout': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
}
(root / 'pins.json').write_text(json.dumps(pins, indent=2))
print('Created', root)
PY

.venv/bin/python -m environments.connected_shopping \
  --pin .local/laptop-world/pin-v1 \
  --output .local/laptop-world/preview-v1
```

Keep this terminal running. Open the printed **localhost index URL** in the
Windows browser. It links retailer, comparison, review and travel pages. Ports
are dynamically allocated; old desktop URLs are not laptop configuration.
Stop with Ctrl+C. Use a new output directory on restart and rebind task cards
because page origins change.

In another terminal at the repository root, publish a separate public task card:

```bash
.venv/bin/python -m environments.product_world.episode_preview \
  --scenario .local/laptop-world/pin-v1/scenario.private.json \
  --runtime-output .local/laptop-world/preview-v1 \
  --output .local/laptop-world/task-card-v1 --port 47403
```

Verify and open http://localhost:47403/task.html. The task is separate from the
browsable world. Never serve the repository, pins, `.env` or trace directories
with a generic static server: private scenarios contain task/reference data.
The built-in runtimes serve only their own routes.

This is a baseline research world, not every WIP profile/presentation on the
desktop and not a guaranteed-solvable task. Extensions live in
`environments/product_world` and `environments/connected_shopping`. Create fresh
world/browser state per independent episode; do not share a human preview's
mutable state with evaluation runs.

## 6. Validate and connect the harness

Run independent checks in parallel and inspect both logs and exit codes:

```bash
.venv/bin/python -m pytest -q environments/product_world/test_scenario.py \
  > .local/laptop-world/generation-tests.log 2>&1 &
generation_pid=$!
.venv/bin/python -m pytest -q tests/test_input_budget.py tests/test_runtime_defaults.py \
  > .local/laptop-world/harness-tests.log 2>&1 &
harness_pid=$!
wait "$generation_pid"; generation_status=$?
wait "$harness_pid"; harness_status=$?
printf 'generation=%s harness=%s\n' "$generation_status" "$harness_status"
```

Use a shell without `set -e` for that status-collecting block, or explicitly
handle each failed wait. Do not start with the entire repository test suite:
some tests require optional assets, services or retained local fixtures.

For a separately authorized **model plumbing smoke**, the current toolset can
operate the built-in Finish-button page:

```bash
.venv/bin/intent-browser run --env-file .env --api-key-env OPENROUTER_API_KEY \
  --headless --no-preview --search disabled --max-steps 8
```

That is not a generated-world evaluation. To connect a real world, use its
current task launcher if published, or adopt these existing interfaces:

- `Episode.from_runtime(scenario, runtime).policy_input()` exposes public task
  data. Keep the full scenario/reference in trusted host code.
- `standard_profile(navigation_origins=tuple(runtime.origins.values()))` scopes
  tools to actual world origins. Use a fresh BrowserGym context and existing
  `run_episode`/`ChatCompletionsBackend`, with provider options and
  `session_routing=True` for OpenRouter. Current defaults are 200 decisions and
  100000 next-input tokens; retain them unless the agreed run says otherwise.
- Answer tasks need explicit `terminal_response_instruction`, not a generic
  completion-only "Done" instruction. Preserve the adapter's public/trusted
  boundary for memories, clarifications, answer extraction and grading.
- Generated worlds use native observation capture; do not force the live-web
  human-handover background path onto an incompatible adapter. Windows CDP and
  monitor placement are not required for headless WSL Chromium.
- Invoke matching grading with trusted effect evidence at its documented
  finalization boundary. Normal termination or an answer alone is not success.

**Publication caveat, 28 September 2026:** at base `27576b1`,
`intent_browser/connected_world_task.py` and `experiments/focused_shopping/` were
still untracked desktop work. Check `git ls-files` before relying on them. If
absent, report that specific gap and request the owner's committed launcher;
do not invent an equivalent grader or copy arbitrary desktop `.local` scripts.
Generation/manual browsing and the core smoke above do not depend on that work.

## 7. Clone common_agent_util and view traces

Clone the companion repository as a **sibling**:

```bash
git clone https://github.com/BjornWest/common_agent_util.git ../common_agent_util
.venv/bin/python -m pip install -e ../common_agent_util
mkdir -p runs
.venv/bin/python scripts/view_traces.py --runs runs
```

If it already exists, inspect its status before updating. Use GitHub SSH or the
user's credential helper if authentication is needed; never put tokens in URLs.
Expected layout:

```text
~/code/
  LLM_proj_uu/
  common_agent_util/
```

Verify and open http://localhost:8878. Another location is supported with
`--common-util /absolute/path/common_agent_util`; select a cohort with
`--runs /absolute/path/to/runs`. An empty library before creating/copying traces
is normal. This explicit `--runs` path uses the shared renderer directly.

`runs/` and `.local/` are ignored, so old traces must be transferred separately.
Some desktop viewer refinements were still uncommitted in the companion repo at
review time. In particular, project `27576b1`'s default multi-root trace hub expects
an HTML integration anchor missing from published companion `8ee71c5`; it returns
HTTP 503. Use the explicit `--runs` command above until matching viewer changes
are published. Do not claim full desktop UI parity. After that compatibility fix,
the no-`--runs` path uses `.local/trace-viewer/sources.json`; configure laptop-local
roots there rather than desktop absolute paths. Record both repository commits.

## Raven demo on the laptop

The Raven demo (an LLM browser agent in a Chrome side panel) runs its backend in
WSL and drives a **native Windows Chrome for Testing** window that carries the
Raven extension (`--windows-browser`). This section is independent of sections
1-7; the setup script below performs the relevant parts of them.

### Prerequisites

- Windows 11 (or 10 21H2+) with WSL2 Ubuntu 24.04 (22.04 works with Python 3.11).
  Keep the checkout in the Linux filesystem, e.g. `~/code/LLM_proj_uu`.
- WSL **interop** on (default): `powershell.exe` must run from WSL. The backend
  starts Chrome and relays its debugging port through PowerShell stdin/stdout,
  using `-Command`/`-EncodedCommand` only, so the PowerShell **execution policy
  does not matter** and no `.ps1` file is run.
- WSL **localhost forwarding** on (default NAT mode, or `networkingMode=mirrored`):
  the side panel loads `http://127.0.0.1:8770/panel.html` from Windows. Do not set
  `localhostForwarding=false` in `%UserProfile%\.wslconfig`.
- About 1 GB of downloads (Python packages, Playwright Chromium, Chrome for Testing,
  13 MB tokenizer). No model weights, no GPU.

### 1. Get the code

```bash
cd ~/code
git clone git@github.com:BjornWest/LLM_proj_uu.git   # skip if it exists
cd LLM_proj_uu
git status                                           # must be clean before switching
git fetch origin claude/raven-demo-20261019
git switch claude/raven-demo-20261019 && git pull --ff-only
```

### 2. Run the setup script (idempotent; rerun after pulls)

```bash
bash scripts/raven_laptop_setup.sh
```

It asks for `sudo` once (apt: Python 3.12, venv, git, curl, xvfb; Playwright's
Chromium system libraries via `playwright install-deps chromium`), then:
creates `.venv` from `requirements.lock.txt`; installs Playwright Chromium; clones
`common_agent_util` (provides `agent_trace`) to `../common_agent_util` at pinned
commit `73cf7e9` and installs it into the venv; fetches the pinned Qwen3.8-27B
tokenizer files (revision `1d4bf0f2`, SHA-256 checked against
`intent_browser/model_tokenizers.json`) into `.local/model-tokenizers/` and
`training/.cache/qwen38-tokenizer/`; downloads Chrome for Testing into
`%LOCALAPPDATA%\raven-demo`; writes non-secret `.local/raven-demo.env`
(`RAVEN_CAU_PATH`, `RAVEN_BOUNDED=0`); and runs the **no-model smoke check**
against a temporary backend on port 8790. It ends with `PASS` lines for backend
health, panel and full-page load and a scripted mock run in each layout.

Switches: `RAVEN_SKIP_SUDO=1`, `RAVEN_SKIP_WINDOWS=1`, `RAVEN_SKIP_SMOKE=1`,
`RAVEN_SMOKE_PORT=...`, `RAVEN_CAU_PATH=...`, `RAVEN_CAU_SOURCE=<url|path|bundle>`.

### 3. Create `.env` yourself

The script never writes or copies secrets. Create the file privately:

```bash
[ -e .env ] || install -m 600 /dev/null .env
nano .env                         # add: OPENROUTER_API_KEY=<your key>
```

Other locations: export `RAVEN_ENV_FILE=/path/to/.env`.

### 4. Model access

- **OpenRouter** (default): needs only `OPENROUTER_API_KEY`. The service starts
  with the `default` preset of `apps/raven/models.json` (Gemini Flash); the panel's
  model picker switches between presets (Gemini Flash, Muse Spark, Qwen 27B via
  OpenRouter, Qwen 27B on Vast, Sol). The file is reloaded when it changes.
  `--preset ID` or `--model-backend openrouter` picks the startup model instead.
- **Self-hosted Qwen on Vast** (the "Qwen 27B (self-hosted Vast)" preset expects
  vLLM at `http://127.0.0.1:18000/v1`):
  1. Give the instance the laptop's SSH key. In WSL: `ls ~/.ssh/id_ed25519.pub ||
     ssh-keygen -t ed25519`, then `cat ~/.ssh/id_ed25519.pub`. Either add it under
     *Account -> SSH Keys* in the Vast console (applies to new instances; for a
     running one, use the instance's key icon / `vastai attach ssh INSTANCE_ID
     "$(cat ~/.ssh/id_ed25519.pub)"`), or from a machine that already has access:
     `ssh -p PORT root@HOST 'cat >> ~/.ssh/authorized_keys' < laptop_key.pub`.
  2. Take `HOST` and `PORT` from the instance's *Connect -> SSH* command
     (`ssh -p PORT root@HOST`) and start the self-healing tunnel:
     ```bash
     VAST_SSH_HOST=HOST VAST_SSH_PORT=PORT nohup apps/raven/vast_tunnel.sh >/dev/null 2>&1 &
     curl -s http://127.0.0.1:18000/v1/models     # lists Qwen/Qwen3.8-27B-FP8
     ```
     Logs/known_hosts: `.local/raven-vast/`. Stop: `kill "$(cat .local/raven-vast/tunnel.pid)"`.
     vLLM must already be serving on the instance's port 8000.
- **GPT-6.1 Sol** (the `sol` preset) needs the workstation's Codex subscription
  bridge (Node, `pi`, Codex login) and is not set up on the laptop.

### 5. Start and verify

```bash
apps/raven/start_demo.sh 8770
```

Chrome for Testing opens on the Windows desktop with the Raven side panel. The
script stops an earlier service on that port and only Raven's own Chrome for
Testing processes (never your normal Chrome), starts `Xvfb :99` for Linux-side
background browsers when needed, and logs to `.local/raven-logs/raven-8770.log`.
Verify:

```bash
curl -s http://127.0.0.1:8770/api/health
.venv/bin/python -m apps.raven.smoke --url http://127.0.0.1:8770 --windows-browser \
  --output .local/raven-logs/smoke-8770
```

Then open http://localhost:8770/ in Windows and ask one short question in the side
panel (one real model call).

### Troubleshooting

- `powershell.exe: command not found`: enable interop (`[interop] enabled=true`,
  `appendWindowsPath=true` in `/etc/wsl.conf`), then `wsl --shutdown` in Windows.
- Side panel blank / "refused to connect": Windows cannot reach WSL's
  `127.0.0.1:8770`. Check `curl` inside WSL first, then open
  http://127.0.0.1:8770/api/health in Windows; re-enable localhost forwarding or
  use `networkingMode=mirrored`, then `wsl --shutdown`.
- `Install Windows Chrome for Testing first`: rerun the setup script, or
  `PYTHONPATH=$PWD .venv/bin/python -m apps.raven.windows_browser --setup`.
- `Diagnostic port already occupied` or a stale Raven window: rerun
  `start_demo.sh` (it stops Raven's Chrome for Testing) or close it in Task Manager.
- `ModuleNotFoundError: agent_trace`: rerun the setup script; or set
  `RAVEN_CAU_PATH` in `.local/raven-demo.env` to the `common_agent_util` checkout.
- `Commit 73cf7e9... is not available`: that commit must be on GitHub (or pass a
  bundle via `RAVEN_CAU_SOURCE=/path/cau.bundle`).
- Chromium fails with missing `lib*.so`: `sudo .venv/bin/python -m playwright
  install-deps chromium`.
- `Current harness requires the local Qwen tokenizer`: rerun the setup script
  (step 5 restores `training/.cache/qwen38-tokenizer/`).
- `KeyError: 'OPENROUTER_API_KEY'` in the log: `.env` is missing the key or is
  elsewhere (set `RAVEN_ENV_FILE`).
- Vast preset errors: `curl http://127.0.0.1:18000/v1/models`; see
  `.local/raven-vast/tunnel-ssh.err` (`Permission denied (publickey)` means the
  laptop key is not on the instance).
- `Raven did not start`: read the log path printed by `start_demo.sh`.
- On the workstation, `RAVEN_BOUNDED=1` (default without `.local/raven-demo.env`)
  runs the service under `scripts/run_bounded_job.py`.

Validated on the workstation (2026-10-21) as a fresh clone with a new venv and
common_agent_util clone, `RAVEN_SKIP_SUDO=1 RAVEN_SKIP_WINDOWS=1` and the
workstation's sudo-less Chromium libraries: setup, tokenizer download/hash check,
all five smoke checks and one scripted (no-model) background episode passed. Not
covered there: apt/`install-deps`, the Windows Chrome download, the
`--windows-browser` path on another PC, the Vast tunnel, and real model calls.

## Laptop agent's completion report

Report both repo commits, Python/Playwright versions, tokenizer hashes, Docker
image ID (or explicit limitation), scripted browser/focused test outcomes, and
verified world/task/viewer URLs. Check required key **presence only**. Distinguish
offline setup from separately authorized model episodes and record trace paths.

Leave Vercel, imported datasets, model weights, remote training, desktop cookies
and this PC's services untouched. Report concrete missing/unpublished pieces
rather than trying to reproduce the whole workstation.

## Guide validation

Checked against an isolated archive of `27576b1`, excluding uncommitted project
code: the generation/pin recipe, world index and all 15 site roots, task card,
scripted Chromium smoke, tokenizer/profile initialization, and 30 focused tests
(plus two subtests) passed. Published companion `8ee71c5` served HTTP 200 using
the explicit `--runs` command; the default hub incompatibility is documented
above. The existing Docker image passed the explicit-entrypoint calculation smoke.
These checks reused this PC's installed dependencies and tokenizer files; a fresh
laptop dependency installation/download and paid model episode were not run.
