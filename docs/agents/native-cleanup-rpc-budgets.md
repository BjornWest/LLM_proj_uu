# Native cleanup RPC budgets

The runner applies its existing per-phase cleanup RPC budgets to all available
owned task and chat Playwright connections, including native and pooled episodes
without human-tab support. Task and remote chat connections may be distinct;
handles sharing a connection are deduplicated. No shared Chromium group or
sibling episode is closed by the budget. The phase event records the connection
count and configured RPC budget; nonbrowser callbacks remain supported.

This uses the existing qualified Playwright 1.44.0 cancellation adapter.
Timeouts retain unknown effects and cleanup errors; they do not replay operations
or certify successful teardown, recording, grading or lease release. All patched
connection methods are restored when the phase exits. This is an RPC-await budget,
not a guarantee against blocked synchronous Python callbacks or transport-stop
paths that bypass RPC wrapping. Evaluation's separate configurable parent case
watchdog and bounded containment remain necessary. It must contain only the
owned case, preserving shared Chromium and other episodes.

This source correction is prospective. Frozen runs, raw click-stall evidence and
existing provider/task/world bindings remain unchanged. Model-free synthetic
cancellation tests establish the adapter boundary; actual pooled browser and
provider adoption require separate qualification.
