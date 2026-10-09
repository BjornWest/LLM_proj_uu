# Native tool argument feedback

Native argument errors return structured `not_executed` feedback even when
`retry_policy=None`. The entire response batch is rejected before any action,
helper, or task callback dispatch; nothing is silently clamped. The agent may
correct arguments on its next ordinary turn within existing turn/context limits.

Each well-formed call keeps its ID and receives one matched tool result. Invalid
JSON, duplicate JSON keys, non-finite numbers and non-object argument roots stay
inert in a controller notice: raw response/IDs remain in the trace, but request
templates never need repaired arguments or outstanding malformed calls. Matched native-result call IDs are consumed and cannot be reused. Inert controller
proposals do not reserve wire IDs; a corrected call may reuse those IDs. Reasoning replay follows the profile.

This does not enable transport retries, replay actions, or recover unsafe call
identities, unsupported tools, navigation-policy violations on otherwise valid calls, or truncated output.
Invalid argument batches never navigate; any corrected URL must still pass the
configured origin boundary.
Strict `parse_completion` and `parse_batch` APIs still raise for offline validators.
Metadata records `invalid_argument_feedback` version `native-argument-rejection-v1`.
Failed proposals and their precise parameter diagnostic are retained in the trace;
correction does not claim task success. Automatic grading proceeds normally when
the episode later completes, using the existing attached grader.

`ax_read.limit` caps returned AX **nodes**, not tokens: default 20,
maximum 50. Token budgets/pagination may return fewer nodes; use `next_offset`
(or `next_text_offset` for node-text pagination) to continue.

Implemented in `NativeBrowserTools.parse_for_dispatch` and the native runner path.
The model controls whether/how to resubmit; a schema error consumes one ordinary
decision, not an extra provider call hidden outside the episode budget.

Decimal-valued integer parameters (such as `50.0`) are rejected without casting.
Oversized/deep JSON uses bounded inert history; exact originals remain in the trace.
Rejected proposal replay is limited to 4096 characters; feedback names encoding
bounds in characters, independently of model token limits. Skipped calls are counted
as proposals in the viewer, with no execution lifecycle events or effects.

Argument rejection does not reset an existing transport/structural failure chain:
only a successfully validated decision does. It also does not consume an additional
retry allowance. Rejected display strings are explicitly inert proposals, not
serialized executable browser calls. Overlong JSON integer literals return bounded
argument feedback without weakening Python's integer-conversion protection.
