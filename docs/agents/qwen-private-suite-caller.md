# Private Qwen suite caller

Future OpenRouter Qwen releases cap each policy and formatter request at 180
seconds, including the total-duration watchdog and the HTTP timeout. A timed-out
request is an infrastructure failure with unknown remote cancellation; it does
not establish task failure or authorize an automatic replay. Historical frozen
callers keep their original limits. This hosted cap does not apply to private
vLLM serving: parked requests need capacity-aware waiting and the separately
agreed rental deadline.

Private Qwen callers may explicitly set `private_read_wait_policy` to
`rental_bounded`. This is separate from the hosted 180-second cap. Unsent local
capacity waits already use the rental deadline. The opt-in extends buffered HTTP
reads after submission to the remaining rental time, since queued work, prefill
and generation cannot be distinguished before the reply arrives. Connection,
write and connection-pool waits stay bounded by the smaller of 30 seconds, the
configured request timeout and remaining rental time. The deadline is measured
again immediately before submission, after parking and count/source checks.

The default `bounded_request` policy retains the previous maximum 600-second
HTTPX timeout and request payload. Both policies now emit a
`private_http_wait_policy` meter row; expiry before submission fails without
installing a request hook or sending bytes. Neither policy measures active decode or guarantees cache
retention. HTTPX read timeouts apply between reads; the parent's existing rental
watchdog remains the total-wall bound and the host-deletion watchdog remains
independent. A local timeout/close does not prove remote cancellation or justify
early permit release. New policies need fresh source/config/native acceptance;
under `rental_bounded`, a connected server that stops progressing can consume
the rest of the rental unless an operator or the host watchdog intervenes.
Historical releases and their receipts remain unchanged. Future private GPU
callers use one continuously replenished finite cohort. Omit `canary_task_ids`
or set it to `[]`, and omit `canary_enabled` or set it to `false`. Nonempty or
enabled historical canary configuration is rejected by this new release rather
than silently reintroducing the completion barrier.

This additive mode extends `scripts/comparison_suite.py`; it reuses the ordered
queue, prewarming channel, source-isolated saved consumers, recording hook,
automatic native grading and viewer projection. It does not allocate a host,
install dependencies, generate a world or retry episodes. Source/CPU approval is
separate from actual frozen-native/browser acceptance and serving qualification.

## Commands and paths

The Training worker uses the dedicated browser Python, with bytecode disabled:

```
/opt/qwen-runtime/suite-browser/.venv/bin/python -I -B /opt/qwen-release/caller/scripts/comparison_suite.py prepare-qwen /private/qwen-runs/RUN/suite.json
/opt/qwen-runtime/suite-browser/.venv/bin/python -I -B /opt/qwen-release/caller/scripts/comparison_suite.py supervise /private/qwen-runs/RUN/suite.json
```

`prepare-qwen` only checks pinned source/recipe inventories and reports preparation;
it does not import target consumers, contact serving or qualify dispatch.
`supervise` requires reviewed exact configuration, exact positive scripted case
acceptance, separate finite episode/rental approval and a fresh live serving
contract. The worker must run under the existing bounded launcher/cgroup limits.
Training owns an allocation-anchored host-deletion watchdog. The source capsule
and environment must be qualified before these are usable host commands.

Use `runtime_mode: "qwen-private-v1"`, `server_context_tokens: 262144`,
`max_input_tokens: 250000`, `max_steps: null`, `episode_timeout: null`,
`max_tokens: 16384`, startup watchdog at most 900 seconds and request watchdog
at most 600 seconds. Seven active lifecycles and seven generation requests, with one warm environment,
are conservative proposed initial settings. These are separate targets: supply
explicit `runtime_limits` ceilings that fit the deployed browser/tokenizer/host
bounds, and keep vLLM max-sequence capacity separate. `start_order` determines
which cold case is created next; it does not delay activation until earlier tasks
finish. The queue fills and refills its target continuously. There are no injected
model diagnostics or first-N task-completion barriers. Serving approval must bind
the complete user-authorized finite case list before launch. `suite_timeout` must
be finite and reflect the remaining approved rental plus cleanup; it must not
become an independent model episode ceiling.
No old MiMo/Luna approvals authorize Qwen or a GPU rental.

The spec separately pins `qwen_sources.runtime` (`qwen_suite_runtime.py`),
`observer` (`qwen_suite_observer.py`), `rpc` (`episode_capacity_rpc.py`),
`control` (`capacity_control.py`) and `telemetry` (`serving_telemetry.py`). The
controller/telemetry are loaded together in one isolated namespace. Source
paths must be frozen exports, never the preserved shared working tree.

## Fresh serving contract

`serving_live` is a path/SHA256 pin to `qualified-serving-live-v1`. It includes:

- `base_url: http://127.0.0.1:8000/v1` and separate
  `qualification_base_url: http://127.0.0.1:8001`;
- model/checkpoint/tokenizer/template/processor/parser `identity`, with **no
  case-specific source commit** in this measured serving identity;
- current `serving_session_id`, `server_context: 262144`, `isl: 250000`, numeric
  UTC `deadline_utc`, and `dispatch_authorized: true` only after actual approval;
- exact `capability_receipt`, `instance_readiness_receipt` and
  `deployment_receipt` pins. `serving_compatibility_fingerprint` in the reviewed
  suite spec must equal the actual capability fingerprint.

Keep the existing reusable `serving-stack-capability-v1` compatibility schema:
actual runtime/package/patch/lock/projection hashes, SM120 hardware, exact model
revision, tokenizer/template/processor assets and all effective serving settings.
The compatibility includes `runtime.counter_projection_sha256`, the SHA256 of
`ast.get_source_segment` for this release's `tokenize_payload` function. Case
source/recipe identity is separately bound by the orchestrator.

Capability `checks` require true image-input, retained-reasoning, prompt-usage,
input-boundary, output-control independence and native-tool parity; this mode
also requires `structured_output_prompt_independent: true`. Original
qualification/deployment/processor evidence stays pinned and unchanged. Synthetic
capability/deployment receipts cannot authorize real dispatch.

The fresh instance retains the established fields, with the new 250k policy cap
and native physical context. Deployment additionally binds `identity`,
`serving_session_id`, `observed_compatibility`, `allocation_utc`, integer
`approved_rental_seconds`, numeric `deadline_utc`, and `synthetic: false`.
Allocation plus approved duration must equal the deadline. Do not relabel old
100k/source95 receipts or equate an original historical proof session with the
new serving process.

The qualification adapter returns `status: "ready"`, `exact_request_counter:
true`, current identity/session/fingerprint/context/ISL/deadline and
`observed_compatibility`. Raw `/health` only needs HTTP200; its body can be empty.
Raw `/tokenize` returns `count`, complete integer `tokens`, and `max_model_len`.
No developer-mode or mutation route is needed.

Counting preserves nested tool-schema insertion order and mirrors the vLLM
`reasoning_content` alias only in the tokenize payload. Generation remains raw.
`response_format` is omitted from tokenize solely under the actual explicit
schema-prompt-independence proof. The formatter sends strict `json_schema` from
the caller-written `schema.json`, without tools or policy session state. Both
count receipts and actual HTTP bytes bind the complete generation request.
At 250,000 input tokens, output is clipped to at most 12,144 tokens. Actual
prompt usage mismatch preserves the paid response and stops before acting.

## Capacity and observations

One shared poller scrapes raw `/metrics` every second; it feeds both the reviewed
capacity controller and `ServingTelemetry.observe`. No second scraper or W&B
client runs in the browser workers. Each activated case retains one lifecycle
until policy, optional one formatter, recording/native close and grade projection
finish. Warm environments are not preclaimed capacity rows. Clean EOF retires
dispatch; failed cleanup does not release lifecycle capacity or create resume
credit. The existing capacity parent owns cohort failure/retirement semantics.

A private Unix relay connects child clients to the existing parent RPC. Each
case has a distinct capability; no inherited file descriptor across the bounded
launcher is assumed. Counting and complete buffered generation occur on the
creating browser thread inside a generation permit. After waiting, serving/source
admission is rechecked and native page text/form state must be unchanged; a changed
page fails explicitly instead of dispatching a stale action request.

`observer-transport.json` announces a private read-only Unix socket, epoch,
observer ID, session and journal path. Send one newline JSON frame:

```
{"op":"read","after":0,"limit":120}
```

Continue with the returned epoch and observer ID plus last received sequence.
Replies have `status: "ok"` and `value`; malformed/changed cursors have `status:
"error"`. Read at most 120 rows. Buffer gaps and scrape/observer failures remain
explicit. `serving-telemetry.jsonl` is append-only, with incremental batch records.
Training's SSH return transport reads this journal; the workstation owns the sole
existing W&B writer and all W&B credentials.

## Completion and private artifact return

Remote Events records remain in `completion.sqlite`. `completion-return.jsonl`
announces pinned consistent SQLite snapshots under `completion-snapshots/`, with
pending notices. The remote worker never invokes the workstation Codex daemon.
Training returns snapshots; workstation delivery uses the existing Events helper,
retaining notice IDs and uncertain-delivery behavior rather than replaying notices.
Remote absolute evidence paths require an explicit local-return path mapping;
changing a path for presentation must not rewrite original SQLite/grade evidence.

After cleanup, `terminal-artifacts.json` inventories regular files relative to
that unique private run root, including native/canonical grades, trace media,
private fact/span/delivery evidence, counter/usage records, capacity state and
cleanup receipts. Preserve infrastructure failures separately from task
pass/fail/inconclusive. The manifest is transport integrity, not task success.
Raw capability tokens/run internals and privileged fact recordings remain private.
The worker's accepted viewer reader/assets and local HTTP service must also be
bound; the workstation's existing viewer is not automatically available on a VM.

## Qualification still required

CPU controls use fake evidence/counts and local HTTP mocks; they do not establish
GPU parity, actual generated-world cancellation, combined same-build full-suite
readiness, host environment portability or a deployed observer/W&B transport.
All actual source-root/case/environment/recording and native grade/HTTP controls
remain required before promotion. Public-request alignment concerns in H01/H02
and known extractor/basis caveats are separate from serving infrastructure.


The Qwen capacity parent deliberately stops the cohort on an infrastructure error
while permit/drain/cleanup ownership is unverified. It does not release capacity
or retry the failed paid case. A normal native task fail is a completed case and
does not stop its peers. This differs from the legacy independent case watchdog.
Scripted canary infrastructure failure also stops remainder admission.

The worker may use a flat source capsule only with an explicit `source_export`
descriptor (`index` path/SHA pin and `root_id`), both on the caller specification
and each exported case. The index is the exact approved
`private-frozen-source-capsule-v1` source-index.json with committed root identity
and per-file SHA, bytes and Git modes. Git remains mandatory without this
explicit mode; missing Git never triggers a fallback. Training must index the
final approved caller root separately alongside the nine case roots. Current
source inventory alone is insufficient; the relocated descriptors must be bound
in the new reviewed configuration and actual capsule acceptance.

Saved consumers supply the formatter's `transport` directory; its schema is read
from the sibling `extraction/schema.json`. The installed httpx encoder is checked
against ordered UTF-8 JSON before backend construction. Instance readiness must
expire at the allocation-anchored rental deadline; readiness remains freshly
checked on each call. Capability-bearing runtime specifications are temporary
private transport files and are excluded from returned artifacts.


## Runtime concurrency control

The optional `runtime_limits` setting binds three positive integers:
`max_active_ceiling`, `max_generation_ceiling`, and `initial_generation_requests`.
The initial episode target remains `max_concurrent_episodes`. The immutable
browser pool and tokenizer capacity are created from the active ceiling plus
`prewarm_count`; increases cannot exceed those reviewed resources. Omitting
`runtime_limits` preserves fixed-cap behavior.

The parent writes `runtime-limits-private.json` with mode 0600 outside the trace
roots. Use the frozen `scripts/qwen_suite_observer.py` through SSH on the worker:

```bash
python -I -B scripts/qwen_suite_observer.py --descriptor RUN/runtime-limits-private.json limits
python -I -B scripts/qwen_suite_observer.py --descriptor RUN/runtime-limits-private.json update_limits --max-active-episodes 3 --max-generation-requests 3 --expected-revision 0
```

Read the returned revision before each update. Stale revisions, malformed values,
expired/finished suites and requests above fixed ceilings are rejected. Queue
admission and controller CAS updates share the queue lock. Lowering targets
drains already-created environments and in-flight requests without cancellation
or prefix credit. An admitted actor still constructing its environment can park
before native capacity registration until existing actors finish. The existing
read-only observer and controller `status()` formats remain unchanged. The
capability token never belongs in policy context, argv or public viewer metadata.
Each accepted update is retained in `runtime-limits-events.jsonl`.

Source/CPU approval does not qualify a new host's browser capacity, inference
context or serving counter. Use actual bound startup/grade/HTTP controls and the
current serving qualification before the finite authorized cohort is dispatched.

When qualifying the exact caller in `scripted` mode with runtime controls enabled,
the parent uses an explicit local `ScriptedMetrics` fixture and the real parent /
child capacity RPC. Policy and formatter remain supplied scripted responses.
`scripted-capacity-fixture.json` records that no serving readiness, Qwen counter
parity or provider inference was established. This branch cannot run for a model
episode; real mode still requires `ServingAdmission` and its current source proof.

## Formatter cleanup during a cohort abort

A cohort stop retires/cancels dispatch admission but keeps an already-sent
request's release/ack channel open. The private relay drains an established
connection for `shutdown_grace_seconds` (default30, validated1..120), bounded
also by the allocation deadline. No new request may acquire a permit.
The caller still verifies process exit, wrapper/HTTP cleanup and persisted
terminal evidence before finishing the controller row. An expired drain, peer
death or missing acknowledgement retains ownership; abort alone never frees a
sent request. Explicit cancellation and final host close still force transport
containment and do not claim verified HTTP cleanup. This is prospective source
behavior; the original Verda B02 failure and all grades remain unchanged.
# Hosted OpenRouter Qwen preparation

`scripts/comparison_suite.py` also supports explicit `runtime_mode="qwen-openrouter-v1"`
for the newly authorized finite 34-case suite. This mode uses ordinary OpenRouter
inference and the same source-bound native graders, recording, pool and capped
prewarming queue. It never imports private serving admission or emulates GPU
telemetry/capacity. Legacy MiMo/Luna and private-Qwen gates remain separate.

The exact new authorization pins the request's ordered task list and public prose.
All 34 cases require fresh driver/execution/recipe-bound scripted positive native
and HTTP acceptance, plus reviewed configuration. Bind `hosted_runtime` to
`scripts/openrouter_qwen_runtime.py` and `hosted_readiness` to Training's read-only
provider/counter release. Both policy and formatter retain the exact existing
provider allowlist/order/fallback settings and reasoning configuration.

The input ceiling is 150,000 tokens of estimated complete next input using the
registered official local Qwen tokenizer/template and existing image estimator.
The formatter adds a labelled conservative schema overhead estimate and sends
the actual saved schema with strict `response_format`. Provider prompt usage is
authoritative; local estimates are not a parity qualification. Output is clipped
to `min(65536, 262144-estimated_input_tokens)`. Unknown assets, missing schema,
expired suite deadline and oversized requests reject before dispatch. There are
no automatic formatter retries or provider model substitutions.

There is no artificial turn or per-episode time ceiling. Explicit request/startup
watchdogs and one finite `suite_timeout` bound the local job; the supervisor's
runtime-only `suite_deadline_utc` reaches child requests and parent watchdogs.
Independent case failures are retained individually rather than treated as task
verdicts. Model episodes are not tagged `scripted`; zero-provider controls are.
Source/CPU preparation alone does not authorize dispatch or runtime promotion.

Hosted dispatch starts with the four leading cases in parallel and waits for their
automatic grade projections before admitting the remainder. Ordinary native
failures still count as measured completions. Infrastructure failure stops
further claims, preserving not-started events. A total-duration request watchdog
also interrupts stalled HTTP reads; it does not retry the paid request. Actual
case counter sources and asset bundles must match the qualified source hashes.

A failed hosted canary stops future admission while healthy active cases finish
and grade. At least one canary must exercise the formatter; budget-stopped
cases remain measured native outcomes. A retry configuration keeps all34
authorized cases but declares only the remaining IDs in start_order, plus
evidence-bound resume records for completed real cases. Native failures are
retained too. Different attempt directories/suite IDs preserve earlier evidence.
Pending cases receive not_started events even after supervisor interruption.

Prospective corrected hosted attempts allow up to65,536 output tokens and1,800s
per request, retaining the150k complete-input ceiling and actual output headroom.
The first attempt16k truncation is preserved. The wrapper supports the saved
extractor request_options setter, tested through actual extract_and_grade.
Resume requires pinned prior spec/completion database/terminal inventory and
retains every grade-complete result, including nativeFalse after cleanupfailed.
Viewer evidence must belong to the same case trace; missing/omitted results
fail closed. A later hosted infrastructurefailure blocks new admissions while
healthy active work drains. Formatter-free retries do not require extraction.

Future hosted callers may opt in with `formatter_quote_pair_schema=true`.
The decoder then requires nullable `{value,evidence}` claims to be either both
null or both non-null, including false and zero values. All native schema
constraints remain in force; the native schema and returned claims are unchanged.
The exact refined wire schema is saved in `transport/response-format-schema.json`
and included in the input estimate. This does not enforce quote substring
authenticity or semantic correctness, replace native grading, or authorize retries.
Existing frozen callers retain their original schema; provider acceptance of the
refined schema requires separate real formatter qualification.


### Optional whole-browser-step containment

Future callers may set `browser_step_watchdog_seconds` to an integer from 1 to 600
(default `None`, disabled), and `env_step_telemetry` to an explicit boolean
(default omitted, preserving the runner's existing choice). This does not change
model messages, native tool arguments, episode duration or generation deadlines.

The child pairs trusted start/end acknowledgements around the entire `env.step`
call. The parent uses its own monotonic clock, checks active admission and exact
sequence, and bounds that call plus the existing cleanup grace. Lookup, action
execution, callbacks and post-action observation all fall inside this boundary.
Completion restores the earlier active/rental deadline; a slow model generation
is covered only by its separate provider watchdog. A step cannot extend the
active deadline, nest, send a provider request or silently close its channel.

On expiry, only the case-owned bounded launcher is terminated and its channel is
closed. The shared Chromium service and healthy siblings are preserved. Record
an infrastructure failure with unknown action effects; never replay the action
or report that it was not executed. Native cleanup budgets and actual browser,
grading and viewer acceptance remain separate qualification requirements. CPU
containment checks alone do not establish healthy pooled leases after a timeout.


Hosted retry history is qualified only for canonical
`launch-spec-approved-v*.json` files beside the authorization file with its exact
unchanged authorization pin. Other filenames/locations or a re-pinned
authorization can hide earlier attempts; generic history discovery is not a
complete duplicate-attempt guard. Do not use those configurations for retries.

Quote-pair refinement covers closed objects with exactly required `value` and
`evidence`, `additionalProperties=false`, explicit list-valued nullable types
and string-or-null evidence, without existing object composites. Other shapes
are unchanged, and the saved wire artifact alone does not certify enforcement
on every claim. Unresolvable field references fail before provider dispatch.
The request watchdog retains the enclosing suite alarm: an expiring outer alarm
can interrupt failure recording during suite shutdown; parent terminal evidence
remains necessary. These limits do not imply provider schema acceptance.


### Hosted concurrency amendments and resumed shared services

Keep the original `authorization` file and pin unchanged for a resumed hosted
cohort. A new user concurrency instruction is recorded in the ordered
`authorization_amendments` list. Each pinned receipt must bind the original
file, its preceding amendment (or null), and only `max_active_combined`.
Other episode, model, input, warming and outcome-retention rules cannot change
through this channel. The effective cap remains within the finite task count.
Historical attempt discovery continues using the original cohort pin.

The shared tokenizer and Chromium service start from the first case in this
attempt's `start_order`, so a retained older case cannot supply an incompatible
pool manifest for corrected pending cases. All pending clients still need the
same installed pool adapter/shutdown/asset qualification. `pool_memory_mib`
(default3072, range1024–8192) and `pool_tasks` (default512, range128–512) are
finite per-service ceilings, not reservations. Bind these settings in actual
native/browser/HTTP acceptance and report measured concurrency and memory.

Shared services verify that all pending cases bind the same pool client, broker,
BrowserGym adapter/shutdown and runner bytes before registering the attempt.
Retained outcomes keep their historical sources and are excluded from this
prospective service compatibility check.


## Finite hosted task instances

The opt-in `hosted_limit_profile: finite-task-limits-v1` accepts an exact pinned
request with per-case `max_steps` and `maximum_complete_input_tokens`. The suite
maxima bound each case; both policy and schema formatter enforce the case input
ceiling. It retains the native 262144-token context, 180-second hosted request
watchdog, one formatter dispatch and no automatic retries. Older hosted suites
retain their 150000-input/no-turn-limit contract.

A `hosted-finite-task-authorization-v1` binds the complete request, model,
concurrency and ordered prepared instances. `finite-hosted-native-controls-v1`
may reference independent scripted native controls from the identical prepared
recipes and source root. These controls retain their original producer, result,
canonical grade, public task, metadata and actual HTTP evidence; they are never
relabelled as executions of the hosted caller. Source, counter, hosted transport,
recording and configuration qualification remain separate requirements.

Finite mode additionally requires the first up-to-four cases to pass actual
caller-path scripted acceptance through its queue, pool, recording and shared
viewer. Independent native HTTP evidence binds both recording and episode IDs
to the same trace. An atomic request-hash dispatch claim prevents a different
authorization/spec filename from issuing a second attempt. Correctly graded
no-answer or limit outcomes do not hold later finite cases; infrastructure
failures can still stop admission. Per-case turn limits apply only in this
explicit profile, preserving legacy/private no-turn behavior.


## Continuous private admission and isolated failures

The prospective private admission policy is `continuous-v1` (default). Hosted
OpenRouter and historical frozen callers retain their own behavior. One parent
owns the queue, one capacity controller and one shared metrics poller for the
whole finite cohort. Existing sticky KV-pressure parking, retirement, acknowledged
permit release and atomic queue/controller limit CAS remain in force.

A normal negative or inconclusive native task verdict is a measured completion;
it never aborts other cases. A technical case error can also release its lifecycle
slot after the child has exited, the exact launcher proves containment, wrapper
finalizers acknowledge pool and capacity-channel cleanup, and the controller has
no outstanding request for that case. The failure receipt keeps its task verdict
null. The parent verifies shared source/service health and fresh telemetry, then
uses the existing final cleanup boundary to finish that case. It never cancels a
sent request or grants early capacity credit merely because the child failed.

The parent waits for natural child cleanup for at most the configured shutdown
grace, bounded by the remaining rental. Missing cleanup evidence, an uncertain
request/acknowledgement, source integrity failure, dead shared service, stale
telemetry, containment failure or rental expiry keeps cohort-level failure
handling. A complete cohort containing isolated technical errors still exits as
failed after collecting the other cases; its original case grades remain distinct.
Zero-provider controls retain their explicit scripted allowance; this allowance
never becomes a real-model episode ceiling.

Trusted phase timestamps are written in `phases/CASE.jsonl` (parent) and
`CASE/child-phases.jsonl` (child). They include queueing, process launch, environment
readiness/activation, capacity wait/permission, actual generation dispatch, browser
step start/end, native-grade availability, grading projection and cleanup, with
UTC/monotonic times and caller commit/driver/configuration fingerprints. A generation
scope ending is not a remote cancellation certificate. Native grader entry is not
instrumented; that timestamp remains unknown. `suite-measurements.json` indexes all
phase files, including cases without a final result. These machine-readable files
are inputs for a human timing dashboard; no existing viewer grade is overwritten.

Qualify source, ordinary browser/native grading and HTTP projection locally before
rental. Reusable serving capability and task acceptance remain separate from cheap
fresh host/source/config/readiness checks. Changing caller/source/profile bindings
still requires matching acceptance; this policy does not relabel old evidence as a
new execution or require an entire redundant scripted cohort on the GPU clock.
No rental is released until Training's independent, tested expiry/deletion path can
survive loss of the local workstation. This source change does not implement that
provider control-plane guard or authorize inference.
