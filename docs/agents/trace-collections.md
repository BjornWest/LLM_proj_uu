# Trace viewer folders

The standard local viewer supports logical folder paths independent of episode
storage. Selecting a folder includes episodes assigned to it and to its
descendants, with exact segment boundaries (`Integration` excludes
`Integration-other`). Folders are shown as a tree with nested branches collapsed by default. Use
the arrow to expand a branch and the folder name to filter episodes. Expansion
is retained during refreshes; a selected deep link reveals its ancestors.
The chosen folder is kept in the URL. Explicit episode
links reveal their folder; `#latest` selects the latest episode in the current
folder.

Use **New folder** to create a path, including nested/empty folders. Use
**Select episodes**, the per-episode checkboxes or **Select folder**, then
**Move selected** to assign episodes to another folder. Folder selection reuses
sidebar cards. Moving a parent also moves helpers without their own overrides.
An individual helper assignment takes precedence over its parent's assignment.
Bulk selection is limited to 1,000 episodes per operation.

New BrowserGym episodes can declare their folder without changing `--output`:

```bash
intent-browser run ... --collection 'Integration/checkout'
```

Programmatic launchers pass `metadata={'collection': 'RL/experiment-1', ...}`
to `run_episode` or `Trace`. Paths are normalized and validated before creating
the recording. Helper recordings inherit their parent's declaration. The label
is recording metadata, not model input. Declarations are optional for backwards
compatibility; launch authorization and automatic-grading requirements remain
unchanged.

Existing traces default to their registered source folder. The project registry
can give a source a shorter logical label with an optional `collection_roots`
mapping from absolute source path to logical folder path. A recorded collection
declaration takes precedence over that fallback. Viewer moves take precedence
over both.

The shared single-root viewer stores assignments in
`ROOT/.trace-collections.json`. The project hub stores them in
`REGISTRY_PARENT/collections.json`. These files are viewer-owned metadata;
original metadata, steps, observations, evaluations and grade bindings are not
rewritten. A folder edit does not invalidate trace-body caches or ETags.

`GET /api/collections` supplies persistent empty folders and an edit revision.
`POST /api/collections` accepts `create` or `move` with a logical `path`, and
`episode_ids` for moves. It requires JSON, a bounded request, same-origin browser
requests and the current `If-Match` revision. Atomic replacement and a shared
file lock prevent partial writes and lost concurrent edits. A stale editor gets
409 and refreshes before another attempt. No request path becomes a filesystem
path. All trace/artifact routes remain read-only.

Zero-provider checks:

```bash
python3 scripts/run_bounded_job.py -- .venv/bin/python -m pytest \
  tests/test_trace_collections.py tests/test_trace_hub.py tests/test_ledger_trace_hub.py -q
python3 scripts/run_bounded_job.py -- .venv/bin/python scripts/check_trace_collections.py \
  --output .local/trace-viewer/collections-ui-check
```

The UI check runs the shared and hub modes concurrently with separate fixture
recordings, metadata files and browser sessions. It checks parent filtering,
prefix boundaries, persisted empty folders, bulk moves, cached card identity,
deep links, edit conflicts, invalid paths, mobile rendering and unchanged
recordings. No model or evaluation episode is dispatched.

The sidebar shows the last three recording-path segments below each episode
name, with the absolute location on hover. The trace heading shows the complete
absolute location. BrowserGym episodes show their recording directory; portable
groups show every source trace file, including groups combining multiple files.
Logical moves do not alter these locations. Older external catalogs without
location metadata omit the path rather than guessing one.

Tags combine with the selected folder scope. Open **Tags** and click a label to cycle neutral → green
(include) → red (exclude) → neutral. Green keeps traces with the tag; red hides
traces with the tag. Multiple include filters all must match and every exclude
filter must be absent, within the selected folder. Filters are preserved as
repeated `tag` and `exclude_tag` URL parameters. Clear tags resets both modes;
explicit episode links clear incompatible include/exclude filters. **Select episodes → Edit tags** adds or removes comma-
separated labels in bulk, preserving other labels. Sidebar badges show episode
tags. Recorded metadata may declare `tags` as a list of strings. Viewer edits
store additions/removals in the same separate metadata file, preserve folder
assignments and body caches, and can suppress a declared label without rewriting
the recording. Tags are independent per episode (no implicit helper inheritance).

Every scripted episode must declare `metadata.tags` including `scripted`.
New `Trace` recordings normalize caller tags and add the default for explicit
scripted driver labels (scripted as a hyphen/underscore/space-delimited token),
CLI smoke runs, or `model=scripted`. The viewer applies the same default to
recognized historical recordings without rewriting them; a viewer tag removal
can suppress it. Custom scripted drivers must pass the tag explicitly. Missing
models/zero counters and real model episodes launched by Python do not establish
scripted behavior and are not automatically tagged.


The trace heading and sidebar show the recorded episode end reason independently
of the grade. Turn limits (`max_steps`), input context token limits
(`max_input_tokens`), interruptions and manual close reasons are labeled directly;
recorded turn counts and configured limits appear when recorded. A turn-budget
stop can occur below the configured turn limit (for example, a shared helper-call
budget); the viewer preserves the recorded code rather than claiming the limit
was reached. **Recorded end details** shows the exact
reason, source and execution error. A saved `episode.json` is authoritative;
`episode_finished` lifecycle events provide a fallback. Missing reasons are
reported as unrecorded, never inferred from counters or a model response's
`finish_reason`. A hard process kill without a terminal record cannot establish
why the episode ended. The lazy hub catalog reads this from small summary/lifecycle
files without loading conversation history.
