# Commercial product ranges

Decision `PRODUCT-MARKET-RANGES-20261001`; Product owns the shared producer,
Curation owns domain-package adoption, Website owns departments/filter rendering.
Implemented as an additive existing-DSL stage and callable opt-in product/world
augmentation. Historical sources and worlds retain their frozen meanings.
Department rendering and task/memory resolver adoption require their owners' checks.

## Facts and applicability

The canonical **product/model** fact is `product.facts.market_range`, enum
`women | men | unisex`. All SKUs of that product inherit it. It describes the
marketed range; it is not a body measurement, sex/gender inference, material,
size conversion, or quality claim. Names remain neutral. Actual charts/fit stay
separate; no automatic chart conversions or construction changes are introduced.
Different ranges can identify separate products even if manufacturer names coincide.

| Scope | Probability policy |
| --- | --- |
| Footwear, jackets, trousers, tops, knitwear | Women 40%, men 40%, unisex 20% |
| Fragrance, budget/mainstream | Women 40%, men 40%, unisex 20% |
| Fragrance, premium positioning | Women 50%, men 50%, unisex 0% |
| Running/hydration pack with `pack_format = running_vest` | Women 40%, men 40%, unisex 20% |
| Ordinary packs, including hiking/commuter/travel and `pack_format = backpack` | Not applicable |
| Sleeping bags, sleeping mats, all other current families | Not applicable |

These are per-product weights, **not exact population quotas**. Small samples may
be uneven. Range is independent of colour, execution and emphasis; positioning only
conditions the premium-fragrance exception. High end means the declared internal
`premium` positioning class, not a retail-price threshold or an inference from scent.
This exclusion implements Bjorn's requested synthetic policy; it is not a claim
that premium unisex fragrances do not exist in real shops. Explicit weight overrides
are allowed, except they cannot reintroduce unisex for premium fragrance.

`backpacks.running_hydration_packs` requires a canonical structural declaration
`product.facts.pack_format`: `running_vest` or `backpack`. Missing construction is
unknown; do not infer it from a concept's name, an image, or hydration compatibility.
The stage doesn't invent the construction of a future unimplemented pack concept.
Missing fragrance positioning likewise yields unknown, preserving the premium rule.

## Notation and stage order

Policy: `environments/product_world/data/shared_product_features/market_range.json`.
`stage_document(concept_id)` emits an executable `product-package-v1` document:

```json
{
  "id": "market_range",
  "target": "product.facts.market_range",
  "sample": "weighted_choice",
  "weights": {"women": 4, "men": 4, "unisex": 2}
}
```

Fragrance adds an existing `cases` entry with
`when: "profile.positioning == 'premium'"` and weights `1/1/0`. No new comparison
language/compiler changes are needed. Conditional applicability is resolved before
invoking the stage. Positioning precedes this draw; range precedes range-aware
retailer allocation. Scope is declared centrally and validated against real registry
concept IDs. This is a reusable stage, not a new manufacturing axis or SKU selector.

Inputs identify the product and, for fragrance, its sampled positioning. World seed
plus product ID isolate its stream. It draws once per product and adds no random
consumption to the original domain sampler. The opt-in preview projects this stage
after the current range-agnostic allocation, which commutes with the independent
draw. Future range-aware retailer allocation must consume the field before allocation.

A stage's task/filter binding uses
`product.facts.market_range in request.accepted_market_ranges` with a nonempty set
of declared values. `matches_market_range(public, {'women'})` checks exact range;
`{'women', 'unisex'}` explicitly permits both. Unisex is not silently added to a
hard predicate. Unknown and not applicable cannot pass a known-range requirement.
Production task registration and recipient/default resolution are still pending.

## Producer and website contracts

`sample_market_range(...)` returns `product-market-range-export-v1`, concept/product
identity, source hashes, an executed stage hash, trace and
`fields['product.facts.market_range']`:

- `{ "status": "known", "value": "women" }` (or men/unisex);
- `{ "status": "unknown" }` when a required applicability/profile input is missing;
- `{ "status": "not_applicable" }` outside scope.

`augment_product(item, seed=...)` copies a rich authoring product. Known scalar
values enter `public.facts.market_range`; all statuses enter
`public.fact_status.market_range`. Descriptions receive a guarded ordinary label;
private metadata retains provenance. Product/SKU IDs, manufactured combinations,
stock, reference prices, reviews and other facts remain unchanged. Already augmented
products fail rather than being silently resampled. Existing products without this
opt-in stage retain unknown range and must not be assumed unisex.

Shared assertion identity: `catalog.market_range`, `kind: field_value`, canonical
field above, `authority: catalog_fact`, exact product subject ID, status/value.
Generated label formulations communicate exactly that assertion and receive a private
`public_content` envelope following the resolved producer export contract. A label
is not evidence of cut, measurements or gender-conditioned performance. The envelope
is producer metadata, not browser payload; no claim of complete arbitrary-English
entailment validation is made. Structured labels/filter results share the same
field/subject identity in publication and fact-span instrumentation.

Website should add discoverable men's/women's divisions and an explicit unisex
choice only in applicable departments; mixed outdoors must retain unrelated gear.
Division/filter membership uses actual retailer assortment, not all world products.
Retain sold-out listings and exact SKU links. No automatic range selector between
different products or duplication of all SKU grids. For layouts using a combined
women/unisex division, state that choice clearly and use the corresponding set.
Website's adoption boundary and delivery receipt live in
`.local/coordination/product-market-ranges/handoff.md`.

Clothing/footwear memory defaults and consequential recipient/range clarification
remain in `apparel-shopping-defaults.md`. Fragrance preferences are separate; an
apparel default does not automatically exclude fragrances. Range generation doesn't
implement or claim the question-before-search grader or recipient rebinding.

## Reproduction

```bash
.venv/bin/python -m pytest -q environments/product_world/test_market_range.py
python3 -m environments.product_world.market_range footwear.walking_shoes --seed 0
python3 -m environments.product_world.market_range fragrance.floral_fragrance --positioning premium --seed 0
python3 -m environments.product_world.market_range backpacks.running_hydration_packs --pack-format running_vest --seed 0
python3 -m environments.product_world.market_range footwear.walking_sandals --stage
```

For an independently generated rich assortment, import
`experiments.product_width_market_ranges.model.generate(seed, review_count=...)`.
This consumes acceptance-gated concepts and is an authoring preview, not a new
production connected world or task grader. No old sources/hosts are rewritten.
