# Procedural commerce: task families, grading and world requirements

Discussion draft, updated 2026-09-22. This is the next design priority before further sampler tuning or new storefront designs. It extends the [world design](procedural-commerce-design.md) and keeps the existing [outcome/procedure distinction](task-definitions.md). No generator, memory integration, new grader or deployment is implemented by this document.

The [request-by-request requirements wishlist](procedural-commerce-request-requirements.md) expands the 16 generic request families into navigation stages, shared capability IDs and outcome checks. It is the current detailed scope, including the later account-task extension.

## Design order

Start with the user-facing task families and their acceptable outcomes. Derive the facts, interactions and evidence the world must support from those contracts. Then define sampling relationships and distributions for those facts, followed by renderer implementations.

This determines the world's **schema and supported capabilities**, not a desired answer. After generating a world and request, query what outcomes are possible. Never discard or reshape a world because the user's budget, deadline, requested variant or top-K size cannot be satisfied. Unfulfillable requests are ordinary tasks.

A task combines an objective, a target specification, constraints/preferences, action authorization, initial user context and a response contract. Memories can supply some of these semantics without changing the shopping task family.

## Initial task-family inventory

| Family and example | What we grade | What the world must represent |
| --- | --- | --- |
| **Exact-product offer search:** “Find the lowest delivered price for this shoe/color/size.” | Correct equivalent SKU, eligible offer, landed total and currency, required qualifications; cheapest acceptable offer or truthful infeasibility/uncertainty report | Canonical variants, cross-retailer equivalence, offers, destination-specific quotes, commercial conditions, bounded comparison scope |
| **Shortlist/comparison:** “Give me the three cheapest qualifying offers and their delivery dates.” | Eligibility, distinctness under the requested unit, accepted top-K membership/order with ties, accurate requested fields; fewer than K when fewer qualify | Same offer world, multiple candidates, explicit comparison fields and ranking relation. Specify whether K counts products, stores or offers |
| **Product selection:** “Find a new laptop with at least 32 GB RAM and under 1.5 kg, within my budget.” | Attribute constraints and any stated ranking/tradeoff; accept all permitted choices where no unique optimum is specified | Several models/configurations with typed specs and genuinely relevant differences; usable search/filter/detail pages |
| **Audit an advertised offer:** “Is this 849 kr price actually available for one pair in my size, delivered to me?” | Correct validity/qualification conclusion, actual applicable total or explicit unknowns, accurate explanation of material conditions; no unauthorized purchase | Aggregator claim independently represented from actual SKU, promotion eligibility, shipping and retailer terms; source pages exposing relevant facts |
| **Execute a purchase:** “Buy the cheapest eligible pair, up to 1,100 kr, arriving by Friday.” | Committed SKU, quantity, terms, delivery option and total; authorized effects across the entire episode; selection optimum only if requested | Stateful cart, option selection, quote calculation, checkout, immutable orders and side-effect history. An impossible order request permits a correct no-purchase report |
| **Prepare or correct a basket without buying:** “Set up this cart with express shipping and no warranty; stop before ordering.” | Desired final cart/quote, correct selections, preserved unrelated initial items if required, no committed purchase or other forbidden effects | Persistent editable carts, explicit initial state, quote invalidation, extras and shipping selection; final cart itself is the requested result |
| **Optimize a shopping list:** “Find/buy these three items for the lowest total; separate orders are fine.” | Correct quantities/variants, total across orders, applicable basket discounts and shipping, any order-count constraint, global acceptable solution | Basket-dependent rules, cross-store allocation, shared shipping/thresholds, discounts and whole-run order ledger |
| **Explain tradeoffs or request a decision:** “What is cheapest, and what faster alternative is worth considering?” | Accurate alternatives and tradeoffs under stated preferences; an appropriate specific clarification when a material choice is unresolved; no unauthorized choice/commit | Multiple cost/delivery/service dimensions, user preferences, explicit uncertainty; scripted user responses/session continuation if interaction is part of the task |
| **Catalog enumeration:** “List every laptop in this catalog with at least 32 GB RAM and below 1.5 kg.” | Exact matching set, no omissions or spurious items, correct deduplication and requested fields; empty set is valid | Bounded catalog scope, typed attributes, pagination/filter behavior and stable identities |
| **Price statistics:** “What is the average delivered price of this exact configuration across these stores?” | Correct population, applicable prices, aggregation, units/currency, rounding and treatment of unavailable observations | Comparable offers/quotes, explicit aggregation grain and missingness; enough public data to calculate the statistic or correctly report limits |
| **Price movement:** “How much did the average price of these models change over the last month?” | Correct dates, cohort and statistic, comparable price basis; distinguish absolute change, percentage change and mean individual percentage changes | Coherent timestamped price histories, variant/offer identity across time, history access and missing-history semantics |
| **Attribute prevalence:** “What percentage of the listed phone models support wireless charging?” | Correct numerator/denominator and percentage, including declared treatment of unknown attributes and duplicates | Typed attribute applicability, known/unknown values, explicit model-versus-variant population and accessible complete catalog scope |

These are different outcome contracts, not mandatory separate engines. Search, shortlist and offer audit can reuse the same quote/oracle machinery. Purchase adds effects. Basket preparation changes the terminal target. Multi-item optimization changes the aggregation scope.

Current scope clarification: account/order inspection and explicitly supported order changes belong in the wishlist, staged after core comparison/purchase. Persistent price monitoring and seller negotiation are out of scope. The initial inventory above predates the account-task extension; see Q13/Q14 in the detailed requirements.

## Analytical tasks: specify the population before the formula

Analytics are a first-class task family, not merely a shopping-report variation. They also require broader catalog coverage than inspecting a few attractive offers.

Each generated task needs public, understandable semantics for:

- **Population:** which retailers/catalog/category, geographic market and time range; all listings, unique models, canonical variants or one selected offer per item.
- **Measure:** advertised price versus actual purchase price; product-only versus delivered total; tax/fees, quantity, currency and any modeled FX basis.
- **Operation:** complete set, count, mean, median, percentage, absolute movement or percentage movement; weighting and deduplication.
- **Missingness:** not applicable versus unknown versus unavailable; zero-member populations; absent observations at a date. Never silently count unknown as false or absent price as zero.
- **Reporting:** requested precision, reasonable rounding tolerance, coverage qualifications and any source/date requirements.

For example, “mean of the cheapest in-stock offer for each distinct laptop configuration at these three stores” gives each configuration one vote. “Mean of all retailer listings” weights multiply listed configurations more heavily. Both are legitimate tasks; their difference must not be hidden only in grader code. Natural ambiguous requests can support a clarification or explicit conditional answer rather than one secret interpretation.

For an exhaustive listing, record false positives and missed items separately. For attribute prevalence, a zero denominator is undefined, not automatically 0%. If attributes are genuinely unknown, the task may require reporting known coverage or bounds rather than an invented exact percentage.

Price histories must belong to the same semantic world: identify what each series measures, its dates, currency/market and variant, and relate its final point to the corresponding current or explicitly stale state. Do not independently draw decorative graph values and then grade them as authoritative history. Historical prices do not imply historical inventory/eligibility unless the world represents those too. Start with static, dated history; no wall-clock-driven world mutations are required.

## Product families and reusable traits, beyond SKU identity

A canonical SKU identifies a particular sellable configuration. It does not by itself describe valid dimensions, their relationships, their meaning to the user, appropriate task types or compatible hindrances.

Use **product-family definitions composed from typed traits**, with category-specific parameters and rules. A family defines meaningful combinations; traits provide reusable semantics. Do not put every possible field on every product or use one giant list of category exceptions.

| Trait | Example products | Meaning for tasks/user context | Constraints and possible hindrances |
| --- | --- | --- | --- |
| Personal fit/sizing | Shoes, trousers, fitted clothing | Fit to a particular person, not “larger is better”; exact size or accepted range may come from memory | Size system/chart, cut, width, waist/inseam; price for wrong size; selector resets; available size does not fit |
| Ordered technical specification | Phones, laptops, storage devices | Minimum, exact or preferred capacity/performance according to the request | Real compatible configurations; low advertised price refers to lower spec; changing one option changes others |
| Compatibility | Chargers, replacement filters, cases, accessories | Must work with a specified owned product/system | Explicit compatibility relation; superficially matching but incompatible revision/connector; misleading recommendation |
| Pack quantity/unit measure | Consumables, multipacks, batteries | Buy quantity or compare price per usable unit | Pack size versus item count, mass/volume/unit dimensions, minimum bundles, mismatched unit-price claims |
| Physical dimensions | Furniture, appliances, displays | Fit an available space or preferred dimensions | Units and measurement definitions; product versus package size; clearance constraints where modeled |
| Condition/refurbishment | Electronics, furniture, resale goods | Hard constraint or an explicitly permitted tradeoff | New/refurbished/used state and relevant grade definitions; low price refers to another condition |
| Style/colour/material/cut | Clothing, furniture, accessories, electronics | Identity requirement, preference or unspecified choice | Valid family-specific vocabulary and combinations; wrong-colour link, colour-specific price/stock |

Traits may combine: a pair of trousers can have sizing, style/cut and pack quantity; a laptop can have technical specs, dimensions, condition and compatibility requirements. Not all items need meaningful variant axes. Do not invent shoe sizes for a television or a capacity upgrade for a fixed object just to fit a template.

A family definition should declare:

1. Attributes and variant axes, types/units, valid domains and labels.
2. Valid **joint configurations** and dependencies, rather than the unrestricted Cartesian product of attribute values.
3. Canonical equivalence rules and retailer-specific identifiers/labels.
4. User-context bindings (subject, category, sizing system or compatibility target) and supported comparison predicates.
5. Relevant traits and renderer/control capabilities.
6. Conditioning inputs for realistic product/pricing/logistics sampling.

Trait semantics constrain what tasks mean, but the current request still decides intent. A user can require exactly 256 GB rather than “at least 256 GB”; a shoe purchase can allow several sizes or be for another person. Clothes' men's/women's/unisex labels are product/cut attributes, not a basis to infer the shopper's identity or automatically forbid a choice. Size equivalence must use declared product/chart mappings; do not assume every brand/system shares one universal conversion. Arbitrary contradictory synthetic mappings should not be introduced as difficulty.

### Share mechanisms without flattening meaning

A reusable `advertised_price_for_other_variant` hindrance can target shoe size, laptop storage or colour. Its commercial operation is shared: the cheap claim references a different canonical variant. Its applicability requires multiple actual variants and a price/reference relationship. Which variant is acceptable comes from trait-aware task intent.

A `minimum_required_spec` task fits ordered technical attributes. It does not automatically apply to personal shoe sizing. A `match_required_attribute` task can apply to both, but it binds different predicates: size/chart compatibility for footwear versus exact/range/threshold semantics for specifications.

Each task/hindrance declares required traits, compatible attribute roles, affected rules, public evidence requirements and supported UI realizations. Example: a size-conversion task requires a declared sizing system and mapping; without them, it is not a meaningful template for that product. This is an applicability rule used when constructing semantic task templates, not a filter rejecting worlds because no offer satisfies the user.

Unsupported combinations indicate missing implementation or an invalid schema/configuration, with retained diagnostic evidence. Ordinary valid combinations can produce zero qualifying products; preserve those worlds and grade a truthful shortfall. Compatibility constraints should describe coherent products, not guarantee a successful purchase.

### Established methods, with domain work still required

This is a familiar structured-generation problem. Grammars provide rules for which structures can expand into which other structures; declarative constraints can specify allowed combinations. The procedural-generation literature covers both [grammar-based generation](https://www.pcgbook.com/chapter05.pdf) and [answer-set/constraint-based generation](https://www.pcgbook.com/chapter08.pdf). These are methods we can borrow, not ready-made retail semantics or a requirement to adopt a solver.

Our initial implementation can use typed data, explicit family/trait composition, conditional distributions and small deterministic rule functions. [JSON Schema conditional validation](https://json-schema.org/understanding-json-schema/reference/conditionals) can check some structural dependencies; it does not by itself ensure realistic distributions, sensible preferences or correct commerce arithmetic. Those remain authored domain rules and tests. Constraint checks must not quietly become rejection sampling for favorable user outcomes.

## Factual tradeoffs and diagnostic evidence

A structured pros/cons comparison is useful when its claims are grounded: “200 SEK cheaper,” “arrives four days later,” “30-day rather than 14-day returns.” Grade factual accuracy and requested comparison coverage. Grade a preferred choice only where the user supplies an applicable ordering or tradeoff rule. A free-form “better value” judgment need not have a unique deterministic label. Pros/cons need not use a prescribed prose template.

Procedure analysis remains outside reward. Useful structured diagnostics include:

- selected canonical variant/quantity before and after navigation or a configuration change;
- advertised-to-quoted differences and whether the updated facts reached a policy decision;
- quote invalidation/recalculation after destination, delivery method or basket changes;
- relevant terms or compatibility tables delivered before an irreversible action;
- catalog pages/ranges inspected, duplicate results and coverage achieved for an exhaustive/aggregate task;
- which memory facts were retrieved, and actual memory deltas;
- repeated actions, technical errors, prices cited without matching accessible evidence, and suspiciously correct answers without an apparent information path.

Bind diagnostics to step/event IDs and the exact evidence. Distinguish page capture from actual policy delivery. Receiving a fact does not establish understanding or causal use; failure causes and suspected shortcuts need trace review. These flags should help group and compare successful and failed trajectories, not award points for following an expected route.

## Grading contract shared by the families

1. **Resolve task intent** from the explicit request and any actually available user context. Preserve the origin, subject, scope and strength of each fact; do not flatten all preferences into hard constraints.
2. **Compute the permitted outcomes** from the actual world, task and initial state. A set of answers is often more appropriate than one exact answer. Distinguish feasible solutions, no feasible solution, an unresolved user choice and a result not knowable through allowed public information.
3. **Evaluate named requirements individually.** Include identity/quantity, constraints, choice quality, response accuracy and authorization as applicable. Grade the committed terms for purchases; a statement that an order succeeded is not an order.
4. **Evaluate memory changes separately**, when a task includes them. Do not let shopping success hide an incorrect persistent update.
5. **Record technical validity and procedure diagnostics separately.** A missing page/verifier observation is not proof of agent failure. Receiving terms before purchase is useful diagnostic evidence, not a mandatory browsing route or proof of comprehension.

Examples of distinct terminal outcomes:

| World/task situation | Acceptable behavior |
| --- | --- |
| A qualifying purchase exists and authorization is sufficient | Complete the requested purchase with permitted effects |
| No offer satisfies the request | Accurately explain the shortfall; do not purchase an unapproved substitute |
| Two offers tie under all stated ordering rules | Either is acceptable, unless multiple results were requested |
| A material choice lacks user guidance | Give the permitted alternatives or ask a specific necessary question, according to the task contract |
| Final fees genuinely cannot be obtained without prohibited information/action | Report the uncertainty accurately; do not invent an exact total or claim proven global optimality |
| Site/setup/evidence is broken | Preserve known facts and mark the technical limitation; do not reward an invented commercial explanation |

Doing nothing alone does not pass an infeasible task; an unsupported “nothing qualifies” statement fails when qualifying offers exist. Full success on an infeasible task can be as valuable as a completed purchase. Wrong-answer and false-refusal rates should be reported separately.

“Cheapest” has a scope: all relevant offers in the simulated commerce world or an explicitly specified set of retailers. Do not grade a universal claim about the real internet using a three-store simulation. Define stock/backorder semantics and whether arrival means a guaranteed latest date, an estimate or an interval. Do not silently treat an estimate as a guarantee.

An audit explanation or requested warning is part of the **answer outcome**, not a procedure requirement. For example, “flag delivery over one month and give a faster option if available” can be checked without requiring any specific browsing sequence. The one-month threshold must be a declared user preference/task rule if it is a hard grading boundary; do not penalize the model against a secret intuition threshold.

Natural final answers should be separated from answer interpretation. A structured submission channel or a separately audited extractor can map answers to fields, but must preserve ambiguity, unsupported claims and formatting/transport errors distinctly. The commerce oracle remains deterministic; an extractor cannot supply missing facts or repair the answer using privileged world state.

Start with full success versus failure and the complete requirement vector. Decide partial-reward weights with the training owner later. Effort, visiting several stores and refusing all extras are not substitutes for outcomes. Authorization breaches cannot be compensated by cheap prices or success on many small checks.

## Explicit prompts and memories are two sources of intent

Model each relevant fact with its subject, value, strength, scope and provenance. Examples: the user's own shoe size, a brother's shoe size, an existing paid membership, a pickup preference, a hard no-subscription instruction, or a one-purchase exception. Membership also has a real account/entitlement state: memory about it is not sufficient to manufacture retailer eligibility.

| Context variation | Expected behavior and grading |
| --- | --- |
| Explicit prompt supplies size/destination/budget | Apply those constraints; no memory retrieval is required |
| Prompt omits a fact that usable memory supplies | Apply it correctly; retrieval method remains diagnostic |
| Current request explicitly overrides a durable preference for this purchase | Apply the temporary override, preserve durable memory |
| User explicitly changes a lasting preference | Apply the new value and make exactly the required semantic memory delta |
| Purchase is for somebody else | Apply that person's stated needs; do not overwrite the user's own profile |
| Existing membership supplies an eligible discount | Use it where appropriate; do not confuse existing entitlement with permission to sign up |
| User requests forgetting/removing information | Verify deletion and absence of unintended changes; specify subsequent usable context |
| Irrelevant memory or incidental remark | Do not force it into the decision or create an unnecessary persistent fact |
| Required information is absent everywhere accessible to the agent | Ask a necessary question or return the defined conditional result; do not guess |

Keep **using memory**, **mutating memory**, and **whether memory could affect this task** as distinct checks/metadata. Correct selection when all offers happen to have the same delivery mode does not establish that a remembered pickup preference was used. Include both decisive and irrelevant memories; not every recalled fact should signal the puzzle's solution.

Generated initial memory must reach the policy through an implemented harness path before memory-dependent grades are fair. The private oracle's copy alone is insufficient. For initial browser prototypes we can supply explicit user context in the task input, clearly labeled as a non-memory baseline. This does not validate retrieval or memory CRUD. Real memory tests can then use the same semantic task with actual retrieval/mutation interfaces.

Memory maintenance can also be an explicit standalone request, but should usually compose with shopping families rather than multiply the task-family list. Verify required and forbidden deltas, including no-update cases, rather than rewarding memory-tool calls or one canonical wording.

## Required world size versus required detail

There is no minimum number of valid answers. Size below means capacity to exercise a task family; actual sampled worlds may contain no matching product/offer.

| Task capability | Useful initial world capacity | Detail that matters more than raw size |
| --- | --- | --- |
| Exact-SKU comparison and purchase | One aggregator and three stores; requested product plus nearby variants and coherent unrelated inventory | Correct variant mapping, complete quotes, stock/eligibility and commit semantics |
| Top-K retailer offers | Configurable retailer/offer count; three stores can test top-2 or truthful top-3 shortfalls | Distinctness, ties, exclusions, ranking and requested fields |
| Choosing among models | Multiple models and configurations per relevant category | Typed comparable specs, meaningful tradeoffs and equivalent-item identification |
| Multi-item shopping | Several requested product lines offered with overlapping store coverage | Basket-level shipping, thresholds, quantity and cross-order accounting |
| Catalog/statistical analysis | Configurable category catalog and dated observations; small cases first, larger populations later | Complete population definition, typed attributes, deduplication, history continuity and transparent missingness |
| Memory/intent cases | Can reuse the same small commercial world | Correct subject/scope, accessible memory, state deltas and ambiguous/contradictory context handling |

Do not expand catalog size as a proxy for all difficulty. A three-store task can be demanding if the decision depends on variant, conditional promotion, delivery and intent. Conversely, a thousand unrelated listings may only increase scrolling or token cost.

Distinguish facts that are decision-relevant from ordinary surrounding commerce content. Search, navigation and recommendations should remain plausible and usable, including non-target products; they need not acquire every possible mechanism just because they exist. Public behavior must never label a product as a hidden grading target or distractor.

## Proposed first task contracts to write out fully

- Cheapest exact-SKU recommendation, including no-qualifying-offer and tied-answer outcomes.
- The corresponding purchase request, adding effect/authorization checks.
- One advertised-offer audit, testing conditions and accurate explanations without purchase.
- One basket-preparation task, proving that “stop before checkout” has an independently verifiable result.

For each, write a prompt-only case and a version using user context; add a durable-update/temporary-override pair once memory is integrated. Top-K is a close follow-on using the same offer engine; broad product selection and basket optimization require more world detail and should follow deliberately.

Next decision: agree these initial families and their response/authorization contracts before choosing distributions or building more pages. Hand-checkable reference cases cover positive, infeasible, tied, forbidden-side-effect and unknown-evidence outcomes; generated worlds themselves are not filtered to match those outcomes.


## Bounded user mistakes and evidence-based clarification

Design decision, 2026-09-22. Sample a small, explicitly configured rate of recoverable user mistakes; no numeric default is agreed. Maintain separate records for intended request, expressed request, exact mistaken field, correct fact, plausible confusion, accessible evidence and allowed clarification. These are private scenario metadata, not facts automatically delivered to the policy. Ordinary unfulfillable requests remain valid and must not automatically be treated as user mistakes.

For account tasks, generate coherent account history from the scenario, bind the intended target, then optionally introduce a bounded error in the expressed reference. This is distinct from changing general retail inventory to guarantee a feasible purchase. Do not rewrite the intent midway through an episode merely because the agent proposes another product/order.

A generic question such as “Are you sure?” receives no new corrective information. A useful question identifies the disputed field, offers a specific candidate or asks for a precise identifying detail, and is supported by available conversation or browsing evidence when asserting a discrepancy. For example: “Your order history lists 990v6, but your request says 990v8. Is the 990v6 order the one you mean?” Verify any claimed page observation against delivered evidence; do not demand a particular URL, phrase, click count or search sequence. Do not imply a model is globally nonexistent just because it is absent from the generated catalog.

Ordinary missing-information questions such as “What size do you need?” do not require preliminary browsing. For correction scenarios, do not turn repeated guesses into a hidden-fact enumeration API: retain the agreed bounded conversation mechanism, reveal only the relevant authorized fact, and return uncertainty rather than automatically accepting a proposed replacement. Ambiguous evidence can justify a pointed open question, not just a yes/no candidate.

Grade final reports and state changes against legitimate authorization and the clarified intent. A user-mistake label does not permit silently purchasing a different product or modifying a different order. Diagnostic fields can record discrepancy discovery, specificity, evidence support and correction receipt, but do not reward a prescribed browsing procedure or asking questions by itself. Explicit conditional reports or truthful unresolved-ambiguity reports remain possible where the task contract permits them. A scenario whose only successful resolution requires unavailable evidence or a withheld answer is a generation defect, not an agent failure.
