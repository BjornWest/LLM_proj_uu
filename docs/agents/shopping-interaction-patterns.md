# Shopping interaction patterns

Implemented locally, opt-in. These patterns change how a shopper discovers facts;
they do not change product identity, inventory, prices, geographic quotes, account
eligibility, comparison coverage or the correct task outcome. No model evaluation
or deployment is claimed by the scripted acceptance below.

## What the saved real-page evidence showed

In GLM's first real-web run, turns 10–17 searched for Sony WH-1000XM5 on Prisjakt.
The first search response included the page title, search field, query heading and
a category shortcut. The model expanded a list of categories/brands before finding
the later results list. That later list mixed a review article and a product.
Both contained the model name. The review had editorial wording; the product
contained the product family, price, retailer and store count. A role=link filter
alone could not distinguish all meanings, and searching for a guessed URL spelling
returned nothing. Reading the relevant containing structure exposed the difference.

Exact delivered result excerpts, original file hash and call IDs:
`.local/review/retail-interaction-patterns-v1/real-ax-evidence.json`.
This is saved evidence, not another live visit. The excerpt does not establish
that every wrong match caused wasted work or that one fixed retrieval recipe is
optimal. Real font colours were not established as a cause.

The synthetic counterpart deliberately contains legitimate links with overlapping
names: department shortcuts, independent review articles and product results.
Reviews also appear among product results. Prices and retailer context appear on
product entries; editorial context appears on reviews. All links lead somewhere
meaningful. There are no correct-target labels, task-aware ordering or privileged
answer annotations in policy-visible HTML. Base layouts place the structures
differently. A useful strategy is to inspect the containing article/row and then
scope subsequent queries; neither the first match nor a heading/link role suffices.

## Supported controls

| Sidecar field | Effect | Scope |
| --- | --- | --- |
| `search_sections` | Matching department shortcuts and internal product-information links; comparator results additionally interleave independent reviews with products | Retailers and all four comparator bases |
| `result_presentation` | Product cards or a compact price-list table with row headers, column headers and expandable facts | Retailer catalogs and related products |
| `offer_disclosure` | Native expandable retailer-offer container | All four comparator bases; existing per-offer controls remain |
| `specification_disclosure` | Visible versus collapsed product specifications | All retailer bases; explicit setting overrides boutique default |
| `shipping_disclosure` | Inline quote or a working separate fulfillment page | Retailer product pages |
| `destination_form` | No new gate, one postcode field or country-appropriate two-part input | Delivery lookup |
| `related_limit` | Maximum number of existing other-model links | Retailer product pages; never fabricated to meet a quota |

The controls compose with existing model/variant selection, partial comparator
coverage, warehouse/branch stock, signed-in coupons, labelled advertising and
independent reviews. None of those existing capabilities is newly claimed here.
`inline` offer disclosure means no additional outer disclosure; a base design can
still have its ordinary merchant-specific disclosure or a separate retailers page.

Search sections are bounded by actual matching catalog entries and supported
families. No matches means no invented matching reviews. Retailer list presentation
uses a table rather than only changing CSS, so it changes AX structure. The current
fixed editorial positions are layout choices, not sampled independently; broader
placement variation remains future work. Search controls do not add dynamic typeahead.

## Sampling and runtime boundary

Product owns `environments/product_world/interaction_patterns.py`, including
sampling, validation, configuration, destination matching and Episode context.
Curation owns `environments/connected_shopping/interaction_patterns.py` and its
renderer/runtime integration. Sampling uses correlated direct/browse/compact site
profiles with configurable probabilities. It does not consult task requirements,
winning offers or feasibility and never redraws for a desired outcome.

The accepted export is `shopping-interaction-patterns-v1`. It binds the exact world,
geography and comparator coverage, with one row for each retailer/comparator. The
runtime validates this before opening servers, deep-copies it, retains it as
`rt.interaction_patterns`, and records `interaction_patterns_sha256` in provenance.
Pattern names and profile configuration are not inserted into public pages.

```python
from environments.product_world.interaction_patterns import attach_interaction_patterns
from environments.connected_shopping.runtime import Runtime

# Existing frozen scenario and matching coverage; no mutation of either.
sampled = attach_interaction_patterns(scenario, coverage=coverage, seed=42)
with Runtime(sampled, comparison_coverage=coverage,
             comparison_profiles=profiles) as world:
    print(world.index_origin)
```

The CLI also accepts `--interaction-patterns FILE`; an explicit file overrides the
scenario attachment. It saves the exact sidecar as
`interaction-patterns.public.json` beside `manifest.json`. Episode validates the
same artifact/hash and supplies the known destination postcode to policy context.
A default runtime with no sidecar retains its earlier behavior. The legacy single
comparator uses the existing full comparison renderer only when explicitly opting
into these patterns; this is recorded as an opt-in UI change, not identical legacy HTML.

## Destination and quote correctness

The generated postcode is a public, country-shaped **synthetic alias** of the frozen
home geography, not a geocoded real address. Only that alias resolves to the existing
quote. Other countries/postcodes receive explicit not-modelled feedback. A valid
postcode never converts an ineligible merchant into an eligible one. All prices,
arrival estimates and reason codes come from the existing quote engine.

Before lookup, product/search surfaces show item price and stock facts, not the
withheld destination total, arrival or delivery eligibility. Branch disclosures
also withhold destination-specific delivery charges/arrival. Pickup and inspection
remain separate from home delivery and do not require the home postcode.

Forms use ordinary GET navigation. The result URL retains entered values; there is
no per-store remembered destination state yet. A bad new address removes an earlier
valid displayed total. Native maxlength makes the split-field case reproduce the
real three-plus-two interaction, but server validation remains authoritative.
Blank/invalid inputs cannot manufacture a quote. Coupon application remains an
explicit code entry and invokes the existing account engine after location lookup.

## Acceptance and boundaries

- 68 focused HTTP/unit regression checks cover interaction contracts, comparator
  designs, canonical identity, defaults, accounts/stock and the independent checker.
- `scripts/verify_shopping_interactions.py` runs three isolated BrowserGym cases with
  two workers, fresh runtimes and no model requests. It captures nonverbose harness
  AX results and screenshots. The discovery case selects the product by public AX
  article context, then uses its current BID. Location cases exercise failed input,
  correction and invalidation of an earlier quote. Retail list AX exposes table,
  row and column semantics. Output directories must be new.
- `scripts/verify_connected_world_conformance.py` checks all 438 offered products,
  all 438 offered variant selections, all 438 delivery quotes, 44 fulfillment
  boundaries, 14 comparison matrices, 4 omitted-comparator routes and 26 review
  articles in the published rich fixture: 1,402 HTTP checks. It supplies the public
  alias for gated quotes and compares their outputs to canonical geography.
- These checks establish implementations and factual consistency, not model
  difficulty or training generalization. Frozen prior hosts and results remain intact.

Evidence paths and latest live links are in
`.local/coordination/retail-interaction-patterns/handoff.md` and the local human report
at <http://localhost:8876/shopping-interaction-patterns.html>.

## Remaining patterns

More realistic variants of conditional shipping (first-order promotions, thresholds,
method-dependent fees), stale advertised prices beyond existing model/SKU differences,
and deliberately unavailable quote facts require explicit world/quote/task semantics.
They must not be invented as misleading display text over an unchanged verifier.
Dynamic promotions/lazy loading, location-modal persistence, alternate storefront
markets and more varied mixed-result ordering remain separate extensions. Existing
verification simulation is separate. None of these is claimed as implemented by this
increment. Procedure/search/reading events remain diagnostic, not required rewards.

## Retailer home/navigation correction

User review identified two pre-existing connected-world shortcuts: retail home
was the paginated exact-SKU search listing, and retailer headers linked directly to
the comparison/index/review sites. The new price-table layout made the first more
obvious; it did not introduce it. The latest search-pattern renderer had also added
external review links in retailer search. Those shortcuts are now removed from
retailer pages. Comparator editorial links remain appropriate there.

Retail homes have bounded category collections and a link to the full catalog.
Footwear catalog/related entries group sizes by model, state “From” prices derived
from the actual listed options, and lead to an existing matching SKU page with
variant controls. Exact SKU searches still reach that SKU; every original option
page remains available. Other families keep configuration-level listings. Retailer
menus/footers also use grouped footwear names. Retailer advice now links only to
its own product details. Map directions remain available; independent reviews must
be discovered through the index or a previously known URL.

Current publication: `.local/connected-shopping/interaction-patterns-v3`, index
<http://localhost:35567>. Previous publications/cards remain historical. Acceptance:
77 focused tests; four isolated BrowserGym cases in
`.local/preflight/shopping-interactions-home-v1/report.json`, including full home →
collection → product and index → merchant-review navigation. All-offer conformance
is `.local/preflight/retailer-home-conformance-v1/report.json`. No model calls.
