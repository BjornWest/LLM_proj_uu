# Raven assets handoff

> These notes describe the original imported prototype. The full-page v42 entry now uses the backend API; see [current integration and acceptance](raven-backend-chat-handoff.md). The compact v40 demo retains the original behavior described here.

The Raven prototype is imported at [`design/raven/`](../../design/raven/). This is an **uncommitted source and asset export**, not an application integration, deployment, or an adoption-ready harness change. The existing application is not wired to these demos.

The package contains the latest approved full-page chat design, the earlier extension-shaped chat design, their live-rendered Raven assets, the native Blender sources needed by the exporter, and provenance/validation files. Start with the full-page demo when assessing the current visual behavior.

## Preview locally

From the repository root, run the preview with the repository's bounded-job wrapper:

```sh
python3 scripts/run_bounded_job.py --memory-mib 1024 -- python3 design/raven/outputs/raven/server.py --port 8766
```

Then open:

- Full-page design: <http://127.0.0.1:8766/chat-fullpage-v42.html?v=42-flock-1>
- Extension-shaped design: <http://127.0.0.1:8766/chat-live-v40.html?v=40-live-1>
- Package navigation: <http://127.0.0.1:8766/>

Python's standard library is sufficient for the server. The live demos need a browser with WebGL support. Dependencies are vendored; there is no npm installation or build step for previewing this snapshot. Serve it over HTTP rather than opening the HTML with `file://`.

The server listens on `127.0.0.1`. It also supplies the same-origin website-preview endpoints used by links and the current-website indicator. Plain static hosting can show the Raven and chat layout, but those previews need equivalent backend endpoints.

## What is included

| Area | Entry or source | Purpose |
| --- | --- | --- |
| Current full-page design | [`chat-fullpage-v42.html`](../../design/raven/outputs/raven/chat-fullpage-v42.html) | Sidebar history, borderless assistant messages, search-style composer, direct upward takeoff, and a manual helper-flock demo |
| Extension-shaped design | [`chat-live-v40.html`](../../design/raven/outputs/raven/chat-live-v40.html) | Compact chat suitable for a panel next to an agent-controlled browser tab |
| Shared live renderer | [`raven-live-v42.js`](../../design/raven/outputs/raven/raven-live-v42.js) | Mesh pose interpolation, head attention, petting, rendering several Ravens through one WebGL context |
| Native motion bank | [`live-raven-v34.json`](../../design/raven/outputs/raven/live-raven-v34.json), `live-raven-v34.bin` | Exported evaluated Blender geometry, local transforms, cameras, markers, colors, and sampled poses |
| Random flight composition | [`chat-flight-director-live-v36.js`](../../design/raven/outputs/raven/chat-flight-director-live-v36.js) | Side-heavy routes, swerves, depth changes, wingbeats, occasional rolls, turns, and continuous return |
| Helper flock | [`raven-flock-v42.js`](../../design/raven/outputs/raven/raven-flock-v42.js) | Up to six independently patrolling helpers, sharing the main Raven's renderer and assets |
| Message rendering | [`chat-messages-v33.js`](../../design/raven/outputs/raven/chat-messages-v33.js), [`raven-citations-v40.js`](../../design/raven/outputs/raven/raven-citations-v40.js) | Sanitized Markdown, tables, links, website previews, and captured-evidence hover cards |
| Native authoring | [`work/export_raven_live_v34.py`](../../design/raven/work/export_raven_live_v34.py) | Read-only extraction from five saved Blender scenes |

Version suffixes describe a dependency's origin, not a requirement to upgrade every filename together. The v42 page intentionally uses v34 motion data, the v36 flight director, v38 idle gaze, v39 activity indicator, v40 citations, and v41 conversation history. Preserve the shipped relative layout and filenames until changing imports deliberately.

## Behaviors to inspect

- Send a message: the main Raven braces and pushes off, flies upward into the sky area, patrols, then returns to the send button and caws when the demo response arrives.
- Enable **60-second flight** before sending to inspect more route variations. The normal demo reply is after ten seconds.
- Use **Spawn raven** to add helpers arriving from either screen edge. **Clear helpers** removes them. These buttons simulate subagent visuals; they do not create actual agents.
- Move the cursor near the perched Raven's head for smooth attention. Leaving the tracking area holds the current head pose until a later idle turn. Click the main Raven to pet it.
- Try the 60, 120, and 144 fps targets in the demo controls. These are render targets, bounded by the browser, display, and hardware; they are not guaranteed measured frame rates.
- Resize the window and inspect the flight area, composer, and sidebar. Hover or focus links and numbered evidence citations. Inspect scroll behavior while a reply arrives away from the bottom.

## Integration status and next steps

The prototype has no model or harness transport. Its response, browsing sequence, seeded history, and shopping evidence are illustrative fixtures. The main controller contains automatic response logic in two places, and the flock has no mapping to real subagent IDs. Do not treat the public-looking controller methods as a complete production protocol.

Read [`raven-integration.md`](raven-integration.md) for exact APIs, payloads, missing lifecycle pieces, and an integration plan. Read [`raven-authoring.md`](raven-authoring.md) before changing geometry, timing, topology, or native scenes.

Provenance is recorded in [`manifest.json`](../../design/raven/manifest.json); export verification is recorded in [`validation.json`](../../design/raven/validation.json). From the repository root, verify the exported inventory and integrity with:

```sh
python3 design/raven/tools/verify_bundle.py
```

The verifier is [`tools/verify_bundle.py`](../../design/raven/tools/verify_bundle.py). These files describe the exported bundle and checks actually recorded there; they do not constitute application integration, a new browser acceptance run, or a performance guarantee. Re-run verification after transferring or modifying the package and compare changes against the intended snapshot.

For a finite local server/asset delivery check (no browser or model launch):

```sh
python3 scripts/run_bounded_job.py --memory-mib 1024 -- python3 design/raven/tools/smoke_preview.py
```

The check uses port 18766, fails if it is occupied, and stops only the server it starts.

Follow the repository's [`AGENTS.md`](../../AGENTS.md) for any subsequent implementation. In particular, later implementation commits need independent review from the other agent family before adoption handoff or dev/prod integration: Codex-authored commits require Claude Code review; a same-family subagent is not sufficient. This file export creates no commits and does not claim that review or integration approval has occurred.
