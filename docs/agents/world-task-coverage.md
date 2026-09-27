# World features, task coverage and remaining generation work

Implemented local authoring/reference increment, 2026-09-26. Owners: product-world
and shopping-intent. No commerce-engine, shared-index or review-renderer edits. The
live inspector is <http://localhost:47401/>. No model episodes or paid calls performed.

## Coverage audit

| Generated feature | Task/memory coverage now | Remaining boundary |
| --- | --- | --- |
| Six canonical product families, SKU axes and description facts | Existing typed product predicates and fit/compatibility clarification | Forty intent families exist, but only six have canonical world generation |
| Delivery country, price, stock, arrival | Cheapest/fastest/average; geographic single-line quote adapter | Full browser checkout still has its own narrower contract |
| Physical branch inventory and warehouse transfers | Cheapest/nearest/soonest pickup, no-transfer preference, readiness limit | No branch-to-branch or partial-stock transfers |
| Inspection/display units | Nearest physical shop to inspect footwear/laptops | Display availability is separate from saleable stock; no opening-hour schedules |
| Walking/cycling/driving | Mode and one-way distance OR duration requirement in request or memory | Local walk/cycle only; unknown estimates remain unknown |
| Foreign retailers | Merchant-home-country predicate, including durable domestic preference | Merchant origin, delivery destination and product origin remain separate |
| Merchant reviews | Minimum arithmetic mean stars AND minimum published count | Historical testimony, not merchant safety or guaranteed service quality |
| Packs, volume and weight | Exact delivered cost per litre/kg objective | No subjective quality/value score |
| Cookie purpose decisions/history | Optional typed consent memory/request override and separate score helper | Episode exposure and journal delivery are harness responsibilities |
| Names, merchant scale, branch count | Background facts shape the environment | Do not force arbitrary name/size requirements just to make every field graded |
| Independent product reviews | Existing exact-SKU facts can substantiate product requirements | New measurements, opinion interpretation and product-rating tasks need a source/evidence contract |

## Grader coverage boundary

The sampler's output space is larger than the connected-world grader's coverage.
`shopping_intent.oracle` evaluates typed predicates (`eq`, `ge`, `le`, `contains`,
`excludes`) against supplied authoritative candidates. `product_world.outcomes`
constructs those candidates only for single-line geographic scenarios in the six
world families. Non-geographic exports need another quote adapter; the remaining
intent-only families have no canonical generated worlds here.

Supported objectives are cheapest delivered, fastest delivered within budget,
average delivered price (cheapest eligible quote per retailer), cheapest/nearest/
soonest pickup, nearest inspection for footwear/laptops, and cost per litre/kg for
drinks/pet food. Product requirements and bound memories, quantities, stock, delivery
limits, merchant country/review thresholds, travel mode/limits and transfer/readiness
predicates are checked against exact SKU and branch facts. Tied optima are accepted.
Unknown and no-match statuses are supported, but their prose explanations are not.

Important incomplete paths:

- Basket and split-basket tasks can be sampled. The generic predicate checker can
  inspect an externally supplied complete basket plan, but the world adapter cannot
  yet construct/price those plans. Joint shipping, allocation and shared quantities
  are missing; it explicitly rejects multiple lines.
- A hidden size/compatibility requirement yields `unresolved_user_specification`
  until the trusted host records clarification. The grader handles that condition;
  the current connected demo does not implement a conversational user simulator.
- Answers must be structured. Free-text extraction, every explanatory claim,
  justifications for unknown/no-match, subjective product opinions and browsing
  procedure are not graded. Correct structured selection is not a full-response grade.
- Answer-v3 requires an exact SKU/retailer link for recommendations, except when an
  explicit task request asks for the product's comparison page. Average-price overview
  links are optional, with no per-SKU requirement. No-match/uncertain responses need
  relevant source links; checking those links does not grade the explanations.
- Whole-run side effects and cookie exposure require trusted host evidence. The
  local script supplies it; this is not a completed model-training reward pipeline.

Audit `.local/product-world/grader-coverage-20260926/` covers 168 fixed generated
cases: all 42 applicable family/query pairs, four seeds with varied memory/world
preferences, including 21 hidden-clarification cases. Every expected structured
result was accepted and unresolved clarification stayed ungraded. This uses private
reference truth, not browser solving or exhaustive coverage of all combinations.

## Footwear comparison and exact pricing

Footwear comparisons are at model level, with size/ordinary colour/width selected
at the retailer. No fabric-changing colour semantics exist yet; a distinct material
or construction belongs in a distinct commercial product identity, not an inferred
split by cosmetic colour. Other families retain exact configurations.

New worlds export `public.comparison_listings`: one footwear retailer/model row,
`advertised_price_minor`, and a listed `entry_product_id` for navigation only.
Ordinary options share one retailer/model price. Authored store prior
`footwear_size_surcharge_probability` defaults to 0.1 per retailer/model; when
sampled, the largest generated size adds 10%, rounded to whole SEK. The advertised
comparison price stays unchanged. This is a configurable synthetic hindrance, not
an empirical prevalence estimate. Canonical offers and geographic quotes retain
actual prices/stock; the oracle never treats the advertised price as checkout truth.
Pin-v2/new runtime demonstrates this contract; pin-v1 remains historical evidence.

## Task construction

`product_world.scenario.sample_task` now composes the existing product-intent sampler
with `shopping_intent.world` and optional `shopping_intent.consent` extensions. It
finishes the full task before world construction. Neither extension can inspect
realized products, stocks, routes, ratings or a winning offer. Changing world/review
seeds or review counts leaves the task, memories and hidden specifications fixed.

New single-line query names:

- `cheapest_pickup`: minimum collection total.
- `nearest_pickup`: minimum one-way travel minutes in the required mode.
- `fastest_pickup`: minimum ready days, then collection total.
- `nearest_inspection`: minimum one-way travel minutes to an available inspection
  unit; only footwear/laptops, no purchase eligibility or purchase budget.
- `unit_price`: minimum delivered total divided by full purchased litres (beer/wine)
  or kilograms (pet food). Pack count and per-unit volume both contribute.

Existing cheapest, fastest, average and basket recipes remain. Random single-line
query selection is uniform among applicable recipes; it never inserts basket families.
Inspection and collection require a sampled home. Random family selection respects
query capabilities; explicit unsupported combinations fail rather than being repaired.

`world_preferences`: `none`, `reputation`, `domestic`, `reputation_domestic`, `auto`.
Auto has authored weights 40% none and 20% each remaining recipe. Collection/inspection
still require a travel mode and limit when optional retailer preferences are `none`.
Only one distance/time limit is sampled. No-transfer and waiting-limit statements
are alternatives, avoiding redundant ready-now rules. All are requirements, not
unmodelled soft preferences. Product size remains a product requirement.

Request predicates are in `explicit_world_requirements`; private bindings for durable
profile/episodic memories are in `world_memory_facts`; resolved predicates are in
`resolved_task.world_requirements`. Each predicate has field/operator/type/unit/value,
and resolution adds its request/memory source. Shopping-wide memories and pickup/
inspection memories have distinct scopes. Explicit same-field/operator instructions
override memory without rewriting it. These preferences are never hidden user blockers.
Prose episodes carry private structured bindings; unbound filler prose has no reward
meaning. Both world and consent bindings enter the task semantic fingerprint.

The authoring interface keeps one human-style message with coloured source segments,
plus structured profile and prose episodic memories. Separate prose seeds change
wording without changing semantics. Geographic context, counting conventions and
authorization are delivered separately, not appended as repeated safety instructions.

## Reference outcome and evidence

`product_world.outcomes.candidates_for(scenario)` validates the world/geographic
sidecar, matches the task destination and checks review corpus hashes/statistics.
It enumerates the complete bounded single-line population of offers and applicable
branches using the existing fulfilment quotes. All candidate data is privileged.

The generic `shopping_intent.oracle` now checks world predicates, activity-specific
availability and objectives. Inspection uses `inspectable`, not `purchasable`, and
does not require a purchase price. Unit prices use an integer numerator and integer
milliunit denominator, ranked with exact fractions; no rounded floating-point ties.
Unknown routes/reviews remain uncertain unless another known failure already excludes
that candidate. Empty reviews have count zero and undefined mean, not five stars.
Best candidates are never fed back into task/world generation.

`evaluate(scenario)` returns candidate diagnostics and determined/no-match/uncertain
reference results. The inspector's button calls private `/api/reference-outcome`;
the public travel origin has no such endpoint. Basket evaluation explicitly refuses
to approximate complete-order shipping by summing independent one-SKU quotes.
Structured selection grading additionally checks branch, mode, travel/readiness or
unit-price evidence when applicable. Fit clarification and whole-run effects checks
remain; free-text grading still reports `full_response_evaluated: false`.

Every combined scenario now exports `merchant_reviews` independently of the request.
Optional `review_options` supplies seed, frozen date, reviews per store and existing
review priors. Renderers/harnesses must use this same corpus before its thresholds are
task evidence. Existing separately generated review previews are not silently replaced.

## Cookie preferences and auxiliary scoring

Coordination: `COOKIE-MEMORY-20260926`, `.local/coordination/cookie-memory/handoff.md`.
`cookie_preferences`: `none`, `necessary_only`, `analytics_allowed`,
`analytics_required`, `auto`. Auto samples none with probability 1/2, otherwise the
three authored recipes equally; with memory mode none, auto remains unspecified.
Explicit cookie recipes with no memories appear in the current request instead.

Each of analytics/personalisation/marketing resolves to `unspecified`, `allowed`,
`forbidden` or `required`. Current request overrides remembered state per purpose.
Allowed is never interpreted as required. Absence is never interpreted as rejection.
`cookie_memory_facts` bind profile/prose memories to these states; ordinary task
completion does not depend on cookie choices.

`shopping_intent.consent.score_consent` consumes the curation-owned private
`site-consent-journal-v1`, an explicit delivered-preference flag and exposed session
IDs supplied by a trusted harness. Journal presence/request logs do not prove exposure.
No preference, permission-only preferences, no exposed popup, or undecided choices
yield no positive score. Opening settings/button order are not scored. A committed
forbidden opt-in fails even if later revoked; required states are checked at the end.
Repeated saves do not add reward. Missing history is rejected. This is one auxiliary
0/1 component, with configurable authored default weight **0.05**, separate from main
task completion. Pending encountered popups prevent positive completion credit.
This score is implemented locally and consumed by the connected episode adapter;
it is not wired into a model-training run.
Consent journal events must be handled through this component, not blindly classified
as forbidden purchases/cart changes by a generic commerce-effects adapter.

## Comparison coverage sampling

`product_world.comparison_coverage.generate_coverage(world, sites, seed=..., config=...)`
exports `comparison-coverage-v1`, a separate public membership sidecar bound to the
canonical `world_sha256`. Each site specification has a stable `site_id` and a list
of `families`; membership exports `comparison_ids` and actual
`{comparison_id, retailer_id}` listing pairs. Footwear uses model IDs, other current
families use exact SKUs. `validate_coverage` checks source binding, identity, family
scope, duplicates and real listing pairs. A tracked product may have zero listings.
The catalog may also contain variants carried by no retailer; these are distinct
from offered products deliberately omitted from all comparison sites.

Sampling uses independent identity/site RNG streams: a global retailer-only mask
(default .12), shared core among the remainder (.75), site additions outside that
core (.45), retailer feed inclusion per site (.85), then listing inclusion (.90).
These are conditional probabilities, not guaranteed realized population fractions.
Family scope always applies. Site order and adding another site do not change the
existing sites' membership. No task, winner, price, stock or layout enters sampling;
no retries force feasibility. Zero/one probabilities support explicit authoring
recipes. Public membership contains no task or winner annotations.

Existing tasks still concern all provided retailers. Missing comparison entries do
not mean globally unavailable, and comparator prices do not prove a global optimum.
Canonical retailer discovery must remain available independently. The oracle keeps
all canonical candidates, even if every comparator omits them. `coverage_summary`
and `candidate_visibility` return private, post-generation authoring diagnostics;
they do not alter task requirements, filter candidates or reward a browsing route.
Average-price tasks keep their existing population and optional overview link.
Future questions explicitly scoped to a named comparison site need a typed population
contract. Likewise, comparison-page answer bindings must respect actual membership
when these sidecars become part of a graded episode. `Episode.from_runtime` now
checks coverage and URL-binding hashes, matches registered comparison sites and
accepts only actual covered pages. An omitted product has no comparison answer URL;
it remains eligible for an ordinary retailer-link recommendation.

Coordination `COMPARISON-COVERAGE-20260926`: frozen additive demonstration at
`.local/coordination/comparison-coverage/pin-v1/`, over unchanged product-pin-v2.
Four sites include two general sites and footwear/laptop specialists. The single
seed-42 draw has 57 comparison identities, 40 offered somewhere, nine offered but
untracked everywhere, and one tracked on exactly one site. The laptop specialist
tracks three products with zero listings; this sampled case is retained as-is.
`coverage.public.json` is the only public artifact. Adjacent recipe, byte/source pins
and private visibility diagnostics are host-side evidence; do not serve that folder.
Curation owns projection, filtering and publication. This sampler does not replace
the live task world or establish browser/model acceptance for the new designs.

Reproduce the frozen membership from the repository root:

```python
import json
from pathlib import Path
from environments.connected_shopping.pins import load_pin
from environments.product_world.comparison_coverage import generate_coverage

root = Path('.local/coordination/comparison-coverage/pin-v1')
recipe = json.loads((root / 'recipe.json').read_text())
scenario, _ = load_pin(recipe['source_pin'])
coverage = generate_coverage(scenario['bundle'], recipe['sites'],
                             seed=recipe['seed'], config=recipe['config'])
assert coverage == json.loads((root / 'coverage.public.json').read_text())
```

Eighteen deterministic checks in `test_comparison_coverage.py` cover validation,
identity agreement with the renderer, independence and unchanged global outcome
analysis. Independent pure membership and geographic-oracle test groups were run
concurrently. These are local software checks, not training or model results.

## Next work, in order

1. **Connected episode coverage:** the first research episode now binds storefronts,
   review corpus, travel snapshot, web index, delivered memories and grading to the
   same immutable world. Public-page scripted footwear solving is verified; see
   [connected episode adapter](connected-shopping-episode.md). Broaden browser
   acceptance to pickup, inspection and review predicates before claiming those
   complete task paths are verified. Paid model evaluation remains separate.
2. **Basket fulfilment:** authoritative order/shipment grouping, joint shipping fees,
   shared stock quantities and pickup allocation. Existing basket intent does not
   make the single-line geographic quote adapter sufficient.
3. **Product-review evidence:** structured exact-SKU opinions, reusable templates,
   majority/rating preferences and count-task helpers now exist; see
   [review evidence](product-review-evidence.md). Finish renderer binding of the
   frozen corpus and browser acceptance before claiming review-dependent site tasks
   are end-to-end verified. Measurements and general prose extraction remain pending.
4. **Broader world semantics:** more of the 40 families, returns/warranty policies,
   branch-stock correlations and richer compatibility/dependency constraints. Add
   request/memory/oracle coverage alongside each data contract.
5. **Sampling calibration:** measure success/no-match/unknown distributions, tune
   transparent priors and query weights without retrying worlds until they succeed.
   No empirical distribution or model performance claim exists yet.

## Checks

137 unit/reference tests across product_world, travel and shopping_intent pass;
six isolated browser cases cover collection, inspection, unit value, reputation,
cookie memories and legacy baskets. Evidence:
`.local/product-world/world-intent-browser-v1/report.json`. The semantic/memory audit
uses four bounded workers; browser cases use two isolated contexts. Consent tests
consume actual `ConsentUI` journals without editing the curation-owned runtime.
