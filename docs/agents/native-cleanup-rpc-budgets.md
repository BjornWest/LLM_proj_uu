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


Qualified native resource teardown and pooled close dispatch separate budgets
for task teardown, task/chat contexts and owned client connections. Each new
resource gets a fresh deadline; one expired context budget must not starve a
later connection close. Pooled recording wrappers still execute around their
original close. The phase hook is scoped to that environment/PoolEpisode and
restored on exit. Nested lease closes dispatch individual resources instead of
sharing an enclosing five-second composite budget. Recording transfers within
one context still share that context's budget; any failure remains explicit.
The pool release acknowledgement is not proof that contexts, recordings or
native teardown succeeded. Unsupported custom closes retain their explicit
composite budget and independent owned-connection fallback. Version/connection
qualification failures remain fail-closed; parent containment is required.
