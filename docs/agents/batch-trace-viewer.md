# Batch trace review on the private website

The shared BrowserGym adapter emits one recorded model request/response per turn,
then a separately identified tool/result pair for every native call. The pinned
projection in `deploy/daylight/vendor/agent_trace` is the same source closure as
common_agent_util commit `0887af2`. Existing single-call traces remain supported.

The website's **Tools only** view retains its numbered chronological list. Calls
in the same model turn share a prominent header and bordered group with a call
count; numbering continues across groups. Results are matched by tool-call ID,
not array position. Skipped calls are explicitly not executed. Readable element
labels come from selected observations and earlier recorded AX tool results.
Document changes, removed nodes and full legacy snapshots invalidate stale
labels. Unknown targets retain their IDs. These labels describe recorded page
content, not inferred agent intent. Exact calls and results remain expandable.

The regular **Conversation** view starts with Agent outputs: turn grouping,
recorded reasoning disclosures, readable calls/results and the final user reply.
Full message records are collapsed underneath and retain the shared JSON/AX
renderer. Raw evidence is never rewritten. Reasoning is displayed only when
retained by the provider; opaque-only records are not decoded or invented.
Task grading remains separate from successful tool execution.

## Local validation

```
npm --prefix deploy/daylight run build
npm --prefix deploy/daylight test
.venv/bin/python scripts/smoke_batch_viewer_ui.py --episode PATH_TO_ROOM_BATCH_RUN
.venv/bin/python scripts/smoke_worker_replay_ui.py --episode PATH_TO_WORKER145_FAILURE
```

The browser checks use an isolated actual API handler, private SQLite store and
saved trace ZIP; inference access is blocked. They cover the eleven-call/four-turn
room form, descriptive fill/click labels, final reply, reasoning, mobile layout,
legacy malformed-response visibility, screenshot replay and zero agent writes.
The room form is a synthetic development diagnostic, not a benchmark score.

Control image `intent-browser-control:batch-viewer-v1` contains the new pinned
projection. The execution worker remains `expanded-candidate-v3`; publishing the
viewer does not enable native batches for existing production tasks. Previously
stored projections are immutable. Worker projections use the source fingerprint
in their cache key. Local trace publication is explicit and owner-scoped, using
`publish-library.mjs` after sample-specific confidentiality review; no Blob calls
or new model calls are required.
