# Prospective queue/capacity composition

`scripts/episode_capacity_rpc.py` adds a private inherited-socket RPC adapter
around Training's `EpisodeCapacityController`. The outer caller owns one
controller and one `SharedMetricsPoller` per dedicated serving model/engine.
This revision requires the reviewed `retire_dispatch` API from Training
`103b2b9`; the old controller fails closed at construction.
Use the direct `EpisodeCapacityController` from its frozen module namespace.
Ordinary delegating/decorated/subclass/partial controller wrappers fail the
structural checks. These name/namespace checks do not prove source provenance:
lookalike names or instance-patched methods can bypass them. The outer caller
must verify the exact reviewed controller source/function bindings; such
wrappers and rebinding remain unqualified, even if construction succeeds.
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
Pass the same `threading.Event` to `CapacityParent(suite_stop_event=...)` and
`run_ordered_suite(stop_event=...)`. If omitted, the parent creates an event
that must then be passed as `parent.suite_stop_event` to the queue. Cleanup or
terminal-evidence failure sets that event before the case worker returns,
stopping the cohort, waking parked acquisitions and warm admissions, and
rejecting active siblings' next dispatch guards. Retained rows keep their permits
and lifecycle caps. `parent.stop_cause` retains the first case/type/message
and explicit infrastructure classification. `cleanup_failures` independently
records the first actual failed final verification per case, with its stage and
retained request ID, even after user cancellation or another first cause.
Caller-classified aborts are not final-verification evidence. `secondary_exits`
records later exits without overwriting the stop cause; it is bounded and is
not an authoritative cleanup ledger. A pure ordinary cancellation leaves
`cleanup_failures` empty, but any later failed final check populates it. An empty ledger is not completeness proof: require every activated case in
`parent.finished`, actual child exit and HTTP cleanup evidence, and join this
with the retained ledger. Later verified cleanup does not erase a prior failure.
The queue's `cancelled` boolean alone
does not express its cause. A differently bound queue stop event is unqualified.

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
The client's numeric `cleanup_timeout` is in `(0, 5]` seconds; it may only
shorten that IPC-only grace. A
`CapacityTransportTimeout` denotes our socket/deadline fault and preserves an
ordinary paid return/provider error, while a Python signal-handler
`TimeoutError` propagates. The distinction uses the traceback at the direct
builtin socket call; Python socket subclasses with overridden I/O are not
qualified transport implementations. Asynchronous CPython thread-injected
exceptions (such as `PyThreadState_SetAsyncExc`) cannot reliably be separated
from builtin socket timeouts by this traceback rule and are unqualified.
If release fails, retain a paid response/original provider error and mark the
client broken. The outer caller MUST persist `client.infrastructure_error`
and classify terminal infrastructure failure before queue refill. Further
generation fails closed. This is response preservation, not a successful RPC
or permission to continue the episode. A production sink failure is itself
an infrastructure error.
Parent error frames become `CapacityParentError` with `parent_reason`,
`parent_error_type` and `telemetry_fresh` attributes. The durable client event
`capacity_parent_error` carries these fields without requiring message parsing.
Local client deadline expiry can precede that frame, so join the parent's
retained diagnostic with the child error when classifying the terminal cause.
Parent-initiated socket shutdown can also prevent delivery of that frame.
Use the retained parent `stop_cause`/diagnostic as the authoritative cause in
that case, rather than interpreting a generic child EOF as a new peer failure.
Typed errors support copying/pickling across process boundaries. If the durable
event sink fails, its error retains the typed parent diagnostic in
`capacity_parent_error`. An existing sink cause is preserved; otherwise the
typed parent diagnostic becomes its cause. Pickled/copied errors retain notes.
Interrupts, signal-handler `TimeoutError`, and non-I/O control exceptions always
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
always shuts down its sockets, including protected rows, but never frees
permits or finishes cases. Without a stop cause its reason is `parent_close`;
it does not invent an infrastructure cause. No RPC/model retries are added.

At channel EOF, cancellation and before cleanup verification, the parent
calls `retire_dispatch`. It excludes the ended row from acquisitions, parking
victims and resume recipients, and clears its parking flags/bound credit. It
does not cancel a clean episode, finish it, release an HTTP request, free the
active lifecycle cap, or grant another actor a resume. Event consumers must
apply the same clearing rule on `dispatch_retired`; only verified terminal
cleanup followed by actual `finish_episode` can grant a resume.
An already-retired controller's acquisition wake becomes
`CapacityDispatchRetired` channel feedback,
without an `episode_cancelled` event. Explicit parent cancellation still
records cancellation, including when the dispatch was already retired.
The direct `ActiveCapacityAdmission.environment_ready` path raises the typed
`CapacitySuiteStopped`; only `runner_callback` translates that into the caller's
native cancellation class. A direct caller must classify it explicitly.
Other channel failures and EOF with a retained in-flight request remain
cancellation failures even if their row was retired earlier. Parent diagnostics
retain distinct `reason` values for retirement, explicit cancellation, rental
deadline, channel failure, in-flight disconnect, cohort abort and infrastructure
abort. Requested explicit cancellation is not relabelled by an unrelated later
cohort abort. The parent also checks
retirement immediately before sending a granted permit and releases an unsent
retired grant. Already-sent permits still require verified cleanup; production
dispatch guards must recheck admission after the permit.

Last-drainer policy: the caller owns bounded recovery attempts before calling
`finish_after_cleanup`, which is the final verification boundary. During that
recovery, retire dispatch but retain other actors' parked environments/leases
and all permits/caps. Verified success may finish the actor and resume a victim.
Failure of the final check is terminal for this cohort: set its stop event,
wake/cancel other local acquisitions immediately and stop refill. Retain all
sent requests until their actual HTTP abort/drain is verified. Later cleanup
can release retained ownership but never clears the stop or restarts the
cohort. `cleanup_failures` retains the original failure as historical evidence.
The existing finite caller/rental deadline bounds recovery and teardown; no
new arbitrary episode time/turn/token cutoff or model retry is introduced.

Every outer case path must use `try/except/finally` to own native process/HTTP
cleanup. If it exits before final verification, invoke
`parent.abort_after_failure(case, original_error, infrastructure=True)` before its queue worker
returns, then persist the infrastructure cause and perform bounded cleanup
without masking the original error. This also covers bad final-verifier
arguments; validation intentionally rejects them before cleanup starts.
The RPC cannot infer that an arbitrary outer function has returned or that
remote HTTP work has stopped. A caller omitting this failure binding is
unqualified. Tests exercise the early-failure binding, terminal failure with
active/warm/parked siblings, and verified success resuming a current victim.
Catch the caller's known native/user cancellation separately and use
`infrastructure=False`; a blanket exception handler cannot infer that cause.
The classification argument is mandatory. Later caller aborts only add secondary
exit evidence. Every genuine failure raised inside `finish_after_cleanup` is
recorded by the parent, independent of caller classification and stop order.
Coordinated abort/close cannot introduce cancellation of the infrastructure root,
an actor with a failed final check or an actor already in final verification.
An explicit standalone `cancel()` remains an intentional cancellation request.
This does not undo an earlier independent cancellation or genuine
child-death event. Parent-initiated shutdown is recorded as a cohort stop,
not as a child disconnect. All sent permits remain owned through either path.

Controller `turns`/turn events count grants,
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
When `scripts/episode_queue.py` exists in the composed root, tests exercise
that actual queue instead of the fixture. A host whose soft fd limit cannot
reach fd1100 explicitly skips the high-fd-only control; it does not claim that
qualification or silently change host limits. The ordinary controls still run.
Tests make zero provider/GPU/browser
calls. Actual frozen native-runner/browser/grade/viewer integration and actual
vLLM cache/offload behaviour remain unqualified. The current MiMo cohort is
unchanged; this is an additive future caller building block, not a production
rollout or a new episode authorization.

## Prospective native failure controls

The model-free native probe supports explicit `fault=cancel_warm` and
`fault=failed_close` controls. The first cancels the suite while a second actual
browser is prewarmed; the second injects a native close error after real cleanup.
Both stop refill and forbid requests from the warm actor. They distinguish
ordinary cancellation from infrastructure failure and require actual child,
identity-fenced browser-descendant, RPC, HTTP and tokenizer cleanup. They are
scripted infrastructure controls, not model results or GPU/KV restoration proof.
SIGTERM/SIGINT unwind native runner cleanup using a BaseException; bounded
termination escalates only identity-fenced descendants. Native positive and
failure evidence must bind the exact new probe/RPC files independently of old
cohorts. `psutil` is an explicit installed dependency of this probe.
