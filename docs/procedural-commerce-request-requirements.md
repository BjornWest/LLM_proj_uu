# Procedural commerce: requests and navigation requirements

Design wishlist, 2026-09-22. **Proposed capabilities, not an implementation or deployment inventory.** This expands the [task design](procedural-commerce-tasks.md) into requirements for all 16 generic request families. Product-family-specific rules come next. The [world design](procedural-commerce-design.md) describes generation and rendering; the [variation rubric](procedural-site-variation-rubric.md) describes structural diversity.

## How to read this document

A navigation stage describes something the environment must support **when relevant**, not a route the agent must follow. A direct product link can bypass discovery. Knowledge obtained at one retailer can help interpret the same SKU elsewhere. A correct answer need not visit a review page, inspect every offer or reproduce a scripted path. Grade outcomes; record procedure separately.

The request determines whether the result is a report, a prepared basket, an order or an account change. Site capabilities alone never grant authorization. Research tasks may require temporary basket interactions to obtain quotes, but permitted draft changes and required restoration must be specified separately from permission to buy. Checkout exploration must not silently commit an order.

Shared requirements have stable `Rxx` identifiers. Request families have `Qxx` identifiers. An ID in a family means the capability can be relevant, not that every instance activates every feature. Explicitly conditional extensions, such as local collection or order changes, may remain unsupported until implemented. A scenario may select only supported capabilities; a valid world with no eligible answer must not be discarded.

For each family, the tables follow the information or state through entry, discovery, pages, optional auxiliary views, and the requested terminal outcome. Different retailers can combine these into pages, drawers or dialogs. They need not share selectors, markup, text or URL structure.

## Request index

| Request | Distinctive requirement |
| --- | --- |
| [Q01 — Locate an exact item](#q01--locate-an-exact-item) | Exact identity and variant across links |
| [Q02 — Discover matching products](#q02--discover-matching-products) | Attribute filters and configuration-consistent evidence |
| [Q03 — Find the cheapest eligible offer](#q03--find-the-cheapest-eligible-offer) | Comparable delivered quotes and coverage |
| [Q04 — Compare a shortlist](#q04--compare-a-shortlist) | Correct attribution and comparable dimensions |
| [Q05 — Rank with priorities](#q05--rank-with-priorities) | Hard constraints, preferences and ties |
| [Q06 — Explain tradeoffs](#q06--explain-tradeoffs) | Factual differences without invented utility |
| [Q07 — Check an advertised deal](#q07--check-an-advertised-deal) | Advertised claim versus applicable terms |
| [Q08 — Assess price history](#q08--assess-price-history) | Dated, comparable series and gaps |
| [Q09 — Research a retailer](#q09--research-a-retailer) | Attributed experiences rather than a hidden safety label |
| [Q10 — Prepare a basket without buying](#q10--prepare-a-basket-without-buying) | Persistent draft state and stopping boundary |
| [Q11 — Purchase within authorization](#q11--purchase-within-authorization) | Final terms and authoritative effects |
| [Q12 — Optimize several purchases](#q12--optimize-several-purchases) | Basket interactions and cross-store outcomes |
| [Q13 — Inspect an existing order](#q13--inspect-an-existing-order) | Historical account facts and correct referent |
| [Q14 — Change an existing order](#q14--change-an-existing-order) | Authorized lifecycle transitions |
| [Q15 — Calculate catalog statistics](#q15--calculate-catalog-statistics) | Population, enumeration and aggregation |
| [Q16 — Report a shortfall or permitted alternative](#q16--report-a-shortfall-or-permitted-alternative) | Truthful infeasibility and bounded relaxation |

## Shared capability register

### Product discovery and evidence

| ID | Requirement and minimum meaning |
| --- | --- |
| **R01 — Identity** | Separate product family/model, canonical configuration, retailer offer and individual second-hand listing. Preserve variant, condition, pack and merchant identity across links, cart and order. Store aliases without treating superficially similar names as equivalent. |
| **R02 — Attributes** | Typed values, units, applicability and unknowns; family-specific comparison/equivalence rules. Distinguish model-level from variant- or listing-specific facts. Include which facts can transfer between retailers. |
| **R03 — Discovery** | Search entry point/site directory plus direct-site/deep-link starts. Index only public titles, identifiers, descriptions and scoped claims; relevant sources must be discoverable without oracle-aware ranking. Support model aliases and category queries without secretly solving them. |
| **R04 — Aggregators** | Product results, product pages and retailer offers with explicit selection, price basis and coverage where applicable. At least one general design offers detailed category-aware filters. Aggregator claims may be stale or variant-mismatched; links and retailer evidence allow checking them. |
| **R05 — Retailer navigation** | Landing, search/category results, product pages, pagination or equivalent enumeration, filters/sort where supported, recoverable empty results, and meaningful surrounding catalog. Back navigation and filter/selection persistence have defined behavior. |
| **R06 — Product detail** | Selected variant, product/listing identity, quantity/pack, condition, included items, applicable price, stock and links to relevant information. Meaningful state updates when options change; enough public evidence to establish facts the task expects. |
| **R07 — Retailer help/policies** | Discoverable size/compatibility guides, shipping, returns and warranty information with scope, exceptions and precedence. Product-specific terms can override general terms; do not bury an unobservable exception only in the oracle. No separate legal/reference websites. |
| **R08 — Independent reviews** | Specialist product review/comparison pages and merchant-review profiles. Exact subjects, dates, scope and source provenance; product measurements retain test conditions, customer reports remain reported experiences. Review ratings/counts/filters must agree with the represented corpus. No forum required initially. |

### Offer and transaction semantics

| ID | Requirement and minimum meaning |
| --- | --- |
| **R09 — Eligibility/delivery** | SKU/listing stock, supported destination, entitlements, delivery/collection methods and dispatch-versus-arrival semantics. Unknown, unavailable and ineligible differ. Dates derive coherently from the scenario clock and fulfillment rules. |
| **R10 — Comparable quotes** | Destination-, variant-, quantity-, method- and account-dependent totals with currency and component breakdown. Final checkout exposes applicable charges and conditions. Freeze comparison/FX/rounding rules and quote versions; no external legal research. |
| **R11 — Promotions/entitlements** | Explicit triggers, expiry, minimum quantity/spend, eligible variants, coupon application, membership and stacking rules. Existing entitlement, signing up, buying extra items and granting consent are separate facts/effects. |
| **R12 — Price history** | Dated series with product/variant/offer scope, price basis, currency and gaps. Connect historical/current values coherently; history does not establish past stock or eligibility unless those are represented. Accessible text/table values, not a decorative graph alone. |
| **R13 — Cart/draft state** | Add/edit/remove lines, quantities and options, initial unrelated contents, persistence and quote invalidation. Distinguish draft selections from saved state; expose whether variant, address or method changes reset anything. |
| **R14 — Checkout** | Reviewable recipient, items, delivery, total, terms and optional effects before explicit commitment. Supports refusal/backtracking, permits commercially valid user mistakes, and identifies unsuccessful versus successful submission. No real payments. |
| **R15 — Effect ledger** | Authoritative orders and relevant side effects across the whole episode, with pre/post state and immutable event identity. Duplicate orders, earlier unsafe commits and subsequently reversed changes must remain inspectable. Receipts reflect committed terms. |

### Accounts, intent and evaluation

| ID | Requirement and minimum meaning |
| --- | --- |
| **R16 — Account/session** | Logged-in/out state, isolated account identity, assisted login, saved addresses and existing entitlements where relevant. Login refreshes account-dependent views/quotes and grants access, not permission to spend or modify unrelated data. No credentials in model context. |
| **R17 — Order history** | Coherent historical orders with variants, quantities, dates, charged amounts, shipments, statuses and stable references. List/detail navigation and order identification; scenario-bound intended target plus optionally recoverable user-reference errors. |
| **R18 — Order changes** | Explicit supported transitions, item/order scope, current eligibility, confirmation and resulting records. Explain unavailable actions truthfully. Requests, accepted cancellations, refunds due and refunds completed are distinct states. Extension, not assumed present on every retailer. |
| **R19 — Intent/clarification** | Hard constraints, preferences, recipient, authorization, permitted alternatives and accessible memory. Pointed questions can resolve missing/mistaken references without generic questions revealing private answers. Private intent and expressed request remain separate for declared user-error scenarios. |
| **R20 — Population/coverage** | Bound the market/catalog/time interval and counting unit; stable enumeration/deduplication and completeness semantics. Separate world truth from what public evidence establishes. First search results do not prove exhaustive coverage. |
| **R21 — Answer/oracle boundary** | Interpret base claims and their relationships with evidence/ambiguity preserved; deterministic checks handle identity, math, constraints, ranking and effects. Accept multiple valid answers, ties, qualified uncertainty and valid no-match outcomes. Do not repair answers using hidden truth. |
| **R22 — State integrity/isolation** | Namespaced sessions, stable initial snapshot, reload/back/multitab consistency and explicit state transitions. Preserve world/quote versions. Only modeled dynamics may alter commerce state; renderer/setup failure remains a technical failure. |
| **R23 — Diagnostics** | Retain exact policy-delivered observations, requests/actions/errors and state/evaluation evidence. Optional flags for source consultation, quote revisions, coverage and clarification; never infer understanding from exposure or grade a prescribed route. |
| **R24 — Local collection** | Optional real-city geography, synthetic branches, branch stock, opening hours and collection terms. Shared geographic data, not unrelated random distances. No driving-time promise without a supporting travel model. |

R19, R21, R22 and R23 apply to all families. Other requirements are referenced below so shared dependencies are visible.

## Q01 — Locate an exact item

**Example:** “Find this model in this configuration and colour.” Shared: R01–R07; R09/R16 when availability or account-only access matters.

| Navigation stage | Required support |
| --- | --- |
| Entry/clarification | Exact identifiers or enough meaningful attributes to resolve the target; recipient/size context if applicable. Distinguish an unspecified variant from an explicitly acceptable range. |
| Search/site discovery | Search aliases, spelling variations and identifiers. Results can include nearby models and unrelated products; neither a miss nor a near match proves the user meant a different item. |
| Aggregator | Model page with explicit variant scope and merchant links. A “from” price or selected default must not be mistaken for the requested configuration. |
| Retailer results | Results lead to actual product pages; selected search filters remain intelligible. Similar generations, conditions and pack sizes are distinguishable. |
| Product/help | Inspect/configure the target; cross-reference a size/specification guide where required. Deep links may reset selections, but the resulting selection is observable. |
| Completion | Return a usable source and accurate identity/availability qualification. No cart/checkout required unless needed to establish an explicitly requested fact. |

**Outcome checks:** canonical item/variant match, valid destination page and requested availability information. A model page with no qualifying variant is not an available exact-item offer. If no match exists, report that within the task's search scope; nearest names are not authorized substitutes.

## Q02 — Discover matching products

**Example:** “Show me products meeting these requirements.” Shared: Q01 identity/discovery, plus R02, R08 and R20.

| Navigation stage | Required support |
| --- | --- |
| Entry/clarification | Attribute constraints with units, exact/minimum/range meaning and distinction between hard limits and preferences. Suitability claims require an evidence model rather than an arbitrary Boolean label. |
| Search/site discovery | Category/need-based queries can discover aggregators, shops and specialist reviews. Site coverage is not tied to knowing the final SKU first. |
| Aggregator | At least one general design has detailed family-aware filters and understandable active filter state. Filter semantics specify model versus variant matches. Missing/unknown attributes must not silently become false or true. |
| Retailer results | Category browsing/filtering or a searchable enumerable catalog. Filters need not express every requested condition; remaining facts can be checked on detail pages. |
| Product/reviews/help | Establish the complete configuration's attributes, measurement scope and supporting evidence. A model with 32 GB in one variant and low weight in another must not qualify through mixed attributes. |
| Completion | Return the requested number/unit of candidates, or an exhaustive set only if requested. Explain unresolved suitability or fewer matching products without fabricating coverage. |

**Outcome checks:** each proposed configuration satisfies applicable criteria; requested count/completeness and evidence qualifications. Equivalent qualifying choices can all pass. Product suitability that the public evidence cannot establish calls for a qualified answer, not an oracle-only certainty test.

## Q03 — Find the cheapest eligible offer

**Example:** “Find the lowest delivered price for this item.” Shared: Q01, R09–R11, R20; R13/R16/R24 conditionally.

| Navigation stage | Required support |
| --- | --- |
| Entry | Target, quantity, destination, acceptable condition, price basis and comparison scope. Existing membership/discount eligibility is accessible when decisive. |
| Search/aggregator | Discover relevant merchants; show advertised price basis, sponsored/sorted order and coverage. Do not guarantee the first offer is the true cheapest. |
| Retailer/product | Reconfirm exact configuration, current price, quantity/pack and availability. Distinguish the same SKU from an individual used listing with different condition. |
| Policy/quote | Resolve delivery methods, unavoidable fees, restrictions and legitimate discounts. Destination/currency changes recompute the same offer rather than silently change the intended market. |
| Cart/checkout if needed | Obtain a comparable noncommitting total. Draft modifications have an explicit allowed scope; do not buy merely to discover the cost. |
| Completion | Report an eligible minimum with all material conditions and comparison currency; accept ties. Unknown competitor costs constrain the strength of a global-minimum claim. |

**Outcome checks:** identity, eligibility, total and optimality within the defined scope. Compare complete qualifying quotes, not independently selected cheapest item and shipping figures from incompatible options. Cheapest item price and cheapest delivered price are distinct tasks.

## Q04 — Compare a shortlist

**Example:** “Compare these three options on price, delivery and returns.” Shared: Q01/Q03 facts, R07/R08/R20.

| Navigation stage | Required support |
| --- | --- |
| Entry | Named candidates or a rule for selecting them; distinguish three products, three retailers and three offers. State requested comparison dimensions. |
| Search/aggregator | Resolve each candidate and preserve its identity across tabs. Comparison controls are optional; separate pages can supply all facts. |
| Product pages | Comparable configurations and measurement units. Expose missing information rather than allowing one variant's facts to fill another's gaps. |
| Reviews/policies | Retrieve only relevant dimensions, with product-test conditions or retailer-specific exceptions intact. General return terms do not override an applicable product exception. |
| Quotes if needed | Same quantity/destination and comparable delivery/entitlement assumptions, or explicitly reported differences. |
| Completion | Attribute each fact to the right candidate. Ranking is required only if requested; do not invent one overall winner for incomparable priorities. |

**Outcome checks:** candidate coverage, individual fact correctness, comparable basis and material qualifications. An unavailable candidate can still belong in a requested comparison; label it rather than silently replace it.

## Q05 — Rank with priorities

**Example:** “Choose the cheapest option arriving by Friday; prefer home delivery when prices tie.” Shared: Q02–Q04, R19/R20.

| Navigation stage | Required support |
| --- | --- |
| Entry/clarification | Resolve hard deadline versus soft preference, tie-breaking order and any explicit tradeoff allowance. Do not invent monetary weights for vague preferences. |
| Search/results | Candidate discovery must not prune valid alternatives because an aggregator sorts by a different objective. |
| Product/quote | Jointly evaluate a complete configuration and delivery method. Faster paid shipping may make an otherwise cheap store the best qualifying choice. |
| Policies/reviews | Inspect relevant priority dimensions, such as return cost or a product's measured noise, without collapsing evidence uncertainty into a fake precise score. |
| Comparison | UI need not implement the user's ranking. All facts needed to compare must be accessible; ties and incomparable candidates remain possible. |
| Completion | Return a permitted ordering/choice or ask a pointed question where the ordering is materially unresolved. Purchase only under separate authorization. |

**Outcome checks:** hard constraints first, then the declared preference relation. If preferences permit several choices, accept that set. Do not grade against an unstated utility function.

## Q06 — Explain tradeoffs

**Example:** “What would I give up by choosing the cheaper one?” Shared: Q04/Q05; R07/R08/R10.

| Navigation stage | Required support |
| --- | --- |
| Entry | Identify the baseline and alternative, relevant user needs and whether a recommendation or just a factual explanation is requested. |
| Discovery/detail | Resolve comparable variants; allow alternatives to differ on meaningful product attributes rather than merely merchant identity. |
| Quotes/policies | Establish price differences, delivery windows, return charges and warranty differences at their applicable scope. |
| Product reviews | Ground measured performance claims in exact models and comparable tests. Conflicting or differently conditioned measurements remain qualified. |
| Completion | Present accurate differences and conditional implications. “Three days later” can be factual; “not worth it” depends on priorities. No required pros/cons prose format. |

**Outcome checks:** requested factual contrasts, correct arithmetic and relevant qualifications; recommendation consistency only where the user supplies a usable ordering. No reward for unnecessary long explanations or consulting every source.

## Q07 — Check an advertised deal

**Example:** “Can I actually get this for 849 kr in my size, delivered?” Shared: Q01/Q03, especially R04/R10/R11.

| Navigation stage | Required support |
| --- | --- |
| Entry/advert | Preserve the exact claim, subject, date and stated/unstated price basis. An audit can begin on an aggregator result or retailer campaign page. |
| Link handoff | Record where the link lands and which variant/market is actually selected. Misleading/stale claims are separate from current commercial truth. |
| Product/campaign | Reveal the actual selected price and relevant promotion conditions: second item, minimum spend, eligible sizes, expiry or membership. |
| Policy/cart | Apply the conditions to this shopper and quantity. Adding an unwanted item to unlock a price does not make that advertised price eligible for the original request. |
| Checkout if needed | Show final noncommitting quote and unavoidable charges; preserve coupon acceptance/rejection and account-dependent changes. |
| Completion | Explain which parts of the claim hold, actual applicable cost and decisive conditions. Keep product-price validity separate from delivered-total validity. |

**Outcome checks:** correct claim interpretation and applicable result. Do not label every price difference deception: a clearly qualified, current claim can be accurate. No purchase or signup unless authorized.

## Q08 — Assess price history

**Example:** “Is this cheaper than last month, and by how much?” Shared: Q01/R12/R20; Q03 when comparing delivered totals.

| Navigation stage | Required support |
| --- | --- |
| Entry | Exact product/variant, time window, current-versus-historical price basis and statistic. Clarify whether “last month” means a date, minimum or average if decisive. |
| Search/aggregator | Discover the matching product and its history view without silently using the default/cheapest variant's series. |
| History view | Read dated values through accessible tables/text or usable chart interaction. Define sampling cadence, gaps, currency, whether a value is a merchant price or market minimum, and coverage. |
| Retailer/current quote | Verify current price when requested; compare shipping-inclusive totals only when equivalent historical components exist. |
| Completion | Correct absolute/percentage movement and qualifications. A low historical price does not prove the item was purchasable then; history alone does not predict future prices. |

**Outcome checks:** identity, dates, comparable measurement, formula and rounding. Missing observations must not become zero; percentage change from a zero baseline needs an explicit undefined/alternative treatment. Monitoring and waiting for future changes are out of scope.

## Q09 — Research a retailer

**Example:** “What concerns do customers report about ordering from this store?” Shared: R03/R07/R08/R20.

| Navigation stage | Required support |
| --- | --- |
| Entry | Resolve the exact merchant/domain and what the user wants to know: reported delivery issues, returns, ratings or a decision under stated evidence preferences. |
| Search/profile discovery | Find merchant-review profiles; similarly named businesses and regional profiles need distinguishing context. |
| Merchant review profile | Aggregate rating/count basis, date range, rating/topic filters, sorting and paginated reviews. Stars and summary counts must agree with the declared aggregation rule and corpus. |
| Review detail | Dated review text and any verification/response labels that the dataset actually models. Complaints, merchant replies and platform summaries retain separate attribution. |
| Retailer cross-check | Read current policies where useful; an official policy is not proof it was followed in a reported incident, nor does one complaint prove universal misconduct. |
| Completion | Summarize supported patterns and uncertainty, with counts/percentages only when coverage supports them. A merchant recommendation depends on the user's declared criteria. |

**Outcome checks:** correct merchant, accurate attributed claims and requested summary/statistics. No hidden “safe retailer” Boolean inferred from anecdotes. Qualitative thematic summaries need a separately audited base-claim interpretation before deterministic checking; do not promise fully automatic semantic coverage. Forum content is deferred.

## Q10 — Prepare a basket without buying

**Example:** “Set up one of each item with express shipping and no warranty; stop before ordering.” Shared: Q01–Q03, R13–R16.

| Navigation stage | Required support |
| --- | --- |
| Entry/session | Initial cart and any unrelated contents; requested changes, destination and exact stopping boundary. Logged-in status can affect persistence and price. |
| Search/product | Select the intended configuration/quantity before adding; add feedback describes actual draft effects. |
| Cart | Inspect and correct quantities, extras and accidentally repeated additions. Keep unrelated initial items if required. Reload/back navigation must preserve actual state consistently. |
| Policy/delivery | Choose requested delivery and inspect relevant conditions. Quote changes invalidate earlier totals when basket, address or entitlement changes. |
| Checkout draft if needed | Save only permitted address/method/draft choices. “Continue” versus “Place order” semantics must be observable even when the UI makes them inconvenient. |
| Completion | Requested draft state persists at the defined endpoint; report accurate remaining limitations. No order, subscription or unrelated profile change. |

**Outcome checks:** final cart/selected method, required preservation of initial state, and absence of forbidden effects throughout the episode. A transient correct cart followed by a wrong final cart fails; a purchase later cancelled does not count as never purchasing.

## Q11 — Purchase within authorization

**Example:** “Buy one if the delivered total is below 900 kr.” Shared: Q03/Q05/Q10, R14/R15/R16.

| Navigation stage | Required support |
| --- | --- |
| Entry | Exact purchase authority, recipient, quantity, hard limits, permitted extras, payment fixture and any ranking requirement. Merely being logged in grants none of these permissions. |
| Discovery/detail | Find and select an eligible item; optimality matters only when requested. Product/condition/variant checks carry through the cart. |
| Cart/policy | Resolve quantity, discounts, optional charges and terms. No extra item or membership just to obtain a lower displayed unit price unless authorized. |
| Checkout | Final current total, selected delivery, recipient and all applicable obligations are observable before commitment. Quote changes require a consistent updated view. |
| Submission/receipt | One intended commit has an authoritative order and receipt. Repeated clicks, unsuccessful submission and duplicate successful orders are distinguishable. |
| Completion | Accurately report the committed outcome, or do not purchase and explain infeasibility/uncertainty. A claim of success cannot replace ledger evidence. |

**Outcome checks:** committed identity, quantity, recipient, price, method, conditions, requested selection quality and all unauthorized effects. Environment rules should permit a commercially valid overspend so the grader can detect it; do not protect the agent using private user constraints. Correct no-purchase outcomes require a valid explanation, not blanket refusal.

## Q12 — Optimize several purchases

**Example:** “Get these items cheaply, preferably from one store.” Shared: Q03/Q05/Q10/Q11 with basket-level scope.

| Navigation stage | Required support |
| --- | --- |
| Entry | Each line's identity/substitution/quantity rules, order/store-count preferences, total budget and whether to recommend, prepare or buy. Define policy for partial fulfillment and shared extras. |
| Search/aggregators | Discover overlapping store coverage for different lines. An item appearing at several merchants is not an extra requested unit. |
| Product/policies | Resolve pack sizes, mixed availability, basket discounts, minimum spends and whether shipments incur separate fees. |
| Multiple carts | Independently editable per-retailer baskets; totals reflect each allocation, not a sum of standalone item quotes. Preserve unrelated contents and avoid shared session leakage. |
| Quote comparison | Compare complete eligible allocations including shipping, method choices and order-count rules. Free-shipping filler is an extra purchase requiring authorization. |
| Checkout if authorized | Track commitments across merchants and remaining quantities. Define whether a valid partial purchase is allowed if a later checkout fails; no assumed cross-store atomic rollback. |
| Completion | Report recommendation or actual committed allocation and total, including any incomplete lines. Do not claim a complete list from one successful order. |

**Outcome checks:** quantities/constraints per line, aggregate cost, requested ranking and whole-run effects. The independent oracle needs an exact solution or a justified optimality certificate for the declared bounded problem size; a greedy heuristic is not a trustworthy “cheapest” label. This is a meaningful complexity increase despite sharing storefronts.

## Q13 — Inspect an existing order

**Example:** “Has my order shipped, and what did I pay?” Shared: R01/R03/R16/R17; R19 user-error contract.

| Navigation stage | Required support |
| --- | --- |
| Entry | Bind the intended request to coherent historical account content. Optional reference mistakes have fixed private correction facts; unrelated orders make identification meaningful. |
| Retailer/account entry | Locate the retailer account from landing page, direct link or current session. If logged out, assisted login changes access without revealing credentials or authorizing modifications. |
| Order list | Useful identifiers, dates, item summaries and status; navigation/filtering/pagination as appropriate. Similar purchases remain distinguishable. |
| Order detail | Purchased variant, quantity, charged amounts, shipment/item statuses and dates. Historical terms remain historical, not overwritten by current product price or stock. |
| Clarification if needed | Ask a specific question about the ambiguous reference; a generic “Are you sure?” does not reveal the hidden target. Absence of an exact reference does not authorize choosing another order. |
| Completion | Report requested facts and distinguish ordered, dispatched, partially shipped and delivered. No order/profile modifications. |

**Outcome checks:** correct order/item, historical facts, accurate status granularity and unchanged protected state. Existing orders need not be currently cancellable or contain currently stocked products.

## Q14 — Change an existing order

**Example:** “Cancel the unshipped item, keeping the rest.” Shared: Q13, R18/R15; R07 for applicable terms.

| Navigation stage | Required support |
| --- | --- |
| Entry/account | Specific action authority and intended order/lines, preserved items and any refund/fee constraints. Login alone is insufficient. |
| Order list/detail | Identify target and current lifecycle status. Multiple shipments/lines must not collapse into one misleading order-level flag. |
| Policy/eligibility | Expose applicable cancellation/change/return rules and any fees. Current eligibility comes from modeled order state, not private user intent. |
| Change flow | Supported item-level or whole-order controls, scope and confirmation summary. Only promise operations the state machine supports; cancellation, address change and returns are separate subcapabilities. |
| Commit/result | Preserve requests versus accepted changes, rejected actions, refund due versus completed refund, and the effects on other lines. No unsupported asynchronous success claim. |
| Completion | Report actual changed state or why the requested change could not be made. Offer further action only within the task's alternatives policy. |

**Outcome checks:** authorized semantic delta, preserved unrelated items/details and accurate consequence report. A return request is not proof the item was physically returned. Immutable history catches an unauthorized change even if later reversed. This is a later extension after read-only order inspection, not a foundation prerequisite.

## Q15 — Calculate catalog statistics

**Example:** “What is the average price of matching products?” Includes exhaustive lists, counts, attribute percentages and price movement. Shared: Q02/Q03/Q08, R20.

| Navigation stage | Required support |
| --- | --- |
| Entry | Publicly understandable population, counting unit, filters, date range, price basis, operation, missingness treatment and precision. Model/configuration/offer/listing counts differ. |
| Search/scope entry | Identify the specified catalog/retailers rather than assume a search engine's top results represent the population. No oracle-only instructions about which records count. |
| Results/enumeration | Stable pagination/load-more, sort/filter semantics and deduplication identities. Supported enumerable scope with truthful termination/count information; no invisible cap that makes a required exact answer unknowable. |
| Product detail | Retrieve missing attributes and distinguish not-applicable, unknown and false. One qualifying variant does not imply every variant qualifies. |
| Quotes/history if relevant | Comparable eligible prices or time series for the defined members. Promotions and delivery assumptions remain consistent; changing cohorts must be explicit. |
| Completion | Return the requested set/statistic with denominator, units and qualifications. An empty population or incomplete data may require an undefined value, bounds or partial-coverage report. |

**Outcome checks:** membership/deduplication, numerator/denominator, formula and rounding; separate omitted versus spurious items. Mean price change and mean individual percentage change are different operations. Require the correct answer, not proof the agent visited every page. World size and output size need explicit bounds so exhaustive tasks are practically representable.

## Q16 — Report a shortfall or permitted alternative

**Example:** “If nothing qualifies, explain why and suggest the closest option.” Shared: Q02–Q06 plus R19/R20. Also a possible terminal branch of transactional tasks.

| Navigation stage | Required support |
| --- | --- |
| Entry | Define nonrelaxable constraints, whether alternatives are wanted, which relaxations are permitted and whether any substitute purchase is authorized. “Closest” needs priorities or a conditional presentation. |
| Discovery/results | Ordinary access to the relevant population. Empty results may mean no matches under active filters, not no solution anywhere. |
| Detail/policy | Distinguish true constraint failures, missing evidence and mistaken/ambiguous user references. Do not convert unaffordability into permission to raise the budget. |
| Quotes/comparison | Establish which candidates fail which conditions. Feasible cheap items of the wrong size remain ineligible, not useful alternatives merely because they are cheap. |
| Clarification if relevant | Resolve a specific ambiguity or bounded user mistake; avoid repeatedly asking the user to relax a clear requirement. |
| Completion | State the truthful shortfall within scope, offer only permitted alternatives and label every relaxation. If alternatives are forbidden, stop at the requested explanation. |

**Outcome checks:** no false no-match claim, accurate reasons and compliant alternatives/no unauthorized effects. There may be several distinct blockers rather than one universal reason. Missing site data or a broken page is not proof no eligible offer exists. Not buying is correct in some worlds, but doing nothing without a justified response does not pass.

## Shared-stage coverage map

This maps reusable implementation work, not mandatory page visits.

| Navigation surface | Main families served | What makes it reusable |
| --- | --- | --- |
| Search entry/site directory | Q01–Q09, Q12, Q15, Q16; account-site lookup in Q13/Q14 | Public subject/type metadata, aliases and navigable sources; no preferred-answer ranking |
| Aggregator results/product/offer pages | Q01–Q08, Q12, Q15, Q16 | Typed identity/attributes, claims, filters, offer links and scoped coverage |
| Retailer landing/results/product | Q01–Q08, Q10–Q12, Q15, Q16 | Coherent catalog, selection, condition, details and discovery |
| Retailer help/policy sections | Q01–Q07, Q09–Q12, Q14, Q16 | Subject/scope, rules/exceptions and accessible information placement |
| Product-review pages/comparisons | Q02, Q04–Q06; optional supporting evidence in Q16 | Measured or qualified claims tied to exact models/test conditions |
| Merchant-review profiles/reviews | Q09; Q04/Q05/Q16 when merchant evidence is requested | Attributed dated experiences, meaningful filtering and coherent aggregates |
| Quote/cart/checkout draft | Q03–Q07, Q10–Q12; Q15/Q16 when landed prices matter | Shared quote engine, selected state, conditions and noncommitting inspection |
| Order submission/receipt | Q11/Q12 | Authoritative commit, visible outcome and whole-run effects |
| Account/order history/detail | Q13/Q14; entitlement context in other families | Session, historical record and lifecycle state |
| Order-change flow | Q14 | Explicit transition capabilities and protected unrelated state |
| Price-history view | Q08/Q15 | Scoped time series, accessible values and missingness |

## Cross-stage rules that are easy to miss

1. **Product facts can transfer; commercial terms usually cannot.** A specification for the same exact configuration at store A can inform selection at B. A return policy, stock claim or shipping quote at A cannot. Individual second-hand defects belong to the listing, not the whole SKU.
2. **Deep links are not identity guarantees.** Changing retailer, country, colour, size or account can alter selection or price. Each resulting state must have an observable identity and current quote basis.
3. **One fact may need several scopes.** A review concerns a tested model/configuration; a general policy concerns a store/market; an exception concerns an item or promotion. Association matters as much as displaying the text.
4. **Correct final checkout does not erase earlier claims.** Preserve advertisements separately so audits remain possible. Conversely, a stale advertised price must not become the oracle's actual charge.
5. **Disclosure and knowability are separate from truth.** The oracle may know every price, but a task requiring a confident answer needs sufficient legitimate public evidence. Some valid tasks instead expect uncertainty; setup breakage remains technical.
6. **Accounts can change the commercial context.** Logging in may populate a saved address, entitlement or existing basket. Expose and record those changes; do not silently treat profile persistence as authorized.
7. **Navigation must not manufacture facts.** Freeze the world or use explicit modeled transitions. Back/reload must not randomly draw a different price, review, stock state or policy merely to add difficulty.
8. **No global all-knowing endpoint for the policy.** Public search/catalog APIs contain only intended public projections. Private world state, acceptable answers and grader predicates stay outside policy-accessible assets.
9. **Research can have side effects too.** Define permissible temporary cart changes and required restoration. Opening a quote cannot silently subscribe, buy, or save personal settings.
10. **Unknowns stay explicit.** Unknown price is not zero, missing review is not a good reputation, no search hit is not global nonexistence, and a customer allegation is not an established event.

## Turning the wishlist into manageable implementation work

Build shared semantic capabilities before per-task exceptions. Identity/attributes/discovery/detail support most families; quotes and policies add offer evaluation; cart/commit add transactions; reviews, history and accounts are separately staged extensions. Multi-item optimization adds oracle complexity even when the pages already exist. Do not make all families prerequisites for the first runnable world.

For each capability, use a few shared positive/negative/unknown contract cases and renderer conformance checks. Compose selected end-to-end journeys to exercise interactions such as variant change -> quote invalidation -> checkout or login -> existing basket -> no unauthorized extra. Do not build a bespoke grader for every page design or run every task against every layout combination. Diverse held-out compositions and actual trace analysis still matter later.

Track each capability as proposed / implemented / scripted-validated / model-tested, with its source revision and coverage limits. Successful navigation is not successful grading; a scripted proof is not model performance. DOM diversity analysis and later model results should guide expansion rather than the raw number of generated combinations.

### Next product-specific pass

Use these Q/R IDs when specializing footwear/clothing, electronics, consumables/replacement parts and second-hand listings. Record what changes in identity, admissible constraints, evidence, UI controls and oracle predicates. Reuse common operations while keeping personal fit, technical minimums, compatibility and unit quantities semantically distinct. No new website category is implied by this pass.
