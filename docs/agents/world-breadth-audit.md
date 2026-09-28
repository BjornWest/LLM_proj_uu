# Three-world breadth and page audit

Local scripted audit, 2026-09-26. No model or search-provider calls. “Width” was
interpreted as broader world coverage pending user clarification. Existing v9/v10
previews, scenarios and model traces were preserved; no new product family or task
success requirement was introduced.

## Samples and current local links

| Fixed draw | Browse | Task card | Models / SKUs / offers | Oracle status |
| --- | --- | --- | --- | --- |
| Seed 0, footwear, Malmö | http://localhost:38897 | http://localhost:44129/task.html | 20 / 256 / 406 | No match |
| Seed 7, laptops, Berlin | http://localhost:40191 | http://localhost:34165/task.html | 15 / 50 / 55 | Determined; 13 eligible |
| Seed 23, cat food, Amsterdam | http://localhost:36187 | http://localhost:41873/task.html | 18 / 82 / 77 | No match |

These three worlds collectively cover footwear, laptops, dog food, cat food, beer
and wine, with 18 retailer instances, seven countries, 74 branches, 432 merchant
reports and 1,260 product reports. Counts are sums across separate worlds, not a
single shared catalog. Product generated the immutable first draws and owns the
independent data audit and task cards. Curation composed the sites and checked pages.
The laptop minimum is 8,269 SEK delivered, not a model result.

## Renderer corrections

- Retailer specification tables omitted attribute units. Tables and catalog cards
  now consume schema labels/units and format booleans/lists as human-readable text.
  Canonical product attributes remain unchanged. The conformance checker now rejects
  the old unitless presentation, independently deriving expected units from metadata.
- “Other products” could list eight size variants of the current model. It now shows
  one listed option per different model in stable catalog order. No task-conditioned
  ranking, cheapest-variant selection or stock-based hiding was added. Ordinary search
  still lists exact product options, so large footwear catalogs can remain repetitive.
- Delivery prose mixed transit time with “authored” border charges. It now directs
  the shopper to the destination-specific total and arrival estimate.

Code: `environments/connected_shopping/pages.py`, `conformance.py`,
`test_breadth_polish.py`, `test_conformance.py`.

## Evidence and scope

Under `.local/coordination/world-breadth-audit/`:

- `samples-v1/manifest.private.json`: recipes, immutable scenarios and source/file pins.
- `renderer-before.json`: original unitless render examples from all six families.
- `publications-v1.json`: three independent server processes and output locations.
- `conformance-v1/*/report.json`: **1,870 passing HTTP checks** for every offered
  product/selection/default delivery quote, bounded quantity/branch boundaries,
  comparison tables/omissions and all supplied review panels.
- `homepage-links-v1.json`: **887 passing unique one-hop homepage links** across the
  three worlds, checking same-world destinations and HTTP success. Not a full crawl.
- `native-v2/report.json`: **eight passing browser journeys**, all six families;
  index search → retailer → details where needed → delivery quote → independent
  review. Retains screenshots, raw AX, nonverbose semantic projections and outlines.
  Product-page semantic trees range from **163 to 363 nodes**. These are generated
  product pages, not a claim of parity with large real retailers.
- `native-v1/`: retained partial development attempt. Two driver timeouts came from
  looking for SKU IDs in link labels that correctly contained product names. Search
  results existed. Corrected the driver, not the sites; interrupted the remaining
  run and used a new output directory.
- `data-audit.md` / `data-audit.json`: Product's independent quote, corpus and task
  checks: 1,514 delivery quotes, 5,812 branch quotes, all 444 candidate assessments.
- `episode-bindings.json`: independently bound task cards; originals unchanged.

Forty focused unit/regression checks pass (presentation, adversarial conformance,
ad binding and comparison designs). Native journeys are privileged scripted tests,
not model solves or exhaustive interaction coverage. Site facts match their source;
this does not establish subjective realism, all geography accuracy or every possible
search/filter/quantity permutation. These connected worlds remain research-only;
cart/order execution is not supported.

## Follow-up knobs, not repaired outcomes

The shoe request asks for white while the explicit typed-shoe recipe only supplies
black/blue; independently no merchant meets its required mean rating. Cat food asks
for at least 40 merchant reviews but all stores have exactly 24. Both are valid,
retained no-match worlds, with easy impossibility proofs. Review-count distributions,
colour palettes and rating distributions need more variation independent of the
request; do not reroll until a desired answer appears.

Prices remain SEK even for Berlin/Amsterdam destinations; prose is English. This is
an explicit scope limitation, not a currency conversion claim. Size variation is
available, but this audit did not implement regional size conversion. Product review
coverage is bounded to two variants per model; absence remains unknown. Simple unit
labels can still be grammatically mechanical (e.g. “1 units”). No additional generator
patch was justified by these three samples.

## Reusing the check

```bash
.venv/bin/python -m scripts.verify_connected_world_conformance \
  --scenario PATH/scenario.private.json --runtime PATH/published \
  --output PATH/new-conformance --workers 4

LD_LIBRARY_PATH="$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
  .venv/bin/python -m scripts.verify_world_breadth_pages \
  --publications .local/coordination/world-breadth-audit/publications-v1.json \
  --output PATH/new-native-output
```

Native output paths are exclusive; the driver snapshots its source before browsing.
It chooses first offered products without checking feasibility, then follows public
search results and compares selected page facts against canonical inputs. No model
backend is constructed. HTTP source conformance and native interaction evidence
should remain separate in future reports.
