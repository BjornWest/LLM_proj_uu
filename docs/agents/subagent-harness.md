# Combined harness and bounded delegation

Implemented and deployed on September 21, 2026. Code release `8bdcbde` passed
48 read-only production checks with zero model calls. PC control and worker use
the accepted current runtime. Detailed evidence and rollout commands are under
`.local/current-standard/`; see [release notes](standard-harness-release.md).

The current policy factory is `intent_browser.standard_profile.standard_profile`:
native structured calls (up to eight sequential calls), preserved model reasoning,
incremental token-budgeted AX with scoped search/traversal, compact action feedback,
requested viewport screenshots retained by default, and optional bounded helpers.
Explicit older profile factories remain available for reproducible comparisons.

## Delegation contract

The root may spawn two active helpers, four total, one level deep. Default child
limits are ten decisions and 180 seconds; the family shares a 40-request ceiling
and the caller's existing budget-enforcing backend. Numeric limits are configurable
through `AgentLimits`. Limits are recorded in every trace. Call reservations and
actual reported costs remain distinct. A helper never creates its own credential,
spend ledger, transport retry policy or independent allowance.

A helper inherits the parent's native tool definitions except `spawn_agent`.
The tool registry is fixed per conversation. No-browser mode returns an explicit
unavailable result for browser tools. Search, when configured, shares the parent
search budget. Parent-supplied task, system instructions and public evidence form
a separate child conversation; privileged verifier state is never copied into it.

`browser=own` requires a trusted helper environment factory. It must preserve
site boundaries and account authorization without resetting a shared task. Cookie
transfer is private setup, not policy evidence. Browser storage may be independent
while server-side accounts/state are shared. The runtime never assumes that a
second browser is a copy of a transaction. Task adapters must explicitly account
for helper effects before claiming whole-family authorization or safe success.
Unsupported adapters reject own-browser launch visibly; no-browser assistance
remains usable. Do not silently substitute a blank browser or rerun task setup.

Each browser is owned exclusively by its agent. BrowserGym's synchronous
Playwright API stays on its original thread. A cooperative scheduler interleaves
conversations at inference and wait boundaries. Inference is serialized through
one backend to preserve its existing cost/readiness hooks; this version does not
claim concurrent model HTTP calls. The shared slot is acquired before refreshing
the actor's page, avoiding capture-then-queue stale observations. Completed action
notices identify another browser's tool and URL without exposing its actionable
BIDs; a notice is not proof of a committed transaction. These notices help
coordination but do not provide transaction isolation across server accounts.

Cancellation prevents subsequent actions and waits for any dispatched model
request to finish recording response and cost. It does not undo browser actions
already executed. Root shutdown drains/cancels children before final evaluation
and browser close. Retained child evidence is under `children/<episode_id>/` in
the parent archive; each child is itself a complete ordinary trace. `agents.json`
and `metadata.agent_lineage` link the family.

## Validation

`tests/test_delegation.py` covers registry inheritance, session/request isolation,
shared call limits and real reservation-wrapper integration using HTTPX mocks,
late-response cancellation, numeric limits and public coordination notices.

`scripts/verify_subagents.py` runs an offline scripted BrowserGym conversation in
no-browser or own-browser mode. `scripts/run_subagent_probe.py` provides an
independently graded read-only fixture. The parent must stay on its main page,
ask a helper to read the public lookup code, collect the result and answer. The
goal explicitly requires delegation, so success establishes feature operation,
not its usefulness or efficiency on an ordinary benchmark. The verifier checks
helper page evidence and final answer before closing the parent browser.

The probe is offline by default. `--live --cap-usd .25` opts into a separately
authorized Qwen run; the cap is shared by the entire family. Exact request and
response payloads, reasoning, tools, sessions, usage and per-request reservations
are retained. Old profiles/ledgers and production certificates are not modified
by running the probe.

The two live Qwen synthetic runs each used six requests and succeeded. The first
reported $0.00743652; the final runtime run reported $0.0118935. Total reported
cost is $0.01933002 against the shared $0.25 authorization, with no unknown-cost
attempts. Their frozen traces and exact request/budget audits are under
`.local/preflight/subagent-qwen-v1` and `subagent-qwen-v2`. The task explicitly
requires a helper; this is functional evidence, not a delegation benchmark.

## Adoption and remaining boundaries

CLI, local BrowserGym demo, live task worker and shared manual Ask now select this
same factory. Existing explicitly selected experiment/training profiles remain
unchanged. The browser-side Campus JavaScript demonstration remains a separate
runtime. Low-level `run_episode` callers must still select a profile explicitly.

Manual Ask borrows the already open browser without resetting or closing it.
Exact core requests cross the authenticated controller boundary for inference;
retry waits occur before fresh capture, outside the browser RPC timeout. Stop
prevents subsequent batch actions and retains already returned response/cost.

The shared utility projection and authenticated worker viewer expose nested
conversations individually with family links. The original ZIP includes every
child artifact. Costs sum across the family; provider-switch diagnostics compare
within each session rather than between independent helpers.

`CurrentPolicyTask` retains outcome verification but explicitly leaves legacy
single-observation exposure/avoidance labels unknown for incremental delivery.
It does not enable own-browser helpers on browser-local journals or HAR tasks.
Those require adapter-specific state/effect ownership and new exposure evidence.
Normal outcome checking and retained historical labels are not silently rewritten.

Prislyktan uses its original four-origin server and private ledger for tasks,
manual interaction and Ask. Its client-side design preview uses the original
assets with a documented local-storage shim and has no task grading. Six fixed
goals are enabled only after source-bound worker acceptance; manual browsing is
not task success. Packaging preserves the older fixtures/certificates separately.
