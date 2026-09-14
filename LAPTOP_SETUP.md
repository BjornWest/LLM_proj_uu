# Laptop setup

Use Ubuntu/WSL with Python 3.12 and Git. Node.js 22 or 24 is needed for Chaos
and the Tricky fixture. No GPU or inference credentials are needed for the
scripted demos below.

```bash
git clone git@github.com:BjornWest/LLM_proj_uu.git
cd LLM_proj_uu
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
.venv/bin/playwright install chromium
# If Chromium reports missing system libraries (may require sudo):
.venv/bin/playwright install-deps chromium
.venv/bin/python -m pytest -q
.venv/bin/intent-browser smoke
```

Open **http://localhost:8877** to watch browser observations. It remains open
between episodes without taking desktop focus. Add `--headful` only when you
want native browser windows. The initial setup downloads dependencies and
Chromium; run it before the meeting.

## Tricky shopping demo

```bash
.venv/bin/python scripts/setup_tricky.py
npm ci --prefix environments/tricky --ignore-scripts --no-audit --no-fund
node environments/tricky/build.mjs
.venv/bin/python scripts/verify_tricky.py --case clean --case allowed --case warranty
```

The setup fetches the pinned shopping import closure (about 16 MiB), checks its
Git blob hashes, and retains unmodified upstream files under `.local/tricky`.
The build applies recorded instrumentation patches. Cases drive the browser
through the same action parser as the model loop. They test the verifier and
are explicitly ineligible as model-training demonstrations.

To operate the page through terminal actions:

```bash
.venv/bin/intent-browser development --pilot-task P07 --condition warranty
# Read the printed observation and supply one BrowserGym action at a time.
```

## Chaos

In one terminal:

```bash
npx --yes browser-agent-chaos@0.1.0 --no-open
```

Use the **agent port** printed by Chaos in another terminal:

```bash
.venv/bin/intent-browser development --chaos-base-url http://localhost:AGENT_PORT \
  --chaos-task confirmshaming
```

The recorded Chaos build gate checks installed files and verifier source on
Linux/WSL. A different build remains unvalidated until local preflight/review;
see [CHAOS_VERIFIER.md](CHAOS_VERIFIER.md).

## Credentials and local artifacts

Copy `.env.example` to `.env` and fill it locally only if you need model/search
calls. Transfer credentials through your own secure method; they are not in
GitHub. Paid calls still need an explicit budget; the scripted commands above
make no inference or search requests.

`.venv/`, `.env*` (except the example), `node_modules/`, `.local/`, `.research/`
and `runs/` are excluded from Git. Therefore old recordings, source caches,
scores and local report servers do not appear on a fresh laptop checkout.
The live viewer starts with the first CLI episode; the older documentation
links on port 8876 refer to this workstation's local report server.

To restore the small source cache used by the curation integrity check:

```bash
python3 data/curation/check_preflight.py --fetch
.venv/bin/python scripts/preflight_pilot.py
```

MiniWoB setup is optional and documented in [README.md](README.md). Finish the
plain smoke test first; it does not require the MiniWoB source checkout.
