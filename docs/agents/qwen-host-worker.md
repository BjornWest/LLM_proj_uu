# Qwen serving worker on an SSH host

This source is prepared for the Verda suite. GPU, OS libraries and actual full
wire acceptance remain runtime checks. Evaluation owns the exact suite caller,
worlds, grades, Events and viewer registration. The worker never allocates a VM,
installs packages, downloads weights or dispatches browser episodes.

`qwen_host_worker.py` starts serving and the qualification adapter in separate
systemd user services. Each receives the remaining **original allocation**
lifetime, memory/no-swap limits and `KillMode=control-group`; CUDA/compiler
children remain covered even when they create process sessions. Enable the user
manager and linger through the approved bootstrap. Serving must remain outside
the bounded browser job slice; it normally uses a 56 GiB host-memory cap.

An ordinary GPU container uses the explicit `execution_backend:
container-monitored-v1` and a separately reviewed `container_launcher` path/hash.
`bootstrap_qwen_container.sh` installs the same locked environments without
systemd. It requires visible finite cgroup v2 outer memory/task limits, zero
container swap and at least 1 GiB of shared memory. The launcher applies sampled
RSS/thread thresholds and subreaper/pidfd process containment. These are not
per-job kernel memory or task caps; bursts between samples remain possible.
The independent provider deletion watchdog is still required.

Serving and the qualification adapter each have a distinct guardian, payload
birth identity and original-rental wall deadline. The worker verifies their
actual entry/result schema, source hash and identities and requires verified
exec-gate release and complete cleanup. Internal service-state keys are an
interface shared with the VM backend, not fabricated systemd observations.
The source index must additionally cover `qwen_container_services.py`; the
caller injects the same reviewed launcher separately for browser jobs. Container
qualification does not establish nested Docker/Python sandbox availability.

Use the reviewed host export, runtime and actual B02 seed, not mutable modules.
The prospective wire qualifier pins Evaluation runtime SHA256
`35b5d8aa7bcf54f6940e41aa355a3e63288d0b5e51ad7ce4a9b729013d98d563`
from reviewed `47aa96f`; update the worker's runtime pin and source export together.
Its ordered counter projection remains
`e818865d35a1a4cd9c6d3abc1c3fa02786cad1cb8eb89bd57b870f2ae6b8c27e`.
The unchanged projection alone does not establish background request/cleanup
acceptance or fresh instance readiness. Keep older frozen qualifiers and receipts
unchanged. Integrate this Training pin update only with that Evaluation runtime;
older caller trees intentionally fail the exact source gate. CPU fixtures use
the composed tree's runtime by default; an isolated test tree may set
`QWEN_TEST_RUNTIME_SOURCE` to the exact external reviewed source.
The worker spec has schema `qwen-ssh-serving-worker-v1` and these fields:

| Field | Meaning |
| --- | --- |
| `rental` | Pin to actual approved allocation record: canonical distinct run/instance UUIDs, numeric allocation UTC, integer approved seconds, matching deadline, allocation authorization, and separate first-stack diagnostic authorization |
| `host_root`, `host_source_export` | Installed Training source root and immutable source-index pin/root ID covering all worker dependencies |
| `runtime`, `request`, `runtime_lock` | Exact reviewed Evaluation runtime, actual native B02 request and **installed serving environment** lock pins |
| `rl_python`, `browser_python` | Absolute managed environment interpreters |
| `snapshot` | Exact official HF revision017b9c7af6b5689d5dd426a76e0bc077eb5ca20a |
| `cache_root` | Existing absolute owned writable ordinary compiler-cache directory, with no root/write-directory aliases, escaped descendant aliases or overlap with frozen sources/run outputs; the compiler's separately validated read-only CUDA library link is allowed |
| `output_parent` | Existing private owned directory; worker creates a unique run UUID child |
| `server_memory_mib` | Explicit48–64GiB serving service ceiling; measure host RAM before choosing it |
| `reuse_capability` | Original actual capability pin, or null for separately approved first qualification |
| `dispatch_approval` | Separate finite-case approval pin, or null; qualification cannot create approval |

```bash
/opt/qwen-runtime/rl/.venv/bin/python -I -B \
  /opt/qwen-release/training/scripts/qwen_host_worker.py \
  --spec /private/qwen-worker-spec.json --spec-sha256 EXACT_SPEC_SHA256
```

Default only prints a plan. Add `--execute` on the authorized real Linux VM.
It refuses WSL, expired/unapproved rentals, missing diagnostic approval and
changed source hashes/modes. Neither this plan nor a source review is host
readiness. Bootstrap and full source/asset installation happen separately.

For a first stack, it performs the previously reviewed five diagnostic
generations; compatible later instances reuse actual capability without these
calls. `measure_qwen_host.py` reads the current owned process/executable/environment,
installed package and patch versions, official effective processor/tokenizer,
read-only `/tokenizer_info`, and backend decisions in a private snapshot of this
worker's new serving log. Missing or conflicting backend decisions fail; it
never substitutes requested `auto` settings for resolved selections. It labels
prefill/decode by the selected attention-backend **family**, separately records
GDN prefill/decode and vision backends, and leaves individual CUDA kernel tracing
outside this qualification. vLLM process-title changes use `SPT_NOENV=1` so the
actual exec environment remains inspectable. Model revision binds the trusted
HF snapshot/config; this is not a full shard-content integrity audit.

Complete actual session/source/lifetime-bound wire evidence is required before
publishing the first capability. It creates typed qualification, deployment and
processor proofs, then a fresh deployment receipt. On reuse it compares actual
current measurements with the original capability and all original typed proofs.
The read-only adapter validates these receipts again, binds the live listener and
publishes fresh readiness. No historical readiness is reused.

The worker prints and saves `worker-ready.json` with the actual live receipt pin.
Evaluation's separately approved caller can then run on the same host. That
caller must write `/private/qwen-runs/RUN_UUID/finish.json` after terminal
verification, with this exact shape:

```json
{"run_id":"ACTUAL_RUN_UUID","instance_id":"ACTUAL_INSTANCE_UUID",
 "serving_session_id":"ACTUAL_SESSION","reason":"completed"}
```

Reasons are `completed`, `caller_failed` or `aborted`. The marker controls service
lifetime, not grades; a failed task can still be a completed episode. The worker
stops its two services on this marker, original expiry, signal or worker error,
and writes `worker-terminal.json` plus a checksummed relative artifact index.
Cleanup errors remain explicit and must never be reported as clean shutdown.
The worker monitors both service birth identities and their invocations after
readiness. Adapter death/replacement stops serving immediately. Failed verified
service cleanup produces a nonzero CLI exit after preserving its terminal receipt.
Ambiguous service creation may only clean up a service bound to this run directory.
The caller's browser processes and terminal verification remain caller-owned.
Live SQLite return requires Evaluation's consistent snapshots, not copying an
actively written database. Stop the caller before final indexing when aborting.

The workstation returns compact observer/Events rows and incrementally syncs
regular trace artifacts over SSH; model request histories stay on the VM.
Use `rsync --partial --append-verify` for append-only journals and normal rsync
for immutable artifacts, never `--delete` against a historical local run. Register
the downloaded run and its frozen sources with the workstation viewer; remote
absolute paths are not automatically local paths. The worker index contains stable
worker files only (top-level files and `wire`, `measured`, `ready` subtrees);
it excludes the caller's `suite` subtree. Caller final artifacts and consistent
snapshots require separate finalization after caller cleanup. Changed files are
rejected while hashing. Failed service cleanup publishes an explicitly unfinalized
empty index, since its log may still be written. The worker index proves bytes,
not task completion, automatic-grade publication or Events delivery.

Provider credentials remain outside the GPU host. Before another rental, qualify
independent provider deletion supervision that survives workstation/agent loss;
the Florida attempt's workstation watchdog did not do this. Service expiry or VM
`shutdown` does not stop billing. Return artifacts within the finite rental,
delete the instance and created volumes, then confirm provider absence. Historical
overnight authorizations are consumed; source preparation grants no new rental,
storage or model dispatch allowance.

Runtime concurrency control is caller-owned. Construct the controller with
explicit fixed resource ceilings and use `limits()` followed by
`update_limits(max_active_episodes=...,max_generation_requests=...,expected_revision=...)`.
Defaults cannot invent more hardware capacity. Lower targets drain existing
active/parked episodes and generation requests; new admission waits, no current
request/prefix/policy is cancelled. Higher targets wake generation waiters. The
parent must update its queue target together with the controller, and preserve
pool/server/browser ceilings. Stale revisions and invalid/above-ceiling targets
are rejected. The private API must authenticate updates and record them.
