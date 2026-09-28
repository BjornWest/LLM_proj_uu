# Generated specialist product-review sites

2026-09-26. A local browsing foundation with three distinct AX structures and five
specialist publications, using the existing six-family product catalog. No model
calls, production deployment, new graded tasks or independent lab simulation.

[Open the showcase and AX comparisons](http://localhost:8876/product-review-sites.html).

## Cookie-popup extension

[Three independent consent designs](review-cookie-popups.md) are now enabled in the
local human previews (`preview-v5`). Earlier popup-free structure captures remain
historical; consent is opt-in on the Python runtime and does not change products.

## Current reference-structure follow-up

[Structure report and missing world contracts](product-review-structure.md) covers
the expanded article trees, real archive/navigation routes and 69-test/eight-case
validation. Current preview: `.local/product-review-sites/preview-v4/`. Earlier
family-audit evidence below is preserved.

## Current family audit

The follow-up [family-language/filter audit](product-review-family-audit.md) adds
product-aware vocabulary, checkbox facets, numeric bounds and ingredient exclusions.
It also gives twelve-reader-page AX counts and current evidence (63 tests, eight
new native cases). The sections below retain the initial foundation's evidence.
The local preview links still work; current process/data manifests are now under
`.local/product-review-sites/preview-v3/`.

## Research and resulting designs

Native BrowserGym captures use the project's actual compact nonverbose AX adapter,
not an HTML-tag count or the browser's visual layout alone. Three references
returned HTTP 200 and exposed substantial content:

| Reference | Structure observed | Semantic AX nodes / controls / depth |
| --- | --- | --- |
| [RunRepeat shoe review](https://runrepeat.com/asics-novablast-5) | Contents sidebar; long review; many measurement sections/tables; comparison and offer context | 1699 / 143 / 8 |
| [Tom's Hardware laptop review](https://www.tomshardware.com/laptops/chuwi-unibook-review-a-budget-rival-to-the-macbook-neo-and-dell-xps-13) | Deep site navigation; author/date; verdict and pros/cons; long article, specifications and surrounding links | 567 / 120 / 7 |
| [Untappd beer profile](https://untappd.com/b/fox-brewery-ipa/147717) | Product/style facts and aggregate rating; repeated dated check-ins; recurring product/member links and related beers | 669 / 269 / 6 |

These are snapshots, including consent interfaces, not benchmark targets. Initial
screenshots show consent overlays. Captured underlying AX content does not prove
that those controls were unobstructed for interaction. Tom's Hardware also produced
child-frame extraction warnings; counts describe the extracted sample, not a claim
of complete frame coverage.

[All About Dog Food's directory](https://www.allaboutdogfood.co.uk/the-dog-food-directory)
provided searchable source text with extensive product/ingredient filters,
comparison controls and recipe information. Its native browser visit returned a
403 security page, so it contributes **no valid AX measurement**. The
[Vivino homepage](https://www.vivino.com/en/) also returned a blocked native page;
we make no native wine-profile fidelity claim. Beer/wine share the initial community
architecture because it is reusable, not because their reference sites are identical.

Raw evidence: `.local/product-review-sites/reference-v1/capture/`. No copied real
review prose, user identities, logos or remote assets are used in generated pages.

## Implemented structures

- **P01 lab-directory:** search and category header, left contents navigation,
  central specification notebook with multiple real tables, right related-product
  area. Directory filters live in a sidebar. “Lab” is a private layout identifier;
  the public text does not claim that catalog facts are measured test results.
- **P02 editorial-magazine:** masthead, section navigation, search disclosure,
  author/date, narrative introduction and related articles. Overview,
  specifications and reader responses require distinct page navigation. This
  pagination is an intentional prototype variant, not a claimed reproduction of
  the particular Tom's Hardware page.
- **P03 community-feed:** activity-led home, product identity/rating header,
  definition-list facts behind a native disclosure, dated reader-note stream,
  rating filters, pagination, individual-note permalinks and related products.

All have working home, catalog, article, exact-variant, comparison and methodology
routes. Links to other articles and variants are real. Retailer links require an
explicit SKU-to-URL binding; missing bindings produce no pretend retailer button.
No accounts, voting, submissions or inert advertisement controls were added.

The preview has **36 model articles, 864 reader opinions, five sites**: footwear,
computing, pets (dog and cat), beer and wine. Site identity and family coverage are
runtime configuration. It is three base structures, not five independent designs.

## World-to-page contract

`environments/product_review_sites/generate.py` accepts a `product_world` catalog
or store-world bundle. It reads only `public.products` and `public.product_groups`.
Each article selects one canonical reviewed SKU deterministically. Every other
variant has its own fact page and is explicitly not a separately reviewed result.
No assumptions transfer between laptop configurations, shoe sizes, food recipes or
wine vintages.

The export is `product-review-export-v1`:

```text
schema_version
public
  as_of
  variants[]: sku, model_id, name, family, facts
  articles[]: id, model_name, family, reviewed_sku, published, author,
              reader_opinions[], reader_statistics
private_provenance: seed, catalog/public hashes, authored distribution and semantics
```

Facts are projected from the exact SKU attributes; reference prices, stock, hidden
preferences, task answers, generation priors and provenance are not page data.
Supported family groups cover fit/use, computer configuration/ports, food
recipe/ingredients/labels, beer production/style/pack, and wine vintage/origin/bottle.
Unknown extra attribute keys can appear under additional recorded details.

The renderer reads an immutable validated public copy. It does not sample on click.
Changing layout, name, page size or related-link density leaves facts, reviewed SKU,
ratings and dates unchanged. Source order is irrelevant; increasing reader count
preserves existing reader records. No feasibility filtering against a user task.

Ratings currently use a deliberately simple uniform 1–5 demonstration distribution
and short sentiment templates. They are **not correlated estimates of product
quality**, measurements or proof of suitability. Counts/histograms/means are computed
from the complete corpus and stay fixed under filtering. Empty corpora are unrated.

This is a website-generation foundation, not a complete independent-review world
model. It does not yet supply measured shoe fit, cushioning, battery life, nutrition,
tasting descriptors, detailed review pros/cons or an oracle for those claims.
Existing product-world packages and shared commerce/harness code were not modified.

## Variation: implemented and proposed

Implemented controls are separate from data semantics:

| Control | Current support |
| --- | --- |
| Fictional publication name | Deterministic name pools per specialty; stable site ID |
| Base structure | Three choices; all accept every currently supported family |
| Coverage | One or more product families; article corpus follows input world |
| Catalog/reader page size | 4–24 items |
| Related articles | 0–12 available same-family articles |
| Scale | CLI 1–30 models per family; 0–100 reader notes per article |
| Retailer destinations | Explicit canonical-SKU URL map, no guessed live links |

**Discuss before implementing:** inline versus linked test details; table versus
prose emphasis; contents location; amount/order of adjacent editorial content;
collapsed versus expanded facts; article length and reader-feed density; prominent
versus secondary comparisons. Variation should alter accessible structure or the
navigation needed to find facts, not just padding/class names. Do not independently
permute substantive measurement values with layout or publisher identity.

More important than additional skins: agree on a product-review evidence sidecar.
It should distinguish manufacturer claims, generated test observations with units
and conditions, and noisy reader opinions. These may share product-level causes,
but must not be sampled as contradictory independent facts. Include the exact tested
configuration and permitted generalization scope. Then task checkers can query those
facts deterministically; visiting a review remains a procedure diagnostic rather
than an outcome requirement unless the actual user requested a source/citation.

## Running and extending

```bash
.venv/bin/python -m environments.product_review_sites \
  --output .local/product-review-sites/my-preview --seed 42 \
  --models-per-family 6 --opinions-per-review 24

# Or consume an existing generated world:
.venv/bin/python -m environments.product_review_sites \
  --world /path/to/world.json --output .local/product-review-sites/my-world

.venv/bin/python -m environments.merchant_reviews \
  --export .local/merchant-reviews/preview-v2/reviews.json \
  --seed 7 --output .local/merchant-reviews/my-renamed-preview
```

Output directories must be fresh; authoritative inputs are preserved. CLI ports,
PID, identities and source hashes are in each manifest. Servers bind loopback;
these are local previews, not Vercel deployments. Product sites use native HTML
links/forms and no client scripts or runtime network dependencies. They render
routes on demand; mutable browser state is not shared. Logs record HTTP requests,
not proof of model exposure. `Runtime` accepts an explicit layout/family/name and
read-only SKU bindings for future environment integration.

## Validation and limits

- 44 local tests across product-review and merchant-review packages, including
  six-family fact projection, exact-SKU scope, source/order invariance, opinion
  prefix stability, bad-export rejection, every route/link, escaping, simultaneous
  publisher names, empty data and store-world input compatibility.
- Eight fresh native BrowserGym cases, two concurrent isolated cases at a time,
  with 17 checks each. Three use identical footwear data across all base designs;
  the others cover laptops, dog food, cat food, beer and wine. Search, filter,
  comparison, variant links, reader pagination/permalinks and mobile width pass.
- Raw cases: `.local/product-review-sites/acceptance-v1/`; summary and input/source
  hashes: `suite.json`; per-case capture hashes: `report.json`.
- These test all three renderers using the public data, not an LLM policy. No
  claims about task difficulty, model success, or reward correctness.

Initial review AX on the same eight-model footwear corpus (four reader items/page):
lab 260 nodes/depth 8; magazine overview 100/depth 6; community 228/depth 7. The
magazine overview deliberately omits the linked specification/reader pages.
These are smaller than the real references; fidelity and realistic nuisance density
are not yet calibrated. Full-tree node counts are not model context token counts.
Saved initial overviews use the local Qwen tokenizer; the full outline is an audit
view, not a single delivered model message.

```bash
.venv/bin/python -m pytest environments/product_review_sites environments/merchant_reviews -q
LD_LIBRARY_PATH=$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu \
  .venv/bin/python scripts/verify_product_review_sites.py \
  --output .local/product-review-sites/new-acceptance
```

Integration still needed: site discovery/index entries, real merchant runtime URL
bindings, evidence sidecar semantics, task definitions/graders, trace exposure hooks,
shared deployment/package registration. Those are not established by HTTP/browser
acceptance of this isolated site.
