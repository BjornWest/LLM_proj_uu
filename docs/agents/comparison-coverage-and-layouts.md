# Four comparison layouts, filter capabilities and partial coverage

26 September 2026. Current integrated local world:
[search index](http://localhost:45095), PID 69744; public manifest
`.local/connected-shopping/preview-v4-coverage/manifest.json`. This is a new world
runtime over the unchanged product pin-v2, plus Product's independently sampled
coverage sidecar. Previous world/task hosts and evidence remain untouched.

New task card: http://localhost:35539/task.html. Product independently checked the
public retailer-search route and canonical grading: all 78 candidates/reference
outcomes remain unchanged, including the cheapest offer omitted by all comparators.
This is scripted acceptance, not a model run; consent history was not graded.
Evidence: `.local/product-world/connected-coverage-acceptance-v1/summary.json`.

Human review with site links, screenshots and nonverbose AX outlines:
http://localhost:8876/comparison-designs.html.

## Four base structures

| Base | Demonstration site | Distinct navigation/AX structure |
|---|---|---|
| Directory | Prislyktan, general | Category collections, sidebar facets, comparison cards, inline retailer table and specifications |
| Ledger | Prisradar, general | Department directory, collapsible navigation/refinement, matrix results, product-summary aside and ordered retailer list |
| Specialist | Stegvis, footwear | Family collection, expandable refinements, product detail with retailer disclosures and separate specifications |
| Finder | Datorval, laptops | Attribute-based collection links, ordered catalogue with refinement aside, product dossier, separate retailer-listing page |

Both specialist bases are reusable across families. Family choice changes the data,
wording and available attributes, not a hardcoded shoe/laptop engine. Source files:
`comparison_designs.py`, `comparison_alternatives.py`, `comparison_profiles.py`.
The short descriptions above document what each base contributes to design diversity;
future bases should introduce another interaction structure rather than copying one
and changing spacing/classes.

## Independent dimensions

1. Canonical world products/offers remain Product-owned.
2. Membership is sampled by `product_world.comparison_coverage` independently of
   task, price, stock and layout. It binds the source world hash.
3. Filter capabilities are explicit presentation input: per-family attribute fields,
   price-ceiling availability and sorting availability. These are independent of
   membership and base design. The current demonstration uses authored, varying
   profiles; it does not claim an implemented stochastic filter-profile sampler.
4. Layout renders the selected public projection. URL binding is separate again.

The demonstration deliberately differs: Prislyktan offers richer facets, price and
sorting; Prisradar offers one attribute facet per family and price, without result
sorting; Stegvis offers activity and sorting, without a price-ceiling control;
Datorval offers RAM/storage, price and sorting. Missing filters do not erase product
facts from detail pages. Unsupported filter query parameters are rejected, rather
than becoming hidden capabilities. Footwear size/colour/width selection stays at
retailers.

## Membership contract and semantics

The exact frozen input is
`.local/coordination/comparison-coverage/pin-v1/coverage.public.json`, recorded with
recipe and hashes in the adjacent `pins.json`. Only the membership file is public;
private candidate visibility/summary files are not website assets.

```json
{
  "schema_version": "comparison-coverage-v1",
  "source_world_sha256": "...",
  "sites": [{
    "site_id": "comparison-general-a",
    "families": ["footwear"],
    "comparison_ids": ["footwear-model-0001"],
    "listings": [{"comparison_id": "footwear-model-0001", "retailer_id": "store-001"}]
  }]
}
```

Footwear uses model IDs; other current families use exact SKU comparison IDs.
A tracked product may have no tracked retailer offers. Product-level omission,
retailer-feed omission and individual listing omission are distinct. Sampler knobs
cover a shared core, site additions, retailer-only fraction, retailer-feed probability
and listing probability. See Product's implementation and coordination decision for
sampling details; curation does not duplicate that sampler.

Every public surface uses membership: home/results, facets, counts, related products,
lowest-price retailer links, comparisons, product/specification/retailer routes and
index documents. Manually entering an untracked URL returns 404. A product covered
by a site but without listings shows no tracked offers, not global out-of-stock.
Price calculation uses only that site's tracked listings and keeps advertised
model-price semantics. Public stock remains a frozen retailer snapshot, with shoe
model stock explicitly distinguished from selected-size availability.

The new runtime has four comparison servers and **no separate all-products comparator**.
Its legacy `origins['aggregator']` is merely a navigation alias to one general site.
Retailer pages and all their canonical offers remain available independently.
The index includes their product discovery documents even if all comparison sites
omit those products. `bindings.comparison_products` contains only real covered URLs,
with an empty array for an untracked comparison identity.

The fixed draw has 44/25 and 45/28 product/listing counts for the general sites,
4/4 for footwear and 3/0 for laptops. Nine offered identities are absent from all
comparison sites. The empty laptop feed was preserved rather than repaired to make
an attractive demonstration. It is a useful distinction between knowledge of a
product and possession of a retailer offer.

Existing cheapest/average tasks still grade against the complete canonical retailer
population. Omission cannot narrow the oracle, create global no-match, or justify
claiming a covered price is globally cheapest. Finding a route is diagnostic, not
rewarded procedure. Product owns the task card/grade integration for this runtime;
no paid/model evaluation is claimed by the site acceptance.

## Runtime and reproduction

```bash
.venv/bin/python -m environments.connected_shopping \
  --pin .local/coordination/connected-shopping-world/product-pin-v2 \
  --comparison-coverage .local/coordination/comparison-coverage/pin-v1/coverage.public.json \
  --output .local/connected-shopping/preview-NEW

.venv/bin/python -m pytest \
  environments/connected_shopping/test_comparison_scope.py \
  environments/connected_shopping/test_comparison_world.py -q

LD_LIBRARY_PATH="$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu" \
  .venv/bin/python scripts/verify_comparison_coverage.py \
  --coverage .local/coordination/comparison-coverage/pin-v1/coverage.public.json \
  --output .local/comparison-designs/coverage-acceptance-NEW
```

Runtime accepts `comparison_coverage` and optional `comparison_profiles`; CLI accepts
`--comparison-profiles FILE` for a separate explicit map by site ID. Without coverage,
the earlier runtime path remains available. New provenance records membership and
profile hashes separately. Site/journal/task/private boundaries remain unchanged.
This composition creates 18 site origins plus one index, with 188 indexed documents.

## Acceptance and limitations

- Eight scope/base tests cover membership on all page surfaces, direct-route denial,
  empty feeds, hidden-filter rejection, independent filter/layout selection and
  specialist reuse across shoe/laptop content.
- Four frozen integration tests check covered index routes, canonical retailer
  discoverability, scoped prices, all nine retailer-only identities and HTTP filter
  rejection. Seven legacy connected tests also passed after the additive runtime change.
- Native BrowserGym acceptance: all four design journeys plus search absence on every
  comparator followed by index-to-retailer recovery. Each case used an isolated runtime
  and browser; bounded concurrency two. This is scripted acceptance, not agent skill.
- Evidence `.local/comparison-designs/four-bases-acceptance-v1/`: four cases passed;
  the new ledger failed mobile width due to CSS grid min-content sizing. Retained.
- `.local/comparison-designs/four-bases-acceptance-v2-ledger/`: targeted replay passed
  after the mobile grid fix. No generation/content repair. Other cases retain their
  original source fingerprints; the only post-suite renderer delta is this responsive
  CSS rule in `comparison_alternatives.py`.

No screenshots/AX evidence is silently relabelled as a different source revision.
No task was resampled to manufacture a feasible answer. New stochastic filter/layout
sampling, larger catalogs and paid model difficulty evaluation remain separate work.

Final website/publication audit: `.local/comparison-designs/four-bases-review-v1.json`.
All 19 website/index origins and the new task card respond. The original publication
source map is retained: Product subsequently changed only its episode.py and
episode_preview.py task-adapter modules within that recorded map to bind the new
card. The audit records both hashes; it does not claim the entire checkout is identical
to the website launch snapshot. Website modules are unchanged.

## Mixed-category discovery sections

Directory now accepts optional `discovery: {mode, seed, limit}` in its presentation
profile. Modes are `trending`, `popular`, and `new`, displayed as “Trending now”,
“Popular products”, and “New on this site”. `sample_discovery(seed)` deterministically
samples the mode; explicit mode selection is also supported. New default demonstration
profiles enable this on general-a. Previously saved profiles without the field retain
their old behavior. Other bases do not yet render this section and reject a non-null
configuration rather than silently ignoring it.

Selection is hash-seeded, category-interleaved, unique and bounded (default 12 cards).
It draws only from that comparator's tracked products, with existing real product and
retailer links and coverage-scoped prices. It does not inspect task answers, stock,
price ranking or user preferences. A small limit may not fit every category; missing
categories are not manufactured. Empty catalogs omit the section. Current preview
has two products from each of all six families.

These labels are synthetic merchandising variants, not measured sales, click trends
or product release dates; no counts/dates or underlying popularity facts are invented.
“New” means featured as new on this comparison site. Do not grade factual popularity
or recency questions from these labels without adding explicit world metadata.

Additive preview command (links into the existing retailers; does not replace the
world index or task card):

```bash
.venv/bin/python -m environments.connected_shopping.discovery_preview \
  --published .local/connected-shopping/preview-v4-coverage \
  --output .local/comparison-designs/discovery-NEW --seed 42
```

Native checks: `scripts/verify_comparison_discovery.py`, run with `python -m`, two
independent browser sessions at a time. Checks named AX region, 12 unique links,
six-family mixture, product navigation, stable reload and mobile overflow. Unit checks
also cover scope, empty coverage, invalid settings and seed repeatability.

## How the AX interaction differs

Side-by-side CSS columns alone are not a meaningful AX variation. The useful
variation is the hierarchy, roles, document order, disclosures and page transitions:

- Directory exposes a named filter **complementary** region followed by product
  articles. Product offers form a table with column/row headers; specifications are
  inline. The new discovery section is a named region containing a heading and 12
  articles, each with category, linked product heading, facts and scoped prices.
- Ledger puts refinements behind a **DisclosureTriangle**. Results are table rows
  with selection controls. Product details use a summary aside followed by an ordered
  retailer list. Collapsed navigation/refinements hide descendants until expanded.
- Specialist exposes collection refinements and individual retailer offers through
  disclosures. The agent must expand an offer to expose its retailer action and can
  navigate to a separate specifications page.
- Finder exposes attribute collection links and an ordered product catalogue, with
  refinement controls later in document order. A product dossier leads to a separate
  retailer-list page, adding a navigation/observation step before choosing an offer.

Exact control IDs depend on the live observation. Historical outlines in the gallery
show roles/nesting; they are not a current target list. Screenshot positioning may
look different without changing AX, and accessibility extraction can omit generic
HTML wrappers. These descriptions concern the retained nonverbose semantic trees.
