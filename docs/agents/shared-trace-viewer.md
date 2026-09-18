# Shared viewer in the site workspace

## Scope and current status

`SHARED-TRACE-VIEWER-01` adds the existing `common_agent_util` session viewer to
Daylight's site/global trace lists. This frontend is prepared for local review;
authenticated PC publication, API/build integration and deployment are separately
owned by the backend thread. The fixture server is not the production importer.
No saved private runs are included in deployed assets.

The workspace retains site navigation, recorded activity/condition/grade filters,
and existing conversation grouping. Published library sessions open the shared
readable renderer inside that layout. Current Campus, live job and manual-session
records retain their existing renderers until compatible adapters are available.
Missing historical metadata remains unknown; equal goals do not join sessions.

## Source and extension boundary

`deploy/daylight/vendor/agent_trace/` pins the exact shared viewer HTML and its
SHA-256 provenance. This includes pre-existing readability edits in the sibling
checkout; `source_worktree_modified` is recorded and the sibling is untouched.
It is application-owned code, never HTML supplied by a saved-run upload.

`prepare-viewer.mjs` checks the source hash and every integration anchor, extracts
scripts/styles for the deployed CSP, and adds the separate `trace-browser.js/css`
project extension. A changed upstream source must be deliberately repinned and
the packaging/browser checks rerun; changed anchors fail the build.

The shared renderer retains readable JSON, accessibility-tree formatting, search,
message filtering, paging and scroll-position handling. BrowserGym adds:

- **Conversation:** model bubbles left, user/tool messages right; exact recorded
  content and provenance remain accessible. Recording limitations are expandable.
- **Tools only:** chronological recorded tool events, using `tool-activity.js`.
  Generic decision counts do not stand in for BrowserGym action counts.
- **Available tools:** definitions from each step's retained/actual request, not
  inferred from actions or today's runtime. Missing and explicitly empty differ.
- **Replay:** selected-step screenshots, previous/next/slider and a one-step-per-
  second slideshow. This does not run a browser, model, reproduction or verifier.
  Decision observations and transition feedback are separately selectable. An
  action's target is never resolved against a later page. The inventory selection
  follows the replay step. Leaving the view unloads playback.

Tools/replay are enabled for `environment=browsergym`; other shared-viewer
environments retain the generic renderer. Projection messages are not rewritten.
Privileged evaluation remains separate from model input; raw outcomes are kept.

## Backend contract and packaging

- `GET /api/library/sessions`: `{sessions,has_more,cursor}`; opaque cursor,
  owner-authorized summaries only. Workspace loads one page then explicit more.
- `GET /api/library/sessions/:id`: common session projection, with optional
  additive `library_metadata` for deep-link summary display.
- `GET /api/library/sessions/:id/assets/:attachmentId`: authorized mapped asset.
  Every access requires owner checks; no arbitrary paths/URLs. Current client
  accepts same-origin exact paths without query strings or fragments.
- Protected `/trace-viewer` maps to `trace-viewer.html`. Workspace uses
  `/trace-viewer?embed=1#OPAQUE_ID`; no catalog fetch is needed inside this frame.
- Build calls `prepareViewer(destination)` and adds its returned filenames to the
  protected asset allowlist and source/asset fingerprints. Existing
  `tool-activity.js/css` are dependencies.

Summary fields used when explicitly present: `site_id`, `collection`,
`interaction_kind`, `task_id`, `task_name`, `condition`, `execution_status`,
`execution_mode`, `evaluation`, `grade`, `rubric`, `goal`, `started_at/created_at`.
Recorded classification is not filled from the current task registry. Explicit
publication metadata must retain its provenance, separately from the projection.

Screenshots and original attachments load on demand; there is no saved-library
idle polling. Refresh is explicit. Catalog failures retain loaded rows and offer
retry. Normal list-to-session navigation fetches one full projection; direct
workspace deep links currently fetch it once for metadata and once in the frame.
Large assets/archives must be streamed or bounded by the backend, not base64
embedded into a catalog response. The frontend does not import local directories.

## Reproducible local review

After the ordinary build, with the two frozen v2 bundles under `.local/review/`:

```bash
npm --prefix deploy/daylight run build
node --test deploy/daylight/tests/shared-viewer.test.mjs
.venv/bin/python scripts/smoke_shared_trace_viewer.py
.venv/bin/python scripts/smoke_workspace_ui.py
LIBRARY_PREVIEW_AUTOLOGIN=1 node deploy/daylight/tests/library-server.mjs
```

The final command prints its localhost port. Open `/workspace/replays`. Autologin
is a local fixture convenience, not production authentication. Without that flag,
the fixture uses the actual invitation handler and tests owner isolation. It
serves exact frozen projection data and hash-checked mapped media, with explicitly
labelled fixture publication metadata. Writes/model dispatch are rejected.

Browser checks cover full-layout embedding, paging/retry, direct links, invitation
and owner boundaries, lazy images, the 12-action timeline, unknown inventories,
phase separation, replay controls, mobile sizing, iframe unloading, parser-error
unknown grading, and zero writes. Unit checks cover exact observation/tool
provenance, authorized attachment paths and pinned packaging. All these checks
are scripted UI validation, not new model or benchmark results.
