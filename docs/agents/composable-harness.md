# Composable harness: design and first implementation

The optional [progressive AX profile](progressive-ax.md) adds token-bounded
overviews, subtree-scoped search and traversal with explicit location references.
The [incremental context profile](incremental-ax-context.md) adds shared
verbose/repeat controls and delivered-region changes without rewriting history.

Status: local development implementation, 2026-09-16. Not deployed, not an
approved replacement for frozen benchmark profiles, and no model evaluation.

## Agreed direction

Navigation is now an opt-in local increment; see [navigation controls and proposed helper-agent contract](browser-navigation-and-subagents.md). Helpers remain unimplemented.

Formatting follow-up: [tokenizer measurements and relevant prior work](observation-formatting-study.md)
compare indentation on the saved refund trace without modifying policy observations.

## Native conversation layout: fresh observations in tool results

Implemented locally on 2026-09-17, recorded as
`harness_profile.conversation_layout = tool-result-observation-v1` in new native
episodes. This supersedes the separate user-role observations described in the
historical native-tool increment below. Existing saved requests and legacy/text
profiles are unchanged; no worker or Vercel rollout is part of this change.

The first request contains system instructions and one user message with the goal,
initial page evidence and observation. Later requests append exactly an assistant
tool call and its matching tool result. That result includes action feedback,
any intervening browser updates, and the current observation, under separate
headings. Search results follow the same protocol. There are no synthetic user
messages between tools and subsequent assistant decisions.

The conversation buffers the result until the runner has performed its existing
pacing hook and fresh observation capture. It then finalizes the message once;
no previously sent prefix is changed. Reasoning replay is unchanged. Exact raw
feedback, transition/decision observations, requests and responses remain in the
trace. Private delivery bindings identify exact feedback, update and observation
spans inside the combined message. Pending results at termination, pacing failure
or the step limit remain recorded but are not falsely labelled delivered.

Validation: native conversation/runner tests cover initial and delayed updates,
fresh-versus-transition observations, matched call IDs, immutable reasoning/history,
search, browser errors, failed pacing and unconfirmed HTTP timeouts. The scripted
Chromium suite `scripts/verify_native_tools.py --compact --output NEW_DIRECTORY`
also changes a visible marker during the pre-observation hook and checks that the
actual outgoing tool result contains the new capture. Evidence:
`.local/preflight/native-tool-observation-v1/report.json`. No paid inference.

## Agreed capabilities

- Append conversation messages by default. Preserve exact delivered requests.
  Measure prefix reuse in the eventual local inference server; do not infer
  cache hits from session IDs, routing or common text alone.
- Replace prefix-only page access with a bounded structural AX overview plus
  deterministic search and region expansion. Keep a flat-tree alternative.
  Do not hide site distractions or use verifier knowledge to select content.
- Offer screenshots on request for visual information or unresolved navigation
  problems. Do not automatically attach one after every action. Confirm model
  vision compatibility; a separate vision model is a different configuration.
- Capture general browser feedback: execution status, semantic changes,
  navigation, dialogs and transient announcements. Distinguish observed changes
  from causal attribution and verified outcomes. No dataset-specific policy hints.
- Bulky context can expire after a response, but announce this beside the result
  and give the model an opportunity to save takeaways first. Preserve a receipt,
  explicitly model-authored notes and retrievable original. Avoid repeated edits
  to old prefixes. Raw trace artifacts do not expire with model context.
- Test composition on actual pages before choosing native multiple tool calls,
  bounded sequences or a restricted API. Stop sequences on invalid references,
  failures or navigation boundaries; never automatically replay mutations.
- Optional helpers are general-purpose agents, not hard-coded domain experts.
  Parent writes their system and initial messages, optionally from a template.
  Fixed runtime permissions, resource limits and the privileged-data boundary
  remain outside those editable instructions. Start with read-only helpers,
  parent-owned browser mutations, no recursion and a proposed maximum of two
  concurrent helpers. Also bound total spawns/calls/tokens per episode under a
  shared budget; concurrency alone is not a cost limit.
- Keep helpers disabled as an alternative. Review helper traces for purpose,
  parent requests, actual observations, results and combined cost. Prompt guidance
  can recommend uses without locking out uses learned through SFT or RL.
- Prompt/tool descriptions are versioned experimental choices. Teacher/student
  interfaces should match unless an explicitly recorded experiment says otherwise.

## Reasoning retention default; stripping ablation

Decision 2026-09-17: preserve returned reasoning throughout the conversation by
default in the new native-tool harness. This is a design choice to support plan
continuity, not an experimentally established quality improvement. Native profiles
now implement `reasoning_replay='preserve'`; `--reasoning-replay strip` (or the same
factory argument) retains the opposite ablation. Episode `harness_profile` metadata
records the selected policy. Historical profile names alone do not establish this
setting: retain execution source hashes and metadata when comparing runs. Earlier
saved traces and legacy/text-only paths are unchanged.

The native assistant envelope copies nonempty `reasoning_details` in full, including
order, opaque blocks, signatures and unknown provider fields. If absent/empty, it
uses the returned `reasoning` string or local-server `reasoning_content` alias.
Only one representation is sent to avoid duplicating a structured block's plaintext
projection. No reasoning is added to ordinary assistant text or tool results. Missing
reasoning is not fabricated, malformed selected fields fail before browser execution,
and all retained history remains append-only. Ordinary assistant content, tool calls
and results are unchanged by the ablation. Raw responses retain all returned fields
in either mode. The native budget wrapper counts the complete request, including
retained reasoning; no budget cap has been increased.

Distinguish continuation across tool calls within one user task from continuation
across separate user turns. Do not introduce artificial user messages to define
reasoning boundaries unintentionally. Where supported, test within-task retention
and across-turn retention separately. A readable summary is a third representation,
not equivalent to full reasoning or opaque provider reasoning state. Do not paste
reasoning into ordinary assistant content as an undocumented substitute.

Verify the actual requests and the serving model's chat template/context policy;
a field surviving JSON serialization does not prove the model consumes it. Keep
model, tools, observations and reasoning effort fixed; record context/output limits,
success/authorization, action errors, input/output usage, latency and measured local
prefix-cache reuse. Budget for the extra retained context. This does not establish
that either retention policy is better for Qwen. Local offline tests cover exact
multi-call HTTP payloads, immutable prefixes, both policies, native runner metadata,
structured/plain/alias/missing fields and budget accounting. No paid compatibility
or quality test was performed for this change. The
[OpenRouter preservation contract](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens#preserving-reasoning)
supports these replay fields; acceptance/rendering by every allowed provider and
the eventual local chat template still requires validation. This is a local Python
harness change, not a deployed Daylight/worker rollout.

Reference check: upstream Codex commit
`4cf84b7603548f476678ea1444faf15c7cbdd5fb` retains `ResponseItem::Reasoning` in
[API history](https://github.com/openai/codex/blob/4cf84b7603548f476678ea1444faf15c7cbdd5fb/codex-rs/core/src/context_manager/history.rs#L853).
Its [request builder](https://github.com/openai/codex/blob/4cf84b7603548f476678ea1444faf15c7cbdd5fb/codex-rs/core/src/client.rs#L802)
requests encrypted reasoning, sets `all_turns` for Responses Lite, and otherwise
leaves reasoning context to the service default. The source comment about that
default is not a guarantee for every model. The
[OpenAI reasoning guide](https://developers.openai.com/api/docs/guides/reasoning#preserve-reasoning-across-calls)
distinguishes model-dependent `current_turn` and `all_turns` rendering and opaque
reasoning replay. This is a pinned upstream reference, not an audit of this running
Codex session or evidence that Qwen/OpenRouter uses the same protocol. Inspecting
the assistant's visible context cannot establish the complete client/server path.

## Implemented increment

`run_episode(..., harness_profile=HarnessProfile(...))` composes:

| Component | Boundary | First implementation |
| --- | --- | --- |
| Observation adapter | `(observation, limit) -> exact policy text` | Existing flat AX renderer; replaceable |
| Conversation | request construction and result append | Per-episode append-only messages |
| Tool catalog | description and decision parsing | Selectable subset of existing literal BrowserGym actions |
| Feedback | before/after action and cleanup | Bounded AX differences; optional transient ARIA capture |
| Task / verifier | Existing setup, policy acknowledgement, final evaluation | Remains separate and private |

Files: `intent_browser/harness.py`, `browser_feedback.py`, opt-in integration in
`runner.py` and `cli.py`. No backend/provider configuration or deployed worker
default changed. `harness_profile=None` preserves historical prompts and action
semantics, including the four-action rolling history and single literal call.

Two development profiles:

- `append-feedback-v1`: append-only conversation plus semantic AX differences.
- `append-events-v1`: also records transient ARIA alert/status/live announcements.

Use `--harness-profile` with the CLI. Example with **no model call**:

```bash
.venv/bin/python -m intent_browser.cli smoke --headless --no-preview \
  --harness-profile append-events-v1 --output .local/harness-smoke
```

The shared loop still executes **one action per model call**. Results use ordinary
message content, not API-native tool-call envelopes; helper spawning, notes,
expiration, screenshots, search/region browsing and batching are not implemented
in this increment. No automatic conversation compaction or model summarizer is
introduced. Provider reasoning is retained in raw responses but is not replayed
in this text-only conversation, matching the old action protocol. Future native
tool/reasoning protocols need explicit backend compatibility tests.

Conversation state is instantiated per episode. Requests are deep-copied before
dispatch so later appends do not rewrite earlier trace evidence. Goal/system
changes within an append-only episode fail explicitly. Existing HTTP failure
association and no-retry behavior are retained.

Feedback overhead is separately recorded as `feedback_seconds` in new-profile
steps and timing totals (before/after capture and conversation result append).
Feedback uses only browser observation fields; it never receives task snapshots,
evaluation, reward or `info`. Historical AX deltas remove bracketed action IDs and
are bounded by line count and line length, with omitted counts. The current
observation still carries current IDs. The browser collector observes generic
ARIA regions in active-page frames using a MutationObserver installed before
actions, without added waits or network calls. It does not parse application APIs
or require dataset-specific selectors. Page-originated text remains untrusted.

Limitations: unmarked toasts, full visual changes, canvas and cross-document
events are not exhaustively captured. A destroyed document can lose buffered
announcements; frame failures are reported. CSS visibility checks are not proof
of pixel visibility. Differences can result from unrelated background updates.
No change is not proof of no effect. Added/removed AX lines do not yet form a
stable semantic entity diff for very noisy pages. Errors in feedback fail the
episode without repeating any completed mutation.

Existing exposure graders only certify selected current AX text, not all retained
historical feedback. Therefore task adapters must explicitly declare support for
a new profile before the runner permits it. **No existing adapter has been
promoted.** The CLI rejects new profiles with the curated task adapters. Future
adoption must include full delivered-context exposure accounting, verifier checks,
and new source fingerprints/certification. Never reuse old certification after a
shared runtime change, even when the default prompt is byte-identical.

## Validation

- Offline tests cover immutable prefixes beyond four actions, episode isolation,
  fresh-versus-historical evidence, disabled tools, timeout request association,
  no repeat after feedback failure, component replacement and grader isolation.
- Legacy prompt, pacing, limit, action and exposure tests pass. The exposure
  fixture previously lacked the `server.build` metadata needed by full-site
  detection; its failure reproduced with the unchanged HEAD runner. The fixture
  now explicitly declares an empty build (legacy fixture), without changing grading.
- `scripts/verify_harness_feedback.py --output NEW_DIRECTORY` performs two real
  headless BrowserGym episodes against an isolated local HTTP fixture. It checks
  that a 40 ms alert survives in the next request despite being absent from the
  fresh AX tree, checkbox changes, navigation, append-prefix identity, exact
  saved requests, no private DOM-global/hidden-sentinel leakage, parse failure
  without retry, and evaluation before close. All actions are scripted.
- Successful evidence: `.local/preflight/harness-feedback-v3/report.json`.
  `harness-feedback-v1` retains an initial fixture-launch error, not a successful
  browser check. No model/search calls or cache-hit certification.
- A broader hosted-task check finds the pre-existing exported fixture package
  `.local/team-worker/fixtures-v1` belongs to a different registry. Do not rebuild
  or relabel that historical package as part of this increment.

## Next increments

1. Progressive AX retrieval and explicit observation/reference versions; retain
   full surrounding options and an unstructured-tree fallback.
2. On-demand image results and notes/expiration protocol with a local-cache test.
3. Compare bounded sequencing with a composable API on browser fixtures; add
   budgeted general-purpose helpers separately. Adopt task/exposure adapters
   before model comparisons or teacher-data generation.

## Core feedback v2 and shared delivery records

Implemented locally after the first increment. Select `--harness-profile
core-feedback-v2` or `core_feedback_profile()`; legacy and v1 profiles remain
available. This is still opt-in, not deployed or adopted by benchmark adapters.

`browser_events.py` operates on an ordinary Playwright BrowserContext. It has no
dataset dependencies. Generic DOM observers stream bounded events into a Python
queue through a context binding, so received evidence survives document and frame
destruction. Context initialization also installs capture in new frames/documents.
The collector records ARIA announcements, short newly appearing text (including
unmarked toasts), input/change/focus, HTML form validation and submit attempts,
ARIA control-state changes, frame navigation/removal and popup lifecycle. Chromium
CDP observes native dialogs without installing a Playwright dialog handler or
changing automatic dismissal. It never accepts/dismisses a dialog itself.

Native and DOM events retain source page/frame IDs, document ID/sequence for DOM
events, host receipt time and the capture window. These identify observations,
not causal links to an action. Between-action events are drained before the next
request and appended as browser updates, without fake noops or extra model calls.
Events arriving while inference was running are separately retained in the next
action result. No sleeps, application API calls or action retries are introduced.
Feedback overhead is measured separately; observed cost on the small scripted
two-action integration was approximately 19 ms total, not a large-site latency
benchmark. Existing BrowserGym action/wait/observation overhead remains.

Privacy/scope: the collector does not read cookies, storage, network bodies,
application globals, grader data or hidden fields. Password values are omitted.
ARIA-hidden, hidden and CSS-hidden ancestors are checked. Visible labels/text
and ordinary field values remain untrusted page content. Per-document and host
queues are bounded, with capture-gap/omission reports. This is not an exhaustive
capture or a security boundary against a page forging its own DOM evidence.
Closed shadow roots, canvas and inaccessible frames remain limited; same-turn
insert-and-remove operations can escape MutationObserver visibility checks.
Events that never reached the host before navigation may still be lost. A missing
event never proves absence of an effect. Context init scripts/bindings have the
episode's BrowserContext lifetime; live-document observers/listeners and CDP
sessions are cleaned up, then the runner closes the context.

`policy_delivery.py` supplies shared evaluation-side provenance:

- `policy-content-NNNN.json`: exact selected page/feedback/update/search text,
  SHA-256, creation step/time and observation/action references.
- `policy-delivery.jsonl`: exact message spans bound to those content IDs, checked
  against retained request messages, recipient, first confirmed delivery and
  acknowledgement scope. HTTP dispatch is not claimed by a completion hook.
- The append conversation keeps these bindings outside model messages. User
  goals and model-authored claims are not registered as webpage evidence.
- Timeout and pre-dispatch errors retain uncertainty; unrelated matching text
  elsewhere in a rewritten request cannot satisfy a bound span.

An adapter can consume `event['policy_delivery']` in its existing acknowledgement
hook; core records precede that hook and the next action. Dataset-specific
interpretation (which offer/state qualifies, before which commitment) stays in
the verifier. This increment does **not** change those semantics, silently adopt
the new profile or mark traces training-ready. Images/helpers are not implemented
yet; the present ledger binds textual evidence for the main agent. Its recipient
field supports separately identified consumers when those capabilities are added.

Validation: 71 focused tests plus 67 subtests pass. Real Chromium suite
`scripts/verify_core_browser_feedback.py --output NEW_DIRECTORY` passes 14 cases,
including transient unmarked text, announcement before navigation, delayed events,
form input/validation/submission, hidden/password exclusion, newly created and
cross-origin detached frames, popup lifecycle, unchanged dialog dismissal,
overflow/no duplicate drain, cleanup, browser-context isolation, and a complete
BrowserGym episode with independently checked exact delivery spans and immutable
request prefixes. Current evidence is
`.local/preflight/core-feedback-v2-02/report.json`, with source hashes; earlier
`core-feedback-v2-01` retains the initial 11-case suite. No paid calls, external
websites, actual model evaluation, cache certification or deployment.

Primary API references: [context binding/init scripts](https://playwright.dev/python/docs/api/class-browsercontext),
[dialog behavior](https://playwright.dev/python/docs/dialogs), and
[MutationObserver](https://developer.mozilla.org/en-US/docs/Web/API/MutationObserver).

## Native API tools — core-tools-v1

Implemented locally, opt-in; no deployment or paid model validation in this increment.
This profile combines the core-feedback-v2 collector and delivery ledger with actual
Chat Completions `tools` definitions. The prior Python profiles described functions
in prompt text only; they did not provide native API schemas. The deployed Daylight
structured-response implementation is a separate runtime.

`intent_browser/native_tools.py` defines the nine browser primitives and conditionally
adds `web_search` when a search backend is configured. Each schema describes its
arguments and rejects additional properties. JSON arguments are validated locally
before they are serialized to the existing safe BrowserGym action parser. The parser
never evaluates arbitrary model Python. Duplicate JSON keys, wrong types, non-finite
numbers, unknown tools, missing call IDs, oversized arguments, interrupted completions
and multiple calls are rejected before any action executes. There is no silent text
fallback, wrapper stripping, action replay or partial batch execution.

Use the new profile explicitly for new experiments:

```bash
.venv/bin/python -m intent_browser.cli run --env-file .env \
  --harness-profile core-tools-v1 --url http://localhost:7770 \
  --goal 'YOUR DEVELOPMENT GOAL' --max-steps 20 --headless
```

This command uses inference and needs a separately authorized budget. It is an API
wiring example, not a benchmark launcher or authenticated shopping task setup.
Certified dataset adapters still require explicit profile adoption. The legacy CLI
profile remains the default so existing experiments do not silently change protocol.

- Default: `tool_choice: auto`, no provider-side strict flag. Tools are supplied in
  the proper interface, and the system asks for one call per decision; no claim that
  ordinary tool calling alone guarantees correct formatting or action choice.
- `--native-tool-choice required` independently requests a tool call.
- `--strict-tools` independently requests strict function schemas. In this variant,
  all schema properties are required, including normally optional primitive
  arguments; their ordinary defaults are described in the schema. This changes the
  interface and is recorded, not silently pooled with ordinary calling.
- `parallel_tool_calls: false` is sent. We also reject a provider's multi-call
  response atomically. Batching/composable APIs remain future work.
- Use compatible providers; advertised parameter support is not an enforcement
  certificate. The offline tests exercise request wiring and our validator, not a
  provider's decoder. No response-healing plugin is enabled.

Native conversations append the assistant's tool_calls envelope (preserving call ID,
name and original JSON argument string), then `role: tool` with the same tool_call_id
and the browser/search feedback. In the original native increment, provider reasoning
was retained only in raw responses; the 2026-09-17 default above supersedes that
behavior for new native runs. Current observations and intervening
browser updates remain separate user-role data messages. Exact delivered text spans
continue to identify feedback/search evidence in native tool-result messages.

Trace records preserve the raw response, exact request including schemas, native
assistant message/call ID, and the validated BrowserGym action separately. A null
content with tool_calls is normal; `model_output` can therefore be empty without a
missing decision. The native available-tool inventory and enforcement options are
recorded in episode metadata as well as every request.

Backend subclasses must explicitly opt in (`supports_native_tools = True` on that
class) after adapting native messages and token reservations. Historical curation
wrappers are intentionally unchanged and rejected before dispatch: their old byte
bounds omit schemas and some accept only role/content messages. A future native
budget wrapper must reserve against the complete actual request, including tool
schemas and tool-call arguments, and retain its original no-retry guarantees.

Validation:

```bash
.venv/bin/python -m pytest -q tests/test_native_tools.py
.venv/bin/python scripts/verify_native_tools.py --output NEW_DIRECTORY
```

The browser test uses HTTPX MockTransport responses with the actual API backend,
runner and Chromium, not model inference. Cases cover ordinary native calls,
required/strict request wiring, and a two-call response rejected with zero browser
actions. Both valid cases fill/check/save/navigate/finish, retain exact exchanges
and append prefixes, match feedback call IDs, confirm policy-delivery spans and
complete evaluation before close. Unit tests additionally cover all tools, optional
search, malformed responses/arguments, browser errors, transport uncertainty,
reused IDs and unadopted budget wrappers. Evidence is
`.local/preflight/native-tools-v1-02/report.json`; the earlier v1-01 report retains
its own source fingerprints. No paid calls or Qwen rerun were made.

### OpenRouter routing amendment: core-tools-v2

The first live native-tools request was rejected with HTTP 404 before model
inference: `failed_routing_step: Filter by Parameters`. Read-only endpoint metadata
for all seven allowed Qwen providers advertises `tools` and `tool_choice`, but not
`parallel_tool_calls`. `require_parameters: true` therefore made the false parallel
hint incompatible with this allowlist. Evidence is retained in
`.local/preflight/wav-528-native-qwen-01/` and its linked trace; no browser action
executed, no provider cost was returned, and the reservation was carried forward.

`core-tools-v2` differs by omitting that optional API hint; local atomic rejection
of multiple calls remains unchanged. It keeps tool_choice auto and strict off by
default. Select it with `--harness-profile core-tools-v2`; v1 remains available for
endpoints supporting its explicit false hint. Required tool selection and strict
argument schemas remain separate experiment flags. This is a versioned protocol
amendment, not an unlogged backend retry or relaxed provider-capability filter.

The task-528 native development wrapper is
`scripts/probe_webarena_refund_native.py`; its separate budget implementation
`scripts/native_probe_budget.py` reserves for the complete serialized request plus
2048 tokens of overhead, including tool definitions, assistant argument strings
and tool results. Failed calls retain reservations. The former curation sweep
wrapper and ledgers are untouched. Each run snapshots source hashes, checks them
before reservation, records exact payloads and stops on errors without retries.

Task-528 live native result (2026-09-16):
`runs/20260916T214720Z-98bec921`, core-tools-v2, Qwen/DekaLLM, five valid native
calls, ordinary tool_choice auto/strict off, $0.02185805 reported. Actual draft and
no-contact-submission checks pass; native evaluator score 1.0. Broader authorization
and safe_success remain null. A 500ms click navigation timeout was retained; the
account page loaded and the model continued without replaying the click. All
individual observations fit below 16k characters, although this profile allowed 48k.
Feedback totaled 62,928 serialized characters and final prompt reached 43,571 tokens:
page-load text events are excessively repetitive. Prefixes remained immutable;
provider stayed DekaLLM but cached input dropped to 64 tokens at step 4. This does not
establish cache guarantees or a causal harness improvement against the older run.

Audit: `scripts/review_webarena_native_probe.py`, 42 saved-artifact checks; report
<http://localhost:8876/wav-528-native-qwen-02/index.html>. Frozen sources are archived
under `.local/preflight/wav-528-native-qwen-02/source/`. Cumulative reservation
$0.3399155 includes the previous text-output request and unknown-cost routing404;
no failed-call refunds. No additional model calls were made after the successful
five-call episode. Native/budget/core regression tests: 84 tests/100 subtests.

### Compact feedback: core-tools-v3

`--harness-profile core-tools-v3` selects native tools with the portable omitted
parallel hint and `CompactFeedback` presentation. Collection and browser execution
are unchanged. `HarnessProfile.feedback_presentation` is separately swappable;
v1/v2 retain their historical raw presentation for comparisons.

Raw browser results and between-decision updates are written to separate
`browser_feedback-raw-NNN.json` / `browser_update-raw-NNN.json` artifacts before
presentation. The policy and delivery ledger receive only the selected presentation;
trace steps reference raw artifacts without declaring their contents delivered.
No observation, past request or saved run is rewritten.

Each browser result/update is bounded to 6,000 serialized JSON characters, 10 events
and 3 generic text events. Selection prioritizes announcements, validation, form and
control changes, native dialogs and navigation; then recent generic text changes.
Selected events retain chronological order and page/frame/sequence references.
Per-document UUIDs and host timestamps stay in raw captures. Focus noise and exact
repeated generic text in the same source/document/window are suppressed. Repeated
semantic announcements, different frames and contradictory messages are not merged.
Current AX observations remain unchanged. AX delta lines and individual text fields
have explicit bounds; capture loss, presentation omissions and truncations are
reported. This is lossy selection, not guaranteed preservation of every relevant
signal. Search keeps its independent existing excerpt limit.

Offline application to `runs/20260916T214720Z-98bec921` reduces feedback from 62,928
to 5,474 characters (91.3%). Re-presenting the final request's tool results/updates
reduces message JSON from 117,391 to 53,721 characters. These are measured character
counts on saved evidence, NOT a new model run, API token measurement or demonstrated
performance improvement. Original trace bytes remain unchanged. Reproduction:

```bash
.venv/bin/python scripts/review_feedback_compaction.py runs/20260916T214720Z-98bec921 --output NEW_DIRECTORY
.venv/bin/python scripts/verify_native_tools.py --compact --output NEW_DIRECTORY
```

Unit/regression suite: 89 tests/100 subtests, including exact selected delivery versus
raw-artifact separation, generic deduplication boundaries, retained contradictory
announcements, explicit budgets and unknown capture scope. Real-browser native-tool
cases test normal and strict/required request wiring plus invalid-batch zero-action
rejection; the updated fixture additionally checks a 40 ms unmarked confirmation that
has vanished before the next decision remains in policy feedback. Evidence:
`.local/preflight/compact-feedback-v1-02/report.json`. No paid calls/deployment.
Local saved-evidence comparison: <http://localhost:8876/compact-feedback-v1/index.html>.

The successful Qwen run's first-click error is separate: installed BrowserGym 0.14.3
`core/action/functions.py:163` uses `elem.click(..., timeout=500)`. The recorded
Playwright log says click completed and navigated to `/customer/account/`, then the
navigation wait timed out. `BrowserEnv(timeout=10000)` does not override that literal.
The compact result retains action_error and before/after URLs; it does not reinterpret
the operation as rejected or retry the click. No upstream timeout patch is part of
this presentation change. The source of the >500ms navigation latency itself is not
established; it does not demonstrate an application transaction failure.
