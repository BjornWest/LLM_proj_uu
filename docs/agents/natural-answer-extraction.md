# Natural answer → extracted claims → shopping oracle

Implementation: `experiments/answer_grading/`. This is a post-episode grading stage,
not a second browser harness. It can consume a completed connected-world cohort
without starting a browser or website. Historical `evaluation.json` files remain
untouched; derived grades live in a new output directory.

## Boundaries

1. `extraction.messages(public_task, final_answer)` sends only the public request,
   memories, environment context and executed final response to the extractor.
   No world catalog, private preferences, expected answers, best candidates, browsing
   history or privileged journals enter this request.
2. OpenRouter `qwen/qwen3.8-27b` receives `response_format.type=json_schema`,
   `strict:true`, `additionalProperties:false`, task-specific fields, nullable missing values and exact
   supporting quotes. Routing uses the frozen cohort's provider preferences with
   `require_parameters:true`; reasoning remains enabled. No tools, automatic
   retries, JSON repair, response-healing plugin or provider/model substitution.
3. Local JSON Schema validation rejects invalid output. Quotes must be verbatim
   final-answer substrings. URLs/codes/explicit IDs must occur in their quotes.
   Money must match a quoted amount/currency; `Decimal` converts major units to
   integer minor units. Missing facts are not recovered from the oracle. Invalid
   extraction yields an ungraded error, not a browser-model failure.
4. The existing `OfferLinks` resolver resolves the cited product URL, including
   variant query parameters. This supplies an otherwise unstated SKU deterministically.
   It does not choose a better offer. An explicit conflicting SKU is retained and
   fails identity checks. Quote URLs are retained as sources, not substituted for
   the required product link.
5. `grade_claims(episode, claims, final_answer, effects=..., ...)` calls the existing
   `Episode.grade`/intent oracle. Its exact result is retained under `oracle_grade`.
   A separate currency check prevents an identical numeric USD total from passing
   as SEK. `selected_candidate_assessment` exposes individual eligibility predicates;
   the existing `base_claim` check determines whether the selection is optimal.

The extractor interprets *what was claimed*, never whether the offer is correct.
Schema enforcement and supporting quotes do not guarantee semantic extraction
accuracy: contextual ambiguity, wrong quotation attribution and omitted claims
still need spot checks. Multiple equally emphasized recommendations are marked
ambiguous rather than selecting whichever passes. “Cheapest I found” is a selection,
not an uncertainty escape from the cheapest-offer objective.

## Supported scope

Single-line `select` and `aggregate` tasks supported by the existing Episode oracle,
including no-match/uncertain responses, coupon-dependent totals, variant links and
optional pickup/travel scalar claims. Unit-price ratios, baskets, branch-assortment
and account-action response contracts are explicitly unsupported by this version.
Some numeric prose spellings/currency aliases also require review: the current version expects
explicit numeric counts and SEK/EUR/USD/GBP monetary notation. It does not use an
LLM to fill missing prices, compute means, resolve variants or convert currencies.

`full_response_evaluated` is always false: explanations, exhaustive factual claims
and presentation quality are not automatically graded. `safe_success` remains
null and training eligibility false. A supported structured-answer verdict is
available separately, without claiming broader safety coverage.

Effects come from the host, never the extractor. The saved-cohort adapter requires
initial and final journals with complete mutation prefixes, retains all intervening
mutations including reversals, and conservatively records unexplained order/account
changes. Consent scoring stays null without trusted host exposure evidence; request
logs or page presence do not establish policy delivery. Clarification-aware callers
must pass trusted `clarified_fields`; the saved CLI does not infer them from prose.

## Commands

Prepare and validate an existing cohort, without inference:

```bash
.venv/bin/python -m experiments.answer_grading.run \
  --cohort .local/synthetic-codex-sol-high-v1 \
  --output .local/my-extraction-prepare
```

For one explicitly authorized extraction call:

```bash
.venv/bin/python -m experiments.answer_grading.run \
  --cohort .local/synthetic-codex-sol-high-v1 \
  --output .local/my-extraction-live --live
```

Replay saved claims through validation and the oracle, with no API call:

```bash
.venv/bin/python -m experiments.answer_grading.run \
  --cohort .local/synthetic-codex-sol-high-v1 \
  --claims .local/my-extraction-live/claims.json \
  --output .local/my-extraction-replay
```

Each output path must be new. The selected cohort's frozen source is used to load
its oracle; source/input hashes, runtime bindings, public task and private reference
must agree before inference. Sources are rechecked before dispatch and after grading.
The original cohort must retain its `source/`, `input/`, `snapshot.json` and `live/`
artifacts; this CLI deliberately does not guess bindings from arbitrary traces.

Artifacts include the exact extraction request, raw response body, HTTP status,
provider response, usage/cost, extracted facts with quotes, oracle input, derivations,
per-requirement grading and source hashes. Credentials/authorization headers are not
written. One selected completed episode entails one request, with 16,384 output
maximum including reasoning and a 180-second request timeout. Failed requests and
unknown cost stay recorded; there is no automatic retry or batch expansion.

For future live cohorts the host can call `messages` after the natural answer,
validate the extraction, then invoke `grade_claims` with the retained Episode and
trusted effects. The default shared runner/evaluation lifecycle is unchanged;
automatic invocation in every browser launcher and deployment are not part of this
additive implementation. The post-run extraction CLI now publishes to the project-local
trace viewer as described below.

## Validation

```bash
.venv/bin/python -m pytest experiments/answer_grading/test_grading.py -q
```

Offline checks exercise a real generated Episode oracle: correct and nonoptimal
selections, wrong/missing totals, currency mismatch, missing/conflicting identities,
no-match versus uncertainty, fabricated evidence, extra/private fields, duplicate
JSON keys, ambiguous recommendations and retained/reversed side effects.

OpenRouter documentation:
[Structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs).
Provider support varies; requiring parameters and validating locally are both
necessary. The extraction model's reasoning, usage and provider are retained as
reported, not inferred from request settings.

## First live validation and schema revision

The first Qwen/AkashML extraction is preserved under
`.local/answer-grading-sol-live-v1/`. It copied the recommendation, total, coupon and
URLs correctly but produced `{amount: "null", currency: "SEK", evidence: "null"}`
for an irrelevant average field. Local grounding validation rejected it; **no
automatic grade** was emitted. Its cost was $0.03071035, with 1,463 prompt tokens,
13,793 completion tokens and 13,013 reported reasoning tokens. This was much more
reasoning than expected for extraction and remains a cost/latency tuning issue.

Version `shopping-answer-extraction-v2` builds its strict schema from the task's
operation and activity. A delivery recommendation has no average, branch or
readiness claim field; an average task has no recommendation fields. This avoids
asking the model to populate irrelevant answer forms, while still rejecting
unsupported or ungrounded output. The original failed attempt is not repaired.
Regression coverage is 17 offline tests. A separate scripted projection of Sol's
answer passed the complete saved-oracle path in
`.local/answer-grading-sol-scripted-v2/`; this is deterministic integration evidence,
not evidence of successful model extraction.

The v2 live attempt (`.local/answer-grading-sol-live-v2/`) ended with
`finish_reason=length` at 16,384 output tokens and incomplete JSON. It is ungraded,
with $0.03641055 reported cost; no partial-output repair was attempted.

Inspection of both saved responses exposed a concrete integration omission: the
model's reasoning explicitly said it did not know the schema and was guessing
field names. The schema had been supplied only in `response_format`, not in the
visible prompt. Both calls reported the same 1,463 prompt tokens despite different
schema sizes. This supports the endpoint-specific hypothesis that constrained
decoding did not make the schema visible to the reasoning model; it does not prove
how every provider implements structured output.

Version `shopping-answer-extraction-v3` includes the **identical task-specific JSON
Schema in the system prompt and response_format**. A regression asserts byte-level
JSON-value equality of these two definitions. This addresses the demonstrated
integration omission without disabling reasoning or adding retries. Every new
output also retains the extractor's exact source files. Eighteen offline tests
pass; the earlier failures and reported costs remain separate artifacts.

Final live v3 acceptance: `.local/answer-grading-sol-live-v3/acceptance.json`.
Qwen 3.8 27B / AkashML produced grounded schema-valid claims, then the original
Sol cohort's oracle graded them. Offline replay at
`.local/answer-grading-sol-replay-v3/grade.json` is exactly equal.
The selection, price, SKU citation, coupon and recorded-effect checks pass;
`base_claim` (optimality) fails. Selected candidate eligibility is `eligible`.
The stated 571.25 SEK is valid, versus the frozen reference winner at 352 SEK.
The public wording "shoes" versus reference inclusion of flip-flops remains a
task-design caveat; the grader is not silently narrowed to walking shoes.

Successful call: 2,293 prompt tokens, 3,914 completion tokens including 3,305
reasoning tokens; $0.00918405 reported cost, 47.9s HTTP wall time.
All three development attempts cost $0.07630495. Cache tokens reported zero.
This is one successful live extraction, not a measured extraction accuracy rate;
reasoning remains enabled and still warrants efficiency tuning before batch use.

Human report: http://localhost:8876/answer-grading.html

## Extractor-only adversarial fixtures

The finite `run_robustness` suite edits the saved Sol answer rather than running
the browser again. It contains ten selection-answer fixtures: components without
a total, context-only canaries, absent product citation, absent coupon, an explicitly
wrong total, equally primary alternatives, uncertainty, no-match, a rejected offer's
price, and quoted website instructions. These are authored mutations, not additional
agent outcomes or an unbiased extraction-accuracy sample.

```bash
.venv/bin/python -m experiments.answer_grading.run_robustness \
  --cohort .local/synthetic-codex-sol-high-v1 \
  --output .local/new-extractor-mutation-suite --live
```

Omit `--live` to prepare fixtures without inference. Each output directory must be
new. Live mode makes at most ten requests, with concurrency two, no retries and
16,384 output tokens per request including reasoning. A transport error stops new
dispatches; an already dispatched concurrent request may finish. Semantic failures
remain results and do not prevent the other finite cases from being tested.

Expected facts stay outside the model messages. Every case retains exact messages,
request/response, extraction, validator result, relevant oracle checks and cost.
The suite separately counts schema/grounding validity and authored expectation
matches: valid JSON with a price attributed to the wrong offer is still a failed
extraction test. Ambiguity requiring review is an expected outcome for the equal
recommendations fixture, not an automatic failing grade of the browser agent.

The lexical validator cannot establish semantic attribution. An offline regression
deliberately demonstrates that a rejected alternative's quoted price satisfies
literal grounding. The model fixture checks that the extractor actually leaves the
selected total absent. A general deterministic fix would require more structure in
the source answer; matching a substring alone must not be advertised as sufficient.

First finite live suite: all ten fixtures passed, with ten valid extractions,
nine reproducible derived grades and one appropriately ungraded ambiguous answer.
Reported cost $0.05351725; Qwen/AkashML for every request. Evidence:
`.local/answer-extractor-robustness-live-v1/`, including `offline-audit.json`.
Twenty-two offline tests pass. See [results and limits](answer-extractor-robustness-v1.md)
or http://localhost:8876/extractor-robustness-v1.html. Several omissions are explicitly
signposted in these authored fixtures; do not extrapolate their pass rate to natural,
less explicit answers or untested aggregate/pickup tasks.

## Trace viewer publication

Successful future live extractions automatically publish `derived-answer-grade.json`
inside their source episode. This is a new, append-only display artifact; it does not
replace `evaluation.json`, requests, responses or any original evidence. Replay-only
commands do not create another displayed model evaluation. A publication failure is
reported separately in `viewer-publication.json` and does not invalidate a retained grade.

Backfill an existing successful live extraction without inference:

```bash
.venv/bin/python -m experiments.answer_grading.publish \
  --output .local/answer-grading-sol-easy-v1
```

The publisher checks frozen extraction inputs and refuses to overwrite a different
existing sidecar. Repeating the same publication is idempotent. The sidecar includes
claims, URL derivations, per-requirement results, extractor identity, source hashes and
scope limits; no full model requests or credentials are copied into it. Source paths
are informational, not an HTTP route for arbitrary files.

The project-local multi-root viewer at localhost8878 shows a top-level **Post-run
answer checks** panel and a separate timeline record. After evidence validation its
sidebar title says “answer checks passed/failed (derived)”; the original recorded
outcome remains visible in the panel and original verifier record. Until a trace has
been loaded, a fresh catalog entry says “derived grade available” rather than claiming
an unchecked pass. Modified episode evidence invalidates the displayed verdict, with
normal viewer cache invalidation. This integration is in `scripts/trace_hub.py` and
`scripts/trace_grades.py`; standalone sibling-utility viewers and Vercel have not been
changed. Full prose/safety remain outside this scoped grade.

Validation: `tests/test_trace_grades.py`, existing trace-hub Python/JS suites, plus
`.local/derived-grade-viewer/` Chromium acceptance. No additional inference was needed
for this viewer integration.

### Final grading note and future rewards

When a verified derived grade is available, its timeline note replaces the empty
`manual-review`/`ungraded` verifier placeholder in the normal view. That original
note remains in diagnostics with its exact recorded content. Known outcomes,
technical errors and invalidly bound grades do not qualify for this replacement.
A run without an available grade must not be presented as graded.

Outcome checks are retained individually, including true, false and unknown values.
New display exports also retain the selected candidate's eligibility assessment
(model, size, colour and other applicable predicates) when supplied by the oracle.
These are evidence for future reward design, not an invented reward schedule.
No scalar training reward is calculated by this implementation.

Future reward calculation should be a separately versioned deterministic function
of these outcome checks and the task contract. Keep raw checks and aggregate
pass/fail unchanged; save the reward-policy version, each component and aggregate
reward as separate derived results. Do not automatically average every available
check: identity/link checks overlap, some constraints may be hard gates, and unknown
is not false. Declare how missing coverage affects eligibility for training.
Procedure/exposure diagnostics stay separate from outcome reward, consistent with
the task-definition contract. Reward weights and constraint penalties remain an
explicit design decision, not something the extractor chooses. Reweighting saved
supported checks need not rerun the browser or extractor; adding new unextracted
facts or missing verifier coverage can require further extraction/verification.

### Inspecting individual checks

Every check in the top viewer panel expands to an explanation, expected result,
supplied/observed result and exact answer quote when relevant. Details come from the
saved task/oracle inputs, not another model call. The quoted total is compared to the
selected offer; the separate task-answer check compares the selection to eligible
optima. Invalid/missing selection identities and absent claims remain explicit.

`derived-answer-check-details.json` is a separate append-only display enrichment,
bound to the summary sidecar's hash. It can be backfilled with the same publish CLI;
existing summary/grade/trace artifacts are not rewritten. Stale or missing detail
bindings display “details unavailable”; they never invent expectations from pass/fail.
Future live extraction and the publication CLI create both records. Original outcome
checks, numeric reward policy and extraction behavior are unchanged.

The UI name “No unauthorized changes” replaces “Recorded effect checks”. It compares
trusted host mutation/state evidence against the research-only action scope. It is
an authorization/outcome check, not trajectory diagnosis. The current implementation
requires no recorded commerce effects and checks account/order state; cookie choices
have separate coverage and unobserved effects are not certified. Diagnostic analysis
of navigation, retries, missed information or failure causes remains a separate tool.
