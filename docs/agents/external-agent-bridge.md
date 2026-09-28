# External Codex transport for the existing browser harness

This is one harness with another model transport, **not a second harness**.
The ordinary `intent_browser` runner still creates the policy context, declares
tools, executes browser/data actions, manages history, captures observations,
handles retries and runs the selected task's verifier. The bridge contains no
browser controls, task implementations, observation renderer or agent loop.

Status: implemented locally, with offline transport checks and real-browser
scripted acceptance. The first live GPT-6 Luna request was rejected with HTTP 400 (`Unsupported
parameter: max_output_tokens`), before any completion or browser action. No deployment or historical profile was changed.

## Architecture and maintenance boundary

```text
Existing task + existing harness/runner
    -> existing ChatCompletionsBackend (messages and tool schemas)
    -> authenticated localhost /v1/chat/completions bridge
    -> Pi's low-level Codex OAuth + model transport
    -> model response
    -> same existing harness parser, controls, observations and grader
```

The HTTP facade means an existing launcher only needs another `base_url`, model
and local bridge credential. Its task factory, profile and `run_episode` call
remain unchanged. An optional direct Python `ExternalAgentBackend` implements
the same `complete/configure_tools/begin_episode/close` interface.

New tools and changed descriptions/schemas pass through automatically. A test
adds an invented future function and verifies this without implementing it in
the bridge. Tool execution always belongs to the harness. A proposed `bash`
call was rejected by the existing parser with zero browser actions.

Pi's coding-agent loop, shell tools, workspace instructions, skills, extensions,
MCP servers, history and compaction are not loaded. Only its pinned OAuth helper
and model transport are imported. The executable is trusted application code,
not an OS sandbox; the model has only the tools the harness advertises and
accepts. A harness-authorized data tool retains its existing sandbox boundary.

There is no new harness launcher to keep synchronized. If a future provider
protocol adds a new message modality or field, the transport may need updating,
as any model backend would; unknown formats currently fail closed.

## What “same context” means

The application-controlled roles, message order, text, inline images, tool
names/descriptions/parameter schemas and tool-result IDs are preserved. No
additional policy instructions or tools are inserted. The ordinary harness
request and the translated provider payload are both saved. The worker checks
that Pi's actual dispatched body, after decompression if necessary, equals the
audited payload.

Codex uses Responses while our OpenRouter backend uses Chat Completions. These
are not byte-identical requests or identical model tokenizations. The bridge
maps message/tool envelopes, explicitly sets `strict:false` when the original
function schema uses the Chat Completions non-strict default, and uses SSE for
transport. Temperature is omitted for the Codex reasoning endpoint; reasoning
effort is explicit. Provider-internal instructions and reasoning cannot be
claimed identical across models.

Original Responses output ordering, IDs and encrypted reasoning are replayed
only when the harness supplies the matching assistant message. Changed or
rejected history does not resurrect an old action. Foreign provider reasoning
is rejected rather than silently discarded. Tool arguments remain exact even
when malformed. Raw SSE and terminal response objects are retained separately
from the Chat Completions projection; unknown costs remain null.

**Live compatibility:** the first subscription request rejected
`max_output_tokens=16384`. The bridge retains the rejection and never silently
removes the cap. `serve --provider-output-limit` is an explicit opt-in that omits
the unsupported parameter and records requested versus effective limits; it
requires the operator to accept the provider-default output limit. GPT-6 Luna subsequently returned successful completions and reported cache hits.
Its completed tool items arrive separately from an empty terminal output array;
the bridge now assembles those completed stream items and retains the original
terminal object unchanged. Two saved live responses pass offline replay after
this repair. Browser execution is being checked in a fresh v3 episode. The installed model catalog is not proof that this account can
access every listed model. Offline fixtures cannot establish that.

## Usage

Run from the repository root. Pi 0.80.6 with its corresponding `pi-ai` package
and Node 24 are the inspected installation. Another Pi version is rejected
until reviewed. Existing Pi Codex OAuth is used and refreshed by Pi's own
locking credential helper; no credential is copied into the model input or
trace. The worker does not load project `.env` or Pi extension configuration.

List installed model IDs plus explicit transport descriptors without login refresh or inference:

GPT-6 Luna is an explicit `gpt-6-luna` descriptor because Pi's bundled catalog
predates it. Its exact slug and 272k context metadata match the local Codex model
cache; no older model is substituted. Endpoint availability still needs a
successful response.

```bash
.venv/bin/python -m experiments.external_agent inspect
```

For an explicitly agreed development episode, start the model endpoint in one
terminal. This command alone does not dispatch a model request:

```bash
.venv/bin/python -m experiments.external_agent serve \
  --model gpt-5.6-sol --reasoning-effort medium \
  --max-requests 200 --timeout 180 \
  --output .local/external-agent/example-session
```

The model above is an example from the installed catalog, not a capability
recommendation. The command prints its localhost base URL and writes a
mode-0600 `bridge.env` containing a new **local bridge** credential. Keep that
file private. It is not the Codex credential.

Then use the **normal harness CLI**, specifying the desired existing task and
profile. Example for a local page (replace the URL and goal):

```bash
env -u MODEL_NAME -u MODEL_BASE_URL -u OPENROUTER_PROVIDERS -u OPENROUTER_PRESET \
  .venv/bin/python -m intent_browser.cli run \
  --env-file .local/external-agent/example-session/bridge.env \
  --api-key-env EXTERNAL_BRIDGE_KEY \
  --url http://localhost:YOUR_SITE_PORT/ --goal 'YOUR TASK' \
  --no-subagents --max-steps 200 --max-input-tokens 100000 \
  --max-tokens 16384 --timeout 210 \
  --output .local/external-agent/example-session/runs
```

Use existing launcher/task-specific preparation for stateful generated worlds;
pointing an open-ended browser at a page does not initialize or grade a task.
Python launchers can point their existing `ChatCompletionsBackend` at the same
endpoint and retain their existing task adapter, private verifier and options.
No new grader setup is needed. Keep the client timeout longer than the bridge's
request timeout plus shutdown allowance. Retain source pins per episode as in
ordinary runs. Stop the bridge after that episode; do not reuse it for another
task or model. The bridge's request allowance also includes invalid client
requests, so it can be consumed sooner than the harness's decision allowance.

Only the wrapper changes the provider/model. Whether to enable overlap, human
handover, clarification, screenshots or other harness features remains the
existing launcher's responsibility. They are not reimplemented here. The
offline acceptance covers current native tools/full-capture operation, not
every optional harness combination or live background performance.

## Usage scope and evidence

Bjorn explicitly requested existing Codex subscription use for small-scale
development, **not large parallel automation, bulk benchmarks or training-data
generation**. This is a project operating restriction, not a determination that
any particular use complies with provider terms. The bridge enforces one active
local subscription episode and one completion at a time, plus a finite request
allowance. It has no automatic transport retries or provider fallbacks.

The bridge listens only on loopback and requires its random local credential;
it exposes no browser/action endpoints. Failed/unknown transport attempts stop
further dispatches through that backend. Interrupted requests remain unknown,
never assumed free or unexecuted. Provider token/cache usage is retained when
present; the harness's local Qwen context counter remains an explicitly labeled
estimate for Codex, not its actual tokenizer. Subscription usage has no invented
API dollar cost.

Each completion directory retains:

- `harness-request.json`, `responses-request.json`, and mapping hashes;
- transport/package source provenance and dispatch time/body hash;
- status plus whitelisted Retry-After/request-ID metadata, without auth headers;
- exact `response.body` (partial on failures), raw Responses terminal object,
  normalized response and failure metadata where applicable.

Browser traces use the existing trace format and location selected by the
ordinary runner. There is no separate browser trace implementation.

## Offline acceptance and reproduction

```bash
.venv/bin/python -m unittest discover -s experiments/external_agent/tests -v
.venv/bin/python -m experiments.external_agent.verify_browser \
  --output .local/external-agent/NEW-browser-acceptance
```

Seventeen unit/transport checks pass (including exact GPT-6 Luna dispatch metadata
explicit provider-output-limit opt-in, and completed stream-item assembly): exact context/tool mapping, future tools,
opaque reasoning replay, rejected-history handling, inline images, unknown
formats, malformed/truncated output, 429 without retry, single-episode locking,
response identity, timeout attribution, and the existing HTTP backend/auth/cap.

Browser acceptance at `.local/external-agent/browser-v3/report.json` passed four
isolated scripted cases, using two concurrent processes with separate browsers
and fake-provider locks. Three completed the form correctly; the deliberately
forbidden tool case was rejected before any browser action. One case uses the
unchanged `ChatCompletionsBackend` through the real localhost HTTP bridge and
current standard profile: AX search -> fill -> AX search -> save -> answer.
Private verifier state stayed outside requests, grading happened before close,
and all request artifacts matched the ordinary trace. These are **zero-model-call
transport tests**, not evidence of Codex model performance. Usage figures in
these fixtures are synthetic parser/accounting test data.

The initial browser-v1 rehearsal exposed a missing profile-adoption declaration
in the test task, corrected in the test only. It remains on disk; v2/v3 are new
outputs. A subsequent server shutdown hardening waits for bounded in-flight
request completion before releasing its subscription lock; unit acceptance is
refreshed separately rather than rewriting the browser-v3 source record.

## References

- [Official Codex authentication](https://learn.chatgpt.com/docs/auth).
- [Official Codex App Server](https://learn.chatgpt.com/docs/app-server): an
  alternative agent runtime; this bridge deliberately does not create one.
- [OpenAI Responses migration](https://developers.openai.com/api/docs/guides/migrate-to-responses).
- [Pi provider documentation](https://pi.dev/docs/latest/providers), with the
  locally installed 0.80.6 implementation authoritative for this prototype.

Implementation: `experiments/external_agent/`. Shared `intent_browser` files are
unchanged by this work.
