# Offline locations and correlated merchant profiles

**Agent-facing travel site:** [Waymark](synthetic-travel-planner.md) now exposes the
saved home and generated branches through public search, journey forms and cached
walking/cycling/driving estimates. The authoring inspector links to each generated snapshot.

Implemented authoring slice, 2026-09-26. Product owns `environments/product_world/`;
coordination ID `PRODUCT-LOCATIONS-20260926`, recorded in
`.local/coordination/product-locations.md`. No shared commerce/runtime, retailer layout
or web-index registration changes. No paid/model calls. Inspector:
<http://localhost:47401/>.

## Construction and scope

The user's clarification defines “transit required” as **stock transfer**, separate
from the customer's journey to a branch. The agreed geographic scope covers Nordics,
UK/Ireland, Benelux, France, Germany, Austria, Switzerland, Spain, Portugal and Italy.
The first bundled fixture contains 59 city anchors across those 17 countries and 64
authored transport corridors. This is a curated subset, not all Western European
addresses. Source/license and important geographic limits are in
[`data/README.md`](../../environments/product_world/data/README.md).

Generation order:

1. Sample user location from the task seed and chosen city (or uniform country, then
   uniform bundled city). User location is part of structured task context and public
   environment context before stores are sampled.
2. Sample task, memories and hidden fit facts. Preserve their full semantics when
   regenerating worlds. Destination country and displayed location agree; prices
   remain authored SEK amounts in every country, without simulated FX.
3. Sample merchant size profiles and geographic footprint, then appropriate product
   specializations, catalog demand, shared SKUs and warehouse inventory.
4. Sample branch inventory separately from warehouse inventory. Precompute user-to-
   branch driving/walking/cycling and warehouse-to-user/branch freight routes.

World seeds affect merchants, stock and geography but never the fixed user's position
or task. The task's product-family and named-model projection remains the only input
to product coverage. Location affects merchant sampling and fulfilment, without
forcing the task to have a feasible solution. No retry-until-success loop.

Default merchant home probabilities: 0.40 in the user's city, 0.45 elsewhere sampled
within the user's country (the same city remains possible), 0.15 in a different supported
country. Conditional on choosing a foreign merchant, `foreign_neighbour_probability`
(default .85) selects among countries with a direct bundled ground/sea corridor to
the user country, then uses that country’s nearest bundled city. With no such
neighbour (Iceland), it falls back to other supported countries. This is corridor
adjacency, not a complete geopolitical border table. These are authored priors. They guarantee neither a nearby shop nor delivery
coverage. Headquarters, online warehouse and physical branches have distinct IDs and
positions. Every retailer has one warehouse in this slice. Local/regional footprints
stay within 60/250 km great-circle distance of the home city and the same country;
major chains can span the supported home-country cities. Unique cities are preferred
until the eligible pool is exhausted; multiple branches then occupy distinct named areas or synthetic sectors. Local
shops still sample only one or two total branches; online specialists have none.
Area labels never force extra locations. `areas.py` supplies curated names for four
cities plus centre/directional fallbacks elsewhere; names and local coordinates share
an approximate anchor. [Sources and limitations](../../environments/product_world/data/README.md#branch-area-labels).

Retailer naming now follows the merchant headquarters country/city, not the user's
country. `naming.py` supplies deterministic fictional brand vocabularies and local
specialization terms across all 17 countries. French/Spanish/Portuguese/Italian names
put the shop type before the brand; other vocabularies use brand then type. The existing
ordinal suffix keeps names distinct within a world. Belgium uses Dutch for Antwerp
and French for Brussels; Switzerland uses German for Zürich and French for Geneva.
Luxembourg uses French and Ireland uses English with its own brand vocabulary. These
are authored defaults for the bundled cities, not exhaustive national language rules.
Synthetic branch sectors use the same locale selection; curated neighbourhood names
retain their existing spelling. Store identity is shared by the index and travel
export; no renderer invents a translated name independently. Naming choices are recorded
in private world provenance. Product brands remain canonical across retailers.

## Routing and consistency

`geography.py` uses a local, attributed GeoNames subset for city centres and an authored
city-corridor graph. Dijkstra selects the shortest estimated-time route. Each route
retains city path, crossing legs, distance, duration, method and approximation flag.
Local positions use synthetic offsets; they are not real street addresses or checked
land parcels. Local walking uses 4.8 km/h, cycling 15 km/h and driving 25 km/h. These are
authored averages using the same local detour distance, without slope or cycle-lane data. Road corridors use
75 km/h and a 1.22 detour multiplier. Crossings have explicit speed/handling priors.

Only same-city walking and cycling are modelled; intercity cycling does not inherit
car corridors or assume access to bridges/ferries. A missing ground connection returns
`status: not_modelled` and null distance/duration, never zero. Iceland has a synthetic
freight-only air corridor; this does not invent a driving route or passenger timetable.
Intercity routes have no traffic, public transport schedules, elevation, tolls or
opening-hour effects. These limitations are explicit in exported provenance and UI.

Route computation happens once during world construction, and routes are exported in
the location snapshot. Quote evaluation reads those stored routes. Generation, quotes
and the inspector need **no external map/geocoding service**.

For higher fidelity later, precompute an immutable matrix from a pinned local routing
engine/map snapshot, including snapped valid endpoints, source/version/mode, distance,
duration and explicit unreachable cells. OSRM's [table and route interfaces](https://project-osrm.org/docs/v26.6.1/http)
are a possible construction-time source, not an implemented dependency. Training
would consume only cached results. Import and route-engine provenance validation are
future work; this version validates its own authored routes by recomputation.

## Fulfilment contract

`locations.quote(world, locations, offer_id, method='delivery', branch_id=None,
quantity=1)` returns deterministic eligibility/reason codes, full item + fulfilment
cost, readiness days, route reference, stock source and `requires_stock_transfer`.
The method operates on one SKU/order line; it is not a basket shipping calculator or
mutable reservation engine. Locations must reference the matching world hash.

- **Delivery:** stock comes from the offer's online warehouse pool. The destination
  must be served and have a freight route. Readiness is dispatch + geographic transit
  + one authored cross-border handling day. Unsupported destination, insufficient
  warehouse stock and unmodelled freight route remain distinct reasons.
- **Pickup now:** enough saleable branch stock, zero transfer days and no delivery
  fee. “Now” is stock readiness, conditional on checking opening hours, which are not
  modelled. Online stock may be zero while local pickup remains possible.
- **Pickup after transfer:** insufficient local stock, merchant permits warehouse
  transfers, and warehouse has the full requested quantity. Readiness includes offer
  dispatch and the warehouse-to-branch freight transit; `requires_stock_transfer=true`.
  It never appears as immediate pickup. This slice does not combine partial branch and
  warehouse quantities or transfer between branches.
- **Inspect/try:** footwear/laptops only in this slice; the exact SKU has saleable local
  stock or an independently sampled display unit. Display units are not saleable stock.
  No showroom promise is inferred from a retailer merely selling the product online.

Transit formula: one handling day + ceil(route km / 650) + one day per non-road
crossing leg + two extra days if air cargo is involved. Shipping: 49 SEK base + 25 SEK
per commenced 500 km + 80 SEK for cross-border delivery + 70 SEK per non-air crossing
+ 250 SEK for air cargo. Transfer fee defaults to zero (retailer absorbs it). These are
**synthetic all-in scenario rates**, not real carrier tariffs or customs/tax rules.
All arithmetic is integer öre; geography, stock and destination coverage determine
eligibility before quotes have payable totals.

The inspector compares geographic availability and sorts branches by estimated driving
distance. It does not assert that a displayed SKU meets the task's product constraints,
that the user has a car, or that pickup satisfies a home-delivery-only request. Travel
cost is not added to the merchant price. No map does not mean no route: unmodelled
travel remains explicit uncertainty. The new nearest-inspection and pickup recipes consume this evidence through a
separate single-line reference adapter; see [task coverage](world-task-coverage.md).
The quote table itself still does not check product requirements; the dedicated
reference-outcome button does. Browser/harness integration remains separate.

## Merchant correlations

Size is orthogonal to product specialization: a major footwear retailer still sells
footwear, not unrelated laptops. Existing general-marketplace limits remain intact.

| Size profile | Default weight | Models vs base | Positive warehouse stock | Branches | International coverage probability |
| --- | ---: | ---: | --- | ---: | ---: |
| Local shop | .35 | ×0.6 | 1–8 | 1–2 | .05 |
| Regional chain | .35 | ×1.0 | 1–30 | 3–5 | .25 |
| Major retailer | .20 | ×1.8 | 1–120 | 6–10 | .80 |
| Online specialist | .10 | ×1.2 | 1–45 | 0 | .60 |

Model counts round up, cap at 20 per store and retain required family anchors. Counts
are bounded demo-scale examples, not representations of actual chain sizes. Stockout
probability remains independently configurable and applies to every size profile;
major retailers can still be sold out. Physical branch stock currently uses 1–8 units
when stocked, independently of size. Branch-carry probability .6, branch stockout .25,
inspection display probability .35 (eligible families only), transfer probability .85.
International merchants currently serve all 17 modelled countries; others serve their
home country. Gradual country coverage, multiple warehouses, store hours, urban/rural
sampling and empirically calibrated profiles are future extensions.

## API and compatibility

```python
from environments.product_world.scenario import generate_scenario
from environments.product_world.locations import quote
s = generate_scenario(
    task_options={'seed': 2, 'family': 'footwear', 'destination_city': 'uppsala'},
    world_options={'seed': 42, 'models_per_store': 5},
    location_options={'config': {'branch_stockout_probability': .25}},
)
first_offer = s['bundle']['public']['offers'][0]['offer_id']
q = quote(s['bundle'], s['locations'], first_offer)
```

```bash
python3 -m environments.product_world scenario --task-seed 2 --world-seed 42 --family footwear --destination-city paris --output /tmp/paris-world.json
```

`location_options` opt in to the sidecar (`product-locations-v1`). It accepts `config`
(probability overrides), `profile_weights` (sparse size-prior overrides), and
`correlated_profiles` (bool, default true), and `merchant_home_cities` (explicit
retailer-ID → bundled-city-ID overrides). For example, a Malmö task can pin
`{"store-001":"copenhagen", "store-002":"malmo"}` without changing its task
requirements, inventories or delivery eligibility. Unknown IDs are rejected. Disabling size correlations uses three
branches per merchant and retains base catalog/warehouse sizing. Without the sidecar,
legacy store APIs preserve Sweden-only metadata and prior size behavior. Geographic
scenarios require a `destination_city` or `destination_country` in task options; contradictory missing
context is rejected rather than silently patching the task after store generation.
`destination_country="FR"` alone samples a French city; when both are specified,
the city must belong to that country. Omit the country and use city `random` for
uniform-country then uniform-city sampling. CLI also accepts `--destination-country`.
The inspector exposes country/city selectors and four location examples: Malmö with
Copenhagen, Amsterdam with Antwerp, Lille with Brussels, and Lisbon. Cross-border
examples pin one foreign and one domestic retailer and use local-shop profiles to
ensure physical destinations. The random generator does not guarantee foreign stores.

Sidecar `public`: user location, merchant headquarters/warehouse/branches/policies,
branch inventory and route lookup. Private: seed, priors, source/version/hash and scope
limits. Full-world export includes the sidecar; dedicated locations download includes
its provenance. The existing public-world download remains the old catalog/store payload;
consumers needing branches must explicitly include the location public projection.
Existing merchant reviews continue to bind by retailer ID without schema changes.

Preview endpoints: `/api/geography` (bundled anchors/defaults), `/api/scenario` (optional
`location_options`), `/api/location-quotes` (same construction options + offer ID and
quantity). The latter deterministically reconstructs the authoring snapshot to avoid
trusting client-edited inventory, then quotes its precomputed routes.

**Integration boundary:** `procedural_commerce.engine` still supports SE-only delivery
and fixed transit. These quotes are a separate data-only reference contract, not an
extension of that engine, existing checkout pages or training oracle. Curation must
integrate the geographic contract before claiming runtime pickup/delivery support.

## Validation

18 dedicated data tests include a four-worker audit over all 17 countries, deterministic
network-free construction, fixed task destination, ferry/bridge/air distinctions,
warehouse transfers, independent branch stock, inspection-only units, coverage/costs,
size correlations, fully sold-out major retailers and rejected corruption/configuration.
Additional country constraints, cycling, area-name uniqueness and three cross-border
fixtures are covered. The combined catalog/store/review/scenario/location/travel
regression run passes 84 cases. Browser cases run in two isolated
concurrent contexts: default, sold-out, basket, beer, named, France, transfer, local
pickup and online-only. Evidence: `.local/product-world/locations-browser-v1/`.

```bash
.venv/bin/python -m pytest -q environments/product_world/test_locations.py
.venv/bin/python -m environments.product_world.verify_preview --output .local/product-world/locations-browser-next
```

These are scripted authoring tests, not model evaluations or deployed retail pages.

Cycling/country browser evidence: `.local/travel-planner/cycling-browser-v1/` (six
cases) and `.local/product-world/country-browser-v1/` (five cases, including all three
border presets). New location snapshots include cycling routes and branch area metadata;
regenerate historical location sidecars before using the expanded quote/export layer.
Previously exported two-mode travel snapshots remain readable by the travel runtime.
