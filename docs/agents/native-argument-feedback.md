# Native tool argument feedback

Native argument errors return structured `not_executed` feedback even when
`retry_policy=None`. The entire response batch is rejected before any action,
helper, or task callback dispatch; nothing is silently clamped. The agent may
correct arguments on its next ordinary turn within existing turn/context limits.

Each well-formed call keeps its ID and receives one matched tool result. Invalid
JSON, duplicate JSON keys, non-finite numbers and non-object argument roots stay
inert in a controller notice: raw response/IDs remain in the trace, but request
templates never need repaired arguments or outstanding malformed calls. Rejected
call IDs are consumed and cannot be reused. Reasoning replay follows the profile.

This does not enable transport retries, replay actions, or recover unsafe call
identities, unsupported tools, navigation-policy violations, or truncated output.
Strict `parse_completion` and `parse_batch` APIs still raise for offline validators.
Metadata records `invalid_argument_feedback` version `native-argument-rejection-v1`.
Failed proposals and their precise parameter diagnostic are retained in the trace;
correction does not claim task success. Automatic grading proceeds normally when
the episode later completes, using the existing attached grader.

`ax_read.limit` caps returned AX **nodes**, not reviews or tokens: default 20,
maximum 50. Token budgets/pagination may return fewer nodes; use `next_offset`
(or `next_text_offset` for node-text pagination) to continue.

Implemented in `NativeBrowserTools.parse_for_dispatch` and the native runner path.
The model controls whether/how to resubmit; a schema error consumes one ordinary
decision, not an extra provider call hidden outside the episode budget.
