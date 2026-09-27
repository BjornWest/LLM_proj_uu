# Product catalog world generation

**Task-first extension:** the local demo now opens the [store and inventory inspector](product-store-world-generator.md), with [offline geography and merchant sizes](product-location-system.md). Use `python3 -m environments.product_world scenario --destination-city uppsala` for that pipeline. This document describes the reusable catalog component and its catalog-only APIs.

Local data-only implementation, 2026-09-25. Package: `environments/product_world/`.
Coordination/ownership: `.local/coordination/product-catalog-world.md`.

This generates canonical products and variant groups independently of websites,
retailers, warehouse locations, stock, offers, requests and rewards. It extends the
product branch of the [sampling DAG](../procedural-commerce-dag.md), not the whole
commercial world. No edits to the commerce generator, engine, runtime or layouts.
No paid calls, deployment or model-performance claims.

## Run and inspect

```bash
python3 -m environments.product_world serve --port 47401
python3 -m environments.product_world defaults
python3 -m environments.product_world generate --seed 42 --models 24 --output /tmp/catalog.json
python3 -m environments.product_world generate --seed 42 --models 24 --summary
python3 -m environments.product_world generate --config /tmp/catalog-weights.json --public-only
python3 -m environments.product_world task --catalog /tmp/catalog.json --family beer --target category
python3 -m environments.product_world task --catalog /tmp/catalog.json --family laptops --target model --query fastest
```

The preview is a privileged authoring inspector, not a retail website. It shows
model/SKU composition, requested weights versus realized counts, shared and varying
facts, unlisted combinations, reference costs per litre/kg, downloads and a task-binding
preview. Only its own HTML/API is served; no repository file browsing. Full exports
include configuration and private generation provenance. Public exports contain only
`products` and `product_groups`, with no task, seed, hidden preference or oracle answer.

## Supported families

| Family | Model's selectable axes | Examples of other facts |
| --- | --- | --- |
| Footwear | EU size, colour, width | Activity, waterproof status |
| Laptops | RAM, storage, keyboard layout | Weight, complete set of represented port types |
| Dog/cat food | Pack net weight, recipe | Life stage, wet/dry, complete ingredient list, labelled complete-food status |
| Beer | Containers per pack, volume per container | Style, ABV, origin country/region, unfiltered status, producer-described bitterness |
| Wine | Bottles per pack, volume per bottle, vintage | Colour, grapes, sweetness, sparkling status, ABV, production country |

Beer and wine are an explicit exception to deferring human food/drinks. They were also
added to the separate task registry, now 40 families. A wine's colour and sparkling
status are independent fields. A partial task requirement such as `grapes contains
Riesling` does not specify the complete blend and must not imply wine colour or
sweetness. Canonical product `grapes`, however, is the complete composition.

The current four-variety catalog vocabulary samples colour first among values with
at least one enabled compatible grape, then samples a compatible grape. Complete
Riesling/Chardonnay-only compositions permit white; red/rosé require a dark grape
(Pinot Noir or Cabernet Sauvignon). White-from-dark-grape compositions remain
allowed. Weights are renormalized within compatible choices; mutually incompatible
pinned weights raise an error. Catalog validation applies the same rule to complete
blends, independently of sampling. This is a bounded authored compatibility rule,
not a comprehensive wine-production ontology; it does not infer sweetness, origin,
sparkling status or ABV. Primary references: [Riesling](https://germanwineusa.com/basics/german-wine-types/white-varietals/riesling/)
and [white Champagne from dark grapes](https://www.champagne.fr/en/champagne-tasting/choosing-your-champagne/blanc-de-noirs).
There are no tasting guarantees or inferred quality scores. Production region is a
product-origin fact, not a retailer or warehouse location.

**Product discovery and retailer comparison are separate scopes.** A catalog can be
used with one retailer or many. Beer discovery may be dominated by style, regional
origin, filtration and described bitterness; it need not be framed as choosing among
shops. "Local" requires a user's location/scope, and "best value" requires a stated
basis such as delivered cost per litre among qualifying beers. The inspector's unit
cost is a **reference-price diagnostic**, not a new task oracle or actual quote. A
unit-value query/grade and subjective recommendation tradeoffs remain future work.
Pet food, skincare, replacement supplies and tools can similarly emphasize product
choice. No changes to multi-retailer task semantics were silently introduced.

## Catalog construction and compatibility

1. Draw a family for each model slot using configurable relative weights.
2. Draw stable model-level facts and sets of axis options. Positive-weight axis values
   are sampled without replacement; option counts are configurable. Fewer positive
   values than the requested count means fewer options, not a zero-weight fallback.
3. Materialize potential option tuples. Select one seed-based anchor tuple and retain
   it so the model denotes at least one SKU; independently omit other tuples according
   to the configured probability. This is a structural catalog invariant, not a
   task-solvability guarantee. Option menus may include a value whose combinations
   are all unlisted, which the existing contract can represent.
4. Derive variant facts: a pet recipe includes its named protein; the complete authored
   ingredient list is shared across pack sizes. Beer production region is conditioned
   on origin country through the same semantic relation used by task generation.
5. Derive correlated reference prices from a common model baseline and configuration.
6. Validate the result against both semantic checks and the existing commerce control
   validator. Reject identity collisions, wrong types, invalid mappings, contradictory
   facts, inconsistent shared model facts or differing ingredients for the same recipe.

Stable `product_id` identifies a SKU; `group_id` identifies a model. Option IDs, labels
and canonical values remain separate. Exports conform to
[commerce-product-controls-v1](procedural-commerce-product-controls.md): `products[]`
records retain the existing product schema and `product_groups[]` retain the existing
axes/selection-to-SKU map. Size × colour × width and RAM × storage × keyboard use the
same contract. No custom renderer component or second variant contract was invented.

Missing catalog tuples and sold-out retailer offers remain distinct. This sampler
creates the former and has **no stock or offer state**. Attaching retailer subsets,
locations, quotes and inventory is a later commercial-world stage; current runtime
limitations around missing retailer offers still apply. A valid catalog does not by
itself establish a runnable full commerce environment.

## Probability controls: what is and is not uniform

The old commerce generator has three exposed Bernoulli controls: stock-out 1/6,
stale claim 0.20 and extra preselection 0.34 (conditional on an available extra).
Other defaults include fixed extra availability 0.72, uniform draws, and deterministic
household-category rotation. The task sampler separately uses uniform choices and
some fixed rates, including 35% hidden-blocker selection per eligible line. There is
no global equal-probability policy across the system.

The new catalog's resolved configuration is included in every full export:

- **family_weights:** all six families default to 1, i.e. 1/6 probability per model
  draw. Relative weights need not sum to one. Zero excludes a family. A small catalog
  may omit a family by chance; the sampler does not retry to force coverage.
- **field_weights:** equal defaults for most categorical fields. Authored exceptions:
  footwear waterproof 35%, pet-food complete label 90%, beer unfiltered 40%, wine
  sparkling 25%. These are prototype priors, not measured retail frequencies.
- **axis_option_counts:** defaults footwear 3 sizes × 2 colours × 2 widths;
  laptops 2 RAM × 2 storage × 1 keyboard; pet food 2 weights × 2 recipes;
  beer 2 packs × 2 volumes; wine 2 packs × 2 volumes × 2 vintages, before omissions.
- **variant_omission_probability:** 0.15 for non-anchor tuples. The realized fraction
  across *all* tuples is lower because the anchor is retained. The inspector reports
  the eligible denominator explicitly. Probability 0 yields complete combinations;
  probability 1 yields exactly one SKU per model.
- **extra_protein_probability:** 0.20; **wheat_probability:** 0.30 for each pet recipe.
- **reference_price_multiplier:** 1.0, bounded to [0.01, 100]. This affects prices,
  not identities, product facts, axis choices or variant omissions.

A partial weight mapping overrides only those entries; others retain defaults. To pin
one value, set every other value's weight to zero. Unknown fields/values, negative or
nonfinite weights, all-zero distributions and incoherent location support fail with
an error. Country weights are normalized over countries with at least one positive
compatible region; region weights are then normalized within the chosen country.
This documented conditional support means field weights are not independent marginals.
Axis sampling without replacement likewise has inclusion probabilities distinct from
a single categorical draw.

Example: beer-only catalog, all models unfiltered:

```json
{
  "family_weights": {"footwear": 0, "laptops": 0, "dog_food": 0, "cat_food": 0, "beer": 1, "wine": 0},
  "field_weights": {"beer.unfiltered": {"false": 0, "true": 1}},
  "variant_omission_probability": 0.1
}
```

**Model weights are not SKU weights.** Families with more variants produce more SKU
rows. Nor do these controls prescribe success/no-match rates or winning retailers;
those are downstream outcomes to measure. Do not resample worlds or choose tasks to
achieve a desired feasible outcome implicitly.

## Reference pricing and seeds

All prices are integer öre, rounded to whole SEK. Synthetic model baselines are drawn
from authored family ranges. Laptop RAM/storage add ordered increments; footwear has
model/width/waterproof effects, with no assumed price benefit from a larger shoe size.
Pet-food cost includes a per-kg component plus packaging, so larger packs usually have
lower unit cost while costing more in total. Beer/wine scale with contained volume and
pack count, with bounded pack discounts. Rounding can create equal prices at extreme
scale settings. These distributions are illustrative, not retail-calibrated data.

Named random streams separate model family, individual fields, reference baseline,
recipe ingredients and combination omissions. Adding later model slots preserves
existing model/SKU rows. Changing a parent such as family can legitimately change its
children. Keep source hashes, schema, seed and resolved config when freezing a cohort;
seed alone is not a promise across source revisions.

## Binding tasks to the catalog

`tasks.generate_task(catalog, ...)` uses the current task/memory sampler and replaces
placeholder model references with canonical model IDs/names. It renders prose again
only after binding. Category requests remain category requests. Selected task families
must exist in the catalog; basket recipes need three distinct present families and
report an explicit limitation when those aren't available, without regenerating a
replacement world. Default task-family selection is uniform among present families,
separate from catalog model-family weights.

Models are selected uniformly within the chosen family without filtering for matching
requirements, reference price, offers or feasibility. Budgets still use the task
sampler's authored family reference priors; no stock/offer truth is available. A
one-SEK budget remains one SEK even when no reference-priced SKU fits. Generated
requirements can be unmet by the chosen model or any offered SKU. Natural impossibility
is not silently repaired. The binding records its source catalog hash and method.

Full tasks retain private hidden specifications and structured memory bindings. The
public projection excludes them. No memory retrieval, NLP clarification simulator,
basket quote calculation, normalized-price oracle or browser-harness adapter is added.

## Validation

```bash
.venv/bin/python -m pytest -q environments/product_world/test_catalog.py \
  environments/shopping_intent/test_generator.py environments/shopping_intent/test_semantics.py \
  environments/shopping_intent/test_oracle.py
.venv/bin/python -m environments.product_world.verify_preview --output .local/product-world/browser-next
```

Tests cover reproducibility/prefix stability, existing variant resolution, zero weights,
probability extremes, price/fact separation, configuration-price relationships, recipe
composition, regional IPA discovery, malformed contracts, catalog task binding, and
no budget repair. A four-worker audit validates 50 catalogs/1,200 models and checks
realized family and omission rates against broad deterministic tolerances. The task
cross-family audit now covers 40 × 5 × 6 × 8 = 9,600 bundles.

Browser cases use two bounded concurrent contexts and separate traces: default catalog,
regional unfiltered low-bitterness IPA, and sparse catalogs plus invalid all-zero weights.
They exercise both downloads, model inspection and canonical task binding. Acceptance
and source hashes live under `.local/product-world/acceptance.json`. These are scripted
checks, not model results or a deployed catalog capability.
