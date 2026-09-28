# Connected shopping world

**Current update:** model-based footwear comparison now runs at [the v2 index](http://localhost:38301), with the same [task-card URL](http://localhost:47403/task.html) rebound by Product. See [comparison-site designs](comparison-site-designs.md) for the v2 contract and additional layout previews. The first-world figures and source closure below describe retained v1 evidence. Its strict generator source pin no longer matches current pricing code; use pin-v2 for new runs.

Local research/comparison integration, 26 September 2026. This connects a pinned
generated catalog to retailer pages, an aggregator, merchant reviews, product
reviews, a travel planner and a search index. It is not deployed on Vercel and
does not yet connect the earlier transactional checkout engine.

## Retained first world (v1)

- [Search index](http://localhost:36625)
- [Task and policy-visible memories](http://localhost:47403/task.html)
- [Site overview](http://localhost:8876/connected-shopping-world.html)

The world process is PID 53440. Its public manifest is
`.local/connected-shopping/preview-v1/manifest.json`; process metadata, bindings,
source hashes and provenance are alongside it. Product owns the separate task-card
process, PID 54214. These are local development processes; their URLs last only
while those processes run. Replacing origins requires rebinding the task card.

There are 16 origins: six retailers, one aggregator, one merchant-review directory,
six family-specific product-review publications, one travel planner and the index.
This pin contains 139 canonical SKUs, 21 model groups and 109 store offers across
footwear, laptops, cat food, dog food, beer and wine. The index contains 296 documents.

## Ownership and canonical inputs

`environments.connected_shopping` owns composition, URL bindings, public index and
the research retailer adapter. Curation also owns product-review generation in
`environments.product_review_sites`. Product owns `product_world`, merchant-review
generation, geographic quotes and task/answer/grading integration. See
[episode integration](connected-shopping-episode.md) for the latter.

The first input is `.local/coordination/connected-shopping-world/product-pin-v1/`.
`pins.json` records artifact and source hashes. `load_pin()` verifies all pinned
artifact bytes and the semantic product/geography modules before constructing a
runtime. The private scenario is never a static website asset.

Composition consumes only `bundle`, `locations` and `merchant_reviews`. It does
not select pages, offers or ratings using the task or its solution. Canonical
objects stay unchanged; generated local origins live in a separate binding map.
The original merchant-review corpus is retained. Delivery, pickup and inspection
call `product_world.locations.quote()`; there is no fixed-SE shipping fallback.
The travel export is derived from the same catalog and location sidecar.

## Product-review generation

Generate one corpus from the catalog before starting family-specific publications.
The default independent review seed is 42, with 24 synthetic reader opinions per
model review and `as_of` taken from this scenario's merchant-review export. These
parameters and the public corpus hash are recorded in runtime provenance. The first
world has 21 model reviews and 504 reader opinions; merchant reviews have 144 entries.

A review identifies an exact reviewed SKU. Other variants remain navigable but are
not silently assigned that review's tested configuration. Facts come from canonical
product attributes, while reader ratings are synthetic opinions with statistics
derived from the complete generated corpus. They are not measured product quality
or independent laboratory findings. Site identity and AX layout use the existing
family-specific designs. Future quality-dependent tasks need an explicit data and
grading contract rather than treating these opinions as ground truth.

## Public navigation and limits

The index uses public names, categories, SKU identifiers and descriptions. Search
matches normalized words, with site-type filtering and stable lexical ranking;
there is no task relevance or winning-offer ranking and no semantic/synonym search.
Off-topic pages remain available. Retailer catalogs reflect actual store inventory,
including sold-out offers. Canonical options not carried by a store are clearly
unlisted, and an unrelated model cannot be opened under an arbitrary store.

Retailer pages reuse the existing layout shells and option controls with a new
research body. They support variant selection, descriptions, related products,
delivery totals, pickup/inspection branches and travel links. Aggregator item
prices are explicitly distinguished from delivered totals. Review pages link back
to actual retailers and products where an offer exists. This is an authored
research adapter, not a claim of identical transactional-storefront behavior.

Ordering is unavailable in this increment. The prior cart/checkout implementation
still exists separately; binding it to geographic inventory and shipping semantics
is future work. Consent is the only supported state-changing action here.

## Runtime contract and diagnosis

```python
from environments.connected_shopping.pins import load_pin
from environments.connected_shopping.runtime import Runtime

scenario, pins = load_pin(".local/coordination/connected-shopping-world/product-pin-v1")
with Runtime(scenario, product_review_seed=42, opinions_per_review=24) as world:
    print(world.index_origin)
    public = world.public_manifest
    private_journal = world.snapshot()
```

`public_manifest` has schema `connected-shopping-world-v1`, `index_url`, and site
rows with `site_id`, `kind`, `name`, `origin`, `families`, `description`. Task cards
are intentionally outside the discovery index. Private provenance records canonical
hashes separately from binding hashes and declares `purchase_supported: false`.

`snapshot()` retains per-site request and consent journals plus research-only empty
order/mutation lists. The request journal does not include the index/travel servers
and is not an exhaustive browser trace. Requests or captured pages do not establish
model exposure; retain the harness's exact delivered observations for that purpose.
Consent sessions in the shared human preview are not automatically attributable to
one agent. Create a fresh runtime and browser context per evaluation episode.

## Reproduction and acceptance

Start a new persistent preview with a fresh output directory:

```bash
.venv/bin/python -m environments.connected_shopping \
  --pin .local/coordination/connected-shopping-world/product-pin-v2 \
  --output .local/connected-shopping/preview-NEW

CONNECTED_SHOPPING_PIN=.local/coordination/connected-shopping-world/product-pin-v2 \
  .venv/bin/python -m pytest environments/connected_shopping/test_connected.py -q

LD_LIBRARY_PATH="$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu" \
  .venv/bin/python scripts/verify_connected_shopping.py \
  --pin .local/coordination/connected-shopping-world/product-pin-v2 \
  --output .local/connected-shopping/acceptance-NEW
```

The integration tests require the local pinned fixture. Browser acceptance runs
independent cases with bounded concurrency and isolated runtimes. No model calls
are needed. Existing output directories must not be reused.

Seven integration tests cover canonical identity, all 296 indexed routes and root
navigation, quote/store isolation, lexical search, private-route denial,
nonmutation, variant availability and task-independent composition.
Three native BrowserGym journeys cover discovery/reviews/delivery, variant
selection/unlisted/sold-out states, and pickup/travel/inspection. All passed.

Retained evidence:

- `.local/connected-shopping/acceptance-v1/suite.json`: variant and travel cases
  passed; discovery initially failed a scripted heading assertion (`name` versus
  the existing `name reviews` heading). The site was correct; failure is retained.
- `.local/connected-shopping/acceptance-v2-discovery/suite.json`: corrected discovery
  driver passed; it also selects the first of the existing repeated website links.
  No runtime repair or historical relabeling was required.
- `.local/connected-shopping/final-review-v1.json`: final source/pin/HTTP checks and
  accepted evidence hashes.
- `.local/product-world/connected-episode-v3/`: product-owned public-page solve and
  deterministic private grading. This is scripted validation, not model success.

The current demo was not sampled repeatedly to obtain a feasible task. It is the
single fixed world supplied by Product. Neither successful scripted solving nor
page requests measure model capability, difficulty or exposure.

### Portable tests versus retained world acceptance

The source suite runs without local world artifacts. Eleven historical HTTP
acceptance cases in `test_connected.py` and `test_comparison_world.py` are opt-in:
set `CONNECTED_SHOPPING_PIN` for the first module, or both
`CONNECTED_SHOPPING_COMPARISON_PIN` and `CONNECTED_SHOPPING_COVERAGE_FILE` for
the second. Explicit inputs still undergo strict byte/source verification; a
missing or stale selected pin fails. The comparison assertions describe the
original four-site coverage sample, not arbitrary generated worlds.

At the September 28 commit review, the retained first-world inputs no longer
matched current generator sources. Those 11 cases were not revalidated; their
historical results remain historical. Run them from their matching source
closure, or establish separately versioned acceptance for a newly frozen world.
