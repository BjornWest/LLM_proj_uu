# Daylight action-response format correction

On 2026-09-15, production assist trace `e4f47e51-7c8f-4c50-93b4-3242bace140a`
recorded two successful selects (Ångström and three people) followed by a
Cloudflare response beginning “I have all the information needed”. The response
was plain text, not the JSON action required by the parser. All three HTTP
responses finished normally; every request had `stream:false` and no
`response_format`. The two client receipts and final raw response remain in the
original private trace. This was not a streaming failure.

## Correction

`deploy/daylight/lib/agent.mjs` now requests a strict `json_schema` response for
task/assist calls. Its four fields are action, nullable control ID, nullable
string/boolean value, and message. A final answer belongs in a `done` action's
message. Read-only legacy chat remains text. The provider allowlist, session ID,
price caps and `require_parameters:true` routing are retained. The reservation
bound includes the serialized schema as well as messages.

The [OpenRouter structured-output documentation](https://openrouter.ai/docs/guides/features/structured-outputs)
describes this request format and endpoint-dependent enforcement. A read-only
endpoint snapshot on 2026-09-15 advertised `response_format` and
`structured_outputs` for all seven configured providers. This is capability
metadata, not a successful live inference test.

Local control validation remains mandatory. Invalid JSON produces a readable
error, with the parser detail and unmodified output retained in the trace.
Responses with `finish_reason:length` cannot execute an action. There is no
automatic retry, prose-to-action conversion, rollback, or inferred successful
completion. Existing receipts survive a later format failure.

## Validation scope

Offline regression tests cover the observed sequence (successful select then
plain text), durable receipts/raw response/error detail, no replay, structured
done with a required client receipt, token cutoff, and requested routing/schema.
The normal browser UI tests use the actual handler with scripted HTTP responses.
They do not establish that every provider enforces the schema.

This change affects the browser-side Campus demo only. The BrowserGym worker,
historical sweep parser/profiles, saved evidence and budgets are unchanged.
Token streaming remains a separate pending UX feature.
