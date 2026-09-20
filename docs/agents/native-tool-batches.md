# Sequential native tool batches

Implemented locally as the opt-in `core-tools-v9-batch` profile. Existing
single-call profiles, production workers and saved cohorts have not been switched.
No paid model call was made for this increment.

## Interface

Select `--harness-profile core-tools-v9-batch` with an existing
`--ax-tokenizer-file`. The CLI includes screenshot support; image retention remains
selectable with `--image-retention retain|agent`. Programmatic callers use
`native_tools_profile(..., parallel_tool_calls=None, compact_feedback=True,
ax_config=incremental_config, batch_size=8)`, optionally with `vision_config`.
Task adapters must explicitly adopt the new profile before running it.

The tool definitions stay constant. A response may contain 1–8 native calls, all
validated against their schemas and URL allowlist before any call runs. IDs must
be unique, including across earlier responses. A final `send_msg_to_user` must be
the last member. Arguments are literals already known to the model: there is no
script evaluation or syntax for referring to the output of another call.

Calls execute sequentially without intervening inference. Every call gets one
matched tool result, including skipped calls. Execution status, errors and
positioning feedback belong to the individual call. Historical page events from
all executed calls are collected with call ordinals, passed through the common
bounded feedback presenter, and appended once. The next fresh AX update is
appended only to the last tool-result message. Intermediate AX snapshots/deltas
are retained as trace artifacts, not repeated as model context. Explicit AX-query
and screenshot results still belong to their individual calls; these are requested
content, not automatic page dumps.

The existing pacing/fresh-observation hook still runs before the next inference.
Transient notices are retained from the action windows; final AX is not presented
as proof that a particular call caused a change. Common selection budgets and
omission indicators apply to the consolidated event stream.

## Boundaries

- Any invalid member rejects the entire proposed batch before execution.
- A browser action error or tool-reported error stops the remaining members.
  Previously completed effects are retained. No automatic action retry/rollback.
- A document, frame, tab or URL change stops the remaining members, including
  same-URL reloads. This first version deliberately uses a conservative barrier.
- Before each call, refresh public browser observations. A BID must still have
  the same DOM/role/name and ancestor identity as in the decision observation;
  missing, ambiguous or relabeled targets stop the remainder.
- These checks reduce stale-target mistakes; they cannot make arbitrary sites
  transactional or prevent every JavaScript race between checking and clicking.
- Environment termination stops the remainder. Unexpected execution exceptions
  retain the attempted call, mark its effect unknown, skip the remainder and end
  the episode. Decision-generation recovery never retries these actions.
- `max_steps` remains the model-decision cap. Up to eight calls can execute per
  decision, so the browser-call bound is eight times that cap. Search's existing
  quota remains independently enforced.

## Trace contract

One `steps.jsonl` row still corresponds to one model decision and contains the
exact request/response once. Batch rows use `kind: batch`, `batch_calls`, `actions`
and `batch_stop_reason`; the singular `action` is null rather than an invented
combined command. Each member records its own action, ID, execution index, guard
observation, feedback, transition and error/skipped status. Lifecycle events also
record `batch_call_completed`. `execution_index` names unique per-call artifacts;
`step` continues to mean model-decision index. Delivery bindings cover each tool
result and the single final observation. Raw reasoning is preserved as before.

Consumers must count `batch_calls` rather than treating the null singular action
as no activity. Existing older viewer projections need that additive awareness
before they can show individual batch actions in their tool-only timeline; exact
native responses/results and nested trace evidence are already retained. This
increment does not publish a viewer or worker release.

## Offline acceptance

Run in parallel local Chromium contexts, with HTTP model responses mocked:

```bash
.venv/bin/python scripts/verify_native_batch.py --output .local/preflight/NEW-batch-check
.venv/bin/python -m unittest tests.test_native_batch -q
```

Current browser evidence: `.local/preflight/native-batch-v4/report.json`, nine
cases: three-action form, navigation, same-URL reload, relabeled target, failed
action, malformed second member (zero executed calls), two distinct screenshots
and two image releases, multiple AX queries, and environment termination mid-batch.
Every result/observation delivery binding was checked; private sentinel data was
absent from requests. Evaluation preceded environment close. Retained v1/v2 runs
caught trace-event naming and evidence-kind integration errors; they are not
passing acceptance reports. V3 passed the initial seven cases.

The 113-test focused regression suite covers legacy native calls, bounded retry,
vision, pacing, policy delivery, feedback, AX and navigation. The browser report
contains exact source hashes and trace paths. This is scripted protocol/execution
validation, not evidence that Qwen will batch effectively; the model rerun is next.
