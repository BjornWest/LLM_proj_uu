# R13 — Dense storefront implementation

2026-09-25. Implemented and locally scripted-tested; not deployed, model-tested or
integrated with the new store-first product sampler.

[Local preview and AX comparison](http://localhost:8876/dense-storefront.html).

## What changed

New `dense-storefront` renderer with a broad searchable header, expandable
department navigation, breadcrumbs, native image selector, a separate buying
region, section links, expandable specifications/delivery/returns/warranty,
two substantial recommendation regions and grouped footer navigation.
Home, search and product-details pages share the same shell. Embedded checkout
uses that same shell with all three existing checkout flow controllers.

Recommendations show actual products, public attributes, merchant prices and stock;
every card links to an existing product route. Same-category recommendations are
not labeled compatible accessories. Maximum card counts are eight same-category
and sixteen other-category products, with no filler duplication for sparse catalogs.
Menus also link to real category searches and product pages. Search paginates.

The preview uses **99 existing product definitions**: the generator's large
96-product catalog plus the three previously authored footwear variants. It does
not fabricate merchant offers for the separately developed `product_world` catalog.
That integration remains a later adapter boundary. Store-specific filtering is
already applied by this renderer: products without a merchant offer are omitted
from menus, result cards and recommendations. Runtime still assumes three stores.

Presentation registration changes are confined to `presentation.py` and
`retailer_designs.py`; new implementation is `dense_storefront.py`. Shared engine,
runtime, checkout, harness and world-generator source were not changed. The preview
and test driver are separate. Existing designs remain selectable and unchanged.

## Measured AX change

Same generated world, same product `product-002`, same 1440×1000 viewport, same
non-verbose BrowserGym/AXContext capture path:

| State | Retained nodes | Interactive roles | Maximum depth |
| --- | ---: | ---: | ---: |
| Existing department design, menu collapsed | 123 | 21 | 7 |
| Dense storefront, menu/specifications collapsed | 645 | 109 | 7 |
| Dense storefront, menu/specifications expanded | 774 | 143 | 7 |

The new page has 32 headings initially, 39 expanded. This is greater meaningful
breadth at the same maximum depth, not added wrapper nesting. The smaller
15-product footwear fixture produced 467 nodes initially and 557 expanded.
The live 99-product footwear page is a different scale from that acceptance case.

The initial generic overview was **927 local-Qwen-tokenizer tokens**, under the
1,000-token standard-profile budget. The full 645-node outline is an audit view,
not a single model message. Initial generic extraction in the three acceptance
processes took approximately 0.25–0.37 seconds; these are a few local samples, not
a throughput benchmark. No model difficulty claim follows from tree size.

## Validation

Six isolated native-browser cases: generic product and size/colour product through
express, accordion and wizard. All accepted cases preserve one correct order,
quantity one and no extra. Checks cover direct entry, gallery selection, menu and
specification disclosures, related-product navigation, search/re-entry, canonical
cart identity, cart indicator and checkout. Footwear cases additionally cover
unlisted and sold-out combinations and selection recovery. The final two accordion
cases also check native quantity validation before any cart mutation.

Each accepted case resolves every distinct linked route on its inspected product
page over HTTP and rejects unavailable-product destinations: 44 routes for the
large generic page and 27 for the small footwear page. This is bounded route
coverage, not a claim that every future product/interaction combination is tested.

117 available commerce tests pass, including 13 new dense-renderer tests for
sparse assortment links, escaped content, private-context isolation, unavailable
variants and the three checkout shells. Full collection currently hits an unrelated
missing `data.curation...test_independent` import in `test_cart_addition.py` because
that directory is absent in the shared checkout. That module was explicitly
excluded; no all-suite-pass claim or restoration of concurrently removed files.

Accepted evidence:

- `.local/dense-storefront/acceptance-v3/`: express and wizard, both product cases.
- `.local/dense-storefront/acceptance-v4/`: accordion, both product cases.
- `.local/dense-storefront/matched-baseline-v1/`: existing department with the same
  world, product and capture procedure; saved standalone capture script.
- `.local/dense-storefront/validation.json`: accepted paths, source/hash checks and
  retained development-failure scope.

Earlier failed cases remain intact. The first suite exposed that inline gallery
JavaScript was blocked by the existing CSP. The final gallery uses native radio
state and CSS without relaxing CSP. Later driver failures came from an exact-label
selector, omitted address fields and failing to refresh the accordion review after
editing details. The shared checkout behaved as designed; the driver was corrected.
The final accordion cases ran separately after that correction; the accepted
express/wizard cases were not relabeled as executions of the later driver.

## Remaining limits

- Symbolic catalog illustrations, not real product photography or visual fidelity.
- Existing single-line basket semantics. No multi-item bundle UI or new reviews,
  geographic rules, finance options or account functions.
- Generic product forms now expose a native per-submit quantity maximum and omit
  Add when sold out. This does not change the engine's generic draft-cart semantics
  or provide a new server-side cumulative quantity guard for forged requests or
  independently configured increment mode. Existing grouped-SKU guard is retained.
- Native menu/details states are real; recommendation sections are rendered
  immediately. We have not implemented lazy AX section loading or an image carousel
  that fetches remote assets.
- Policy and quote routes retain their existing implementations; the new shell
  covers catalog pages and explicitly embedded cart/checkout.
- Preview is one shared local demo session, not a multi-user isolation service.
  Acceptance runs each owned separate runtime/session state.

## Run

```bash
.venv/bin/python -m environments.procedural_commerce.dense_preview \
  --scale large --output .local/dense-storefront/preview-NEW

.venv/bin/python -m pytest environments/procedural_commerce \
  --ignore=environments/procedural_commerce/test_cart_addition.py -q

LD_LIBRARY_PATH=$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu \
  .venv/bin/python scripts/verify_dense_storefront.py \
  --output .local/dense-storefront/acceptance-NEW
```

The manifest records allocated origins. Use localhost rather than 127.0.0.1 when
sharing entry links with the Windows host. Each output directory must be new.
