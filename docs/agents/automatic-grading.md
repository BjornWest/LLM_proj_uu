# Required automatic episode grading

Current `intent_browser.runner.run_episode` requires a trusted automatic grading
contract for every new episode. An `EpisodeTask.evaluate` hook or a `verifier`
metadata string alone is insufficient. This applies prospectively; copied frozen
runners and old traces are not modified. Their new dispatchers must enforce an
explicit outer contract before dispatch and validate final grading publication.

## Caller API

```python
from intent_browser.automatic_grading import AutomaticGrading

contract = AutomaticGrading(
    contract_id="my-task-grader:v1",
    bind=bind_reference,
    grade=native_grade,
    project=canonical_evaluation,
    phase="after_close",
)
path, summary = run_episode(..., automatic_grading=contract)
```

The trusted callbacks are host code, never policy tools or model inputs:

| Callback | Inputs | Required result |
|---|---|---|
| `bind` | `(env, trace, initial_observation)` | A JSON object with `task_id`, actual displayed `goal_sha256`, and nonempty `reference_files` / `source_files` maps of absolute paths to SHA256 hashes. |
| `grade` | `(env, trace, outcome)` | Original native grade as a JSON object, or an `Evaluation`. Runs once. |
| `project` | `(native_grade, binding)` | An `Evaluation` establishing a verdict or an explicit inconclusive reason, with an automatic verifier and trust declaration. |
| `viewer_check` | `(trace, canonical_evaluation_dict)` | Evidence bound to the saved evaluation and episode, described below. |

`source_files` must include the source files for all four callbacks, and the
shared BrowserGym viewer adapter when using the default checker. Include the
native grader, task/reference interpretation and their relevant dependency
closure too; the host must specify it rather than relying on automatic import
introspection. Binding validates after setup, before the first completion.
Immutable file pins are checked before every completion and fully rechecked
around grading/publication. Callback identities are also recorded, including
for later external finalization. Mutable website journals are grading inputs,
not immutable reference-file pins.

`phase="before_close"` collects native state while the environment is alive.
`phase="after_close"` collects after `env.close` (for flushed HAR, for example).
Both publish after cleanup. The ordinary before-close evaluation hook remains
available and is preserved as `evaluation-before-close.json`; it is not silently
substituted for the automatic grade. Trace observation writes are flushed before
native grading. Recording/cleanup errors invalidate infrastructure completion.

### External native session lifecycle

Use `phase="external"` when the trusted owner must first close additional native
session/runtime resources outside `run_episode`. The runner produces a complete
browser trace, but its summary remains `pending_external`, with no success claim.
Then the owner calls:

```python
from intent_browser.automatic_grading import finalize_external
summary = finalize_external(path, contract)
```

The native grader verifies its own lifecycle and exact task/reference evidence;
`finalize_external` cannot itself prove that a separate service was closed. It
requires the original declared callbacks, immutable binding and complete trace.
A durable exclusive claim prevents concurrent/repeated native grading. Failed
finalization is not automatically retried. An old trace without a prospective
manifest cannot be silently adopted through this API.

### Viewer projection

The default `canonical_viewer_check` invokes the existing
`agent_trace.adapters.browsergym.project` from `common_agent_util` and compares
its actual privileged evaluation message with the saved `evaluation.json`.
Install the documented sibling dependency before launch, or supply a supported
custom checker. Missing dependency is detected before provider dispatch.

A custom checker must return:

```python
{
    "schema": "automatic-grade-projection-v1",
    "episode_id": trace.episode_id,
    "evaluation_sha256": sha256_of_saved_evaluation_json,
    "verified": True,
    # Additional native viewer registration / HTTP evidence as appropriate.
}
```

The default proves local adapter projection, not deployed HTTP availability.
An external viewer with a separately cached grade registry needs its own
registration/refresh and availability proof in the trusted checker. No native
AddressStateHub or deployed viewer has been modified by this increment.

## Explicit ungraded diagnostics

```python
run_episode(..., allow_ungraded=True,
            ungraded_reason="Inspect observation latency; no task-grade claim")
```

```bash
.venv/bin/python -m intent_browser.cli smoke --no-preview \
  --allow-ungraded --ungraded-reason 'Local browser controls diagnostic'
```

Neither a manual driver nor a missing adapter implies this escape. It cannot be
combined with an automatic contract. A diagnostic preserves browser-phase
results separately; its final task/authorization labels remain unknown. Helpers
have an explicit root-episode grading scope and no fabricated independent task
verdict; immutable root pins are checked before helper completions too.

For graded CLI launches, use `--grading-factory module:callable`. The trusted
factory receives `(episode_task, argparse_namespace)` and returns an
`AutomaticGrading`; there is no generic factory pretending all adapters provide
correctly bound automatic grading. Existing worker/demo/custom launchers must
adopt a task-specific contract or an explicitly authorized diagnostic escape
before switching to this current runner. This change does not deploy them.

## Evidence and failure semantics

- `automatic-grading.json`: declaration, task/reference/source binding, status.
- `automatic-grade.json`: unchanged native result, binding and source contract.
- `automatic-grade-projection.json`: saved viewer projection proof.
- `evaluation-before-close.json`: original browser-phase evaluation.
- `evaluation.json`: canonical final grade or explicit infrastructure failure.

Missing artifacts, wrong bindings, manual-only grades, failed graders and absent
viewer projections leave `success=null`, `infrastructure_completed=false` and a
separate `grading_error`. They do not become model task failures. Provider/setup
errors remain `execution_error`; cleanup errors remain separate. A valid native
grade can report task failure with infrastructure complete. Authorization and
avoidance unknowns remain unknown. Private references, results and bindings never
enter policy prompts.
