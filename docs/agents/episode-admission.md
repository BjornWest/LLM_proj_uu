# Opt-in environment-ready admission

`run_episode(..., environment_admission=callback)` parks a prepared root episode
on its browser owner thread. The callback receives a frozen
`intent_browser.episode_admission.EpisodeReady(episode_id, directory,
ready_monotonic)` and returns `None` when admitted. It receives no live browser.
The scheduler owns its blocking wait, cancellation wakeup, case ordering,
concurrency cap, warm depth and finite rental/startup/active deadlines.

The hook runs after real environment creation/reset, task initial capture,
runner context setup and automatic-grading binding. The opt-in path defers
`backend.begin_episode` until the callback returns and one real observation
refresh succeeds. It does not reset again, execute tools or call a provider while
parked. Fresh capture preserves the exact task goal and rechecks grading pins
before opening the model session. Root delegation forwards the hook once;
helpers do not inherit it. The default `None` preserves the original lifecycle.
Restoring an inherited checkpoint request is rejected before environment setup
when admission is enabled: replaying that immutable request would substitute old
page state for the fresh activation observation. Fresh episodes may still use
ordinary checkpoint recording; resumed episodes keep their existing nonqueued
lifecycle until a separate continuation/admission contract is qualified.

Raise `EpisodeAdmissionCancelled(reason)` to stop a parked episode. The runner
records `admission_cancelled`, closes its environment through normal cleanup and
retains an infrastructure cancellation rather than a native task verdict. It
skips native task evaluation/grading for this cancellation; zero decisions and
no model session/provider dispatch are recorded. Other callback, refresh or
session-start failures use existing error/finalization paths. Backend object
cleanup remains the caller's responsibility, including when no session began.

The backend constructor and `configure_tools` must not acquire a policy/formatter
lease or send requests. Do not pass a preclaimed suite episode. Existing
`ExternalAgentBackend` acquires its lease at `begin_episode`, but the runner
cannot undo a lease claimed before it is invoked. No formatter starts through
this hook. Any external deadline continues across parking; start the active
watchdog on the scheduler's admission signal, which includes fresh capture and
session setup. Setup and cleanup count against the scheduler's active cap as
defined by its separate contract.

Trace events distinguish `environment_ready_for_admission`, `episode_admitted`,
`activation_observation_refreshed`, cancellation/failure and session start.
`metadata.environment_admission` retains wait time and admission time. Monotonic
values are meaningful within the same running host; they are not portable wall
clock timestamps. Source capability does not qualify a real queue, browser
sharing, family tasks or prod/model dispatch; those require caller acceptance.
