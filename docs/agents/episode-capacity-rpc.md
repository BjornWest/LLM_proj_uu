# Prospective queue/capacity composition

`scripts/episode_capacity_rpc.py` adds a private inherited-socket RPC adapter
around Training's `EpisodeCapacityController`. The outer caller owns one
controller and one `SharedMetricsPoller` per dedicated serving model/engine.
Children never poll metrics or share prompts, HTTP clients, or browsers.
After spawning each child, close the supervising process's duplicate of that
child-end socket. Retaining it hides child death from the parent RPC endpoint.

Create socket pairs for the finite suite and pass only each child's socket to
that process. Give the parent the other ends, unique `run:case` identities and
the existing finite caller/rental deadline. Start `CapacityParent`, then wrap
each existing parent scheduler admission in `ActiveCapacityAdmission`. This
waits for ordinary queue activation before registering the episode. Warming
remains unchanged and cannot claim generation permits. Keep the controller's
active cap equal to the queue cap; sticky parked episodes still count.

In each case create one `CapacityClient`, shared by policy and formatter.
Wrap each phase's backend in `CapacityBackend`, explicitly qualifying its
buffered, synchronous completion semantics. The first composition deliberately
does not opt into background pipeline completion. Native tool configuration,
model identity, session routing and ordinary backend attributes delegate to
the original backend. Source/active/deadline and browser-freshness guards must
be idempotent; they run again after parking, without consuming budget twice.
The caller must supply the actual freshness check, not a no-op in production.
Raw backend request hooks remain in force. This does not change tool/turn/token
limits, admission cost accounting or configured retry policy.
`runner_callback` also preserves the original queue's native cancellation
translation while registering capacity after activation. Do not call an inner
queue callback directly. Source readiness is delegated, never invented.

The generation permit covers the entire buffered `complete()` and releases in
`finally` after HTTP success, timeout, network failure, parsing error or failed
post-wait guard. Streams are unsupported. Each connection binds one case;
policy and formatter share strictly increasing request sequences. One thread
per case allows other releases, parent cancellations and telemetry updates to
proceed while an acquisition is blocked. There is no TCP listener or command
execution protocol.
Pass a durable `on_event` sink to the production `CapacityClient`; it receives
metrics freshness while waiting, per-phase acquisition wait seconds, and any
release failure. Events contain monotonic timestamps. Permit events distinguish
client round-trip wait from controller acquisition wait; failed waits record
their duration too. Linux poll supports high-numbered fds, with a wake socket
that avoids a fixed polling delay on fast grants.
Separate parked time from model inference timing and account
for it in observation age. Parent receives use the absolute deadline; valid
releases get a five-second cleanup grace, which never authorizes generation.
If release fails, retain a paid response/original provider error and mark the
client broken. The outer caller MUST persist `client.infrastructure_error`
and classify terminal infrastructure failure before queue refill. Further
generation fails closed. This is response preservation, not a successful RPC
or permission to continue the episode. A production sink failure is itself
an infrastructure error.
Interrupts, watchdog `TimeoutError`, and non-I/O control exceptions always
propagate. If a completion arrived before the interruption, the backend stores
it in `interrupted_completion`; the outer caller must save it as paid-response
evidence without executing its proposed action. It is not an ordinary return
or permission to act after an interrupt.

On child/channel loss the parent cancels future waits but retains any acquired
permit. A socket disconnect does not prove that remote generation stopped.
An EOF watcher cancels an unsent waiting acquisition; it cannot create a
phantom permit ahead of live cases. Already-sent permits stay owned. Clean EOF
after release and ordinary terminal completion are not cancellation events.
Only the trusted outer caller may invoke `finish_after_cleanup`, after process
exit/client shutdown and actual remote HTTP abort/drain verification. Its two
callbacks must return literal `True`: cleanup verified, and terminal native
grading/projection or explicit infrastructure-failure evidence persisted.
The adapter then releases the exact retained permit and finishes the episode.
Cleanup failure retains active ownership; the outer scheduler must stop refill
and fail the suite instead of returning the lifecycle slot. Closing the parent
alone never frees permits or finishes cases. No RPC/model retries are added.

Remaining native integration dependency: clean EOF or failed cleanup leaves a
nonterminal controller row. Training's current API can select that ended row
as a parking victim. Training owns a separately requested dispatch-retirement
API that excludes it from acquisitions/victims/resume selection while keeping
active-cap accounting and outstanding HTTP ownership. Bind its exact reviewed
release before native rollout. Controller `turns`/turn events count grants,
not HTTP dispatches: a grant cancelled before sending a permit can appear
there. Use actual backend dispatch receipts for model-call counts.

Tests use the reviewed real controller, one local synthetic metrics exporter,
separate spawned processes and synthetic buffered HTTP generation. They cover
cap enforcement, both phases, sticky parking/resume, source/freshness checks,
dead-child ownership, high-fd sockets, signals during release, real queue
callbacks, concurrent finishes and terminal failures. The queue fixture is the
unchanged Git blob from `2ec98d0:scripts/episode_queue.py`, SHA256
`a367f8683a5c93f6db921cfb26db6728843ea5dd9e8753afa1f839c78b388181`.
It is test-only and does not replace runtime queue source.
Tests make zero provider/GPU/browser
calls. Actual frozen native-runner/browser/grade/viewer integration and actual
vLLM cache/offload behaviour remain unqualified. The current MiMo cohort is
unchanged; this is an additive future caller building block, not a production
rollout or a new episode authorization.
