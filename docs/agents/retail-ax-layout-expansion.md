# Building denser retailer layouts from real AX references

Follow-up implementation: [R13 dense storefront](procedural-commerce-dense-storefront.md)
now has local scripted evidence. The proposal below remains the research brief;
the implementation report distinguishes delivered scope from deferred features.

2026-09-25. Research and implementation brief, **not an implemented new storefront**.
No model inference, accounts, cart changes or purchases. Existing runtime and
world-generation code are unchanged.

**Conclusion:** a substantially more realistic product-page AX tree is feasible
using our existing public products, variants, offers and merchant policies. Most
initial work belongs in rendering and browser interactions. We should not make
financing, geographic inventory or a multi-line basket prerequisites for it.

[Local reference browser](http://localhost:8876/retail-ax-expanded.html) ·
[Earlier Amazon/Elgiganten comparison](http://localhost:8876/retail-ax-comparison.html).

## Additional real references

Successful product captures:

- [IKEA KALLAX](https://www.ikea.com/se/sv/p/kallax-hylla-vit-80275887/): broad gallery;
  breadcrumb navigation; colour links; availability controls; product tabs and
  nested disclosures; several recommendation sections with their own options and
  purchase controls. Opening material/care information added nine retained nodes.
- [Uniqlo crew-neck T-shirt](https://www.uniqlo.com/uk/en/products/E422992-000/00?colorDisplayCode=03&sizeDisplayCode=005):
  compact buying region, colour/size buttons, extensive surrounding product cards
  and exposed size-guide tables. This session displayed an out-of-stock selection.
  Its repeated numeric colour labels and wish-list controls make surrounding
  context important for locating the intended item.

Attempted but **excluded from product comparisons**:
[Decathlon jacket](https://www.decathlon.co.uk/p/mens-lightweight-waterproof-hiking-jacket-mh100-beige-black/309604/c382c407m8678198)
and [B&H headphones](https://www.bhphotovideo.com/c/product/1706394-REG/sony_wh1000xm5_s_wh_1000xm5_noise_canceling_wireless_over_ear.html).
Both returned security-verification pages, not product pages. No bypass was attempted.

| Captured state | Retained semantic nodes | Interactive-role nodes | Headings | Maximum depth |
| --- | ---: | ---: | ---: | ---: |
| IKEA after consent rejection, before scrolling | 439 | 133 | 26 | 6 |
| IKEA after bounded scrolling | 912 | 333 | 40 | 8 |
| IKEA material/care expanded | 921 | 333 | 42 | 8 |
| Uniqlo after consent rejection and scrolling | 2,038 | 520 | 38 | 7 |
| Earlier Elgiganten product | 1,285 | 196 | 32 | 16 |
| Earlier Amazon product | 621 | 181 | 39 | 7 |
| Our existing three layouts | 87–139 | 16–24 | 3–6 | 8–9 |

Counts describe these sessions, not universal site sizes or task difficulty.
The initial product samples differed in category and state. The four successful
retailer references are an architectural sample, not coverage of all retail.

### Distribution matters more than one large node count

- IKEA: main subtree **734 nodes**, footer **149**, banner **25**.
- Uniqlo: main subtree **82 nodes**, complementary subtree **456**, related-product
  region **1,254**, footer **99**. The related region alone accounts for about 62%
  of retained nodes. Landmark boundaries are the site's markup, not a semantic
  guarantee that all product information belongs inside `main`.
- Earlier Amazon: main **133**, with extensive surrounding navigation. Earlier
  Elgiganten: main **1,145**. Two equally plausible sites can concentrate their
  complexity in very different places.

These observations support multiple dense architectures, rather than multiplying
every region by the same factor. More unnamed wrappers or CSS classes would not
reproduce this distribution in the model's non-verbose AX view.

## Proposed first dense layout: R13, broad catalog storefront

Proposed card, not an accepted fourth design. Its distinctive structure is a
relatively compact primary buying area within a broad site shell, followed by
substantial independently navigable product and information regions.

Illustrative semantic shape; exact landmarks and hierarchy need capture testing:

```text
banner
  utility navigation
  search form
  department navigation [closed/open states]
  cart link and item count
main
  breadcrumb navigation
  product identity and gallery [selected image state]
  purchase region
    option groups -> current canonical SKU
    price / availability / quantity / add / cart access
    delivery summary and quote link
  product-section navigation
  description / specifications [separately expandable sections]
  shipping / returns / warranty [existing public facts only]
complementary: More from this category
  product cards -> actual product routes
  card image, heading, offer summary, supported variant links
region: Other departments
  distinct product cards -> actual product routes
contentinfo
  grouped category links and policy navigation
```

Recommendations must use merchant-listed products. A broad recommendation is not
a compatibility claim: do not label arbitrary products as matching accessories.
No review stars, membership promises or finance controls merely to fill space.
Gallery controls must actually switch content; disclosures and menus must expose
and hide the corresponding AX content. Links must resolve without changing world facts.

For a first reference instance, try **12–24 distinct surrounding product cards**
across two or three regions, with 6–10 meaningful nodes per simple card, plus
navigation and product information. This is an initial design range, not a quota
or a measured result. Rich cards with variant choices can be larger. Small catalogs
should display fewer cards, not repeat one SKU until a node target is reached.
Start with existing generated catalogs; no new category-specific facts are required.

Do not attach a size guide to products without size semantics. Rich fact sections
should consume whatever attributes are present, and tolerate sparse products. The
separate product sampler will eventually improve content density; this layout need
not block on its complete offer/assortment integration.

Coordination update, `PRODUCT-STORES-20260925`: the product owner is extending
`environments/product_world/` with store-first specialist assortments, a public
store/index manifest and per-store offers referencing unchanged canonical SKUs
and groups. This is in progress, not integrated runtime support. Its reserved
`.test` origins require runtime binding; they are not deployed destinations.
Curation owns the later adapter. Recommendation cards must select from the
current merchant's inventory and offers, not assume every world SKU is sold by
every merchant. Unlisted and sold-out selections remain distinct. Catalog overlap
does not guarantee a feasible task or a winning offer. No edits to the product
owner's package or shared index are required for this layout research.

## Dependency and effort map

Effort descriptions are relative engineering judgments, not token or time estimates.

| Surface | Current source / gap | Work required | World-generator ask |
| --- | --- | --- | --- |
| Larger department navigation, breadcrumbs, footer category links | Public products already carry category and identity; search routes exist | Low: renderer composition and valid links | None |
| Longer titles, fact tables, multiple information sections | `attributes`, `traits`, product identity | Low–medium: truthful formatting and category-appropriate grouping | None for a first version; optional display metadata later |
| Related-product cards with images, prices and product links | Public catalog and merchant offers; existing recommendations show only three plain links | Medium: richer cards, stable ordering, bounded list sizes and route checks | None using the current complete-offer fixture |
| Expandable navigation, tabs, disclosures, image gallery | Presentation/UI state; current layouts already have basic disclosures | Medium: actual keyboard/click/state behavior and AX checks | None; this is presentation state |
| Size/colour choices in buying area | Existing product-group selection contract | Low–medium: reuse canonical selection, change placement | None for supported axes; regional conversions still need their mapping contract |
| Shipping, returns and basic warranty information | `shipping_methods`, offer dispatch data, `policy_summary` | Low: surface available summaries and quote links | None for existing facts; detailed warranty coverage is deferred |
| Product-specific prose/spec grouping and meaningful image captions | Current attributes can support a basic version; rich public content is sparse | Medium, mostly content contract and substitution tests | Small optional public display schema, not a new economic model |
| Review ratings, customer comments, question/answer panels | No established review facts | Separate feature: coherent generated claims and their relationship to product truth | Required; do not invent in renderer |
| Multi-item accessories/bundles | Engine currently allows one product line per merchant basket | Substantial: cart, totals, stock, receipt and verifier coverage | New commerce semantics and, for compatibility, product relationships |
| Store pickup, destination-specific stock, finance/subscriptions | Geography and plan semantics unfinished | Substantial separate increments | New factual contracts; omit active controls for now |

Code boundaries checked: `generator.retailer_view()` supplies public catalog facts;
`retailer_designs.py` owns presentation; `runtime.py` already resolves product,
details and search routes; `product_controls.py` binds selection to SKU;
`engine.py` owns quoting and mutations. Preserve that division. Do not calculate
alternative prices in renderer code or copy hidden oracle fields into page metadata.

Some current constraints are unrelated to making one page denser: runtime insists
on exactly three merchants, stock/offer availability is not a general sparse
merchant-assortment contract, and baskets are single-line. A large page does not
remove these limitations. Related-item *navigation* fits today; faithful
multi-product purchasing does not.

## Scale and a shared stash

No storage architecture needs to be chosen for this renderer increment. Render
only requested pages from stable IDs; do not run another app instance per product.
We have not benchmarked throughput or memory for a dense implementation yet.

An immutable shared pool can hold catalog records, templates and assets. Each world
still needs a stable manifest of which items/merchants/offers exist, and each episode
needs isolated carts, orders and mutable stock. A link should not silently introduce
a new cheaper offer outside the oracle's world. Shared deterministic base catalogs
plus per-world offer mappings and per-episode mutable state are compatible with
the proposal; a globally mutable shared shop would not be.

## Bounded implementation and acceptance sequence

1. Implement one new renderer consuming the same public catalog, leaving commercial
   logic and checkout flow selection intact. Preserve the three existing designs.
2. Add local menu/gallery/disclosure state; broaden real catalog navigation. Avoid
   duplicating the same full purchase form throughout the page.
3. Capture non-verbose AX before/after opening menu and facts, then compare the
   distribution of nodes, roles, repeated labels and region sizes against references.
4. Reuse semantic selection/cart/quote tests. Add a bounded native-browser path for
   search -> product -> variant -> add -> cart -> existing checkout, plus a related
   product navigation and disclosure-state case. Check target identity and stock.
5. Cross the renderer with a sparse generic product and the existing multi-axis
   footwear fixture, long text and the two catalog scales. Cover capability
   combinations without testing every future SKU × layout × task permutation.

Acceptance is not “reach 1,000 nodes.” It is: recognizably different structural
regions, meaningful contextual controls, working navigation/state transitions,
correct outcome facts and no hidden answer exposure. Browser extraction time and
AX retrieval results should be measured on the resulting page. Model difficulty
would require a separately authorized evaluation, not inference from node count.

## Evidence and reproducibility

New evidence root: `.local/retail-ax-study/20260925-expansion-v1/` (ignored).
`capture/` retains first visits including Uniqlo's still-open cookie banner.
`followup/` contains fresh IKEA/Uniqlo captures after explicit optional-cookie
rejection, IKEA material disclosure and the excluded B&H interstitial.
`analysis/analysis.json` records offline subtree counts and input hashes.

Method: BrowserGym 0.14.3, headless Chromium 1440×1000, fresh contexts, actual
`_get_obs()` -> current `AXContext`, non-verbose. Four 1,800-pixel scrolls then return
to top are bounded sampling, not proof of complete lazy loading. BrowserGym emitted
child-frame marking/merge warnings; concurrent capture logs do not reliably assign
them to a specific site. Counts are retained extracted content, not a guarantee of
every frame or every visible/operable element. Uniqlo's extracted tree includes size
tables without an explicit size-guide-opening action; do not infer all these nodes
were visibly displayed or tested controls. Consent removal does not authenticate.

Actual initial-overview outputs were 925 tokens / 14 returned items for IKEA and
916 / 16 for Uniqlo, using the local Qwen tokenizer, under the profile's 1,000-token
overview budget. Full-tree outlines/projections are audit reconstructions, **not
single model messages**. Interactive-role counts include untested controls.

The capture script now recognizes capitalized `Reject All` and limits optional
read-only disclosure clicks to explicit site mappings. Prior capture-source copies
and evidence remain untouched. Offline analysis accepts `--cases` and `--output`
so this reference set can be inspected without revisiting the websites.

```bash
.venv/bin/python scripts/analyze_retail_ax.py \
  --cases .local/retail-ax-study/20260925-expansion-v1/analysis-cases.json \
  --output .local/retail-ax-study/20260925-expansion-v1/analysis-NEW
.venv/bin/python scripts/publish_retail_ax_expansion.py
```

Raw captures are local research evidence; the proposed new renderer uses our own
products/content and borrows structural patterns, not copied retailer pages/assets.
