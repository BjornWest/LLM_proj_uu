# Raven backend and shared window (WEB-A)

Local implementation on `claude/raven-backend-20261019`. No dev/prod integration is claimed. The API follows the shared demo-sprint v1 contract. This commit depends on the separately supplied, untracked `design/raven/outputs/raven/` assets; it does not edit or publish those assets.

## Start

From this worktree:

```bash
python3 scripts/run_bounded_job.py --tasks 512 -- python3 apps/raven/backend.py --port 8766 --user-window
```

`python3 apps/raven/backend.py --port 8766 [--user-window]` is the underlying one-command entry. On this workstation it re-executes the shared project's Python interpreter and adds the shared library and agent_trace paths. Use the bounded wrapper for browser work. The backend listens only on `127.0.0.1` and reads `/home/bjorn/code/LLM_proj_uu/.env` server-side. It uses `qwen/qwen3.8-27b`, temperature 0.6, existing OpenRouter provider routing, 40 decisions and a 100,000-token request limit (the harness's model-matched Qwen tokenizer estimate including tools/reasoning/images).

Open <http://localhost:8766/panel.html> for panel layout inspection. The actual extension opens in the visible Chromium window, using `.local/raven-demo-profile/`. The action button opens it again. The full-page UI assets are served at <http://localhost:8766/chat-fullpage-v42.html> for WEB-B's adapter. Launch without `--user-window` for headless background tasks only.

Required local tokenizer assets are `.local/model-tokenizers/qwen3.8-27b-1d4bf0f2/` and `training/.cache/qwen38-tokenizer/tokenizer.json`. Missing copies were copied from the shared tree, not downloaded. The startup command does not install packages or download Chromium.

## Behavior

- Each request starts one isolated harness process. Events replay from the beginning for every SSE subscriber. Traces remain under `.local/raven-runs/RUN_ID/EPISODE_ID/`.
- Background mode owns a headless browser. Shared mode attaches to the dedicated persistent Chromium over loopback CDP, preserves its current document, and excludes extension surfaces from the agent's tab list. Task cleanup disconnects the agent, leaving the window and tabs alive.
- The existing human-browser custody guard handles handover and fresh observations after handback. Human focus does not retarget agent actions. The panel exposes handback and clickable task-tab indicators.
- Cancel terminates the episode process group; shared Chromium belongs to the service and survives. Closing the service closes its dedicated browser.
- Source excerpts come from native AX observations saved in the trace. The panel uses v40 Markdown/citation rendering and an app-owned derivative of the v40 controller, with both fixture completion paths removed. Original design files remain untouched.
- BrowserGym's native task browser is retained; its separate chat browser is replaced by a message store because Raven supplies the chat UI.
- One shared-window task runs at a time. Background requests can run independently. Events and conversations are in memory; browser profile and harness traces persist. The panel retains only its current page's conversation context, with optional prior turns submitted through the contract.

## Validation

Finite offline integration driver (all its episodes have `metadata.tags: [raven, scripted]`):

```bash
PYTHONPATH="$PWD:/home/bjorn/code/cau-merge-20261016" \
LD_LIBRARY_PATH=/home/bjorn/code/LLM_proj_uu/.local/system-libs/usr/lib/x86_64-linux-gnu \
OPENBLAS_NUM_THREADS=1 \
python3 scripts/run_bounded_job.py --tasks 512 -- \
  /home/bjorn/code/LLM_proj_uu/.venv/bin/python -m apps.raven.verify
```

Background and shared cases run concurrently. Shared round-trip and cancellation checks are sequential because they deliberately reuse the same persistent browser and test its survival and document preservation. Results: `.local/coordination/demo-sprint/scripted-acceptance.json`. Real-run results and independent review are recorded in the final section below after completion.

The requested shared-tree log/screenshots conflict with the instruction to keep that tree read-only. Artifacts therefore use the same relative paths in this worktree: `.local/coordination/demo-sprint/workers/log-web-a.md` and `.local/coordination/demo-sprint/web-a-shots/`.

## Integration status

Coordination ID: WEB-A-RAVEN-01. Owner WEB-A; scope `apps/raven/`, missing bounded launcher copy and this document. Open: reviewed candidate handoff to the coordinated publisher and WEB-B; no integration approval or commit adoption inferred. The shared-tree contract remains authoritative. Do not cherry-pick the untracked design inventory as part of this backend change.

## Acceptance and review outcome

- M1: real background run `da2e5d55288b47429f7b70027ee0b648`, episode `20261019T182339Z-94156a7d`, finished after 16 decisions. Model found an advertised 2,149 SEK Electrokit price, navigated from the supplied 404 URL using site search, and returned the product link and 3 sources. SSE: `.local/coordination/demo-sprint/m1-background-events.json`.
- An initial real panel Python-release episode navigated the visible tab but stalled during a provider request and was cancelled. Its SSE and working-window screenshot remain recorded. Two other startup submissions failed before inference; they are distinct from model episodes.
- Final scripted acceptance also covers opening/navigating/closing a new tab in the same persistent context, two initial pages with identical URLs but distinct CDP target IDs, initial human custody of the other page, actual panel Stop dispatch and composer reset, and failed-POST recovery. Verification uses its own port 18766 and fresh profile, so it can run independently of the demo window.
- Source excerpts now prefer exact captured lines matching the answer, including numeric claims. Applying the final selector to the recorded M1 native AX artifact captures the price/VAT text in a 561-character excerpt; this adapter check does not rewrite the historical recording or make a new model call. Evidence: `.local/coordination/demo-sprint/m1-evidence-adapter.json`.
- Independent review of `9a84977` identified and drove correction of missing v40 cancellation, the wait-only profile disabling tab tools, and initial noncurrent-tab custody. Final fix commit and review disposition are recorded in `.local/coordination/demo-sprint/review-web-a.md`.
