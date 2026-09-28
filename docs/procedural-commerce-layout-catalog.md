# Procedural commerce layout catalog

MVP design registry, 2026-09-22. The first three retailer branches have been reclassified as one legacy family. Three AX-first retailer architectures have passed bounded local browser/AX validation; nothing here is deployed or model-calibrated. Keep each card short enough to read the entire catalog before assigning a new design. Runtime and validation status belong in the MVP implementation report.

All designs consume the same public commerce contract. Differences belong in DOM structure, navigation and interactions, not duplicate price logic. Product traits, compatibility/fit sections, review links and user context are extension points; render only applicable public facts and do not fabricate placeholder claims. No hidden task, expected answer or sampled difficulty metadata in the DOM.

## Scope decisions after real-page review — 2026-09-25

### Page-design TODOs added 2026-09-27

- **Verification gates:** add simulated Cloudflare-style interstitial and embedded
  designs, with the user/simulated-user channel completing a private, episode-bound
  verification tool after the browser agent requests help. Official Turnstile test
  widgets can be an optional integration reference. This is backlog work, not an
  implemented gate or a production CAPTCHA bypass. See the
  [design contract](agents/synthetic-verification-gates.md).
- **Dynamic pages:** rotating promotions, delayed sections and asynchronous
  commercial updates; preserve task facts and explicitly record timing/affected
  regions. See the [dynamic-page backlog](agents/procedural-commerce-mvp.md#backlog-dynamic-page-designs-2026-09-27).

These are authoring requirements, not newly implemented capabilities.

- **Product comparisons:** prioritize the planned third-party product/review sites
  for cross-product comparisons. Retailers need discoverable specifications and
  useful related-product links; they do not each need a full comparison application.
  Comparing retailer offers for the same SKU remains the aggregator's separate role.
- **Warranty:** reserve a semantic product/offer-information field and a reachable
  presentation location in each design. Realization may be inline, a disclosure or
  a linked policy section. Consume the warranty contract being developed elsewhere;
  do not invent coverage or conflate included warranty information with a paid
  protection add-on. Unknown data must not become a promise of coverage.
- **Location:** keep space for destination input, delivery estimates and pickup
  availability. Product-owned geographic sidecar work is tracked in
  `.local/coordination/product-locations.md` (PRODUCT-LOCATIONS-20260926).
  Future binding requires an explicit adapter: the current SE-only, fixed-transit
  commerce quotes do not implement geographic fulfilment. Preserve distinctions
  between warehouse/branch stock, immediate pickup/transfer and inspection/demo
  availability; destination must follow the sampled user location. Do not publish
  inert address controls as working functionality.
- **Monthly plans:** retain as a worthwhile later capability, outside the immediate
  dense-layout increment. Do not display a purchasable plan before its price and
  commitment semantics exist.
- **Surrounding content:** prefer links to real generated products and category
  results, rendered on demand. Stable SKU/model IDs resolve through the same world
  and merchant assortment; visits must not independently resample identity, stock
  or prices. Reuse templates/assets without cloning an application per destination.
  Related accessories should use compatible product data when they imply suitability;
  a general recommendation can be unrelated without making false compatibility claims.
  Broken links are a last resort, not the default source of page complexity.

The separate product owner is developing `environments/product_world/`, a data-only
catalog exporter for the existing product/group contracts. This does not itself
establish merchant offers or working commerce destinations; assortment/offer binding
remains an integration boundary. No edits to that package are implied here.

## A01 — Prislyktan comparison directory

- **Character:** search-led general aggregator; category navigation, structured search results and dedicated product comparison pages.
- **Distinctive structure:** result summaries lead to offer tables; retailer identity and advertised price stay visibly associated; actual shipping is checked at the merchant.
- **Variation/scale:** short summaries versus expanded attribute groups; paginated catalogs use the same routes at 12 and 96 products.
- **Extension space:** category-aware attribute filters, price history and specialist-review links; MVP can omit their controls until supported.

## L01 — Legacy catalog family (reclassified)

The initial Nordhem/Vardagslagret/Teknikgården branches are **variants of one family**, not three accepted base designs. Shared header, product/purchase composition and downstream basket flow dominated their differences. Prior HTML distance numbers did not establish policy-visible diversity.

- **Knobs:** `legacy_style=catalog|boutique|specifications` selects table/list/spec-first discovery independent of retailer name; `layout_variant=compact|expanded` selects detail richness.
- **Boundaries:** existing brand defaults retained for old callers. No claim that every page changes substantially; cart/checkout remain shared. These are development reference variants.

## R10 — Department marketplace

- **Discovery:** top utility navigation plus named nested department sidebar; product results as rich list entries, not a dense comparison table.
- **Product:** title can include actual category/attributes; image gallery precedes product information, purchase options sit in a complementary region, description follows recommendations or uses an explicit configured disclosure.
- **AX target:** separate navigation and complementary landmarks, image names, long heading, intervening related-product links, lower-page facts.
- **Extension space:** future configuration/fit controls in buying region, department-specific filters, independent delivery facts. No fabricated ratings/reviews.

Within-family prototype: explicit flat/expandable navigation, cards/table results,
split/details-first product, table/definition-list facts and select/radio delivery.
These preserve the department architecture and commercial semantics. See the
[matched AX comparison](agents/procedural-commerce-within-design.md); the new
choices are not yet automatically sampled or implemented in other families.

## R11 — Editorial boutique

- **Discovery:** short navbar, story-first landing and linked collections; text-forward ordered results with narrative grouping.
- **Product:** short introduction and figures; full description can require navigation to `/products/ID/details`, with a clear return link. Purchase controls belong to the article flow.
- **AX target:** no department sidebar, distinct information order, image/figure context, real cross-page information discovery and footer policy content.
- **Extension space:** condition/care/fit narrative when facts exist. Small-store identity does not justify fewer meaningful variation options.

## R12 — Technical catalog

- **Discovery:** sidebar-oriented navigation, a filter form and actual result table with associated headers and stock/attribute cells.
- **Product:** section-oriented reading, specs behind a native disclosure by default, table of facts and grouped purchase fieldset.
- **AX target:** table/row/header/cell structure, collapsed/expanded control states, specifications becoming available after interaction, purchase group distinct from department aside.
- **Extension space:** actual compatibility/configuration traits once supported by world schema. No invented electronics claims for generic household products.

These new cards describe the implemented discovery/product architectures; accepted behavior is evidenced by the [AX revision report](agents/procedural-commerce-ax-designs.md). Commercial quote/cart/checkout/receipt logic and initially their downstream HTML remain shared. Distinct discovery/product architecture is not a claim of distinct end-to-end checkout designs.

## R13 — Dense storefront

- **Discovery:** broad header search, expandable department menu, category-led home
  and paginated product-card results; links resolve against the merchant's offers.
- **Product:** gallery and compact buying region followed by expandable information,
  a same-category recommendation aside, a larger other-department region and grouped
  footer navigation. Cards retain their own product identity, price and attributes.
- **AX distinction:** broad surrounding product regions, repeated contextual links,
  native gallery radio state and independently expandable navigation/specifications.
  Matched 99-product world: 645 retained nodes versus the earlier department's 123;
  both maximum depth seven. Expanded menu/specifications reach 774 nodes.
- **Boundaries:** real existing product routes; no invented reviews, compatible
  bundles or monthly plans. Uses existing SKU selection and single-line commerce.
  All three embedded checkout flows passed scripted cases. Images remain symbolic.
  [Implementation, evidence and limitations](agents/procedural-commerce-dense-storefront.md).

## M01 — Merchant-review directory (separate site type)

- **Discovery:** search-led home, category navigation, company results with overall
  rating and review count; generated store identities remain canonical.
- **Profile:** company summary, sidebar histogram/related companies, four recent
  highlights, dated review stream with twenty entries per page; functional star,
  keyword, topic, date and sort controls, review permalinks and reply disclosures.
- **Data:** consumes the product owner's versioned public review export. Complete
  corpus determines counts/mean; filtered views preserve overall statistics.
- **Identity variation:** sample a fictional review-site name independently
  of layout and merchant ratings, keeping it stable across an episode/world and
  consistent in search results, links, page titles and branding. Names must not
  encode reliability or the winning retailer. Keep private stable site IDs for
  diagnostics. Eight authored names now sample in the merchant-review CLI; existing runtime
  callers retain Omdömeskollen unless configured. Shared search-index binding remains future work. Trustpilot is a design reference, not the
  claimed source of the synthetic reviews.
- **Boundary:** synthetic testimony, not merchant ground truth; no accounts or review
  submissions. Retailer links require an explicit runtime binding. Locally scripted
  tested, not deployed or task-certified. [Implementation](agents/merchant-review-site.md).


## Product-review publications — P01/P02/P03

- **P01 specification directory:** left contents/filter navigation, central grouped
  fact tables and right related-product links. Initial specialties: footwear/pet food.
- **P02 editorial magazine:** masthead/section navigation, search disclosure, byline
  and three linked article pages (overview/specifications/reader responses). Initial
  specialty: computing. Relevant facts can require navigation rather than expansion.
- **P03 community activity:** activity-led home, identity/rating header, definition-list
  facts in a disclosure, repeated dated reader notes and related-product sidebar.
  Initial specialties: beer/wine; no account/check-in submission system.
- **Shared boundary:** all three accept every currently supported family and the
  same immutable export. Reviews specify an exact SKU; other variants have fact
  pages, not silently shared reviewed results. Names, density and layout are separate
  parameters. Synthetic opinions are not product truth or lab measurements.
- **Evidence:** eight native scripted cases across six families; no model runs,
  task/grader certification or deployment. [Research, generation and variation
  discussion](agents/product-review-sites.md). More realistic measured/reviewed
  attributes need a future evidence contract, not renderer-invented facts.

Product-review presentation now uses family vocabulary profiles independently of
base layout. Native facets derive choices and ranges from public reviewed facts;
size identity is not treated as a minimum. See the [family audit](agents/product-review-family-audit.md)
for current counts, remaining realism gaps and broader-family preparation.

## Rules for adding or changing a design

The three AX designs now also accept the same optional [size/colour product-control
contract](agents/procedural-commerce-product-controls.md). Dropdown/radio selection
is configured independently per axis and retailer; each design retains its own
buying-area placement. This is an authored footwear fixture, not generated
product-family coverage.

Before implementation, compare against all cards and state one meaningful structural gap the design fills. Reserve the card so parallel workers do not independently produce the same layout. Keep each card to identity, structural differences, supported variation/scale and extension points. Update it to describe the implemented design, not its aspirations.

The capability contract is shared; the component tree need not be. Base-design sampling and within-design variation richness are separate. Boutique designs deserve genuine variation too. The [variation rubric](procedural-site-variation-rubric.md) is a review target; this MVP must report what was actually built rather than claim every proposed axis is already realized.

Functional styling for visibility, hit targets and scrolling is necessary. Decorative styling is secondary. Layout IDs/configuration live in private provenance; ordinary brand identity is public, but grader/mechanism labels are not.

## Independently composable checkout architectures

The initial AX revision kept one shared checkout. The next increment introduces a separate `checkout_flows` configuration, compatible with every retailer design:

- **C01 Compact express:** compact shopping bag with expandable item editing; saved delivery address, inline summary, email and final confirmation on one page.
- **C02 Expandable checkout:** table-style basket and checkout embedded between department navigation and other-product links; contact, address, delivery and confirmation in four native disclosure sections on one page.
- **C03 Guided checkout:** basket item editor alongside a totals panel, then separate contact, address, delivery/payment and review pages with back/edit navigation.

Flow IDs never depend on storefront design IDs. The showcase assigns one of each for easy comparison; generation may sample the checkout independently. Quote calculation, stock and order semantics stay shared. See the [checkout implementation contract](agents/procedural-commerce-checkouts.md) for validation and scope.


Checkout **shell** is an independent presentation axis: `storefront` inserts the cart/checkout content into the original design's main region and retains its exact page furniture; `branded` uses the separate checkout layout. The earlier alternate surround remains a branded variation, not true storefront embedding. Checkout step architecture remains C01/C02/C03 in both shells.

Post-add navigation is another independent axis: `inline` stays on the product and offers Go to cart when the basket is nonempty; `menu` stays and relies on the outer cart menu. Both show actual basket quantity. `redirect` retains historical immediate-cart behavior for compatibility.

Repeated-add semantics are independently configurable with `cart_addition=set|increment` (or a separate seeded sample). This choice must not be inferred from or tied to a base layout, cart-navigation choice or checkout design. Both variants use an absolute quantity editor in the cart. Inline Go to cart is colocated with Add, not inserted above the product layout.

### Product-review structure follow-up

P01 now uses nested attribute contents, corpus comparison tables and linked attribute subsections. P02 adds latest/topic navigation and expands its main article with factual comparisons. P03 adds rating distributions, activity navigation and public reader archives. All three have contributor/archive/footer links. See [the structural report](agents/product-review-structure.md) for AX counts and unsupported reference elements; these are synthetic designs, not complete imported sites.
