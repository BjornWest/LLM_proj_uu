# Human controls inside BrowserGym chat

UI attachment is implemented locally; Backend owns the runner/CLI attachment and
trusted chat delivery. Do not treat this isolated UI test as full-run readiness.

Call `HumanHandoverUI.attach_chat(env.chat.page)` once on the browser owner thread,
after reset, using the same controller passed to the runner. It preserves BrowserGym's
chat input/form/handlers and places a collapsible Agent controls section between
conversation and input. A new help request expands it. Start helping, Finished and
Cancel handover retain the controller's cycle/state checks. Returned means human
finished, not verified success. The standalone panel remains diagnostic fallback.

Attachment requires the private about:blank chat document and expected upstream DOM.
Same instance/document is idempotent; a different existing controller or closed/missing
chat fails explicitly. The caller, not matching HTML alone, establishes chat identity.
The return value contains only version/attached/already_attached. UI text never enters
chat.messages. This component alone does not deliver new user text to the model.

The browser polls/signals a loopback HTTP server independently of the owner thread.
Embedded requests require a separate per-instance capability, valid Host and opaque
Origin:null; null origin alone is insufficient. Only /_embedded/state and
/_embedded/signal receive this narrowly scoped CORS handling. Original standalone
endpoints retain their protections. CORS preflight returns no state; actual requests
always authenticate. No token is returned in attachment diagnostics, trace metadata
or controller events. Keep control-page code/credentials out of policy observations.

Validation: 13 offline controller/HTTP checks; native CDP human start/finish while
owner thread deliberately blocks, using upstream BrowserGym chat markup/callback.
Original chat input remains functional; controls create zero chat messages. Evidence:
`.local/coordination/human-tab-handover/chat-ui-acceptance-v1/`. The test launch differs
only to enable independent CDP access and does not run a model.

Reproduce: `python -m scripts.verify_human_handover_chat --output NEW_DIRECTORY`
with the workstation native-browser library path. Shared runner concurrency, model
request delivery and source readiness need their separate Backend acceptance.
