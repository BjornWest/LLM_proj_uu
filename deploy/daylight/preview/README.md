# Local site-first UX preview

The latest design has three navigation levels:

- **Sites**, grouped by collection in the left rail.
- **Explore site**, with a clickable page and an optional agent sidebar, plus
  **Tasks & replays** scoped to the selected site.
- A separate **All traces & replays** page covering every sample site, with
  search and collection/site/activity/grade filters.

The Campus iframe uses the existing local demo assets and `World`; it supports
manual shop, study-room and preference interactions. Fieldnotes is a small
fictional bookshop. Sidebar replies and task attempts are explicitly scripted
preview examples. No model, worker, cloud key or real inference is used.
Sample grades and requirements are design fixtures, not benchmark results.

## Run locally

From the repository root, build the existing private Campus assets:

```bash
npm --prefix deploy/daylight run build
node deploy/daylight/preview/server.mjs
```

In a second terminal, generate sample viewport images and check the UI:

```bash
.venv/bin/python deploy/daylight/preview/check_workspace.py
```

Open:

- **http://localhost:8892/workspace** — sites, Explore, extension sidebar.
- **http://localhost:8892/workspace?site=campus&view=research** — Campus tasks
  and its replay history.
- **http://localhost:8892/workspace/replays** — the separate global library.

The check uses existing Playwright and local system libraries; it does not
install or download a browser. Generated images go to `.local/ux-preview-images/`
and captures to `.local/ux-sites-*.png`. Set `UX_PREVIEW_PORT` and pass
`--origin` to the check to use another port.

The scripted Ask examples operate the selected live iframe. Switching between
sites keeps their browser state and conversations separate. The agent sidebar
can be hidden for manual exploration. Returning from Tasks or replay preserves
the interactive page state. Newly created sample recording metadata is stored
in the browser's session storage. Replay displays only sample images and never
re-executes a page action.

Task replay rows explicitly contain the task name; Ask rows contain the request.
Succeeded/Failed/Partial are explicit sample grades. Not graded means no
verifier was attached, while Unknown includes an interrupted run without an
outcome. Execution status is separate from grade. The synthetic viewport
images illustrate the layout and are not imported authoritative trajectories.

## Earlier research-view prototype

**http://localhost:8892/harness** retains the first prototype, serving the actual
harness client against synthetic config/jobs/artifact APIs. Check it with:

```bash
.venv/bin/python deploy/daylight/preview/check.py
```

Its current client supports session-resolved task objectives: it queues without
a goal, includes the advertised revision, shows a pending-objective message,
and displays the exact recorded goal when the worker publishes it. Each new
launch still omits the old objective. These checks use intercepted local
fixtures, never real external tasks.

## Integration boundary

All new design files stay in this local preview directory; the production
handler and asset build do not import them. This fixture server binds only to
loopback and is not an authenticated team deployment. The fake bookshop is not
the reviewed P07 fixture.

Actual API contracts live in `../TEAM_UI_CONTRACT.md`. Production integration
needs explicit site, task/Ask mode, task identity/revision, runtime and recorded
grading metadata. Historical modes must not be guessed from goal equality,
partial grades must not be inferred from missing outcomes, and original traces
remain authoritative. Remote manual browsing, shared publication and future
streaming still depend on their respective backend capabilities.
