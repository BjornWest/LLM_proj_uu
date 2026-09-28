# Proposed teacher evaluation: from lookups to constrained research

This is a proposed 20-case task ladder, not 20 already-frozen runnable episodes.
Difficulty is a prediction until model runs establish it. All tasks are research or
recommendation tasks: no purchase, signup or unauthorized account/cart changes.

Use generated names, exact options, stores and destinations when binding each recipe.
The prose below illustrates the request, not a claim that an offer satisfying it exists.
For the current world, home is Malmö and amounts are SEK. Relevant memories must be
provided to the policy; a hidden preference is not a valid failure criterion.

Current support labels:
- **Core:** relevant selection/quote/aggregate predicates exist in the local task and
  grading stack; this exact recipe still needs compilation and end-to-end acceptance.
- **Helper:** deterministic grading helper exists, but the common episode answer path
  is not yet established for this task type.
- **Extension:** public facts exist; a small typed answer contract/grader is needed.

## 1. Trivial to easy: isolate basic browser and answer reliability

| ID | Example request and starting point | What establishes correctness | Support |
|---|---|---|---|
| E01 | On a supplied retailer page: “What is the price of this exact laptop option, and how many are in warehouse stock?” | Exact SKU, item price, stock. An unavailable option is a valid answer. No delivery-total claim required. | Extension: factual lookup |
| E02 | “Find the cheapest delivered offer for this exact laptop.” Start at a product page; use a small world with one or two retailers. | Correct option, eligible minimum delivered total and retailer SKU link; all ties accepted. | Core |
| E03 | “Compare these two laptop configurations: RAM, storage and weight. Which is lighter?” Start at their comparison page. | Each field assigned to the right SKU, correct units, lighter/tied result; missing values stay unknown. | Extension: comparison facts |
| E04 | “What would two packs of this food cost delivered to my home? Is that quantity available?” Start at one offer. | Quantity-aware subtotal, shipping, total, stock eligibility and exact pack. This is a quote, not an order. | Extension: named-offer quote answer; quote engine exists |

These should expose parsing, tool-use, units and basic reporting failures without a
large search problem. E01/E03/E04 need small graders; they should not trigger a new
website or generator subsystem.

## 2. Moderate: normal shopping research across existing sites

| ID | Example request and starting point | What establishes correctness | Support |
|---|---|---|---|
| E05 | “Find the cheapest Aster Stride 0001 in EU 40, standard width, black, delivered to Malmö. Include shipping.” Start at the index. | Correct model and exact option; global eligible minimum total. Advertised model price alone is insufficient. | Core |
| E06 | “Find the cheapest laptop with at least 16 GB RAM, at least 512 GB storage, a Swedish keyboard and weight no more than 1.5 kg.” | Every explicit attribute plus total, availability and exact retailer link. No substitutions without permission. | Core |
| E07 | “Find complete wet kitten food without chicken, at the lowest delivered cost per kilogram.” | Full ingredient exclusion, food type/life stage, complete-food flag and pack-normalized delivered price. Recipe name alone does not prove ingredients. | Core |
| E08 | “Find the lowest delivered price per litre for dry, non-sparkling white wine from France. Maximum total spend 700 SEK.” | Correct wine attributes; bottles × bottle volume; total budget and normalized price. A cheap litre price does not waive the total budget. | Core |

## 3. Hard: collect a population, calculate, or interpret natural text

| ID | Example request and starting point | What establishes correctness | Support |
|---|---|---|---|
| E09 | “What is the average delivered price for this exact laptop option across retailers that can supply it? Count each retailer once and tell me how many.” | Complete eligible retailer population, arithmetic mean of totals, explicit count and rounding. Average-source overview links optional. | Core |
| E10 | “Where can I collect this exact pair of shoes within two days, with no more than 30 minutes of cycling? Choose the shortest journey; break ties by total cost.” | Real pickup/branch stock and readiness, correct travel mode/time, objective ordering and total. Warehouse availability is not branch availability. | Core; compose and validate objective ordering |
| E11 | “List every laptop with a Swedish keyboard, at least 16 GB RAM and weight at most 1.5 kg that any retailer can deliver. Include exact options and the cheapest total for each.” | Complete deduplicated SKU set, no false positives/omissions, correct per-SKU minimum and links. | Extension: complete-set answer |
| E12 | “For this exact shoe option, how many Reader Panel reviews report heel rubbing on long walks, how many explicitly say it did not happen, and how many describe mixed experiences? Also report neutral and unassessed counts.” | Canonical review counts, actual use in context, exact SKU. Exclude attributed second-hand experiences; mixed, neutral and unstated remain distinct. | Helper: review-count task/grade |

E12's counts are not inferred from star ratings. The public task context must define
the relevant corpus and population; the page must not display grading labels.

## 4. Very hard: coverage gaps, combined constraints and justified abstention

| ID | Example request and starting point | What establishes correctness | Support |
|---|---|---|---|
| E13 | “Find the cheapest matching laptop delivered within three days. Only use merchants averaging at least 4 stars with at least 10 reviews.” Product requirements also appear in an accessible memory. | Product + current request + merchant-review population + delivery constraints + global minimum. | Core |
| E14 | “Find the cheapest shoes in my usual size, including delivery. Comparison sites may not cover every shop.” Start at the index in a frozen partial-coverage world. | Global retailer population; an untracked optimum still counts. No reward for a prescribed navigation route. | Core |
| E15 | “Find a pair in my usual EU 40 size delivered for no more than 900 SEK. If none qualifies, say so; do not suggest a larger size or exceed my budget.” | If complete evidence rules out every offer, `no_match`; if there is a valid offer, choose it. The intended rejection-control instance must be independently confirmed. | Core |
| E16 | “Find the cheapest EU 40 shoes where most long-walk users say that exact option is comfortable. Do not transfer reviews from another size.” | When decisive exact-option evidence is missing, `uncertain`, not a recommendation or global no-match. Current accepted v7 example demonstrates this outcome. | Core |

E14 is a coverage challenge, not a task instruction to ignore comparators. In a paired
presentation variant the hint can be omitted, with the same explicitly global scope.
E15 is a normal affordable-budget request, not a contradictory trick. No world is
repaired or discarded to force failure. The outcome must be queried from the frozen
world. No-match can be easy (one decisive contradiction) or hard (exhaustive search).

## 5. Frontier: hardest useful combinations within this project's scope

| ID | Example request and starting point | What establishes correctness | Support |
|---|---|---|---|
| E17 | “For each of these three exact laptop options, count first-hand typing reports that praise keyboard comfort, criticize it or are mixed, and separately count reports of bothersome fan noise versus explicit absence.” | Per-SKU, per-aspect population and all requested counts; no duplicate or cross-aspect/cross-person attribution. | Helper plus multi-subject answer composition |
| E18 | “Find the lowest delivered cost per kilogram for complete wet kitten food without chicken, arriving within three days and costing at most 600 SEK. Most owners reporting feeding that exact recipe/pack should say their cats readily ate it; use merchants with at least 4 stars and 10 reviews.” | Correct ingredients/pack/quantity, unit-price optimization, total/deadline, merchant threshold and contextual product-review majority together. Missing decisive evidence remains unknown. | Core predicates; composite recipe needs acceptance |
| E19 | “Average the cheapest qualifying delivered shoe offer at each retailer for my EU 40, standard-width size. Only include options meeting my long-walk comfort preference and arrival deadline; include stores absent from comparison sites.” | Exhaustive eligible population, one minimum per retailer, contextual evidence and correct mean/count. If eligibility of a relevant retailer is unresolved, do not silently exclude it. | Core aggregate + review predicates; composite recipe needs acceptance |
| E20 | “Find my cheapest suitable walking shoes within 1200 SEK, delivered within three days. Use my size/fit preferences, only established merchants, and require positive long-walk comfort evidence for the exact option. If you cannot establish a valid recommendation, explain whether every offer is ruled out or whether specific evidence is missing.” Start at index; larger world, uneven comparison coverage, natural review disagreement and accessible episodic preferences. | All hard predicates, global optimality when determined, otherwise correctly distinguish no-match/unknown. No unauthorized effects. Qualified explanatory claims need separate review; current status-only checks are insufficient for the full explanation. | Core base outcome; explanatory-claim grading incomplete |

For E20, the accessible memory must make the soft wording concrete: for example,
EU 40/standard width, merchant average at least 4 stars with at least 10 reviews,
and a strict majority of actual long-walk users reporting comfort. These are visible
user requirements, not grader-invented meanings for “suitable” or “established”.

These are the hardest *meaningful current-world compositions*, not a claim of an
absolute difficulty ceiling. Difficulty can grow with more plausible candidates,
less comparator coverage, more reviews and pagination. Random extra text or simply
running out the step budget is not a useful definition of difficulty.

## Three terminal states, plus execution failure

1. **Selection/answer:** a correct supported answer is established.
2. **No match:** complete relevant facts rule out every candidate under the user's
   hard requirements. State the blocking constraint(s); no unauthorized relaxation.
3. **Uncertain:** evidence needed to assess a potentially relevant candidate is
   absent/incomplete. State what is unknown; do not pretend that it is false.
4. **Technical/unfinished:** broken environment, failed tool/provider or search
   unfinished at the budget. This is not evidence that the request is impossible.

The public request should not reveal which of these the private reference expects.
We grade outcomes, not whether a particular page was visited. Traces can diagnose
coverage, review exposure, repeated work or unsupported early stopping separately.

## Binding and evaluation rules

- Bind requests using product identities/traits and accessible user context, not by
  inspecting stock/prices/review opinions to guarantee success. Keep no-match worlds.
- Difficulty settings belong in the recipe: number of stores/models/variants, review
  density, comparator membership, memory placement and start page. Preserve realistic
  correlations. Do not make information available only through private state.
- Freeze a small predeclared seed/config bank. Analyze its outcomes once and retain
  every instance. If it lacks a desired outcome class, report the gap; do not silently
  retry until the requested balance appears. Separate deliberately authored regression
  controls from estimates of naturally sampled outcome frequencies.
- Establish truth for rejection controls before calls. Include feasible controls so
  an agent that always says “nothing qualifies” cannot score well. Do not publish
  outcome tags on the task card or in semantic case IDs visible to the policy.
- Ordinary user prose comes first. A small common structured result envelope can
  support deterministic grading, but record formatting failures separately from
  independently understood answers. No silent response repair or rerun.
- Per-condition checks: product/variant, quantity, constraints, price/units, population,
  source identity, requested answer fields and unauthorized effects. Explanations that
  current graders do not cover stay explicitly ungraded and manually audited.
- Compare teachers on the same frozen worlds, goals, tools, context/memory delivery,
  stopping rules and limits. Use enough headroom for the hard cases; report truncation.
  Difficulty labels remain provisional until observed success/cost/latency/trace data.
- Prioritize binding Core tasks first, then cheap lookup/count answer extensions.
  No new site designs, purchases, basket allocation, foreign-currency conversion,
  price-history feeds, accounts or simulated seller conversations are required here.

The initial suite can use one case per row once its stated gap is closed. For an early
smoke, start with E02/E05/E06/E07/E08/E09/E13/E14/E15/E16 and then E18/E19/E20 after
composite acceptance. The small contract extensions add useful easy controls; they
should not delay checking the existing core path.

## Product review: first six bindings

Reviewed support proposal (26 September): bind E05, E08, E09, E14, E15 and E16 first,
against the unchanged pin-v2 catalog/quotes and **v7** natural-review publication.
This is a bounded first subset, not a replacement for the full difficulty ladder.
All six now have frozen public/private bindings and offline episode acceptance in
`binding-v1`. See the [binding report](agents/teacher-evaluation-six-case-binding.md)
and [local task cards](http://localhost:48764/). E05/E14 are feasible, E08/E15 are
no-match, E09 has an undefined mean (null value, zero retailers), and E16 is uncertain.
These are realized outcomes, not model results. E08/E09 do not exercise successful
unit-price optimization or nonempty averaging; all cases remain retained. Any newer
drink-review preview stays a separate cohort.

Corrections/limits from Product review:
- E10 must explicitly compile the cost tie-break after travel time; current
  nearest_pickup defaults do not implement that wording. Include a time-tie check.
- Empty complete average populations return `average` with value null/count zero,
  not `no_match`. Unknown eligibility preserves uncertainty. Per-retailer minima
  precede the mean; final rounding is half-up to integer öre.
- E12's helper requires positive, negative, mixed, neutral and unassessed totals;
  task wording and the answer envelope must both ask for those five values.
- Current uncertainty handling is conservative: any unknown candidate prevents a
  determined result, even if it might not improve the best known candidate. Do not
  silently test a different proof-of-optimality rule in the first cohort.
- Correct status and links do not establish a correct explanation. No-match blocking
  reasons, population claims and explanation/source entailment require separate
  manual review until typed claim verification exists. An automated status pass is
  not a claim that justified abstention is fully evaluated.

Detailed private coordination review: `.local/coordination/teacher-eval-ladder/product-review.md`.

## Updated evaluation order: Qwen first, then teacher candidates

User decision, 26 September: the next model evaluation uses Qwen, after the world
pipeline is ready end to end. Teacher-candidate comparison is later. The six-case
compilation and offline acceptance are complete; the normal harness bridge and
multi-seed integration checks remain. This document does not initiate model calls.
Fix the exact configured Qwen model, routing, reasoning, context and turn
limits in the new run profile rather than inheriting historical calibration defaults.

Readiness means generation -> frozen scenario/corpus -> published pages -> policy-only
task/memory delivery -> real harness episode -> terminal independent grading -> retained
trace. A task card and HTTP conformance alone do not establish that entire path. Include
positive/negative scripted outcomes and verify unknown versus no-match handling; label
ungraded prose separately. No runtime mutations within the frozen Qwen cohort.

After sandbox runs, try a small set of matched real-web journeys, each with full manual
trace review. Candidate pairs: (1) New Balance 530 Raincloud EU 47.5/US men's 13, total cost
including delivery to Sweden; (2) a real laptop with fixed model/specification/keyboard
requirements; (3) pet food with pack-size/ingredient constraints and delivered unit-price
comparison. Bind actual in-stock or unavailable listings only when preparing the run;
these are prospective tasks, not claims that current offers exist. Reviews may add a
later qualitative pair once a clear, naturally occurring scope can be established.

Use the existing isolated open-internet browser with no personal accounts/data. Research
only, no orders/signups. Match model/tools/request scope where practical; record unavoidable
differences in sites, data, geography and rate limits. Observe headfully if useful. Human
steering or rescuing a stuck agent is allowed for exploration but must be timestamped and
classified as assisted continuation, not an unassisted success.

Review every trace for: first difficulty point; information actually observed; exact
variant preservation; advertised versus final price; shipping/fees/eligibility; coverage
assumptions; interpretation of attribution/reviews; unsupported conclusions; tool or
observation defects; any human interventions. Record successful shortcuts and missing
realistic obstacles as carefully as failures. Save reusable retailer practices separately
from the specific SKU to inform future generator features.

Real-web comparisons are qualitative. Record evidence and its capture time; availability
and prices change. Open-web search cannot generally establish that no matching product
exists anywhere, unlike a complete finite sandbox. Distinguish no qualifying offer among
specified/checked sites, missing evidence, access restrictions and unfinished search.
Do not merge these runs into the sandbox pass rate or adjust the generator after each
single failure without identifying the cause.
