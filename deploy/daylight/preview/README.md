# Local harness UX preview

This preview serves the actual harness client against synthetic API fixtures.
Campus and Fieldnotes are small fictional websites for demonstrating selection
and recorded browser views. They are **not** the reviewed P07 environment.
No worker, model, cloud credentials or real episode is used. Sample feedback is
kept only in server memory. Nothing in this directory is imported by the
production handler or copied by its asset build.

From the repository root:

```bash
node deploy/daylight/preview/server.mjs
```

In a second terminal, generate sample screenshots and run the browser checks:

```bash
.venv/bin/python deploy/daylight/preview/check.py
```

Open **http://localhost:8892/harness**. The checks use the existing Playwright
installation and local system libraries, and write generated images under
`.local/ux-preview-images/`. They do not download a browser. Desktop/mobile
captures are `.local/ux-preview-desktop.png` and `.local/ux-preview-mobile.png`.

Try these flows:

- **Watch a task:** choose Campus or Fieldnotes, then Watch task. The preview
  publishes four sample steps over several seconds.
- **Ask the agent:** switch websites and edit a request. Each site retains its
  draft; sending it starts a synthetic preview run.
- **Replay a trace:** choose a saved run and use Play replay, previous/next or
  the slider. The image is the selected step's pre-action observation.
- **Follow latest:** while watching, pause to pin a recorded step; resume to
  show the latest post-step image. This never controls the agent browser.
- Search/filter runs, expand grouped interactions and raw evidence, and save
  step feedback. All sample verification outcomes stay unknown.

Set `UX_PREVIEW_PORT` to use another port and pass `--origin` to `check.py`.
The server binds only to local loopback. Do not proxy this fixture server as
an authenticated team deployment.

## Current integration boundary

The production client uses the existing authenticated harness config/jobs/
artifacts/issues API documented in `../TEAM_UI_CONTRACT.md`. Optional `site`,
`condition` and `verification_scope` task strings are displayed when supplied.
Only worker-advertised tasks can launch. The library accurately labels its
current BrowserGym/invitation scope. Project-wide publication, the browser-side
demo trace index, P07 worker support, assistant token streaming and action-target
geometry remain separate backend/UX increments. Raw original evidence and
verifier results remain available without reinterpretation.
