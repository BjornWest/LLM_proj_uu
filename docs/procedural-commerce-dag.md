# Can our commerce generator be a DAG?

Design review, updated 2026-09-22 (v2 retailer identity/DOM correlation). **Yes: the current requirements admit a useful directed acyclic sampling graph.** We do not need one giant joint distribution or a simulation of a whole retail economy to start. This is a proposed generative factorization, not proof that we have discovered every real-world dependency.

A cyclic graph would still be directed; it would not become an undirected graph. Correlation by itself has no direction. Here an arrow means “this sampler/calculation consumes those already generated values,” not necessarily “this is the sole real-world cause.”

The root seed provides reproducible randomness; the graph constructs the scenario from it. Separate named random streams are implicit at stochastic nodes. Data dependencies still cause correlated outputs. Fixing a layout stream should not alter a price stream; changing a product parent can legitimately change the price distribution.

[Open the full dependency diagram](../data/curation/procedural_commerce/generation_dag_v2.dot) or inspect the [machine-readable graph](../data/curation/procedural_commerce/generation_dag_v2.json). A rendered interactive-by-browser zoom view is hosted with this document locally. Blue nodes are conditional samples, yellow nodes are jointly sampled blocks, green nodes are derived values/bindings.

## Read the graph as three branches which meet at evaluation

1. **Commercial world:** product universe and reference prices → retailer offerings, prices/history, stock and commercial rules → materialized world.
2. **User request:** product universe/reference prices + user/context → meaningful target, size, budget, deadline and authorization. This branch does not consult actual offer prices, stock, shipping quotes or the answer.
3. **Presentation:** error/disclosure choices and retailer-profile-conditioned layout choices + relevant world facts → public listings and websites. They expose the world, not the oracle.

The final oracle joins the commercial world with the request and shopper context. It can return zero, one or several acceptable solutions. That result has **no outgoing edge back into sampling**. It must not trigger resampling, select a different prompt or relax the constraints.

## Sampling blocks and their main inputs

| Block | Inputs | Why this direction is appropriate |
| --- | --- | --- |
| World setting | Recipe + seed | Date, region, product-family scope, scale and common market factors exist before individual objects |
| Products/reference prices | Setting | Jointly generate meaningful models, configurations, physical traits and price-class anchors |
| Retailer profiles | Setting | Identity/operating archetype, fulfillment, geography and assortment parameters precede offers and condition DOM architecture |
| User profile/circumstances | Setting | Fit/recipient information, destination, spending tendency, urgency and preferences precede the detailed request |
| Shared logistics conditions | Setting | Shared carrier lanes/base rates explain why similar shipments have related prices across stores |
| Assortment/offer identities | Products + retailers | Decide which products each store carries; carrying a product is distinct from current stock |
| Stock/fulfillment state | Assortment + retailer + date | Stock/backorders and dispatch lead time follow the stocking/fulfillment model |
| Commercial policies | Retailer + product traits + setting | Eligibility, membership, return, fee/tax and basket-threshold rules precede their application |
| Actual prices/promotions/history | Products/reference prices + assortment + retailer + policies + date | Prices remain product-correlated; histories and current endpoints are coherent. No independent history graph disconnected from current state |
| Shipping rules/service options | Shared logistics + goods traits + retailer origin + policies | Goods, geography and service determine cost/transit distributions; actual basket totals are evaluated later |
| Initial accounts/memory | User + retailer identities/policies | Materialize existing entitlements and scoped memories; no dependence on a currently advantageous offer |
| Task family/scope | Product traits + setting | Select meaningful operation/attributes; a phone-spec query needs phone semantics, but top-K need not have K matches |
| Detailed semantic request | Product/reference values + user + accounts + task family | Product-appropriate requirements and budget; no current-stock or cheapest-offer input |
| Aggregator error choices | Product capabilities + setting | A wrong-variant link requires meaningful variants. Error choice/severity has no retailer-layout or winner input |
| Aggregator claims | Offers + actual/datetime facts + shipping rules + error choices | A stale/wrong claim references concrete facts; displayed values cannot be statistically independent of their source |
| Initial choices/transition rules | Product/offer structure + prices + commercial policies | Defaults may select cheapest variants or add an offered warranty; they do not know the user's desired size or which offer is correct |
| Disclosure choices | Product traits + commercial-policy capabilities | Decide where/when information is exposed, independently of layout and the favorable/unfavorable answer |
| Page architecture | Product capabilities + retailer identity/operating profile + setting | Choose controls/structure coherently with retailer identity, independently of actual stock, price rank and disclosure choice |
| World, website and task bindings | Their component blocks | Materialize/provide public projections; do not resample incompatible outcomes away |
| Oracle | World + semantic request + shopper context + information contract | Compute feasible outcomes, correct reports, analytic answers and required memory deltas after generation |

This is a graph of sampling/calculation blocks, not a claim that blocks are mutually independent. Products and pricing remain a correlated domain even though reference prices and retailer-specific prices are generated at different stages.

## Where apparent cycles disappear

| Apparent cycle | Resolution in the initial design | Remaining limitation |
| --- | --- | --- |
| Product configuration ↔ realistic price | Sample model/configuration/reference-price structure jointly, then retailer variation conditionally | We still need to author plausible distributions and valid configurations |
| Stores' shipping prices ↔ each other | Shared carrier/route/goods cost model, followed by bounded store-specific variation | Do not draw unrelated wide shipping distributions per shop |
| Stock ↔ delivery time | Separate dispatch delay from carrier transit. Arrival is calculated from both | Backorder may alter dispatch; it need not make the carrier intrinsically slower |
| Current price ↔ price history | One coherent series/current-state sampling block, or generate history forward to the current endpoint | Do not independently sample a current price and an incompatible final history point |
| Free shipping ↔ product price | Sample retailer pricing/subsidy strategy first, then price and shipping policies from it | A later economic margin model may need a small joint block; not an economy-wide fixed point |
| Membership discount ↔ user's membership | Store rules first; existing entitlement is initial user/account state; effective price is derived at query/checkout | A request to sign up changes future account state, not the initial sampled rules |
| Request ↔ product availability | Choose meaningful target/constraints using the product universe and user, then query actual offers | Requested item can be absent/out of stock; never feed that result back into the request |
| Renderer ↔ disclosure mechanism | Independent choices against a common supported interface, then binding | All supported combinations need implementation. Missing support is a technical gap, not permission to keep sampling until a pair works |
| User memory ↔ current instruction | Initial memory first; current utterance and intended semantic change next; actual resulting memory follows agent actions | Respect temporary override, recipient identity and required no-update cases |

Some real phenomena involve genuine feedback: demand affects stock, price affects demand, stock may affect future price. They are not required to simulate a frozen shopping snapshot. If added, model state at successive times, e.g. `(price_t, stock_t) -> demand_t -> stock_t+1 -> price_t+1`, or use a bounded joint block for a static snapshot. Never claim separate independent samples reproduce a coupled economy automatically.

A joint block also needs its own coherent sampler; collapsing a cycle into one box only names the problem. The current small joint blocks (valid product/configuration/reference-price combinations, price histories, retailer profiles) are bounded enough to implement directly. If a new mechanism introduces mutual constraints, review that block rather than grouping the whole environment into one opaque sampler.

## Rules versus their application: an important separation

Generate a shipping *function*, not the final shipping charge for every task. At runtime/evaluation:

```text
quote = price(cart, variants, quantity, destination, account, promotion, method)
arrival = date + dispatch_delay(stock, fulfillment) + transit(origin, destination, method)
```

The destination and selected basket can come from the shopper/request without making the sampled commercial rules depend on their constraints. The same rules answer every shopper's query. Being allowed to query a quote is not permission to change the rules until the request is affordable.

Calculation order must be explicit: which subtotal a promotion/free-shipping threshold uses, whether it includes discounts/tax, and when shipping/tax are applied. If rules are defined circularly (“discount qualifies based on a final total that depends on that discount”), they need an explicit, unambiguous resolution rule before support. That is a local quote-engine issue, not a reason to reshape the world or accept an arbitrary fixed point.

Use shipment origin and destination, not automatically the retailer's registered country or the shopper's nationality. Their warehouse and delivery address are the commercially relevant inputs unless another explicit policy says otherwise.

## Protecting request independence without banning natural tasks

For ordinary comparison/purchase, the detailed request can use product reference-price distributions and the consumer's spending tendency. A low-tail budget is valid even when no current offer meets it. User size and recipient context prevent a cheap children's item from qualifying for a request for the user's adult size. Canonical identity/fit rules, not model-name text alone, establish that distinction.

The graph intentionally distinguishes the **semantic request** from its final **wording/references**. An offer audit may say “Is this advertised price valid for my size?” and therefore quote an already generated public listing. That does not authorize changing the size or budget based on the listing's true eligibility. Likewise, an analytics task may name existing catalog models/dates without selecting them because their aggregate has a desired answer.

Task anchoring/binding must use declared structural or public-reference rules, not the oracle result or a hidden “this deal is wrong” label. Diagnostic metadata may later label such cases, but it cannot choose the generated task. Public wording and memory exposure must remain faithful to the already fixed intent; the formatter has no mandate to repair an infeasible request.

## Graph checks and what they establish

The machine-readable proposal contains **22 nodes and 67 dependency edges**. A topological sort succeeds. Additional ancestry checks confirm:

- actual stock, actual offer prices, shipping rules/quotes, aggregator claims and oracle results are not ancestors of the detailed semantic request;
- commercial-world generation has no semantic-request or oracle input;
- layout does not depend on disclosure, stock, price or the request;
- disclosure does not depend on layout, stock truth, actual prices or the request;
- error-mechanism sampling has no retailer-identity, layout, actual-price, stock or answer input;
- the oracle has no outgoing generation edge.

Evidence: `.local/coordination/procedural-commerce/dag-check-v2.json`. This checks declared edges, **not** the implementation (there is no generator yet), statistical independence in samples, renderer compatibility, or realism. Shared parents deliberately induce correlation; a fixed root seed makes all realized values reproducible.

Current conclusion: **no dependency-cycle blocker is apparent for the foundation.** The work is defining distributions, trait constraints and public interfaces inside this order. Freeze these boundaries first, and require each future mechanism to declare its inputs so that new cycles and forbidden request dependencies become visible.

## V2 change

Retailer identity and operating scale now also condition the DOM/layout sampler, alongside catalog and service samplers. These outputs may correlate through their shared profile. Separate random streams preserve variation, not unconditional independence. Aggregator-error choice remains independent of retailer identity. The v1 graph and check are retained as prior design artifacts; neither version is a running generator. See the DOM-first diversity section in the [design draft](procedural-commerce-design.md).


## Account scenarios and expressed-request errors: pending graph extension

The v2 graph above remains the earlier proposal; its machine-readable nodes have not yet been revised for this extension. For account-specific tasks, a scenario specification can jointly condition historical account contents and the intended referent: scenario -> coherent account history -> intended request binding -> optional bounded wording/reference error -> expressed request. Correction facts and clarification rules derive from that same fixed intent and error record. This is acyclic and does not condition ordinary offers/stock on purchase feasibility.

The earlier requirement that wording faithfully express intent now has an explicit exception for declared, recoverable user-error scenarios. Preserve both representations and the error metadata; accidental formatter corruption is still a defect. Neither a failed search nor the oracle's feasibility result creates a user error after the fact. See the user-mistake contract in [task design](procedural-commerce-tasks.md).
