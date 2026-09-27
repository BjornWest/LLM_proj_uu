# Task-first store and product worlds

**Geographic extension (2026-09-26):** the inspector now includes offline user,
warehouse and branch locations, geographic delivery/pickup estimates, and correlated
merchant sizes. See [location system](product-location-system.md). These are optional
sidecar capabilities; the store-only APIs described below retain their original defaults.

Implemented local authoring extension, 2026-09-25, in `environments/product_world/stores.py`.
Ownership: `.local/coordination/product-store-world.md`. The product owner changes only
this package and documentation. No retailer layouts, shared web-index registration,
commerce engine/runtime or deployment were changed. No model calls.

The inspector at `http://localhost:47401/` starts with a structured task, saved memories
and hidden fit specifications, then generates its stores and inventories. The task card
shows coloured prose, memory content and private structured bindings above the store
controls. Regenerating the world holds the entire task fixed, including named identities.
The shared canonical catalog remains expandable. Legacy catalog/store APIs remain available.

## Generation order and relevance

```text
structured task + memories + hidden fit specifications
    → projected family scope + optional named-model identities
    → enabled families + store priors
    → specialist store identities, locations and permitted product families
    → per-store model demand and shared model assignments
    → canonical models/SKUs/facts/reference prices
    → retailer-specific listed variants
    → offer prices, stock and dispatch times
    → public web-index manifest
```

`scenario.generate_scenario(task_options, world_options)` completes intent generation
before calling the store sampler. Its only task-derived world inputs are family IDs
and optional model IDs/names. Requirements, memories, budgets and hidden fit facts
remain separate; the sampler does not retry worlds until a solution exists. Named
model identities are reserved in the catalog plan before facts/SKUs are sampled, never
retargeted after inspecting the inventory. A fully sold-out world is valid.

Random tasks draw uniformly from the six supported families, independently of world
family weights. Random query selection uses cheapest, fastest and average. Until a
coherent basket sampler exists, basket/split-basket queries require three explicit,
distinct family IDs; they never auto-fill unrelated departments. Disabled task families
or insufficient store coverage fail explicitly rather than changing the task.

Store planning genuinely precedes products. The canonical catalog remains global so
two stores can refer to the same exact SKU, rather than creating two lookalike products
with unrelated identities/facts. A model plan tells the existing catalog sampler which
families to materialize; compatible stores reuse those planned model identities.

## Specialist profiles

| Profile | Supported families |
| --- | --- |
| Footwear specialist | Footwear |
| Computer specialist | Laptops |
| Pet supplies | Dog food, cat food |
| Beer and wine specialist | Beer, wine |
| General marketplace | Footwear, laptops, dog food, cat food |

Most stores are specialists. General marketplaces are optional, capped at one and
permitted only when there are at least three stores. A specialist never receives a
product from outside its profile. Profiles are restricted further by enabled catalog
family weights. These are fictional, authored Sweden-inspired retail profiles, not
measured market shares or a simulation of national alcohol retail rules. For a
single-store alcohol product-discovery scenario use one store and one relevant store.
Product origin remains distinct from retailer city and warehouse city.

## API and configuration

```python
from environments.product_world.scenario import generate_scenario
scenario = generate_scenario(
    task_options={'seed': 0, 'family': 'footwear', 'query': 'cheapest',
                  'memory': 'mixed', 'hidden': 'auto'},
    world_options={'seed': 42, 'store_count': 6, 'models_per_store': 5,
                   'store_config': {'stockout_probability': 1/6}},
)
task, world = scenario['task'], scenario['bundle']
```

```bash
python3 -m environments.product_world world --seed 42 --stores 6 --models-per-store 5 --focus footwear --summary
python3 -m environments.product_world scenario --task-seed 0 --world-seed 42 --family footwear --output /tmp/task-world.json
python3 -m environments.product_world serve --port 47401
```

The existing `generate` and `task --catalog` commands remain catalog-only. Store-world
CLI accepts `--config` for catalog priors, `--store-config` for store priors,
`--public-only`, and exclusive `--output` creation. The preview samples through `/api/scenario-task`, then calls `/api/scenario` with separate
`task_options` and `world_options`; it pins the sampled task options for subsequent world
regenerations. `/api/world`, `/api/world-task`, `/api/generate` and `/api/task` retain
their earlier store/catalog-first behavior for existing callers. The `scenario` CLI
exports the combined private task/world bundle. Public-world downloads exclude tasks.

| Store parameter | Default | Meaning |
| --- | --- | --- |
| relevant_stores_per_family | 2 | Specialist stores guaranteed to list a shared SKU in each scoped family |
| generalist_probability | 0.08 | Chance for each additional eligible store slot, stopping after one generalist |
| profile_weights | Equal among four specialist profiles | Relative weights for remaining specialist slots, conditional on enabled families |
| model_overlap_probability | 0.5 | Reuse an existing compatible model when one is available and not already carried |
| variant_carry_probability | 0.7 | List additional variants of each carried model |
| stockout_probability | 1/6 | Independent sold-out draw per listed store/SKU offer |

One SKU per carried model is always listed, so a model assortment cannot be empty.
Scoped specialists share the same seed-determined anchor SKU for their scoped model.
Other listed variants can differ by store. Thus overlap/carry probabilities are
conditional rates, not global marginal rates; a zero overlap probability still retains
the explicit scoped overlap anchor. A relevant-store count of one does not guarantee
cross-store overlap. Stock-out probability 1 still retains every listing with zero stock.

Catalog family weights apply **within each store's allowed families** during demand
planning, not globally across every model. Specialist/focus coverage and reuse alter
the aggregate model and SKU mix. Price variation uses a shared retailer residual and
per-SKU noise around canonical reference prices. Shipping is not quoted here.

Invalid configurations fail explicitly: disabled focus families/profiles, insufficient
store slots to cover specialist profiles, or too few model slots for the focused
families in one specialist profile. Basket scope must contain enough distinct families;
task generation never broadens the world behind the caller's back.

## Public contract and web-index boundary

Version: `product-store-world-v1`. A full bundle includes config, private coarse scope,
generation order and overlap anchors, plus the complete catalog bundle for task binding.
The `public` projection contains:

- `products` / `product_groups`: unchanged canonical product and
  `commerce-product-controls-v1` contracts.
- `retailers`: identity, name, specialization, supported families, retailer/warehouse
  locations and a reserved site origin.
- `assortments`: retailer/model relation and the exact product IDs carried there.
- `offers`: offer ID, retailer ID, canonical product ID, item price in integer öre,
  stock quantity, dispatch days and the existing optional-extra fields (disabled here).
- `web_index`: site ID, retailer kind, title, URL, description and product families.

There are no task, relevance, winner or overlap-anchor labels in the public index.
Green relevance borders in the inspector are privileged authoring annotations only.

Index origins such as `https://store-001.shops.example.test/` are **unbound placeholders**.
The manifest is exported for the later web-index/runtime adapter; no storefront is
hosted there and no actual browser environment index was changed. Retailer metadata
is not yet a complete commerce-runtime retailer record: shipping/policy/account rules
and missing-offer routing require the existing commerce owner to integrate them. Do
not pass these stores directly into the current Runtime and claim compatibility.

The future adapter must preserve four different states:

1. Combination has no canonical SKU.
2. SKU exists but the store does not list it.
3. Store lists the SKU with zero stock.
4. Store lists the SKU with available stock.

The inspector displays per-store model/listed/in-stock/shared-SKU counts, full inventory
with exact variants and same-SKU competitors, and a model-by-store overlap matrix.
It separately offers task, combined task/full-world, public-world and web-index downloads. Costs shown are
item prices before delivery; an in-stock count is a count of distinct SKUs, not units.

## Tasks and independence

The preferred `generate_scenario` route freezes the task before world generation.
The projection cannot include requirement predicates. Existing clarification and memory
rules are unchanged. Changing world seed, inventory probabilities or store count never
changes the task, memories, hidden specifications, prose or semantic hash. World settings
may make a named model's requested variant unavailable; its identity remains fixed.

The older `generate_world_task` route deliberately remains catalog-bound: it chooses
among models after the world exists, without consulting price/stock. Do not use that
legacy route for experiments requiring task-before-world causality.

The inspector can author basket tasks, but this extension adds no basket quote engine,
shipping evaluator or full-world task oracle. Existing catalog task and oracle
limitations still apply; see [catalog generation](product-world-generator.md).

## Merchant-review export

`environments.product_world.reviews.generate_reviews(world, seed=0, as_of='2026-09-25',
reviews_per_store=24, config=None)` exports `merchant-review-export-v1`. The renderer
receives only `export['public']`: snapshot date plus companies keyed by retailer ID,
store name/domain/category/link, complete bounded review corpus, and derived count,
five-bin star histogram and arithmetic mean. Empty corpora have a null mean. This is
not TrustScore. The separate `merchant_reviews` owner handles the review UI/runtime.

Each fictional review has an ID, fictional handle, stars, title/body, experience and
publication dates, topic, and optional dated company reply. Dates obey experience ≤
publication ≤ reply ≤ snapshot. Topics are delivery, communication, returns and product
condition. Text sentiment agrees with stars and makes no specific SKU claims or verified
purchase claims. Testimony is not a record of generated commerce events or a safety oracle.

Defaults: 24 reviews per store (allowed 0..200), equal star and topic weights, reply
probability 0.25, fixed explicit snapshot date. These are authored uncalibrated priors.
`star_weights`, `topic_weights`, `reply_probability` and `company_star_weights` are
configurable; per-company weights permit authored differences without publishing latent
priors. No automatic latent-quality coupling or temporal trend is implemented. Namespace
streams preserve existing reviews when increasing count or reordering/adding unrelated
stores. Private provenance records the seed, priors, source world hash and export hash.

Exact integration contract and example exports are under
`.local/coordination/merchant-reviews/product-contract.md`. Review publication does not
register websites in the shared index or alter the commerce runtime.

## Validation

```bash
.venv/bin/python -m pytest -q environments/product_world/test_scenario.py
.venv/bin/python -m pytest -q environments/product_world/test_catalog.py environments/product_world/test_stores.py
.venv/bin/python -m pytest -q environments/product_world/test_reviews.py
.venv/bin/python -m environments.product_world.verify_preview --output .local/product-world/task-first-browser-next
```

52 data tests pass (33 catalog/store, nine task-first, ten review export). Independent
suite groups run concurrently; audits use four workers. Task tests check actual call
order, restricted scope projection, independent facts for reserved identities, all six
families × three single-product queries, frozen tasks across different/sold-out worlds,
explicit baskets, and configuration conflicts. Browser acceptance uses two concurrent
isolated contexts and separate traces for default, sold-out, basket, beer and named-model
average cases. Each verifies world regeneration preserves the task, plus inventory,
overlap, downloads and task-first placement. Evidence: `.local/product-world/task-first-browser-v1/`.
These are scripted tests, not model evaluation results or deployment evidence.
