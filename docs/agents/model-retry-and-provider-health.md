# Model recovery and provider-health review

The new opt-in runner argument `retry_policy=DecisionRetryPolicy()` and CLI
`--retry-policy bounded-v1` permit **one additional model request per episode**.
Existing callers default to no recovery; historical profiles and the deployed
worker are unchanged. This is a local implementation with offline validation,
not a live-model effectiveness result or production rollout.

## Policy

- Recover from missing/multiple native tool calls or invalid JSON/schema arguments
  before any action executes. The model chooses a new action; the harness does
  not guess, repair arguments or execute part of a rejected batch.
- Recover from model transport timeout/network errors and HTTP 408/429/500/502/503/504.
  Wait at least two seconds and honor `Retry-After` (seconds or HTTP date).
  If the required delay exceeds 60 seconds, stop; never shorten that delay and retry.
- Authentication, payment, permission errors, refusals, output-length cutoffs,
  unrelated budget/configuration exceptions, navigation-boundary violations,
  duplicate call identities and browser execution failures are not retried.
- All attempts consume the existing `max_steps` request cap and enter the same
  backend accounting/reservation method. No hidden SDK/backend retries. An unknown
  transport charge remains unknown; no refund or increased budget is inferred.
- Wait first, execute the existing readiness/pacing hook, capture fresh observation,
  construct the request, then use the normal backend source/budget checks.
  A second failure stops. No provider or model substitution is added by this policy.

Each failed attempt retains its complete raw request/response/error, routing,
usage and policy-delivery evidence. The next step references `retry_of_step`.
The original failure remains even if the episode later completes. Retry waits
have their own timing counter. Evaluation still occurs before close.

The new request appends a clearly marked **HARNESS RECOVERY NOTICE**, not a
fabricated tool result. When a response exists, its content and selected reasoning
representation are retained. Rejected tool objects are presented as inert proposal
text (bounded to 4096 characters), never as outstanding executable calls. The exact
unbounded response remains in the trace. This exception to normal tool-result
conversation order is explicit: there was no executed tool to reply to. Previously
sent prefixes and tool schemas remain unchanged; images are not implicitly evicted.

Validation commands:

```bash
.venv/bin/python -m unittest tests.test_decision_retry tests.test_native_tools tests.test_runner_pacing tests.test_vision tests.test_ax_context tests.test_backend -q
.venv/bin/python scripts/verify_decision_retry.py --output NEW_DIRECTORY
```

The browser suite runs three isolated fixtures concurrently: missing call,
multiple calls and 429. Each retains the failed response, recaptures a changed
page marker, executes exactly one commit and grades before close. It uses mocked
HTTP generation, not a paid model. Unit checks cover refusal/length/auth/budget,
long backoff, transport failure, browser timeout, exhausted retry/call limits,
reasoning, immutable prefixes and private delivery bindings.

## Saved provider audit (2026-09-20)

`scripts/audit_provider_health.py`
recomputes a bounded saved-request review. It deduplicates generation IDs and
rejects conflicting copies. Source hashes and exact source step paths are saved.
Review roots: `runs/`, `.local/preflight/`, and the local copy of worker task145.
This is NOT every OpenRouter account request, and not a controlled comparison.
Provider-internal fallback attempts are not visible in ordinary final responses.

| Reported provider | Distinct retained requests | Native-tool requests | HTTP service errors | Claimed tool calls, but none returned |
|---|---:|---:|---:|---:|
| DekaLLM |207|178|4 (429)|1|
| Parasail |86|5|0|0|
| AkashML |85|8|0|0|
| Chutes |67|18|0|0|
| Ionstream |61|0|0|0|
| Phala |46|0|0|0|
| Cloudflare |36|0|0|0|

One additional unattributed404 says no endpoint supported the requested parameters:
589 requests total,424 duplicate saved copies excluded. DekaLLM's four 429s were on
September 14, explicitly `upstream_provider_shared_pool`; one followed over eight
minutes idle. They establish that incident, not continuing present-day unreliability.
DekaLLM handled 178/209 provider-attributed native-tool requests, including most new
harness/vision experiments. Its additional multiple-call rejection is an interface
restriction, not evidence of an operator outage. Earlier text-protocol parsing
failures occurred with several providers and must not be pooled with native tools.

Recommendation: retain the current allowlist for now; compare service/transport
failures separately from invalid responses, token cutoffs and ordinary task errors.
Use rates and time windows per model/protocol/provider, with denominators, rather
than raw error counts. The available evidence does not establish that excluding
DekaLLM would improve current reliability. Its one malformed response could arise
from model output or provider normalization; raw logs cannot distinguish them.

OpenRouter already prioritizes recent provider uptime and supports `provider.ignore`
or an explicit `provider.only` allowlist. Our existing options already require
parameter support and permit fallback within the allowlist. HTTP 200 malformed
responses may evade service-error routing; application validation still matters.
Sources: https://openrouter.ai/docs/guides/routing/provider-selection and
https://openrouter.ai/docs/api/reference/errors-and-debugging (inspected 2026-09-20).

Evidence: `.local/review/provider-health-20260920/final-audit.json` and script;
no new model calls or provider-list modifications for this review.

## Completed offline acceptance

81 focused unit/regression tests pass. All three parallel real BrowserGym cases
pass under `.local/preflight/decision-retry-v3/report.json`, with source hashes,
three mocked requests and exactly one commit each. The first two browser-suite
attempts failed during fixture setup (missing/wrong `capture_initial` signature),
before model requests; they remain separately retained. No production worker,
provider configuration, existing profile or live-model result was changed.
