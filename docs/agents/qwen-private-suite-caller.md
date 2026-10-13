# Private Qwen suite caller

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
at most 600 seconds. Four active lifecycles and one warm environment are the
current proposed bounds. B02/B14/H03/H05 must lead the queue and execute in
parallel. A shared canary barrier keeps remainder dispatch closed until all four
have verified grading/projection and terminal cleanup; a model task fail does not
by itself invalidate infrastructure readiness. `suite_timeout` must be finite and reflect the remaining
approved rental plus cleanup; it must not become an independent episode ceiling.
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
