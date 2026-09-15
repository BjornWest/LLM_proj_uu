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

## Membership, privacy and source-checker diagnostics

After the shared Tricky dependency install above:

```bash
python3 scripts/setup_tricky_membership.py --fetch
node environments/tricky_membership/build.mjs
.venv/bin/python -m scripts.verify_tricky_membership --case clean --case allowed --case family
python3 scripts/setup_tricky_privacy.py --fetch
.venv/bin/python -m scripts.verify_tricky_privacy --case clean --case allowed
.venv/bin/python -m scripts.verify_susbench_ikea
```

The membership/privacy setup restores only small hash-pinned source files when missing. IKEA uses a checked-in exact injection fragment and needs no source download. The privacy fixture has explicit derived Save/persistence semantics and excludes scheduling. Membership preserves every simulated activation across reloads. IKEA only reproduces radio/callback behavior; it has no purchase verifier.

Interactive terminal action modes:

```bash
.venv/bin/intent-browser development --pilot-task P11 --condition injected
.venv/bin/intent-browser development --pilot-task P10 --condition clean
```

Use `--condition clean` or `injected` for these new fixtures. See [TRICKY_MEMBERSHIP.md](TRICKY_MEMBERSHIP.md), [TRICKY_PRIVACY.md](TRICKY_PRIVACY.md), and [SUSBench_IKEA.md](SUSBench_IKEA.md). These are scripted/development tools, not trained models or certified training datasets.

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

The versioned repair for dropped Save clicks and collapsed seeded choices is described in [CHAOS_REPAIR.md](CHAOS_REPAIR.md). It copies the exact cached package, reuses dependencies, launches with isolated state, and requires a fresh local certificate. Original and repaired builds are separate benchmark conditions.

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

## Optional saved-trace viewer

Clone the shared utility alongside this repository, then start the viewer:

```bash
git clone git@github.com:BjornWest/common_agent_util.git ../common_agent_util
python3 scripts/view_traces.py
```

Open
[http://localhost:8878](http://localhost:8878). A different checkout location can
be supplied with `--common-util PATH`. Python's standard library is sufficient.
Saved `runs/` are ignored by Git in both projects; copy the episodes you want to
review separately when moving to the laptop.
