# Finished worker traces in the shared viewer

Worker task replay and imported saved traces use the same pinned
`common_agent_util` renderer and BrowserGym projection. Live `/harness` watching
remains a monitor; completed archive-backed replays open `/trace-viewer`.
The original client-demo conversation and manual-session views remain specific
to their respective recording formats.

`GET /api/harness/jobs/:id/session` authorizes the invitation owner at the PC
control service, verifies original ZIP part hashes, safely extracts one episode,
and runs the pinned shared projection locally. This is a read-only derivative:
no model calls, action playback, grader execution, task mutation or public import.
The first open builds a cached derivative; later opens reuse it. Images load on
request through owner-authorized `replay-assets` routes. Cache keys include exact
archive part hashes and projection code; byte-identical media share existing CAS
storage. Private worker derivatives do not create duplicate library list entries.

The shared view retains exact saved requests/responses, including malformed
responses with reasoning but no tool call. It presents the recorded worker error,
final evaluation with nulls intact, and a download link to the unchanged original
ZIP. Historical absent metadata remains absent; current task registries do not
backfill it. The viewer does not claim failure recovery or recompute success.

Security boundaries: ownership is checked even on cached reads/conditional
responses; no extraction of symlinks, traversal, duplicate members, multiple
roots, encrypted entries or oversized files. The projector runs a fixed trusted
script, never archive-provided code or HTML. Limits: 200 MiB compressed,
512 MiB expanded, 64 MiB per file, 10,000 files, two cold projections concurrently,
20-second projection timeout. Failed imports are not indexed; temporary files are
removed. Existing archive access already scopes this evidence to the same owner.

Validation: `npm test` in `deploy/daylight`,
`python3 -m unittest tests.test_worker_trace_projection`, and
`.venv/bin/python scripts/smoke_worker_replay_ui.py --episode SAVED_EPISODE`.
The browser test exercises saved task145 (five responses, four actual actions,
one missing-call error), invitation API -> PC projection -> shared renderer,
original response equality, images, original ZIP link, and legacy replay redirect.
No inference or site actions are involved.

## Missing-call recovery decision

Task145's final raw HTTP200 response claimed `finish_reason: tool_calls` but
contained no `message.tool_calls`. It was not a completion-token cutoff and the
retained transport and parsed response agree. Model generation versus provider
normalization cannot be distinguished from this evidence. Earlier reasoning
was task-related but uncertain about canceled orders and category membership.

Proposed next harness change: at most one separately logged recovery request for
an unusable decision which executed no action, retaining original response and
cost and appending a short protocol correction. Never silently replay browser
actions or convert arbitrary narrative to an action. This is not implemented by
the viewer change; existing failed run and evaluation labels are preserved.
