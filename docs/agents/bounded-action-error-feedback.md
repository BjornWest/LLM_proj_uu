# Bounded action-error feedback

Implemented locally on 2026-09-21 after reviewing capability-suite AU41.
This change does not repair the site's obstructed quantity button and has not
been deployed to the running worker/container or tested with new inference.

## Failure and change

AU41's Increase Value click timed out while the quantity container/input
intercepted pointer events. Playwright's repeated actionability log was 6,420
Qwen tokens. Incremental AX presentation copied it into the non-pageable part
of a 2,000-token overview and crashed before the agent could recover.

`feedback_presentation.summarize_action_error` now retains the exception
headline and up to two distinct actionability blockers. Both compact single-call
feedback and native batch results use this presentation. Truncation/omission is
explicit; timeout feedback says effects are unconfirmed and requests inspection.
Full errors remain in raw observations, execution records and feedback artifacts.

`AXContext.page_update` applies the same summary plus tokenizer-based envelope
limits. JSON escaping is included in the check. Long URLs are explicitly marked
partial, and verbose diagnostics are omitted with a flag if they would exhaust
the envelope. Tree pagination and acknowledgment remain unchanged. Raw errors
remain the comparison key, so changes and clearing still generate updates.

Failed browser actions remain failures. The runner can continue on the next
decision, but a failed action stops the remaining calls in its current batch.
No automatic replay, argument coercion, verifier access or success inference was
added. Existing frozen evidence and results were not modified.

## Validation

- Six focused offline tests (with single/batched runner subcases) pass:
  `tests/test_action_error_feedback.py`. They cover repeated blockers, long
  targets, minimal budgets, escaped text, Unicode, long URLs, verbose metadata,
  acknowledgment, error changes/clearing, exact raw-error preservation, and a
  failed click followed by a separately selected fill action. These runner cases
  use a deterministic fake environment/backend, not a new model/browser run.
- 57 related AX-context, compact feedback, native batch/tools and execution
  feedback tests pass.
- Original AU41 saved input now produces a 98-token error summary and a
  1,955-token initial AX update (2,000-token limit). Its complete batch result is
  248 tokens, including timeout context. Counts use the existing local Qwen
  tokenizer and refer to serialized output/message text, not an API request.
- Saved-input evidence and final source hashes:
  `.local/review/action-error-feedback-v1/saved-au41-final.json`.

Run focused regressions with:

```bash
.venv/bin/python -m unittest tests.test_action_error_feedback -v
```

The suite schema-validation recovery issue is separate from browser-error
presentation. A subsequent local increment adds structured argument diagnostics;
see [model recovery](model-retry-and-provider-health.md).
