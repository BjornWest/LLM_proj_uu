# Expanded task execution bridge

This is the shared adapter entrypoint for local suites and the private Vercel
worker. It covers the reviewed selection of 100 Tricky and 103 WebArena task
bindings. It does not provide a second set of task graders. Current state is
local integration validation; worker/deployment acceptance is separate.

See [CONTRACT.md](CONTRACT.md) for lifecycle, privileged reads, reset ownership,
partial grading coverage and the post-close HAR boundary.

## Build the private registry

From the repository root, using the previously reviewed private binding export:

```bash
python3 -m data.curation.worker_integration.bindings \
  --output .local/curation-expansion/worker-registry-NEW.json
.venv/bin/python -m unittest data.curation.worker_integration.test_bridge -q
```

The builder checks all 203 public objective texts against the pinned private
contracts, retains per-task step caps and terminal instructions, and assigns a
revision to each portable binding. Output creation is exclusive. This private
registry and contracts belong in the worker package, never public site assets.
The existing public review catalog remains unchanged.

## Common invocation

Both the suite entrypoint and worker dispatcher use:

```python
from data.curation.worker_integration.context import RuntimeContext
from data.curation.worker_integration.tasks import make_task
from intent_browser.task_finalization import finalize_task_run
from intent_browser.expanded_tasks import runner_options

context = RuntimeContext(
    registry_path=private_registry,
    fixture_root=complete_tricky_fixture,
    origins={site: dedicated_lease.origin},  # WebArena only
    browser_proxy=dedicated_lease.browser_proxy,
    attest=dedicated_lease.attest,
    state_read=dedicated_lease.state_read,
    native_grade=pinned_native_evaluator,
)
task = make_task(task_id, runtime_context=context, revision=task_revision)
# run_episode(..., episode_task=task, **runner_options(task.row)) uses the row's native profile,
# exact goal/terminal instruction, max_steps and 48000-character observation cap.
# Its environment factory calls task.make_env(video, action_mapping).
# Wait before fresh observation; native request reservation remains backend-owned.
# After run_episode returns and has closed the environment:
authoritative = finalize_task_run(task, trace_directory, summary)
# Publish/archive only after finalization; retain original runtime evaluation.
# Finally task.close(), backend.close(), and release the dedicated lease.
```

Tricky needs no lease: it creates a private fixture server and a fresh browser
context. WebArena requires a dedicated, reset-attested instance even for read-only
tasks. The backend supplies that host service; the adapter has no Docker socket or
arbitrary SQL capability. Do not substitute manual browsing or benchmark servers.
Never serialize `RuntimeContext` or proxy credentials into task metadata.

The native evaluator can run in the existing offline pinned environment:

```bash
.local/webarena-verified/venv/bin/python \
  -m data.curation.worker_integration.native_grader \
  --input PRIVATE_INPUT.json --output NEW_PRIVATE_RESULT.json
```

Its input contains task_id, exact parsed response, har_path and configured origins.
It checks package version 1.2.3 and exact dataset bytes. This command only grades
saved evidence; it does not execute a browser or call a model.

## Scripted checks

One fresh task rehearsal, using the real runner/native parser with an offline
HTTP transport and a privileged browser-derived test driver:

```bash
.venv/bin/python -m data.curation.worker_integration.verify_tricky \
  --task tricky:AU21 --registry PRIVATE_REGISTRY.json \
  --output .local/curation-expansion/NEW-CASE
# Add --negative for the existing negative control.
```

Other checks:

```bash
.venv/bin/python -m data.curation.worker_integration.verify_proxy \
  --output .local/curation-expansion/NEW-PROXY-CHECK
.venv/bin/python -m data.curation.worker_integration.audit_saved_collectors \
  --registry PRIVATE_REGISTRY.json \
  --output .local/curation-expansion/NEW-SAVED-REPLAY
```

The proxy check is synthetic: bootstrap HTTP read → browser navigation → final
private HTTP read, sharing server-issued cookies and retaining a secret-free HAR.
Saved collector replay compares parsing/grading against retained mutation traces;
it is not fresh application execution or host reset validation.

All these commands use zero model calls. Scripted acceptance is not teacher-model
performance, and no task becomes training-eligible merely by passing integration.

Dedicated WebArena rehearsals use the same shared profile builder as the worker:

```bash
# Set WORKER_SITE_SERVICE_TOKEN from the private local credential file first.
# Coordinate ownership of the dedicated forum slot; never use the manual pool.
.venv/bin/python -m data.curation.worker_integration.verify_webarena \
  --task webarena:399 --registry PRIVATE_REGISTRY.json \
  --service-url http://127.0.0.1:8897 \
  --action-timeout-ms 30000 \
  --output .local/curation-expansion/NEW-FORUM-CASE
```

The explicit deadline is a new runtime setting, recorded in each trace. Omitting
it retains the shared default. It changes how long a single browser action may
wait; it adds no click replay. Existing 5000ms cases stay as recorded. Production
selects this option through a reviewed worker certificate, not a queue argument.
Add `--negative` for the incorrect-outcome control. The special wishlist-only
`--wait-for-visible-idle` negative control retains every wait as a native action.

## Current local findings

`validation.json` links the retained checks. All 203 bindings construct with exact
reviewed goals. Tricky has 24 selected positive/negative integration cases across
all four sites and eight adapter groups, plus a fresh provenance-logging smoke.
This is family coverage, not a new browser execution of every task instance.

Dedicated WebArena tests exercise real resets, authenticated proxy, private
state queries and pre-/post-close evaluation. Native shopping retrieval, wishlist,
contact draft and forum vote each have valid positive/negative controls. The first
forum retrieval, biography and post cases produced expected independent grades
but reported cold-navigation action timeouts. Eight new controls using the shared
30000ms action deadline now pass with zero action errors. Their frozen plan and
separate audit verify all 828 artifact hashes; earlier 5000ms cases keep their
errors. Correct final state does not erase an action error. These controls ran
sequentially because they share one exclusive, reset-between-cases forum clone.

The wishlist negative control exposed two test issues: an outdated capitalized
locator, then a click while the page was visibly busy that sent no removal POST.
A new control used one logged native `noop(1000)` while the current AX was busy,
then clicked removal once. It passed with a correctly empty final wishlist. This
is an explicit test-plan variant using an existing tool, not hidden warm-up or
proof that every policy will wait correctly. Earlier traces remain untouched.

No model calls were made. These local results do not by themselves enable website
capabilities; backend-owned worker/container and publication checks remain.
