# Shared local trace viewer

Use **http://localhost:8878/** for the project trace list, sorted by episode start
time, newest first. **http://localhost:8878/#latest** opens the newest trace.
The shared viewer's live toggle refreshes the catalog and selected recording.

Start it from the repository root:

```sh
.venv/bin/python scripts/view_traces.py
```

The launcher uses `common_agent_util` from the adjacent checkout, with a
project-local catalog adapter. Original recordings stay in their original
directories; the viewer does not copy or rewrite them.

The trusted registry is `.local/trace-viewer/sources.json`. Its default sources
are `runs/`, `.local/real-web-*/runs`, and `.local/synthetic-*/live/runs`.
New directories matching these patterns appear automatically. For a different
launcher output location, add its absolute directory to `roots` or add a
project-relative glob to `patterns`; no server restart is needed. This is a local
development viewer, not an authenticated website publication service.

Future trials should use this catalog instead of starting a viewer on a new
port. Explicit single-directory viewing remains available:

```sh
.venv/bin/python scripts/view_traces.py --runs /absolute/path/to/runs --port 8954
```

Session IDs remain unchanged, preserving existing deep links on the shared
URL. Duplicate IDs across registered roots fail closed; register an original
recording only once. Missing roots are skipped. Unknown timestamps sort last.
Cross-root media links are scoped to the registered source and retain the
shared utility's recorded-artifact/path validation.

## Loading and caching

BrowserGym catalog discovery reads metadata and lifecycle records, without
reading `steps.jsonl` or building message projections. Opening a trace projects
only that episode. Subsequent opens check that episode's file fingerprint;
unrelated recordings are not rebuilt. Projections use per-episode locks, so a
large trace does not hold up the catalog or a different trace.

Small sidebar summaries persist under `.local/trace-viewer/summary-cache/`.
The first open fills in exact model-turn/tool totals and maximum recorded ISL;
until then the sidebar explicitly says to open the trace to load those totals.
Summaries survive server restarts and invalidate when source files or adapter
code change. Source recordings are never modified.

Projected JSON and gzip responses have a 256 MiB LRU budget per parsing mode.
The browser retains up to four traces within a 128 MiB serialized-size budget,
uses ETags on revisits, and fetches only the selected trace when switching.
Background polling skips an active load; user navigation cancels the previous
request. The shared renderer's bottom-following/message-anchor behavior remains.
An individual trace's first open still reads its complete recording, including
diagnostics; lazy loading individual diagnostic messages is not implemented.

The historical portable/Civ5 catalog uses its existing compatibility parser.
The shared utility's standalone `--runs` viewer is unchanged; this loader is
installed by the project hub when it serves the shared viewer HTML. Restart the
hub process and reload the page after changing the loader/backend.

Focused verification:

```sh
.venv/bin/python -m pytest -q tests/test_trace_hub.py
node tests/trace_hub_client.test.mjs
```

The Python checks cover lazy discovery, cache invalidation and bounds,
concurrent readers, persisted usage totals, conditional/gzip responses and
artifact isolation. The JavaScript checks exercise request races, navigation,
ETag reuse and scroll-mode selection with controlled responses. They do not
replace a real-browser layout check.
