# Shopping task and hybrid-memory sampler

Local authoring prototype, 2026-09-23. Implementation: `environments/shopping_intent/`.
Current schema: **shopping-intent-v2**. It samples typed intent before rendering a user
message and memories. No offers, stock or oracle winner are inputs. This is not connected
to the commerce world, memory service or browser-agent harness; no model runs are claimed.

```bash
python3 -m environments.shopping_intent serve --port 8876
python3 -m environments.shopping_intent sample --family footwear --hidden blocker --memory mixed --seed 7
python3 -m environments.shopping_intent sample --family cookware --hidden none --requirements 6
python3 -m environments.shopping_intent sample --family laptops --query fastest --budget-sek 1000
python3 -m environments.shopping_intent sample --family dog_food,drills,books --query basket
python3 -m environments.shopping_intent sample --query random --count 100 --output /tmp/shopping-intent-examples.jsonl
```

`--public-only` exports only the initial message, accessible memories and shared environment
context. Single samples are JSON; batches JSONL. Output files use exclusive creation.
The loopback preview serves its own HTML/API only. It is a **privileged authoring tool**,
including private intent; do not register it as a retailer or expose it to a policy.

## Design sources and retained decisions

- [Product handoff](procedural-product-handoff.md), [task families and memory](../procedural-commerce-tasks.md),
  [Q/R requirements](../procedural-commerce-request-requirements.md), [sampling DAG](../procedural-commerce-dag.md),
  [hybrid memory proposal, sections 12–15](../../procedurally-generated-envs.md).
- User's v2 revision: permit hidden user specifications only for objectively missing fit
  or compatibility choices; reject contradictory intent, remove entailed requirements,
  write natural varied messages, and colour generation stages in the authoring UI.
- Query operation, product requirements and memory placement are separate. Cheapest is
  one recipe, not the organizing assumption of the product sampler.
- Page selections and description/filter attributes are separate registry roles. Both
  constrain SKUs. Pack size is a selectable variation; cart quantity remains separate.
- A page requiring a colour selection does **not** mean the user has a secret required
  colour. Unspecified ordinary preferences are unconstrained.
- Pet food, beer and wine are included; other human food/menu/delivery-app tasks are deferred. Health/beauty
  claims are attributed manufacturer labels, not diagnoses or guaranteed outcomes.
- The 40-family registry is authored data inspired by the user discussion and
  [Prisjakt categories](https://www.prisjakt.nu/kategorier). Models, compatibility names
  and reference prices are fictional, not empirical retail distributions.

## Sampling and semantic checks

1. Choose query structure and product families (distinct families in basket recipes).
2. Include essential personal-fit/device-compatibility fields, then sample other
   family-specific predicates. `requirements` is a target count, not a promise:
   two essential trouser measurements may exceed a requested count of one; eliminating
   redundant requirements can reduce the result.
3. Check each candidate requirement against the accumulated intent, using generic
   checks and scoped domain relations. Try only coherent values from that field's
   authored domain; skip the field if none is coherent. This inspects **intent domains**,
   never commercial availability, prices or an oracle winner.
4. Remove a predicate only when the remaining requirements entail it. Keep a private
   audit of removed redundancies and skipped incompatible fields. This preserves the
   satisfying set under the declared domain rules.
5. Place requirements in the current message, structured profile and/or episodic prose.
   For a temporary override, independently validate the older durable requirement set.
6. Optionally withhold one eligible blocking fact per item from both request and memory.
   It must not be derivable from what remains accessible.
7. Sample commercial constraints from reference prices and request circumstances.
8. Build separate accessible and complete intended tasks, then render natural wording.

`semantics.py` contains the rule layer and an explicit review entry for every family.
`/api/catalog` exposes these reviews to the privileged authoring UI. Covered relationships:

| Check | Meaning/examples |
| --- | --- |
| Contradiction | Distinct equalities on one field; empty numerical intervals; a required ingredient/fibre also excluded |
| Numeric redundancy | RAM ≥32 GB implies RAM ≥16 GB; equality can imply a bound |
| Compatibility relation | A 2.5-inch SSD cannot use NVMe within this catalog vocabulary |
| Conditional implication | A magnetic pan base implies induction compatibility; 2.5-inch SSD implies SATA in this vocabulary |
| Presence dependency | A named pet-food recipe contains that named protein, but can contain other proteins too |
| Protocol implication | USB PD PPS includes USB PD; it does not imply a device-specific charging rate |
| Endpoint validity | Minimum player/chest limits cannot exceed maximum limits |
| Applicability of hidden facts | Fit and replacement compatibility are eligible; colour, fabric exclusions, battery capacity and price are not |
| Cross-source consistency | The final resolved task and each durable memory scope are coherent independently |

These are conservative, curated rules. The other fields have no additional hard
cross-field rule in their current vocabulary. Correlation is not implication: low
weight does not entail low capacity, marketed sensitive-skin suitability does not entail
fragrance-free, and a particular flavour does not entail absence of other proteins.
Numeric sampling thresholds are not a closed catalog of possible numeric facts; ingredient
and material sets remain open. Missing facts are unknown, not false or an empty set.
New fields/subtypes require their own semantic review before relying on this sampler.
There is no claim of exhaustive real-world physical/configuration validation.

### Cookware correction

`material` now means **body material**, separately from `base`. Aluminium body plus a
bonded magnetic base is valid for induction. Stainless steel alone does not establish
induction suitability. Bare aluminium/nonmagnetic bases conflict with induction. The
scoped table describes flat frying pans in this authored vocabulary, not every kind of
cookware. See [Bosch's explanation of magnetic layers](https://www.bosch-home.com/ne/specials/pro-induction-cookware)
and [its induction cookware guidance](https://www.bosch-home.com.sg/service/get-support/hob/induction-hob/whats-suitable-for-an-induction-hob).

## Hidden specifications and clarification

`--hidden none` exposes all intended requirements in the message/memories.
`--hidden auto` makes a seeded 35% authoring choice per eligible line to withhold a blocker;
this is an adjustable prototype distribution, not a calibrated training rate.
`--hidden blocker` requires at least one eligible withholding or returns an explicit error.

The allowlist currently covers 11 fields across 10 families: shoe size; trouser waist/inside leg; jacket
size; phone-case model; lens mount; foundation shade in the fictional range; toothbrush
handle system; printer model; vacuum model; duvet dimensions. These facts concern the
recipient's fit or existing equipment. Ordinary product-page variations are not
automatically blockers. Pet harness personal measurements need a richer measurement
contract and are not hidden in this version.

Each private `hidden_user_specifications` entry has a line/subject/family, typed predicate,
a reason, example targeted question and user reply. The initial public export contains
**none** of these entries or their withheld values. Hidden specifications are neither
irrelevant filler nor secretly enforced ingredient/material preferences.

```python
from environments.shopping_intent.clarification import answer_clarification, task_after_clarifications
reply = answer_clarification(bundle, "line-1", "size_eu")
# {"matched": True, "reply": "I wear EU size 40."} for a matching sample
accessible_now = task_after_clarifications(bundle, [("line-1", "size_eu")])
```

The typed stub reveals only the specifically addressed field on that line. A generic
`anything_else`, unrelated preference, wrong line or unknown field reveals nothing.
The preview's question button exercises this through `/api/clarify`; it is not natural
language question interpretation. A future user simulator needs an audited mapping from
a question to recipient/item/field and a trusted conversation record. `clarified_fields`
in grading must come from that record, never an agent-supplied assertion.

The complete oracle task is not information the policy already knows. `grade_answer`
returns `structured_claims_correct: null` with `unresolved_user_specification` when a
complete task contains undisclosed clarification requirements. It does not secretly fail
a choice on an inaccessible size or award full success merely for asking. Conditional
answers and completed multi-turn user interaction remain harness integration work.
Always grade using the complete `resolved_task`; `initial_accessible_task` is an
information-state projection, not a substitute final grading target.

### Stronger omission validity requirement — agreed 2026-09-26, not yet implemented

Bjorn clarified that an omission sample must initially have no uniquely justified
SKU answer. Merely removing a hidden predicate and optimizing the remaining filters
is incorrect: missing personal fit is an unresolved variable, not permission to
buy whichever size is cheapest. Current allowlisting/targeted replies/grade gating
exist; the world-level ambiguity certification and conversational host do not.

The next implementation should retain three requirement channels: explicit request,
bound memories, and private user specifications disclosed through clarification.
For the first omission class, certify the realized world as follows:

1. The withheld field is an allowlisted fit/compatibility blocker, absent from the
   request and applicable memories and not entailed by visible information.
2. Enumerate coherent plausible completions of that field while holding all other
   requirements, stores, prices and stock fixed. At least two completions must have
   feasible selections requiring different SKUs, with no common acceptable optimal
   SKU across those completions. Different stores selling the same SKU do not count.
3. The sampled actual user answer must itself lead to a feasible selection. A
   clarification-leading-to-no-match class could be added separately; do not silently
   mix it into this initial identify-the-SKU class.
4. Before disclosure, reference information state is `needs_clarification`. It must
   not report the optimum obtained by dropping the blocker. This does not require
   artificial price ties: two sizes may cost different amounts, but the user has
   not said which size fits. A numerical cheapest candidate is not a justified fit.
5. The trusted user-interaction host matches a targeted question to recipient,
   line and field, releases only that answer, and logs delivery. A generic
   "anything else?" or a question about an unrelated preference reveals nothing.
6. The grader consumes that trusted disclosure record and then checks the full
   outcome. A lucky unclarified guess cannot finish successfully. Pending interaction
   stays pending; a finalized run still missing required clarification is incomplete.

This is an explicit omission-class eligibility check after world construction, not
a reason to rewrite user preferences, stock, prices or the hidden answer until a
task succeeds. Preserve invalid classifications and report acceptance rates. Any
later conditional sampler must expose its selection policy and bounded attempts.

Diagnostic `.local/product-world/omission-audit-20260926/report.json` inspected 32
predetermined footwear/hidden-size samples: 29 had an actual feasible selection and
at least two feasible size completions; three did not meet this stronger class
definition. No sample was repaired. These are diagnostic observations, not a new
implemented sample gate or proof across all blocker families. Only footwear currently
overlaps the blocker allowlist and the six canonical world families.

## Structured contract and natural language

The bundle includes:

- `request`: query, scoped item lines, explicit predicates, context, constraints and authorization.
- `memory_facts`: private structured bindings behind both profile and prose memories.
- `initial_accessible_task`: matching memories plus current explicit requirements.
- `hidden_user_specifications`: private facts available to targeted clarification.
- `resolved_task`: complete intended task including the withheld predicates, with provenance.
- `public`: single-paragraph `user_message`, accessible `memories`, shared `environment_context`.
- `authoring`: coloured message segments with source references; semantic sampling audit.
- `expected_memory_delta`: empty create/update/delete lists for these comparison tasks.

Predicates use `field`, `operator`, `value`, `unit`, `value_type`, `surface` and `label`.
Operators: `eq`, `ge`, `le`, `contains`, `excludes`. Types: number, string, boolean and
string_set. All current predicates are requirements; vague soft preferences/tradeoffs
need a separate contract. No larger-is-better interpretation of shoe size or fit.

Wording slots have multiple realizations for questions, properties, remembered statements,
exceptions, budgets, delivery and comparison scope. A separate `--prose-seed` varies
wording and clarification replies without changing `semantic_sha256`. Colours identify
question, product, explicit requirements, saved context, override, commercial constraint
and scope. They exist only in the authoring UI; text copying and policy exports are plain.

User messages no longer repeat a research/no-purchase checklist or grading instructions.
A natural "find the cheapest" remains a comparison request. Stable conventions (Sweden,
SEK, delivered cost, price population/rounding, authorization and tie handling) are supplied
separately in `public.environment_context`. A harness must deliver those through its
instructions/environment; it must not grade undisclosed assumptions. The preview exposes
that context separately, and the public export and combined clipboard copy include it.

This still uses authored templates, not an LLM paraphraser. Informal wording is allowed;
changing the meaning or inventing a hidden interpretation is not. Natural ambiguity that
changes the intended objective/population would require an additional clarification
contract. No realized offers are consulted to repair intent or paraphrases.

Memory modes: none, profile, episodic, mixed, override; auto selects a mode. Mixed placement
uses both channels when sufficient predicates remain accessible. Empty relevant memory is
intentional; filler is deferred. Past purchase alone does not establish an enduring rule:
prose memories explicitly retain a continuing user statement. Current same-field/operator
instructions take precedence, without mutating durable memories. External contradictory
memories, retrieval and forgetting are not implemented.

## Query recipes and reference oracle

| Preset | Objective | Population/allocation |
| --- | --- | --- |
| cheapest | Minimum delivered total | One sellable unit |
| fastest | Minimum latest arrival, then cost | One unit within explicit budget |
| basket | Minimum complete basket total | Three lines, one retailer |
| split_basket | Minimum total of all orders | Three lines, retailers may differ |
| average | Mean delivered cost, half-up öre | Cheapest eligible quote per retailer for the specified fictional model |

Basket quantities are 1 or 2 per line. Each line is fulfilled entirely by one retailer;
no partial fulfilment, split-unit allocation or substitution. Average excludes confirmed
unavailable/nonmatching offers; incomplete population or unknown prices means uncertainty,
and zero members has no defined average. Fictional model references are not bound to the
current commerce MVP and must be bound before rendering any runnable browser task.

`oracle.analyze(task, candidate_plans, coverage_complete=True)` evaluates **trusted complete
quote plans**. Each plan supplies candidate_id, total_minor, arrival_days, purchasable,
currency, destination, delivery_modes and lines with line_id, family_id, model_id,
quantity, sku_id, retailer_id and canonical facts. The commerce adapter must bind facts
to actual selected SKUs, validate world/domain invariants, calculate complete totals and
all allocations, and establish honest completeness. This module never invents basket
shipping totals or optimality certificates. Default completeness is false.

`grade_answer(..., coverage_complete=..., effects=..., clarified_fields=...)` checks base
structured claims and an authoritative whole-run effects ledger, including reversed
unauthorized effects. It returns `full_response_evaluated: false`: free-form claims and
shortfall explanations need an audited interpreter. It is not full episode reward.
No page path, filter use, memory tool call or question by itself is rewarded.

## Validation and limits

```bash
.venv/bin/python -m pytest -q environments/shopping_intent/test_generator.py environments/shopping_intent/test_semantics.py environments/shopping_intent/test_oracle.py
.venv/bin/python -m environments.shopping_intent.verify_preview --output .local/shopping-intent/browser-next
```

The cross-family audit uses four bounded workers over 40 × 5 × 6 × 8 = 9,600 bundles,
checking resolved/durable consistency, source delivery, withheld facts, ingredient rules
and public/private boundaries. Dedicated cases check implication minimization against
finite relations, numeric/set contradictions, cookware/SSD counterexamples, all blocker
families, targeted versus generic clarification, and wording-independent semantics.
Browser acceptance uses two concurrent isolated contexts and individual traces, covering
11 scenarios including coloured spans, hidden-size replies and both JSON downloads.
Current evidence is recorded under `.local/shopping-intent/acceptance.json`; no model
runs or paid inference are involved. The browser verifier uses the repository's local
shared-library directory when present.

V1 evidence remains under `browser-v2/`; it does not validate this revision. Reproduction
requires the source revision/hashes as well as schema, seed and options. Named hash-derived
RNG streams separate families, requirements, memory, omissions, commercial context and
wording. V2 intentionally does not preserve v1 seed-to-task mappings.

Remaining limits: curated finite value choices, uncalibrated prices and probabilities,
conservative rather than exhaustive domain rules, hard requirements only, no guaranteed
feasible world, no actual sites/user simulator/memory delivery, and no deployed integration.

## Catalog generation extension, 2026-09-25

[The independent catalog sampler](product-world-generator.md) now generates real canonical
model/SKU references for six families, including beer and wine. The original authoring
page still uses its standalone fictional references; the catalog inspector and its
`task` command explicitly bind references before rendering. Beer has production-region,
filtration and producer-described-bitterness fields. A locality relation prevents
country/region contradictions; these fields are never hidden user blockers. No new
best-value or subjective-taste oracle is claimed.

## World-facing task extension

The combined product-world sampler now adds typed shopping preferences and memories
for travel, collection readiness, merchant geography/reviews, and optional cookie
consent, plus collection/inspection/unit-price query recipes. These additions are
composed by `product_world.scenario.sample_task`; the standalone 40-family sampler
remains the product-predicate authoring entry point. See
[world task coverage](world-task-coverage.md) for schemas, deterministic reference
checks, consent exposure requirements and remaining integration work.
