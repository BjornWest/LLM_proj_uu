# Comparison models and richer comparison-site designs

**New increment:** [four base designs and partial site coverage](comparison-coverage-and-layouts.md) now run in a separate connected world. The two-design stages below are retained history.

26 September 2026. Curation owns the public comparison/index projection and layout
prototypes; Product owns prices, comparison export, task/reference and grader.

## Model identity change (live connected world)

The current connected world is `.local/connected-shopping/preview-v2/`, PID 57605,
index http://localhost:38301. Product's task card at http://localhost:47403/task.html
is bound to this world. Previous preview-v1 remains historical and running.

Footwear comparison now uses a model identity, not every size/width/cosmetic-colour
SKU. The first pin has ten retailer/model listing rows. Model details show one
advertised-price row per retailer. Exact selection and stock remain on retailer
pages. Other product families continue comparing exact commercial configurations.
Index snippets similarly collapse footwear, including retailer discovery entries;
there are now 146 indexed documents. Product-review articles retain their own
truthful reviewed-SKU scope, while index snippets identify the model.

New worlds supply `public.comparison_listings` with `retailer_id`, `model_id`,
`advertised_price_minor`, `entry_product_id`. The entry SKU is only a valid retailer
navigation target. `comparison.build()` rejects duplicate/missing retailer-model
rows, unlisted/wrong-model entry SKUs, and noninteger prices. Stock and selected
option prices do not change the advertised price. Only old exports *without* the
field fall back to a clearly labelled minimum listed option price. Empty or partial
new exports do not trigger fallback. Legacy exact footwear aggregator URLs render
an unindexed model alias; canonical discovery URLs are `/models/{model_id}`.

Product pin-v2 is at
`.local/coordination/connected-shopping-world/product-pin-v2/`. Pin-v1 files are
unchanged, but its old generator source hashes intentionally no longer match the
current pricing implementation. Do not bypass pin checks to restart it.

## What real pages contribute

References inspected through public pages and actual BrowserGym AX capture:

- [Prisjakt home](https://www.prisjakt.nu/): broad category navigation, repeated
  collections, editorial links and a substantial footer.
- [Prisjakt product](https://www.prisjakt.nu/produkt.php?p=16929158): section
  navigation, merchant listings/disclosures, specifications, review and history areas.
- [Prisjakt running shoes](https://www.prisjakt.nu/c/loparskor): category refinements,
  ordering and product comparison selection (public-page inspection).
- [Sneakers4u collection](https://www.sneakers4u.nl/b/new-balance/): narrower model
  collection, from-prices and retailer counts. Its homepage also uses model-focused
  editorial collections.

These are structural references, not imported upstream sites or cloned assets.
PriceRunner's public fetch provided no useful page body, so it is not used as a
verified structural reference. References retain their observed consent/loading
state; AX counts are snapshots, not universal sizes or a controlled benchmark.

## Two base designs, three populated previews

| Design | Distinguishing AX structure | Current populations |
|---|---|---|
| Directory | Broad header categories, category collection sections, sidebar form/fieldsets, card results with comparison checkboxes, tabular merchant offers with disclosures, inline specifications | All six families (Prislyktan) |
| Specialist | Family-only navigation, editorial collection, horizontal refinements inside a disclosure, merchant offers each behind a disclosure, separate specifications route | Footwear (Stegvis), laptops (Datorval) |

Three sites do **not** mean three base designs: the two specialists deliberately
reuse one design with category data. This establishes a reusable boundary without
claiming the planned five aggregator designs are finished. Further useful designs
could emphasize a compact comparison matrix or a search-led vertical list; neither
is implemented here.

The additive prototypes are in `comparison_designs.py` and `comparison_preview.py`.
They bind the existing preview-v2 retailers, reviews and index. They create no
second product world, task host, retailer or geography service. They are not yet
registered in the connected task's discovery index or substituted for its tested
basic aggregator. This permits human layout review without changing the accepted
model-grouping cohort or Product's solve evidence.

Live design manifest: `.local/comparison-designs/preview-v2/manifest.json`.
Open the verified links via http://localhost:8876/comparison-designs.html.

## Working interactions and extension boundaries

Search, category selection, advertised-price ceiling, price/name ordering,
multiselect facets, clearing filters, pagination, two-to-four-product fact
comparison, merchant filtering, offer disclosures, specifications and outbound
retailer/review links are functional. OR applies within one attribute; AND across
attributes. Missing comparison attributes are marked “Not specified”. Numeric
units come from existing attribute definitions. Footwear facets use shared model
facts, excluding size/colour/width. Specialist scopes cannot reveal another family.

Both designs use the same comparison rows and price semantics. They do not present
an advertised price as a delivered total or promise stock. Product facts require no
new world fields. Layout choices are independent of surcharge and inventory logic.

Still unavailable from current world contracts: price-history samples, truthful
campaign/previous-price data, observed popularity, affiliate relationships, and
aggregator-specific shipping/stock feeds. Corresponding working controls/claims are
not invented. No tracking alerts, account persistence or wishlist service is added.
Review links use existing publications. There is no unsupported lab testing claim.

The new pages are richer, but still smaller than Prisjakt, particularly product
pages with few retailers and shared footwear facts. Equal node counts are not an
acceptance condition. Additional merchant coverage, useful disclosure data and
surrounding navigation should increase density coherently rather than padding the
AX tree with repeated meaningless controls.

## Acceptance and reproduction

```bash
CONNECTED_SHOPPING_PIN=.local/coordination/connected-shopping-world/product-pin-v2 \
  .venv/bin/python -m pytest environments/connected_shopping/test_connected.py \
  environments/connected_shopping/test_comparison.py \
  environments/connected_shopping/test_comparison_designs.py -q

LD_LIBRARY_PATH="$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu" \
  .venv/bin/python scripts/verify_comparison_designs.py \
  --output .local/comparison-designs/acceptance-NEW

.venv/bin/python -m environments.connected_shopping.comparison_preview \
  --output .local/comparison-designs/preview-NEW
```

All commands use fresh output paths. The design preview requires the matching
connected world to remain available for outbound links. Each scripted case gets its
own preview servers/browser context; cases run with bounded concurrency two.

Evidence:

- `.local/connected-shopping/comparison-v2-acceptance/suite.json`: three native
  journeys passed after model search plus explicit retailer option selection.
- `.local/product-world/` and the comparison-models handoff: Product owns independent
  public-page solve/grade evidence; it is separate from layout acceptance.
- `.local/comparison-designs/reference-ax-v1/`: actual reference captures, raw AX,
  semantic projection, nonverbose outline, screenshots and metrics.
- `.local/comparison-designs/acceptance-v1/`: all three native case reports passed,
  but suite summary failed due to an incorrect metric key in the driver. Retained.
- `.local/comparison-designs/acceptance-v2/`: corrected summary and current layout
  acceptance, after adding numeric units to the new design's fact displays.

No model calls, purchases or production deployment occurred. Full nonverbose token
measurements use the recorded local Qwen tokenizer; they represent an audit
projection of the entire tree, not one budgeted observation response.

## Stock and related-retailer polish

Current additional design previews are in
`.local/comparison-designs/preview-v3-polish/manifest.json`, linked from the same
[review page](http://localhost:8876/comparison-designs.html). Earlier preview reports
and the accepted connected task world are unchanged.

- Each retailer listing reports warehouse-stock status from the frozen public offers.
  Model status is **some options in stock**, not availability of a chosen shoe size.
  Exact configurations report their own stock. Missing stock stays unknown; stock
  does not establish delivery eligibility or a delivered total.
- Related/home/result cards show the lowest advertised item price and direct links
  to all retailers tied at that price, with their stock indications. Prices are not
  silently changed to the cheapest stocked variant or augmented with shipping.
- Additional size/colour offers remain on retailer pages. Aggregator disclosures
  explain the single listing and link to merchant reviews; they do not enumerate
  the retailer's variant inventory.
- Changing category uses navigation rather than submitting old attribute filters.
  The previous dropdown could submit footwear filters into laptops and get HTTP400;
  its old behavior was reproduced without mutating the preserved preview.
- Empty searches give recovery guidance; pet-food, beer and laptop refinements use
  real family fields rather than guessed field names. The reusable specialist design
  was rendered across all six families and every comparison product in this pin.

Current evidence: `.local/comparison-designs/acceptance-v3-polish/suite.json` (three
native cases), `polish-family-audit-v1.json` (six-family rendering and previous HTTP400),
`polish-review-v1.json` (publication/metrics hashes), plus nine focused design tests.
All passed, no model calls. These snapshots do not yet model an independently stale
aggregator stock feed; that requires a future explicit public-listing contract.
