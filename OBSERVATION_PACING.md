# Optional pacing before fresh observations

`run_episode(..., before_observation=backend.wait_until_ready)` enables the `paced-fresh-v1` lifecycle. The default remains `post-transition-v1`: existing callers keep the original observations, prompts and action sequence. Existing calibration wrappers and profiles were not edited.

```python
run_episode(
    environment_factory,
    backend,
    metadata,
    before_observation=backend.wait_until_ready,
)
```

The hook takes no arguments and may return JSON-serializable diagnostics (or `None`). Those diagnostics are saved in the trace only, never appended to policy messages. It must not dispatch inference, reserve a request or execute browser actions. Unserializable diagnostics stop before inference and remain a loggable failure.

The enabled order for each decision is:

1. Call the readiness/pacing hook.
2. Refresh the current page observation using the version-pinned BrowserGym adapter.
3. Save that decision observation and construct the ordinary goal/history/AX prompt.
4. Call `backend.complete(messages)`, where the new wrapper rechecks source fingerprints and reserves the request before one dispatch.
5. Parse and execute one action, save its post-action observation, and retain the existing task hooks and terminal evaluation-before-close behavior.

A new wrapper should move its sleep out of `complete`. It must still protect shared budget state, recheck readiness after acquiring any dispatch lock, and fail before reservation/dispatch if a concurrent sender changed the deadline. **Do not sleep again inside `complete` on an already-captured prompt.** This hook does not replace the wrapper’s ledger, concurrency controls, reservation or HTTP logging. Curation owns the separately frozen wrapper that adopts it.

## BrowserGym adapter

BrowserGym 0.14.3 does not expose a public observation-only refresh. `intent_browser/observation.py` uses its existing `_get_obs()` extraction and rejects unreviewed versions. It performs DOM/AX/screenshot extraction without calling `env.step`, validating the task, incrementing action counts, or issuing a fake `noop`. The upstream extraction temporarily marks DOM elements with BrowserGym attributes and performs its normal cleanup.

There is still an initial reset observation and a post-action observation. A refresh does not overwrite either. It also occurs after search decisions when the hook is enabled, while retaining the latest public search result. Independent grader data and hook diagnostics do not enter the model prompt.

Fresh capture after pacing removes the avoidable wait before dispatch; a short-lived control can still expire during model inference. This change does not automatically retry, replay or replace a model action.

## Trace additions

- `metadata.observation_lifecycle`: `paced-fresh-v1` or `post-transition-v1`.
- `decision-observation-NNN.{txt,json.gz,png}`: the fresh decision input. The existing `observation-NNN.*` files retain reset/post-action snapshots.
- Each step’s `observation` points at the input actually used; `transition_observation` retains the preceding artifact and `next_observation` retains the next result.
- `observation_text_sha256` hashes the UTF-8 observation text. `messages_sha256` hashes the runner’s messages using sorted-key compact JSON, UTF-8, unescaped Unicode. `delivered_messages_sha256` hashes the exact backend request’s messages when a request is retained. A backend may legitimately enrich messages; both versions remain available and are not assumed identical.
- Lifecycle events bracket waiting and observation capture; `model_started` names the exact observation reference and message digest.
- `pacing_seconds` measures the hook. `request_seconds` measures `backend.complete`, including validation/reservation and completion processing, **not pure HTTP latency**. Both are recorded on failure. `inference_seconds` remains a legacy alias of request-phase time; old wrappers that still sleep internally will still include that sleep.
- `observation_capture_seconds` measures fresh extraction, and `observation_age_lower_bound_seconds_at_model_call` measures time since extraction finished. DOM/AX/screenshot capture is not atomic; this is deliberately a lower bound, not a wire-dispatch timestamp. A new wrapper must log actual dispatch/header/body timing separately.
- `browser_step_seconds` measures `env.step`, including BrowserGym’s normal extraction. Summary `timing_totals` adds the measured phases; it is not total episode wall time. `action_error_count` distinguishes recoverable browser errors from a fatal `error`.
- Failures identify their phase. A failed wait/capture/source check does not inherit the previous request. A transport timeout after dispatch retains the current attempted request when the backend exposes `last_request`.

These are additive fields within the portable trace format. Model requests remain null for scripted backends that made no network request. Preview consumers may keep showing post-action images; consumers displaying policy inputs should follow each step’s `observation` reference rather than infer filenames.

## Validation

```bash
.venv/bin/python -m pytest -q tests
.venv/bin/python -m scripts.verify_observation_pacing
```

Current unit result: 66 tests and 23 subtests pass, including eight pacing tests. Fake-clock tests prove wait → fresh capture/prompt → source recheck/reservation → single dispatch, request/error association, no-hook compatibility, search behavior, hidden-data exclusion, and evaluation before close.

The scripted Chromium comparison uses a two-second notification and a three-second inter-decision wait:

- Legacy internal wait: the delivered snapshot still contains `Transient Close`; one stale click fails, and Continue is not reached.
- Fresh capture after the hook: the delivered snapshot omits the expired control; the same scripted selector picks Continue and completes the fixture with zero action errors.

Both cases make exactly two scripted decisions/two browser actions, with no inference or search calls. Native authorization and safe-success labels remain null. Exact fixture state, traces, timings and source/artifact hashes are in `config/observation_pacing_validation.json`; the reproducible script also writes `.local/preflight/observation-pacing.json`. The earlier development trace `20260914T232528Z-9422dd0d` is retained separately: its control behavior was correct, but the first script incorrectly expected a false native label rather than null for an unterminated episode. It is not one of the final two validation cases.

Adopt this in a **new** curation wrapper/profile and refresh its pinned import closure before any future model run. This does not repair the Chaos form event queue or seeded generator; those remain separate versioned changes.
