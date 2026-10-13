# Container job launcher

`scripts/run_container_job.py` is a separate Linux launcher for environments
without a usable systemd user manager. It does not change `run_bounded_job.py`,
historical VM releases or existing caller defaults. Its protocol is
`container-job-v1`.

## Invocation and deadlines

```bash
python3 scripts/run_container_job.py \
  --memory-mib 2048 --tasks 256 --receipt /run-results/case-unique \
  -- timeout --kill-after=30s 1800s python3 -I -B case.py

python3 scripts/run_container_job.py \
  --memory-mib 32768 --tasks 512 --receipt /run-results/serving-unique \
  --wall-seconds 1800 -- python3 serving_worker.py

python3 scripts/run_container_job.py --probe --receipt /run-results/probe-unique
```

Receipt directories must be new. A probe executes no payload and reports the
actual visible cgroup-v2 hierarchy, CPU affinity, descriptor limits and
`/dev/shm` capacity/free space. It also verifies pidfd open and signal-zero
against the running interpreter and kernel, without starting a payload. Execution requires finite, readable effective outer `memory.max` and
`pids.max`. It refuses missing/unlimited/unresolvable outer limits before exec;
requested thresholds must fit those observed outer limits. Probe mode can
describe unsupported limits without qualifying execution. Host installation
and resource qualification belong to the host owner.

Every execution has an internal monotonic wall deadline. Supply
`--wall-seconds`, or `CONTAINER_JOB_WALL_SECONDS`, or a leading GNU `timeout`
duration in the existing caller command. With a leading `timeout`, the guardian
uses a later backstop: duration + kill-after (two seconds if absent) + one second
+ two sample periods. This lets GNU timeout deliver its own signal and honor
its declared grace. This backstop starts at exec-gate release; finite preparation
has its own bound of the same duration from guardian start. Entry records the
anchor, and result records the effective monotonic deadline. Explicit/environment
wall limits remain strict from guardian start and take
precedence. The command itself is preserved.
Recognized timeout options are `--kill-after`, `-k`, `--signal`, `-s` (with a
separate argument), their long `=VALUE` forms, `--foreground`,
`--preserve-status`, `--verbose` and `-v`. Other forms need explicit
`--wall-seconds`. An earlier external/rental deadline may terminate the
guardian. No launcher deadline extends the rental's original deletion guard.

## What is enforced and observed

The outer cgroup limits are actual kernel limits shared with other container
processes. Per-job `--memory-mib` is a **sampled summed-RSS threshold**;
`--tasks` is a **sampled Linux thread-count threshold**, including subprocess
threads. The launcher installs no per-job kernel MemoryMax, swap limit,
CPU quota or GPU-memory limit. The default sample period is 100 ms, configurable
from 20 ms to 2 s. RSS can count shared pages more than once. Page cache, GPU
memory and resources started outside the owned process tree are not measured
as per-job RSS. Allocation and fork bursts can overshoot between samples.

`--cpus` optionally selects a subset of inherited affinity. Descendants inherit
it, and common numerical-library environment thread limits are set to two.
This does not stop cooperative code from changing its affinity or settings.

Nested instances of the **same exact launcher bytes** inherit a private
`CONTAINER_JOB_REGISTRY`. Registered child payload trees are excluded from the
parent's RSS/thread threshold and separately monitored by their own guardian;
the parent still counts child-guardian overhead. This keeps parent, pool and
case budgets distinct. Parent cleanup still covers the full descendant tree.
Resource violations and supervisor errors trigger immediate KILL containment rather than a graceful
TERM interval; the shared outer limits remain the final kernel bound.

Registrations use guardian/root PID plus `/proc` start ticks; stale records do
not exempt new PID occupants. A source mismatch fails closed. Normal complete
cleanup removes only the guardian's own ephemeral registration. Historical
entry/result records remain immutable.

This is cooperative process supervision, **not a security sandbox**. Same-user
payloads can modify accessible files, move resources elsewhere or tamper with
their inherited registry. Do not use this launcher as the isolation boundary
for arbitrary untrusted programs. The agent's Python sandbox remains separate.

## Ownership and cleanup

The launcher starts single-threaded with no pre-existing children. It verifies
Linux `PR_SET_CHILD_SUBREAPER` and pidfd support before a gated fork/exec.
`entry.json` is durably written and the job is registered before payload exec.
The supervisor discovers descendants by ancestry, including adopted orphans,
and signals through identity-bound pidfds. Python `os.pidfd_open` and
`signal.pidfd_send_signal` are used when available; managed Python builds
without those bindings use typed libc calls, or verified syscall numbers on
Linux x86_64/aarch64. Missing kernel support or permissions fail closed; there
is no bare-PID signal fallback. This capability is verified before exec and
recorded in the probe and entry.

Exited identities have their pidfds closed; reaped history retains only the
latest 64 PIDs plus a total count. Before exec, the guardian qualifies its
NOFILE hard limit against visible outer pids.max plus 64 descriptors, raising
only its soft limit when needed. The payload restores the original soft/hard
descriptor limits before exec; entry records both guardian and payload limits.
Native child signal defaults and blocked masks are restored before exec. The
immediate payload requests SIGKILL if its guardian dies. A recognized leading
GNU timeout instead requests SIGTERM so it can forward the signal and preserve
its own kill-after deadline. This does not prove whole-tree cleanup or produce
a guardian terminal receipt after guardian death; the outer rental guard remains
necessary, especially when timeout has no kill-after or cannot forward a signal. `setsid` and double-fork detachments
therefore remain discoverable. Sibling job trees are not selected.

SIGTERM, SIGINT, SIGHUP, deadline, threshold, supervisor failure and normal
command exit all lead to bounded cleanup. TERM is delivered once to each direct child, allowing forwarding wrappers and
nested guardians to handle graceful delivery below them. A wrapper that stays
alive without forwarding TERM prevents descendant grace; those descendants
receive KILL after the grace interval. Newly adopted orphan
roots receive their own TERM; KILL containment covers the whole identified tree.
Defaults are two seconds of grace and an eight-second cleanup limit. A leading
`timeout --kill-after=K` sets default grace to K and cleanup to max(8, K+2),
and refuses automatic grace/cleanup above that 60-second bound. Long kill-after
values therefore need explicit valid grace/cleanup options. The derived grace
applies to external signals and remaining descendants after normal command exit
as well as deadline stops. Explicit grace/cleanup options can override
these values. Repeated TERM does not interrupt a payload’s `finally` cleanup. Successful cleanup requires no
remaining observed live descendants and kernel `waitpid` reporting no children.
Cleanup failure returns nonzero and records remaining or unknown state; it
does not release capacity permits. Parent/service/native cleanup must still
follow their own protocols before containment is used.

SIGKILL, supervisor/container death, inaccessible kernel state and processes
blocked in uninterruptible kernel I/O can prevent complete cleanup or a final
receipt. Independent host/rental containment remains necessary. These receipts
do not prove remote model cancellation, billing stop, task success or capacity
lease release. There is no automatic episode retry.

## Receipt contract

- `launch.json`: schema, guardian PID/start ticks, executable basename and
  argument count. Raw command arguments and environment values are omitted.
- `entry.json`: immediate payload `root.pid`/`root.start_ticks`, distinct
  `supervisor` identity, observed outer bounds, CPU affinity, verified subreaper,
  sampled thresholds, deadline, accounting mode and explicit limitations.
  If the command is `timeout` or a worker wrapper, root identifies that wrapper;
  actual serving identity must come from `installed-serving.json`.
- `resources.jsonl`: observed RSS/threads/processes, identities, registered
  nested roots excluded from accounting and full owned-tree process count.
  `outer_counters` are raw readable cgroup counters for the shared outer group,
  not per-job accounting. The log has a configurable `--resource-log-bytes`
  budget (default 4 MiB); sampling, thresholds and observed peaks continue
  when it fills. Result fields report logged samples/bytes and truncation.
  `live_cpu_ticks` excludes already exited processes;
  it is not a complete cumulative job CPU total.
- `result.json`: raw command return code, launcher return code, first observed
  stop reason, gate-release/entry status, signals, observed peaks and actual
  cleanup/reap evidence. Normal command failures retain their exit code;
  deadline is 124, supervisor/refusal/cleanup failure 125, sampled threshold
  137, and an intercepted signal is `128 + signal`. Cleanup failure overrides
  the launcher code while preserving the original stop reason and command code.
  `returncode` is normalized to the actual CLI exit status;
  `command_returncode` remains negative for command death by signal.
  `root`, `supervisor` and `source_sha256` must match the recorded entry.
  `cleanup_verified` is true only for a forked payload whose cleanup reports
  complete, kernel `waitpid` reports no children, no live descendants remain
  and remaining state is known. Probe/preflight-only exits set it false.
- `probe.json` exists only for probe mode; `error.json` records an error class,
  errno and phase without copying raw exception arguments.

Counts and peaks are observations, not complete accounting or requested kernel
caps. No sampling of an allocation before exit does not establish zero memory
use. Receipts must retain their mode and must never be labelled `llmjobs.slice`
or VM/systemd enforcement.

Worker acceptance must require schema `container-job-v1`, mode
`monitored_process_tree`, entry/result source and guardian/root identities
matching its pins, `entry_verified: true`, `payload_gate_released: true`,
`cleanup_verified: true`, and its role's expected exit status. Qualification
normally expects zero; an intentional serving termination can expect 143 with
`first_stop_reason: signal` and `interrupt_signals` containing SIGTERM (15).
Neither a missing result nor `cleanup.complete` alone qualifies cleanup.

## Validation boundary

Local synthetic CPU tests exercise actual signals, deadlines, RSS/thread
thresholds, detached/double-fork cleanup, nested accounting, sibling isolation
and strict setup refusals, plus cgroup namespace and PID-reuse simulations.
Run them through the current local bounded launcher:

```bash
python3 scripts/run_bounded_job.py --memory-mib 1024 --tasks 96 -- \
  .venv/bin/python -I -B -m pytest -q -p no:cacheprovider \
  scripts/test_run_container_job.py
```

No local test establishes the Florida container's actual caps, SSH install,
serving identity, native browser/canonical/viewer composition or model readiness.
Use exact reviewed Git bytes and fresh host probes for prospective adoption.

Implementation references: [Linux subreaper semantics](https://www.man7.org/linux/man-pages/man2/PR_SET_CHILD_SUBREAPER.2const.html),
[Linux wait/reaping semantics](https://man7.org/linux/man-pages/man2/waitpid.2.html),
and [kernel cgroup-v2 documentation](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html).
