# Native calls in live task summaries

The native batch runner saves calls in `steps.jsonl[].batch_calls`, leaving the
legacy single `action` null. The completed common_agent_util replay already reads
that representation. The team worker's live publisher still read only `action`,
so Workspace showed “No action recorded” even while the browser was acting.

The publisher now emits an ordered `calls` array, with call identity, action,
recorded/failed/skipped/unconfirmed state and browser-step evidence. Successful
AX queries are recorded tools even though they do not step the browser. Skipped
batch members remain skipped; a returned browser call is not proof of purchase
or any other graded outcome. A short `action` summary supports older clients.
Long live summaries are explicitly truncated; full originals stay in the archive.
The broker applies its existing 300,000-character snapshot envelope uniformly
instead of a smaller legacy-family bound. This is a transport size, not context.

Workspace conversation and tools-only views consume calls individually under
model turns; the embedded watch pane labels batches. Old null-only live summaries
are described as missing published details, not evidence that no call occurred.
Full finished traces still use the shared renderer. Available-tool definitions
remain unknown in the lightweight live projection; the complete request is in
the saved trace. This does not change model inputs, actions, accounting or graders.

Evidence: `.local/live-batches-v1/`. All 20 calls from the affected real run
`20260921T104140Z-ed12f5f8` survive the new projection. Unit/browser cases also
cover multi-call turns, AX queries, skipped/failed members, truncation and legacy
records. Local browser checks use offline transport; no paid calls or reruns.
The original published job record and trace remain unchanged. New summaries take
effect on new runs after the idle worker is replaced.

Image deltas derive from the actual-cost-v2 images; only team_worker.py and broker
presentation size handling change. Source-bound certificates retain parent hashes
and a presentation-only amendment. Append live-batches.override.yaml and select
the new certificate directory while preserving all data volumes.
