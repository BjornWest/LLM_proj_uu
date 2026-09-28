# Procedural shopping environments: first design proposal

Status: discussion draft, 2026-09-21. Based on [the original proposal](../procedurally-generated-envs.md), the [shopping challenge brief](shopping-comparison-challenges.md), and the current Prislyktan implementation. This document proposes contracts and priorities; it does not implement a generator, change deployed sites, authorize model runs, or assign other agents work.

The current next design step is [task families, grading and required world detail](procedural-commerce-tasks.md). Settle those contracts before expanding sampling relationships or storefront designs. The [request requirements wishlist](procedural-commerce-request-requirements.md) now maps all 16 generic families through navigation stages and shared website capabilities.

A [first explicit generation DAG and cycle review](procedural-commerce-dag.md) now records the proposed sampling order, joint blocks and protected request dependencies.

The first milestone should prove that **the same shopping world remains correct through different storefronts**, including a misleading offer, a successful purchase/recommendation and an independently rejected wrong outcome. Generating many scenarios comes after that contract works.

## What we can reuse

Prislyktan already has one aggregator, three retailer interfaces, four separate origins, a shared Python commerce engine, server-computed cart totals and an order/event ledger. Its current catalog contains 18 products and 54 offers; its registry has six fixed development tasks. Those counts are not counts of procedurally generated tasks.

Reuse the server/UI separation and existing adapter/lifecycle approach. Treat the layouts as initial renderers to adapt rather than build new designs immediately. Keep the existing fixture and historical task revisions intact; develop a separately versioned procedural environment.

Important gaps in the current contract:

- One offer ID is derived from retailer + product; multiple offers per retailer/product require separate offer and SKU identities.
- Products use flat variant/capacity text; exact, typed SKU attributes need to replace semantic string guessing.
- Prices are SEK-only; shipping is a fixed amount per offer, combined by taking the maximum. This is an explicit simple rule, not a general shipping engine.
- The public catalog/offer API reveals actual stock and shipping immediately. Delayed disclosure needs different public projections/API behavior, not CSS hiding.
- Retailer identity, product categories and UI wording are partly coupled. Capability declarations are needed before calling a renderer interchangeable.
- Fixed task checks and the exact response format of AG06 should not become the generalized oracle or answer interface.

## Variation inventory

A “hindrance” is a commercial fact, discrepancy, behavior or presentation choice that creates work or a risk of error. It is not automatically deceptive, harmful or difficult. Record those dimensions separately.

| Layer | Variations worth supporting | Initial priority |
| --- | --- | --- |
| Task | Recommend cheapest; buy cheapest; bounded budget; top K; no qualifying offer; several products/split orders | Recommend and buy one SKU first |
| Product identity | Model generation; color; regional model; new/refurbished; pack versus single unit; included accessories | Exact model/color/size first |
| Variant | Size/storage/fit; cheapest price belongs to another variant; deep link selects wrong default; selection resets after another choice | First foundation |
| Inventory | In stock; out of stock; backorder; requested variant unavailable; availability revealed at cart | Static truth + two disclosure modes first |
| Aggregator | Accurate/stale price or stock; shipping omitted/included; “from” price; wrong SKU link; expired promotion; sponsored ordering | Accurate, stale price and wrong-variant association first |
| Eligibility | Destination unsupported; postcode exclusion; existing membership required; new signup required | Destination and membership states early |
| Promotions | Buy two; minimum spend; selected variants only; first-order eligibility; coupon; expired deal; incompatible discounts | Buy-two condition early |
| Shipping cost | Flat fee; free threshold; per-order/per-item; remote surcharge; basket-dependent fee | Flat fee + two delivery methods first |
| Delivery | Standard/express tradeoff; dispatch versus arrival; pickup/home; deadline; long backorder | Arrival window + deadline first |
| Currency/market | Display versus charged currency; fixed FX; country URL changes quote; changing currency does not change destination | Add after single-currency loop |
| Tax/import charges | Tax included/excluded; modeled import/handling fees; prepaid versus payable on arrival; charges known only as bounds | Later, explicit fictional rules |
| Optional extras | Warranty; subscription; membership; donation; marketing consent; preselection or reappearance at checkout | Warranty forbidden AND explicitly required early |
| Returns/service | Return window; return postage; restocking fee; warranty coverage; pickup convenience | Later preference cases |
| Retailer state transitions | Draft versus committed selection; address change invalidates quote; variant change invalidates price/stock; cart reprices; repeated checkout | State integrity from foundation |
| Information placement | Product detail; accordion; shipping calculator; cart; checkout; linked policy page; conditional footnote | At least two realizations of one rule first |
| Navigation/DOM | Grid/list/table; page/drawer/modal; nested containers; filters; pagination; URL structures; control types; meaningful distractors | Reuse three existing layouts, then bounded structural variants |
| User intent | Hard constraint; tiebreaker; quantified tradeoff; task override; buy versus research only; permitted extra | Explicit task intent first |
| Memory | Read/use preference; create/update/delete; temporary override; third-party preference; irrelevant statement | Separate follow-on increment |

Avoid making every lower price a trap or every optional extra forbidden. Include truthful cheap offers, useful memberships already held, explicitly authorized extras, irrelevant preferences and cases where the cheapest valid answer remains unchanged despite a complication.

Broken links, server errors and excessive latency belong in a separately declared resilience track. Do not use accidental breakage as the primary source of commerce difficulty. Normal catalog distractors should be coherent and navigable.

## Define mechanisms once, then compose them

A small typed mechanism registry should contain:

- stable ID/version and category;
- parameters and eligible product/store/task types;
- required world/state support, prerequisites and incompatible combinations;
- the facts/rules it changes;
- supported ways to disclose those facts through ordinary shopper interactions;
- renderer capabilities required for each realization;
- oracle predicates affected and cheap contract tests;
- audit metadata: present, potentially relevant, changes feasibility, changes ranking, and policy delivery observed if instrumentation supports it.

Illustrative declarative entry, not an implemented schema:

```yaml
mechanism: delivery_method_tradeoff
version: 1
parameters:
  destination: SE
  methods:
    - id: standard
      fee: {currency: SEK, minor_units: 9900}
      arrival_days: {earliest: 8, latest: 12}
    - id: express
      fee: {currency: SEK, minor_units: 14900}
      arrival_days: {earliest: 2, latest: 3}
behavior:
  quote_requires: [destination, sku, quantity, delivery_method]
presentation:
  realization: cart_shipping_selector
```

The presentation chooses where/how the method is selected. The engine owns its price, eligibility, date window and effects. No arbitrary executable predicate strings in contributed manifests; use a versioned vocabulary of typed rules.

For a preselected warranty, independently vary whether it is authorized, how selection is exposed, and when it is introduced. The same UI should sometimes require keeping it and sometimes removing it. This is essential to avoid teaching “reject all extras.”

## Attribute relationships: independence, correlation and derivation

Clarification agreed during design: “independent” means statistical independence, not merely separate configuration knobs or RNG namespaces. Independent random streams can feed correlated outputs when their distributions depend on shared attributes. Products and pricing are one jointly sampled domain, with continuous/discrete distributions and internal variation rather than fixed product/price templates.

Use a directed dependency model. Each sampled attribute declares its conditioning inputs, distribution/version, independent random stream and support restrictions. Each derived attribute declares its deterministic inputs and rule/version. No unspecified correlation should arise from retailer names, renderer choice, shared RNG consumption or task feasibility filtering.

The following is a proposed initial relationship map, not a claim about measured retail distributions:

| Attribute block | Correlate with / condition on | Keep independent of by default |
| --- | --- | --- |
| Product assortment and canonical variants | Product family, coherent retailer assortment, model/configuration relationships | Layout identity, user budget/deadline |
| Base prices and promotions | Product/configuration/condition, reference price, retailer margin and promotion rules | Layout, whether this offer will be the oracle winner |
| Inventory/backorder state | Offered SKU and declared stocking/fulfillment model; initially no extra price–scarcity coupling unless explicitly added | Delivery-method random draws, layout, user constraints |
| Shipping methods, fees and transit times | Physical goods class, dimensions/weight, shipment origin, destination, service level | Price ranking, aggregator error choice, layout; stock quantity itself does not determine transit time |
| Dispatch delay | Stock/backorder state, fulfillment type, product production/handling lead time | User deadline and page layout |
| Retailer eligibility | Geographic service coverage, product transport restrictions, explicit account/membership policy | User desire for the offer to qualify, page layout |
| Aggregator discrepancy mechanism/severity | Configured discrepancy distribution; eligible fields and variants | Retailer name/layout, whether the retailer is expensive or the best answer |
| Aggregator displayed claim | Actual offer or modeled historical offer plus sampled discrepancy | Not independent of the referenced commercial values: the claim is derived from them |
| Disclosure/interaction behavior | Required field/state capabilities; independently sampled behavior choices | Layout identity, winner/loser label; avoid making adverse facts systematically deeper without an explicit setting |
| Page architecture and structural variation | Supported controls/product schema and retailer identity/operating archetype, with residual variation | Actual stock/price rank, aggregator error mechanism, oracle labels |
| User request/preferences | User profile, intended product/category and task type | Which retailer is cheapest, current stock, whether budget/deadline are achievable |
| Oracle feasibility/ranking | World facts + user request + applicable quote rules | Never sampled independently; calculated after generation |

“Independent of user constraints” does not mean that all requests need reference a nonexistent product, or that product identity cannot be selected from a catalog. It means we do not choose budgets, deadlines or permissible extras to ensure that the resulting request can be fulfilled. An unavailable requested variant or absent requested product can also be represented normally.

Examples of distinct relationships:

- **Joint/correlated sampling:** laptop configuration influences its price distribution; retailer margin adds variation. Expensive configuration does not force a single price.
- **Conditional independence:** inventory randomness and carrier transit-time randomness are separate, while both can depend on product/fulfillment attributes. They are not necessarily marginally independent across all product categories.
- **Derived relationship:** arrival is simulated date + dispatch delay + transit/calendar calculation. Never sample a contradictory arrival date independently.
- **Deliberate independence:** choosing a modal versus a shipping page should not predict which retailer has the cheapest qualifying offer. Both must expose the same engine-calculated terms.

For shipping, distinguish in-stock parcel dispatch, warehouse transfer, backorder and made-to-order fulfillment. A product/fulfillment-specific lead-time distribution provides realistic long tails where appropriate. Use an absolute impossibility only where the declared world rules justify it; a category alone need not imply that a delay can never happen.

The generator records raw factors and derived outcomes, including zero, one or many qualifying offers. Unrealistic rates or combinations are evidence for revising the sampler, not for dropping inconvenient seeds. Dataset analysis may group by these results without changing the underlying worlds or hiding the population frequencies.

### Infeasible-request outcome

If the request rules out every offer, full task success means correctly reporting that no qualifying offer was found within the declared world/search scope, with a supported explanation, and making no unauthorized purchase. An arbitrary refusal or simply taking no action is not sufficient. Possible alternatives may be reported as alternatives, but never silently substituted or purchased without authorization. Top-K requests can likewise have fewer than K qualifying offers; the task contract should permit a truthful shortfall report. Procedure observations remain diagnostic, not requirements to visit a prescribed number of stores.

## Generation and runtime boundary

```text
Versioned scenario recipe + namespaced seed streams
    -> products/SKUs, retailer rules, offers, user state, simulated clock
    -> aggregator's separate claims + behavior assignments
    -> task contract + oracle answer set + validity checks
    -> materialized private world, public task, presentation configuration
    -> isolated commerce session + renderer assets
    -> browser actions and ordinary shopper API responses
    -> immutable effects/quotes/orders + agent's answer + memory delta
    -> per-requirement evaluation + separate procedure diagnostics
```

Use separate namespaces for products, offers, shipping, user, task, aggregator, each retailer's presentation and decorative noise. Materialize generated outputs with seed, schema/generator/rule/renderer versions and content hashes; retain generation errors as explicit diagnostic records. Session credentials/lease IDs are fresh runtime data, not reproducible public seed fields. The root seed and privileged manifests must not be served to the browser; a known generator plus root seed could reveal the solution even without an answer JSON file.

Generate the world without requiring a successful purchase or a minimum number of valid answers. Query that world against the user request afterward. An empty feasible set is an ordinary result, not a separate rescue template or a reason to discard, repair, or resample the world. Do not tune a generated world to its desired answer. If implausible worlds recur, correct the versioned sampling model and its dependencies for future generation rather than selecting only favorable outputs. Schema/arithmetic/rendering bugs remain explicit technical failures: retain the evidence and fix the generator; do not conceal them by retrying until a case passes. Small hand-authored reference worlds may exercise particular outcomes in software tests, but are not the production sampling policy.

Keep five contracts separate:

| Contract | Consumer | Content |
| --- | --- | --- |
| Private world | Generator, engine, oracle | Canonical SKUs, all facts/rules, initial state, clock/FX, aggregator claims |
| Public task definition | Team UI and policy projection | Objective, explicit constraints and allowed actions; follows existing task-definition distinctions |
| Private evaluation plan | Verifier | Requirement bindings, acceptable outcomes, evidence scope and oracle results |
| Store API + presentation profile | Renderer | Public shopper projections, supported interactions, UI choices; never solutions or hidden world state |
| Episode record | Review/triage/training pipeline | Initial manifest hashes, actual effects, answers, requirement verdicts, exposure/procedure observations, technical errors |

The public task is derived from the same semantic task specification used by the oracle. Human-readable text must faithfully communicate the constraints. Separate projection keeps expected answers and grader bindings out of policy input.

### Commerce engine

Use explicit money objects (integer minor units + currency) and versioned rounding rules. Store FX as exact decimal/rational data and freeze the comparison currency and simulated date. Modeled tax/import rules are simulation parameters, not claims about current law.

A quote is a versioned calculation over SKU, quantity, cart, destination, membership, promotions and shipping method. Changes invalidate or regenerate that quote. A submitted purchase is evaluated against its actual committed terms. The server ignores client-supplied totals and records accepted/rejected mutations and immutable orders with causal event IDs.

Crucially, the engine enforces **retailer rules**, not the user's intent. It must allow a commercially valid purchase over the user's budget or an unwanted subscription when the site offers it; the verifier must then reject the agent outcome. Otherwise the environment protects the model from the failures we need to measure.

Begin with a frozen commercial world and synchronous commits. Later stock/price changes should follow explicit simulated events, not wall-clock browser latency or arbitrary agent step counts. Preserve the state/quote version used for grading.

### Public disclosure and reachability

Public responses expose only facts that an ordinary shopper can obtain in that context. Shipping calculators may require a supplied destination; exact variant stock may be checked at cart. Browsers must not receive hidden values in hydration payloads, source maps, unused JSON, debug routes or semantic answer IDs.

A legitimate public endpoint shortcut is not automatically leakage. If a price is publicly returned by the catalog API, the browser can legitimately know it: hiding it visually cannot make it privileged. Tool access policies belong in the harness contract, not ad hoc grader penalties.

Every graded fact must be discoverable or inferable through available public information and allowed actions with the supplied user inputs. An omniscient oracle alone cannot establish task fairness. If a fee is genuinely unavailable until supplying personal data that the task forbids, an uncertainty-aware report must be a supported outcome. Do not discard the world to retain only exact-total answers.

### Renderers

Renderers advertise supported product schemas, interactions and disclosure placements. Renderer selection uses declared capabilities. A missing implementation is an explicit technical gap to fix, not a reason to discard the world or silently drop its mechanisms. Consistency tests check behavior and disclosed facts, not identical DOMs.

Do not require one DOM or page sequence for grading. Preserve ordinary accessibility while varying useful structure. A change of theme/wrapper depth alone should not be counted as a new storefront architecture.

Client-side Vercel browsing previews can remain a convenience. Agent runs, Ask and remote sessions must use the same authoritative engine and grader as evaluation/training. A preview that embeds the entire world must never become the policy-accessible task runtime.

## Outcome checks and reward

Keep named per-requirement verdicts first; derive training reward in a separately versioned policy. This lets us change reward weighting without rewriting historical facts. Retain true/false/unknown and technical validity separately.

| Outcome dimension | Examples | Evidence |
| --- | --- | --- |
| Requested result | Exact SKU/quantity bought; correct recommendation/top-K | Orders or unambiguously extracted answer |
| Feasibility | Stock, destination, deadline, condition | Committed terms/world version |
| Authorization | No unwanted subscription/add-on; no purchase during comparison; cumulative spend cap | Complete effect history, not final cart alone |
| Selection quality | Lowest valid landed cost; accepted tiebreaker/tradeoff | Oracle feasible set/comparator |
| Memory | Exact required change, no forbidden overwrite or persistence | Initial/final semantic state and mutation history |
| Technical validity | Coherent setup, usable site, sufficient grader evidence | Runtime/validation evidence |
| Procedure observations | Saw promotion terms; inspected another retailer; received shipping quote before purchase | Trace delivery/events; diagnostic only |

For purchase tasks, doing nothing can pass authorization but cannot earn completion reward. An expensive correct purchase cannot compensate for unauthorized effects merely by satisfying many small checks. An explicitly authorized warranty is part of completion, so blanket avoidance fails.

Start with a simple reward baseline: full reward for a fully correct, authorized outcome (including a correct infeasibility report when appropriate); zero otherwise; technical-invalid episodes excluded with reason rather than counted as model failures. Record all component checks from day one. Add partial reward only where actual training evidence shows it is needed, and cap it below fully successful outcomes. Keep unauthorized effects as a separate hard failure; never let an additive sum wash them out. No numeric penalty weights are being fixed here.

Apply bounded efficiency preferences only among otherwise successful outcomes initially. Do not pay for visiting N shops, producing more words or mentioning a preference. Retain procedure/exposure diagnostics without reward, as in the existing task-definition proposal.

Comparison and purchase are distinct. A correct recommendation needs a faithful final answer; a purchase additionally needs the committed ledger outcome. Avoid introducing another brittle `SHOP | PRICE` format as the whole benchmark. We can later reuse the project's separately logged answer-extraction design, but extraction ambiguity/errors must remain distinct from commerce errors and its model cost must be counted. It cannot silently repair a wrong answer or become the authority on commercial facts.

Accept tied optimal offers and valid top-K sets. A comparator needs to represent **incomparability** as well as better/worse/equivalent when user preferences do not determine a unique choice. Ask/alternative-report outcomes should be specified for genuinely underspecified tasks. Do not invent a numeric tradeoff for an unquantified preference.

The memory section of the original proposal is compatible, but should not block the first commerce loop. Keep current-task authorization and durable preference separate now; add real memory CRUD and delta checks afterward. Exempting legitimate memory-write tokens from task-length penalties requires bounded validated writes, not a free unmetered text channel. Financial inference costs still include those tokens; reasoning around memory is not automatically identifiable or exempt.

## Example combined scenario

Synthetic SKU: grey shoe, EU 47.5. Task: find the cheapest offer delivered within five days to the supplied Swedish destination, at most 1,100 SEK, without buying another item. Prices below are fictional and already tax-inclusive.

| Retailer | Aggregator claim | Actual relevant offer | Result |
| --- | --- | --- | --- |
| A | 799 SEK | Claim refers to another size; requested size is 1,049 + 49 shipping, 2–3 days | Eligible, 1,098 SEK |
| B | 849 SEK | Per-item promotional price requires two; buying one is 1,099 + 59 shipping, 2–3 days | Ineligible under budget; buying two also violates intent |
| C | 929 SEK | Standard shipping 99, arrives 8–12 days; express 149, arrives 2–3 days | Express eligible and cheapest, 1,078 SEK |

The cheaper standard option at C is invalid for the deadline. It must be a normal selectable shipping method, not an artificially blocked button. Compare-only and purchase variants share the world but require different outcomes.

Generate clean controls and single-mechanism variants before this combined case. Hold commercial truth fixed when changing layout. For a comparison that changes a commercial rule, recompute the answer: a controlled comparison does not require an unchanged winner.

## Difficulty and efficient QA

A seed identifies a world, not a difficulty level. Difficulty is a recipe/vector plus later empirical measurements:

- **Breadth:** plausible competing offers, not total distractor count.
- **Information depth:** interactions needed to reveal decision-relevant facts.
- **Decision sensitivity:** which discrepancies change feasibility or ranking.
- **Composition:** rules that interact, such as size × promotion × shipping deadline.
- **State burden:** selections/quotes that must be preserved or refreshed.
- **UI burden:** navigation depth, control types and meaningful DOM complexity.
- **Intent burden:** constraints, tradeoffs and relevant/irrelevant preferences.

More hindrances need not mean harder tasks: ruling out most shops can make a world easier. Label intended factors separately from observed Qwen/checkpoint pass rate, uncertainty, error families, steps and tokens. Keep latency/technical failures separate from task difficulty.

Use a test pyramid rather than browser-testing every seed:

1. Cheap validation for every materialized world: schema, money, feasible/empty answer set, disclosure reachability, compatibility and split constraints.
2. Reusable oracle reference cases plus arithmetic/ordering properties. Do not validate a calculation only by calling the same production pricing function twice.
3. Metamorphic checks: layout/retailer-label changes preserve the semantic answer; increasing an eligible charge cannot improve that offer under a fixed cost objective; withdrawing stock removes the SKU from the feasible set. Audit joint factor frequencies and winner distribution.
4. Browser contract cases per renderer × supported behavior family, including deliberate bad actions and disclosure boundaries. Use targeted combinations at actual interaction points, not the full Cartesian product or a bespoke script per seed.
5. Small stratified model cohorts only after the above work, with frozen profiles. Expand audits when new mechanisms, interfaces or error patterns justify it.

Save a privileged witness/example interaction sequence to establish reachability during development; keep it out of browser assets and never require the policy to imitate it.

Split by shared world ancestry/template families, not only random seeds. Track separate IID, unseen mechanism combinations, unseen disclosure realizations and wholly unseen renderer architecture tests. Product names and CSS colors alone do not establish meaningful generalization.

## Site population, page families and layout reuse

Design addition, 2026-09-22. These are requirements/proposals, not implemented storefronts.

### Site population and resource controls

World recipes should separately control topic-relevant and background site counts, product-family mix, catalog-size distributions and offer density. A shared upstream scenario topic/family can condition both world composition and later task selection; do not inspect the final answer, stock or feasibility to decide which sites deserve richer implementations. “Topical” means semantically relevant to the subject, not a retailer that can fulfil the request.

Background stores remain normal navigable stores with supported products and the same engine capabilities. Their average catalogs may be smaller, with overlapping size distributions so every small store is not automatically irrelevant. No task-dependent 404 responses, deliberately broken checkout, hidden `distractor` fields or privileged relevance labels in search/page assets. The public description can honestly explain a store's specialty.

Reuse renderer code/static assets and materialize compact per-site data. Render pages on demand from that data. There is no requirement for one server or browser per site. Initial performance claims should be measured: smaller catalogs reduce data/index size, but actual runtime savings depend on implementation and browser traversal. Defer lazy generation of commercial facts unless measurements justify its reproducibility complexity.

### Aggregator architecture requirement

The planned library needs **at least five substantially different aggregator architectures**, initially **three general-purpose and two specialist designs**. Specialist designs are reusable across supported families through typed facets/attributes; they are not permanently footwear-only or laptop-only sites. A different colour palette or extra wrapper does not count as another architecture.

Possible structural designs, subject to later visual design:

| Architecture | Distinct structure/workflow |
| --- | --- |
| General-purpose department/search portal | Department navigation, faceted product grid, dedicated product/offer comparison pages |
| General-purpose comparison workspace | Table-oriented results, selectable products and side-by-side specification/offer comparison |
| General-purpose editorial/catalog portal | Browsable category/group pages and ranked product lists leading to a distinct offer-list presentation |
| Specialist finder | Family-specific selectors and filters, such as fit/size or required specifications, followed by matching products and retailer offers |
| Specialist model catalog | Family/model navigation with configuration selection and a variant-by-retailer availability/price matrix |

All offer views show the aggregator's generated knowledge, which may be stale or incomplete. Changing architecture never silently upgrades it to current retailer truth. Specialist coverage is independently configurable; it does not make that source automatically more accurate.

### Required retailer page families

Every retailer supports **landing, search-results and product-detail pages**, with stable navigation/state between them. Define these as page roles, allowing distinct layouts, URLs and rendering techniques within each role.

Purchase/basket tasks additionally require cart review/editing, checkout and receipt/order confirmation. Those are mandatory functional states where commerce is supported; they need not each be a separate URL or top-level page template. A cart drawer and a dedicated cart page can implement the same capability. Category browsing can reuse a filtered results template; sizing/delivery/returns information can use reusable information-page components where needed.

Pick a coherent site-wide design before choosing compatible landing/results/product/cart components. Do not independently draw every page from an unrelated visual/navigation system, or redraw the site's layout on each visit. Branding, navigation, field vocabulary and session state should remain coherent across pages and tabs.

### Sampling retailer layouts

**Proposal: use replacement at the architecture level, then instantiate each site with its own stable presentation configuration.** This permits recognizable shared storefront engines without making two retailers literal copies.

The per-site configuration can vary supported header/navigation structure, result composition, facet placement, product-information ordering, image/text proportions, compatible selector widgets, cart presentation, typography and branding. These must be reviewed component variants, not arbitrary DOM corruption. They do not change commercial facts or disclosure semantics, and minor variants do not count toward the five-architecture requirement.

Default architecture draws use replacement, conditional on product/capability scope and retailer identity/operating archetype. If worlds are too repetitive, an optional soft-diversity setting can reduce the weight of already used architectures without setting it to zero. That is explicitly dependent sampling across sites, not independent draws, and should be logged as such. Avoid a fixed all-different schedule, fixed quota of each architecture, or appearance in a predictable order. Do not assume making every training site different can only help transfer.

Example configurable policy (illustrative, no probabilities fixed yet):

```yaml
site_population:
  topical_sites: {count_distribution: configurable, catalog_size_distribution: configurable}
  background_sites: {count_distribution: configurable, catalog_size_distribution: configurable}
layout_assignment:
  architecture_sampling: with_replacement
  repeat_downweighting: 0  # optional positive value; never prohibit reuse
  site_configuration: stable_per_site
  page_components: coherent_compatible_family
```

Use separate evaluation conditions with familiar architecture reuse and withheld architectures. Allow explicit retailer-identity/architecture correlations; keep outcome/winner labels out of layout assignment and audit unintended shortcuts. Five templates alone do not establish UI generalization; inspect actual navigation/DOM diversity and transfer later.

## Extensibility and DOM-first renderer diversity

Design clarification, 2026-09-22. Progress in small increments, leaving new families, mechanisms and architectures additive wherever practical. Avoid designing a universal component tree that fixes the structure of every future storefront.

### Retailer identity and architecture are intentionally correlated

Sample a joint retailer identity/operating profile before the detailed site: assortment breadth/depth, catalog scale, service complexity, fulfillment model, geography and architecture tendencies. Catalog, stock, shipping-policy and DOM samplers consume this shared profile with their own residual variation. This replaces the earlier blanket separation of retailer identity from architecture; the updated DAG v2 adds retailer profile as a layout parent and remains acyclic.

| Example operating profile | Coherent DOM tendencies | Coherent commercial tendencies, not fixed rules |
| --- | --- | --- |
| Small boutique | Few navigation entries, simple forms, inconsistent grouping, verbose or sparse product detail | Narrow assortment, fewer shipping methods, local fulfillment |
| Large multi-department retailer | Deep category hierarchy, many menu entries/facets, richer results and product sections | Broad catalog, more service options and fulfillment choices |
| Modern web-native store | Restrained navigation, progressive disclosure, compact product flow | Curated assortment, focused purchase flow |
| Specialist catalog retailer | Dense specifications, family-specific filters, comparison tables/configuration selectors | Deep assortment within supported families, domain-specific options |

These are overlapping conditional distributions, not one identity = one design. Boutique does not mean broken, large does not mean cheapest, and a minimalist store can have a large catalog. A visual/structural style must not become a guaranteed indicator of the correct offer or the presence of deception.

### Shared contracts, independent implementations

Share product/quote/cart/event schemas, backend state transitions, API helpers and semantic contract checks. Let each base design own its DOM tree, navigation, control grouping, text presentation and mechanism realizations. Do not require common component markup, exact labels, selectors, DOM depths or identical modal widgets merely to simplify scripted drivers.

A hindrance has a semantic contract plus multiple renderer-owned realizations. For consent, for example, a compact banner, modal with a settings subdialog, inline expandable panel or persistent bottom panel can expose the same consent choices. The server owns the resulting consent state. A renderer must not substitute different choices, silently grant consent, or lose an available refusal path while claiming to implement the same semantics. Different consent semantics can be separate explicitly supported mechanisms.

Behavior/disclosure semantics and UI realization are distinct: multiple designs may implement the same delayed-shipping or preselected-extra mechanism differently. Required inputs, actual state changes, availability of public facts and evidence hooks remain contracted. Supported capabilities must be declared; do not require every future renderer to implement every imaginable mechanism or let it silently omit a selected one.

During website authoring, give each design a distinct structural brief: navigation depth, information grouping, results organization, configuration interaction and cart/checkout structure. Review actual DOM/AX and browser interactions for diversity. Do not count cosmetic reskins or arbitrary wrapper inflation as substantial designs. Once repeated implementation patterns emerge, share helpers selectively rather than retrofitting every site into one UI framework.

### Styling priority

DOM structure and interaction diversity are the priority. Do not spend development effort on decorative CSS, elaborate branding or human-facing visual polish now. Retain the small amount of functional styling needed for visibility, overlays, scrolling, collapsed content, usable controls and future screenshots; CSS affecting whether an element is exposed or clickable is behavioral, not merely decoration. Rich visual styling remains a later, separately justified increment.

## Comparable variation within each base design

The [page-variation rubric](procedural-site-variation-rubric.md) proposes a common DOM/interaction standard for all retailer types. Common types can have more base designs, but should not automatically receive more variability per design as a second frequency multiplier. Boutique layouts also need meaningful within-family variation. Sample retailer type, base architecture and configuration separately so combinatorial option count does not determine exposure.

The initial review target is two meaningful structural choices per page role, demonstrated through representative contrasts, assessed on grouping, information order, navigation and control structure. Document practical limits instead of adding arbitrary markup or complex flows to a simple store. This is a proposed subjective authoring rubric, not an established model-difficulty metric.

## First implementation slice to agree

1. Typed SKU/offer/money/task contracts, immutable world plus mutable session, deterministic cheapest-feasible-offer oracle and a few hand-checkable worlds. One product family, SEK and fixed simulated dates.
2. Parameterize existing Prislyktan/retailer APIs and layouts. Prove one semantic world through all three stores with two disclosure placements and one misleading aggregator link. No new visual designs are needed to prove this initial engine contract; the subsequent layout-diversity milestone must meet the five-aggregator-architecture requirement above.
3. Run scripted positive/negative paths through the real adapter, including forbidden extras and the required-extra counterpart. Validate API disclosure and unknown/error outcomes.
4. Add namespaced seeded generation, factor metadata and cheap world validation. Only then calibrate a bounded model cohort and expand mechanisms, currencies, product families, top-K and memory.

This is deliberately narrower than the writeup's full MVP. It tests the expensive architectural assumptions before accumulating scenarios. Future delegation should be by reusable mechanism or renderer against a small frozen contract; keep shared engine/oracle ownership explicit, and use one integration owner. Lower-cost agents can implement bounded renderer/mechanism work after the contract and reference cases exist. Record failures, rework and token use by work packet rather than sending routine status messages to the coordinator.


## Real geography and bounded account scenarios

Design decision, 2026-09-22. Use real countries, cities and geographic relationships, not fictional towns. A future sampler can draw from a pinned, licensed locality dataset, then generate synthetic retailer branches and user addresses within those regions. Exact addresses may be fictional, but must remain geographically coherent; do not claim an invented address is verified, deliverable or guaranteed not to coincide with a real address. City-level pickup needs no street-level routing. Distances and service coverage must share the same geography; precise driving-time tasks remain unsupported without an appropriate model. No locality dataset has been selected or downloaded for this design.

Account contents may be conditioned on the scenario. An order-status/cancellation scenario should create a coherent historical order and bind the intended request to it, rather than independently hoping a referenced order exists. Authentication state can vary even when irrelevant to the task. User-assisted login changes access, not purchase/account-change authorization. Historical orders do not force current stock, favorable prices, or cancellation eligibility; an unavailable requested action can still have a correct explanatory outcome.

Keep merchant and product review sites in scope; size/help/compatibility/shipping information stays on retailer sites. Checkout must expose applicable charges and conditions. Separate legal-reference sites, legal research, seller conversations and persistent monitoring are out of scope. A forum is deferred. Second-hand listings are retail inventory with item-specific condition and contents, not merely another price for an indistinguishable new SKU.
