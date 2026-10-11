# Opt-in env.step phase and RPC diagnostics

Enable this only for a newly bound diagnostic episode:

```python
run_episode(..., env_step_telemetry=True)
```

Alternatively set `HARNESS_ENV_STEP_TELEMETRY=1` for the existing launcher.
The runner default is `None`, resolving an absent variable as disabled; explicit
`False` overrides the variable. Only literal `0` or `1` are accepted. No tool,
prompt, action timeout, wait, capture deadline or retry policy changes. Disabled
episodes create no telemetry artifact or metadata entry. Root/helper dispatch
forwards the resolved option, with separate per-episode diagnostic files.

On the first browser action, the runner creates the exclusive trace-local
`env-step-telemetry.jsonl`. Each start/finish line is flushed immediately, before
an existing wait; an outer process termination can retain an unmatched start.
No background writer, browser request, clock-based abort, signal or action replay
is added. This is diagnostic I/O and can affect timings while enabled; it is not
a performance benchmark mode. Normal buffered `debug_timings` remains separate.

The artifact records step index, tool name, relative monotonic time, nested phase
IDs and RPC IDs. Native BrowserGym 0.14.3 execution records `pre_step`,
`action_execution`, `post_step`, load waits, validation and `_get_obs`. Existing
Playwright 1.44.0 connection sends record the protocol method/channel type and,
for a CDP send, its method such as `Fetch.fulfillRequest` or
`Accessibility.getFullAXTree`. Arguments, URLs, expressions, response bodies,
exception text and stack locals are omitted. Starts precede send; completion
observes the existing future, without cancelling it or waiting again.

To inspect an unfinished episode, find its last unmatched phase and RPC starts.
For example, a successful `action_execution` finish followed by an unmatched
`_get_obs` start localizes the wait to post-action capture. A pending
`Fetch.fulfillRequest` identifies a routing acknowledgement wait. Neither implies
that the underlying site request failed; a sent command may already have effects.
Telemetry is not a task verdict or proof an action was committed. The outer
`tool_started`/`tool_completed` boundary still includes the full environment step.

Hooks are instance-local and restored after each step, including exception paths.
The native step code is retained unchanged with an instance-local execution
callback; no BrowserGym or Playwright package globals are patched. Existing
capture/routing connection instrumentation is preserved. A custom step wrapper
gets coarse method/RPC diagnostics plus `execution_boundary_unavailable`; it must
not be described as having a separately observed native action-execution phase.
Only RPCs using the active task page's existing connection are observed; a second
independently launched chat connection or a direct socket transport is outside
this scope. Native capture subphases that perform no RPC remain within `_get_obs`.

Direct use can add the diagnostic boundary without replacing an older runner:

```python
from intent_browser.step_telemetry import EnvStepTelemetry

recorder = EnvStepTelemetry(trace.directory)
try:
    with recorder.observe(env.unwrapped, step=15, tool="click"):
        result = env.step(action)
finally:
    recorder.close()
```

The runtime owner must retain the recorder across steps and use it only on the
Playwright owner thread. A closed, nested or conflicting active connection scope
is rejected before dispatch. Finite defaults are 20,000 rows and 4 MiB per episode;
`telemetry_limit` explicitly ends recording while execution continues. Diagnostic
write errors after creation stop recording, preserve execution and are recorded
by type in normal final metadata. Exclusive-file creation or unsupported versions
can fail before action dispatch. There is no implicit overwrite, retry or fallback.
The file is flushed to the OS, not fsynced; abrupt process exit is covered, power
loss durability is not claimed. After early termination, final metadata may be
absent or reflect its earlier snapshot; the saved JSONL prefix is authoritative
for the diagnostic events it contains.

Source/synthetic tests use the installed native BrowserGym step with protocol
doubles, a zero-provider runner fixture and a disposable abrupt-exit Python child.
They do not certify a real browser, website application, logical-origin bridge or
previously stalled radio. Prospective Website-owned browser diagnostic binding
and Evaluation runtime adoption remain separate.
