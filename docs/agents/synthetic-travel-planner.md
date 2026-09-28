# Synthetic travel planner

Implemented local browser site, 2026-09-26, in `environments/travel_planner/`.
Data exporter: `environments/product_world/travel.py`. Product-owned scope; no edits
to other owners' retailer layouts, review sites, commerce engine or shared web index.
Related foundation: [offline locations](product-location-system.md).

## Interaction and bounded scope

Waymark is a travel planner with native HTML forms and result cards. It is an authored
synthetic site, not an imported/reduced Google Maps or OpenStreetMap fixture. It needs
no map tiles, JavaScript, live geocoder, external API or turn-by-turn directions.

A user or browser agent can:

- Search generated branches by retailer, branch name, city, country or category.
- Choose a saved home or any generated branch as either trip endpoint.
- Resolve ambiguous text through an explicit confirmation form; unknown input stays
  unknown rather than silently becoming a city centre.
- Compare driving, cycling and walking distance/duration, including unavailable estimates.
- Sort branch search results by estimated travel time or route distance from a chosen
  origin, paginate results, open journeys, reverse endpoints and share journey URLs.

The dataset contains **the saved home and every physical branch**, including irrelevant
retailer families. Online-only stores have no physical destinations. Warehouses and
headquarters are not exposed as customer destinations. Search is scoped to participating
stores/saved places; it does not accept arbitrary real addresses, postal codes or
coordinates. The home currently has a saved-place label, not a generated street address.
Address/postcode aliases and additional public landmarks are later extensions.

Modes: walking, cycling and driving. Public transport would need its own network/service and
waiting-time assumptions; cycling and walking are currently same-city only, with authored
average speeds of 15 and 4.8 km/h respectively. Missing estimates have null metrics and visible unavailability; they are never
zero. A zero-duration trip is legitimate when origin and destination are identical.
Driving uses the existing fastest estimated authored corridor, not a claim of globally
fastest real streets. No traffic, parking, opening hours, or time-dependent schedules.

Travel availability does not establish product availability, inspection permission,
collection readiness or task compliance. Those remain on merchant pages/data. The
planner exposes no inventory, hidden requirements, memories, task labels or grader data.

## Export and size

`export_travel_planner(world, locations)` validates the geographic sidecar and emits
`travel-planner-export-v1` with `public`, `public_sha256`, and private source provenance.
Renderer receives only public place records, supported modes and a complete directed
trip matrix. Each trip contains origin/destination IDs, mode, status, approximate flag,
distance, duration, crossing kinds and an explicit unavailable reason where applicable.

For N places and three modes, the compact matrix has 3×N² records, including self trips.
Thirty branches plus a home require 31 places and 2,883 records. No additional roads or
buildings need to be generated for this UI. The source city/corridor paths are reused;
per-place results do not duplicate full path geometry.

The initial two-mode version measured the following (historical; cycling adds a
third trip record per pair):

| Fixture | Places | Results | Serialized public JSON bytes | Export + validation |
| --- | ---: | ---: | ---: | ---: |
| Default seed 0 | 28 | 1,568 | 392,466 | 0.047 s |
| 16 major retailers, base 1 model | 129 | 33,282 | 8,219,931 | 0.436 s |

These are one local scripted measurement, not latency guarantees or token counts.
Evidence: `.local/travel-planner/size-check.json`. The current upper bound is 161
places (one home + 16 retailers × 10 branches), or 77,763 trip records. Sparse/lazy
route storage can replace the complete matrix if world sizes grow substantially.

All route values are computed at export time and frozen. The existing geographic
quote layer and planner use exactly the same travel estimator. A larger city-path
cache accommodates all current city-pair/freight combinations without live calls.

## Hosting and separation

`travel_planner.runtime.Runtime` runs a separate loopback HTTP origin. It accepts only
the public travel export; there are no task authoring, world-generation, cart mutation
or reward endpoints on that origin. Native routes:

- `/w/<snapshot>`: search and journey forms, sorted/paginated branch directory.
- `/w/<snapshot>/journey?from=...&to=...&mode=...`: resolve endpoints and compare modes.
- `/w/<snapshot>/api/places?q=...`: public search data.
- `/w/<snapshot>/api/journey?from=...&to=...&mode=...`: one public cached trip; ambiguous
  endpoints return candidates and require disambiguation.

The privileged inspector publishes a snapshot after successful `/api/scenario`
generation and returns `travel_planner_url`. Its **Open travel planner** link uses that
world's public snapshot. No complete matrix is embedded into ordinary HTML pages.
The preview registry retains at most 16 snapshots and 100,000 trip records across
multiple snapshots, evicting oldest entries when needed. Expired links return 404;
regenerating the authoring world republishes it. This is a bounded demo registry,
not persistent hosting or multi-tenant isolation. Use a dedicated Runtime per episode.

For a stable standalone snapshot without any authoring server:

```bash
.venv/bin/python -m environments.travel_planner \
  --scenario .local/product-world/location-world-seed42.json \
  --port 47402 --manifest .local/travel-planner/standalone.json
```

CLI prints the full URL and supports a manifest containing PID, URL, export hash and
place/trip counts. `--scenario` requires an existing combined geographic scenario.
The shared browser-environment index and new task/oracle presets are **not integrated**;
this is a browsable site and deterministic public reference data, not a model evaluation.

## Verification

11 data/HTTP tests cover complete matrix bindings, agreement with existing travel
quotes, public-data boundaries, known/ambiguous/unknown resolution, direction reversal
coverage, self routes, null unknowns, ranking, HTML escaping and rejected corruption.
27 geographic/task regression cases also pass. Six browser cases use two isolated
concurrent contexts: journey/mode comparison, cycling, ambiguous-place selection, unknown input,
branch-to-branch routing and nearest-result ordering/pagination. No external requests.
An additional existing authoring browser case passed after the publishing integration.

```bash
.venv/bin/python -m pytest -q environments/travel_planner/test_site.py
.venv/bin/python -m environments.travel_planner.verify_preview --output .local/travel-planner/browser-next
```

Evidence: `.local/travel-planner/cycling-browser-v1/report.json` and per-case traces/screenshots;
`.local/travel-planner/authoring-browser-v1/report.json`. These are scripted tests only.

Country/city controls and cross-border authoring examples are documented in
[the location system](product-location-system.md). Branch area names are searchable
through the same place/alias resolver. Public transport remains unmodelled.
