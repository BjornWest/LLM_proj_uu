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

The default remains one active local subscription episode and one completion
at a time, plus a finite request allowance. On 2026-10-11 Bjorn additionally
authorized exactly 34 GPT-6 Luna/medium evaluation episodes in parallel, dispatched
by Evaluation. That finite authorization does not authorize open-ended automation
or training-data generation. The explicit suite configuration below changes
cross-episode admission; it never changes the per-episode request lock, context,
tools, grading or replay. There are no automatic transport retries or provider
fallbacks.

### Explicit finite concurrent suite

Direct Python callers use the following additional backend arguments (source
qualification is offline; Evaluation owns actual suite composition and dispatch):

```python
from experiments.external_agent.backend import ExternalAgentBackend
from experiments.external_agent.episode_admission import EpisodeConcurrency
from experiments.external_agent.subscription_quota import SubscriptionQuotaGuard

config = EpisodeConcurrency(
    suite_id="LUNA34-PARALLEL-EVALUATION-20261011-01",
    max_concurrent_episodes=34, max_suite_episodes=34,
)
backend = ExternalAgentBackend(
    "gpt-6-luna", episode_transport_directory,
    reasoning_effort="medium", provider_output_limit=True,
    lock_path=canonical_shared_subscription_lock,
    episode_concurrency=config,
    quota_guard=SubscriptionQuotaGuard(episode_quota_directory, remaining_floor=1),
    before_dispatch=verify_frozen_sources,
)
try:
    metadata = backend.begin_episode(stable_unique_episode_id)
    # The ordinary runner uses this private backend; no bridge-owned agent loop.
finally:
    backend.close()
```

Each backend/HTTP server still serves exactly one episode. Every participant,
including bridges loaded from different frozen roots, must use the **same canonical
subscription lock path**, never a per-case lock or separate path per frozen root.
Suite mode rejects an omitted explicit lock path; the CLI also requires a stable
`--episode-id` so relaunching a case cannot silently manufacture a new identity.
The CLI exposes the same opt-in:

```bash
.venv/bin/python -m experiments.external_agent serve \
  --model gpt-6-luna --reasoning-effort medium --provider-output-limit \
  --suite-id LUNA34-PARALLEL-EVALUATION-20261011-01 \
  --max-concurrent-episodes 34 --max-suite-episodes 34 \
  --subscription-lock /home/bjorn/code/LLM_proj_uu/.local/external-agent/subscription.lock \
  --episode-id UNIQUE_CASE_EPISODE_ID --max-requests 200 --timeout 180 \
  --output UNIQUE_EPISODE_OUTPUT
```

Finite integer limits must satisfy `1 <= concurrency <= suite episodes <= 34`.
Suite identity, limits, model, reasoning effort, output-limit mode and quota floor
must agree across participants. The ordinary exclusive lock conflicts with a
parallel suite in either direction. Only one suite configuration can be live on
the shared lock; incompatible participants fail before admission.

The `<subscription.lock>.admission/` directory contains kernel-held episode lock
files and an atomic, fsynced ledger keyed by the suite identity's SHA-256. The
ledger consumes an episode identity at successful admission, even if it later
fails or the process dies; the same identity cannot be admitted again, and no
more than the declared total may start. A full concurrent pool rejects admission
rather than waiting or scheduling a retry. Closed/crashed processes release
kernel leases; stale lock-file text does not hold capacity. Do not delete lock
files or reset ledgers to manufacture more allowance. Use a new suite identity
only for separately authorized work.

Before each worker dispatch the shared control lock serializes a **fresh**
`SubscriptionQuotaGuard` read/check and records an admitted-dispatch counter.
Parallel configuration requires this guard with a remaining floor of at least
1%; CLI suite mode always uses 1%. Either window at/below the floor or unavailable
telemetry stops that backend without a send, retry or paid fallback. The ledger
counts dispatch admissions, not confirmed model sends or billing: interruption
after admission can leave an unknown attempt. Quota receipts remain separate.
The control lock is released before model inference, so already in-flight usage
can cross the floor; this is not an exact provider-side reservation. Both primary
and secondary windows must be present in suite mode, even though the legacy guard
can accept a weekly-only snapshot. Server source checks include the actual quota
reader module as well as the transport package.

Control waiting is bounded to `20 + 50 * max_concurrent_episodes` seconds, allowing
the declared pool's queued quota reads rather than treating a healthy queue as a
quota failure. The 50-second allowance covers the existing reader's connect,
initialization, rate-limit and close timeouts plus local I/O headroom; custom
readers must also be bounded. This bounds a wait, not overall episode wall time
or provider inference. `begin_episode` metadata separately records
`admission_lock_wait_seconds` and `quota_read_allowance_seconds` (50 seconds).
`admission_wait_seconds` is their sum: it includes this request's own quota read
after acquiring the lock, as well as its queue wait.
`server.json` records `minimum_client_timeout_seconds = admission_wait_seconds +
provider timeout + 10`. Suite HTTP callers must use at least that timeout (1960
seconds for concurrency34/provider180); their separate finite episode wall-time
limit remains in force. Provider request timeout stays180. Healthy 0.8-second
quota reads queued by all34 cases are covered by synthetic acceptance. Serialized
quota reads can still throttle dispatch; actual RPC latency/capacity needs runtime
qualification. No automatic retry follows a genuinely exceeded admission deadline.

One episode's completion calls remain nonconcurrent, with private artifacts,
session/cache identity, replay map and failure state. `close()` waits for its
current completion before releasing capacity; it does not cancel a queued quota
check or an in-flight worker. Disconnecting an HTTP client likewise does not
cancel the server's queued request, which may still dispatch later. Keep the
HTTP watchdog at the declared minimum, subject to the separate whole-episode
deadline. If that deadline requires stopping a case, terminate its bounded
process tree and retain the consumed case/possible upstream attempt as unknown;
do not replay it. There is no phase-close cancellation API in this release.
Worker transport failures release
capacity but poison that backend; they do not restore consumed suite allowance.
Process death can leave an unknown upstream attempt and must not trigger replay.
Offline synthetic qualification establishes local admission/isolation, not the
subscription's actual simultaneous serving capacity or 34-browser host capacity.

### One case, separate policy and grading sessions

For callers that open a fresh formatter after closing policy, create a **case-owned**
`SuiteEpisode` first. Its one consumed episode allowance and concurrent lease span
both phases; never construct a second independent episode for the formatter.

```python
from experiments.external_agent.episode_admission import SuiteEpisode

case = SuiteEpisode(config, canonical_shared_subscription_lock, quota_guard,
    model="gpt-6-luna", reasoning_effort="medium",
    formatter_reasoning_effort="low", provider_output_limit=True)
case.begin_episode(stable_unique_case_id)
try:
    policy = ExternalAgentBackend("gpt-6-luna", policy_artifacts,
        suite_episode=case, episode_phase="policy", reasoning_effort="medium",
        provider_output_limit=True, before_dispatch=verify_frozen_sources)
    try:
        policy.begin_episode(unique_policy_session_id)
        # Ordinary policy runner.
    finally:
        policy.close()
    formatter = ExternalAgentBackend("gpt-6-luna", formatter_artifacts,
        suite_episode=case, episode_phase="formatter", reasoning_effort="low",
        provider_output_limit=True, before_dispatch=verify_frozen_sources)
    try:
        formatter.begin_episode(unique_formatter_session_id)
        # Existing separate answer-extraction/grading pass, if required.
    finally:
        formatter.close()
finally:
    case.close()
```

Keep the object in the case-owning process. Policy close releases only its phase;
case close releases capacity after grading. Exactly one policy and at most one
formatter phase may attach, sequentially, with different session/cache identities
and private replay/context/artifacts. Formatter requires policy close; a failed
policy may still receive its separately authorized grading pass. Neither a second
policy nor formatter reattachment is permitted. Closing a case with an active
backend is rejected; close that backend first. Phase claims are durable even when
their dispatch fails. The formatter may admit at most one model dispatch; a
second call is rejected without a send or automatic retry. The suite counter measures **cases**, not the sum of policy
and formatter sessions. CLI servers use the single-policy convenience API; the
case-owned two-phase API is for the existing Python suite caller.

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
