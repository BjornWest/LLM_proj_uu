# Ordered episode admission and environment prewarming

Prospective infrastructure; no frozen suite or model run is changed by this
module. Evaluation owns the queue and caller composition. Harness owns the
native environment-ready, model-session and cleanup boundaries. The queue is
independent of the provider/model and task type.

`scripts.episode_queue.run_ordered_suite` takes a mapping of exact selected case
IDs to frozen inputs, `run_case(value, admission)`, and these settings:

| Setting | Meaning |
| --- | --- |
| `max_concurrent_episodes` | Positive integer. Active lifecycle capacity includes setup, policy, formatter, native grading, publication and cleanup. |
| `start_order` | Exact unique permutation of the selected IDs, defaulting to their manifest order. |
| `prewarm_count` | Nonnegative integer, default one. Additional queued environments creating or parked ready. Zero leaves every later case cold. |

The supervisor records admission intent in this order. Startup, first provider
call and completion times may differ across concurrently admitted episodes.
Admission uses a rolling window: after one entire lifecycle ends, the next case
is admitted without waiting for other active cases. At most the active cap plus
warm depth can have environment setup in flight. The queue does not enforce a
memory-byte ceiling; existing bounded process/service accounting still applies.

The caller creates one isolated environment and invokes
`admission.environment_ready()` at its reviewed native setup/reset-ready hook.
Warm cases block there until admitted; later cold cases never call `run_case`.
The exact environment is reused once, with no second reset. The native hook
must refresh the actual observation after parking before constructing policy
input, preserving task, screenshot and fact-capture identity.

For Harness's opt-in `environment_admission(EpisodeReady)->None`, pass
`admission.runner_callback(EpisodeAdmissionCancelled)`, importing the cancellation
class from that case's exact frozen native namespace. It records immutable
episode/path/readiness-time metadata and translates cancellation to the runner's
native cleanup/finalization signal. It does not pass browser objects between
threads. A multi-root suite must run native cases in separate processes: adapt
the child's readiness/activation channel to this gate, rather than importing
all frozen case roots in the scheduler threads.

`scripts.episode_queue_channel` provides a bounded JSON-only inherited-socket
channel for that process boundary. The child attaches
`ChildAdmission.environment_admission` to the native runner and
`ChildAdmission.before_dispatch` before every policy/formatter dispatch. The
parent's case worker runs `serve_admission(socket, admission,
expected_run_root=...)`, then verifies child exit and the actual grade/HTTP
artifacts before returning. The child closes its socket after cleanup. Only
immutable trace identity/path/time crosses the channel, never an environment
or executable command. A case ID or run root mismatch is rejected. Parent and
child own their socket/process deadlines and stop handling; the channel does
not replace process-tree watchdogs or cancel an in-flight provider request.

The caller attaches the automatic grader and must use
`admission.check_active()` before every provider dispatch. No policy/formatter
lease or model request is permitted before activation. Native backends which
begin a session before environment construction require a reviewed deferred
session boundary; the queue by itself does not retrofit that protocol. A caller
which omits or duplicates the ready boundary fails infrastructure validation.
Queue lifecycle completion is not a native task verdict.

Pass a shared `threading.Event` to stop admissions. Parked cases wake and raise
`QueueCancelled`; dispatch guards reject later calls. The caller owns native
finalization and cleanup in its exception/finally path. Its existing startup,
request and process-tree watchdogs must bound blocked setup or active requests;
Python threads cannot forcibly stop independently owned processes. Cold cases
are reported as `not_started`. There is no automatic retry.
If a worker thread cannot start, its row becomes a retained infrastructure
failure, all later admissions stop, and already parked workers are woken for
cleanup. No phantom active row waits for a nonexistent worker.

Queued waiting must not consume the active episode timeout. The absolute rental
expiry remains unchanged. A prospective process caller must bind admission to
its actual child-ready/activation channel and record queued, warming, ready,
admitted and terminal phases. Do not claim rollout adoption from these fake
lifecycle tests: required real native startup, cleanup, grader and HTTP viewer
acceptance precedes any new provider launch. Existing model runs and their
authorization remain separate.
