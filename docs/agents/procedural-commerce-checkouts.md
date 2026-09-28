# Composable checkout flows

Checkout architecture is configured separately from product-page architecture. A department store, boutique or technical catalog can each use any checkout flow. Existing callers default to the original checkout; the new flows are opt-in.

| Flow | Structure visible to the agent | Required information |
|---|---|---|
| `express` | One compact page with a saved delivery profile | Email and final confirmation; selectable delivery |
| `accordion` | One page with four native expandable sections | Name, email, address, postal code, city, delivery and confirmation |
| `wizard` | Contact → address → delivery/payment → review | Same address/contact data plus phone and simulated payment selection |

All modes use the same commercial engine for stock, prices, shipping, extras and the order ledger. There are no real payments. The checkout controller records actual committed delivery details separately from drafts. The purchase verifier checks those details against the fictional profile explicitly supplied in the task. It does not reward visiting particular steps, expanding sections or taking a particular route. Checkout journals support diagnosis only.

## Configuration

```python
Runtime(
    world,
    retailer_designs={"nordhem": "editorial-boutique"},
    checkout_flows={"nordhem": "wizard"},
)
```

`checkout_flows="sampled"` selects flows using a separate deterministic seed namespace. It does not read the product layout. Explicit mappings allow controlled comparisons; omitted merchants retain `legacy`. Current mixed showcase mapping is for convenient browsing, not a dependency rule.

```bash
.venv/bin/python -m environments.procedural_commerce.runtime \
  --seed 7 --scale small --design-set ax-v2 \
  --presentation-profile showcase --checkout-set mixed \
  --output .local/procedural-commerce/my-new-checkout-preview
```

The output directory must be new. See its manifest for the four localhost origins. Add a product, inspect the basket, and follow Checkout. All checkout details must be synthetic; the demonstration profile is Alex Andersson, alex@example.test, 0700000000, Testgatan 12, 12345 Stockholm. The destination is Sweden. The wizard offers demo card/invoice selections without collecting card numbers.

## State and extension boundaries

`checkout.py` owns flow presentation and server-side stage validation. `checkout_config.py` owns selection. Runtime dispatches checkout routes independently of `retailer_designs.py`. New store designs need normal product/cart links, without implementing checkout forms. A new flow should implement the same controller contract and use engine quotes, never reproduce pricing logic.

A server-issued review token binds final confirmation to the current cart. Cart edits invalidate review, delivery repricing requires reconfirmation, and repeated final submissions must not create duplicate orders. Wizard prerequisites are checked on the server. Profiles and checkout journals are per merchant and per runtime session. GET requests may prepare presentation state but cannot place orders.

Current limitations: one cart line per merchant, Sweden/SEK, fictional fulfillment and payment, no real account authentication or card processing. These flows are local development fixtures, not deployed or model-tested capabilities.

## Retained branded-layout showcase (v2)

Fresh cart/checkout-v2 seed-7 preview (shared manual state, separate from prior previews):

- [Aggregator](http://localhost:46691/)
- [Expandable checkout store](http://localhost:34039/products/product-004) — Nordhem, department-market product design.
- [Four-page checkout store](http://localhost:40355/products/product-004) — Vardagslagret, editorial product design.
- [Express checkout store](http://localhost:39393/products/product-004) — Teknikgården, technical product design.

Each link starts at the same product, initially in stock at all three stores. Add it to the basket and follow Checkout. Manual purchases consume this preview's stock; new task episodes have separate state. Original previews keep their original checkout behavior.

## Initial checkout-v1 acceptance evidence

- 70 focused offline tests passed across the procedural environment, adapter, fulfillment checks and checkout acceptance helpers.
- 11 fresh BrowserGym sessions passed: all nine storefront×checkout combinations completed the same purchase; wrong-address and missing-field cases correctly returned safe_success=false. Zero action errors in all sessions.
- The same Nordhem merchant and commercial world were used for the nine combinations. A separate cross-merchant check confirms checkout drafts/journals remain isolated.
- Raw observations, screenshots, delivered policy text and private journals are retained. No model calls were made; this is scripted implementation acceptance, not evidence of model difficulty or competence.
- Suite: `.local/procedural-commerce-checkout-acceptance-20260922/summary.json`.
- Independent closure: `independent-closure.json` beside the suite; all 1,126 listed artifact hashes and 121 relevant source comparisons matched.

Reproduce into a new directory:

```bash
.venv/bin/python -m data.curation.procedural_commerce.mvp.verify_checkouts \
  --output .local/procedural-commerce/new-checkout-acceptance --workers 2
```

The controller unit tests cover direct-final/skip attempts, back/edit, validation, native quote-update form fields, repricing/reconfirmation, stale/change-and-revert tokens, duplicate submissions, escaping, isolated state and read-only commercial GETs. Native-browser acceptance checks successful navigation and distinct outcomes; it is not a proof of every possible interaction.


## Cart and embedded-checkout revision (v2)

Cart presentation now belongs to the checkout flow, independently of the product design:

- **Express:** compact shopping bag; item/extra/delivery editing behind a native disclosure; total and continuation visible outside it.
- **Accordion:** table-style basket plus delivery-estimate disclosure, surrounded by actual department links and other products. Checkout retains the same store surround, with browseable sidebars.
- **Wizard:** basket item configuration and delivery groups in the main column, a separate totals/continuation panel, and an order-stage navigation list.

The surround is composed from public catalog facts, with at most three other products, and does not depend on a storefront design ID. Its links really navigate. None of these changes alter engine prices, inventory, authorization or fulfillment grading.

### Direct-link defect

Reproduced on the original preview: opening a product at `localhost` rendered an absolute form action to `127.0.0.1`. Chromium refused to send it under `form-action 'self'`. Store navigation switched to the latter origin, explaining why navigating first appeared to fix Add to cart. This was unrelated to stock.

Product, search and legacy cart forms now retain the current origin via path-only actions, preserving any configured mount path. CSP stays unchanged. New flow forms were already relative. Reproduction evidence: `.local/procedural-commerce/direct-link-before.json`.

### New checks

Nine isolated Chromium cases cover every product-design×checkout-flow pairing entered directly through localhost. Each adds, changes quantity and extras in both directions, removes, re-adds, searches, and verifies no order was placed. Accordion cases also inspect both sidebars and follow a surrounding collection link. Raw AX and screenshots are saved in `.local/procedural-commerce/cart-flows-v2-browser/summary.json`. These are scripted browser checks, not model results.

Final v2 end-to-end suite: **11/11 BrowserGym cases passed**, all nine design/flow purchases plus wrong-address and incomplete-form negatives, zero action errors. Report: `.local/procedural-commerce/checkout-cart-v2-acceptance/summary.json`; all 1126 artifact hashes and 132 source comparisons match. Nine separate direct-link/cart cases and nine saved-AX structure checks also pass. The 70 focused offline tests pass. No model calls.


## True storefront embedding (v3)

The surrounding page is now a separate choice from checkout steps:

- `checkout_shells={"nordhem": "storefront"}` uses the exact storefront document builder. Product content is replaced by cart/checkout content inside its existing main region. Header, navigation/sidebar, footer, body class and base stylesheet remain the same. Only checkout-content styling is added, scoped to that main region. There is one brand heading and one main landmark.
- `checkout_shells={"nordhem": "branded"}` retains the previous separate checkout layout, including the alternate accordion surround. This remains the default for existing callers; v2 previews are unchanged.

This presentation option can combine with any of the three checkout flows and retailer designs. It does not change fields, stage validation, quote binding or grading. Browser routes can still change to `/cart` and `/checkout`; embedding refers to the retained page layout, not an iframe or a duplicated full page.

New embedded examples (add the product and continue through the cart):

- [Department store / expandable checkout](http://localhost:35913/products/product-004)
- [Boutique / guided checkout](http://localhost:37753/products/product-004)
- [Technical catalog / express checkout](http://localhost:46627/products/product-004)

Pass `--checkout-shell storefront` alongside `--checkout-set mixed` to create a preview of this configuration. Adapter metadata and private diagnostics retain the resolved `checkout_shells` separately from `checkout_flows`.

Three native browser continuity checks compare the product, cart and checkout documents. Header, external navigation, footer, base stylesheet and body class match exactly in every design; each page has one main and one h1. Full AX and screenshots are retained in `.local/procedural-commerce/storefront-shell-v3-browser/summary.json`. No model calls.

Final v3 acceptance: all nine storefront-design×checkout-flow purchases and both negative cases passed through BrowserGym with the storefront shell, zero action errors. Suite: `.local/procedural-commerce/storefront-checkout-v3/summary.json`. Independent closure checked 1,126 artifact hashes and 143 relevant source entries. The 70 focused offline tests also pass. No model calls; historical branded-shell evidence and previews remain unchanged.


## Explicit navigation after Add to cart (v4)

New `cart_navigation` choices are independent of product design, checkout flow and checkout shell:

- `inline`: adding returns to the same product page; menu basket count updates; a “Go to cart” link appears on product pages only while that retailer has a nonempty basket.
- `menu`: same post-add behavior and factual basket feedback, but no product-level cart link. The agent/user follows the existing outer-menu Cart, Bag or Current order link, now with a quantity count.
- `redirect`: historical immediate-cart behavior, retained for existing programmatic callers. New CLI previews default to `mixed`, assigning inline/menu examples. `sampled` uses a dedicated seed namespace without consulting prices or layout.

This uses POST/redirect/GET back to the product URL, not AJAX. The document reloads, displaying the actual server-side basket; refresh cannot repeat the POST. The one-line basket contract is unchanged: cart.set sets the selected quantity rather than incrementing an existing line. Rejected second-product additions retain the original basket and show an error on the attempted product page. Basket presence is not proof of purchase or eligibility; the commercial verifier is unchanged.

The resolved mapping is retained in adapter metadata, diagnostics and the preview manifest. Static page furniture is still reused; its dynamic basket counter intentionally changes with state.

Latest examples:

- [Inline Go to cart — Nordhem](http://localhost:43889/products/product-004)
- [Outer-menu navigation only — Vardagslagret](http://localhost:44645/products/product-004)
- [Inline Go to cart — Teknikgården](http://localhost:42129/products/product-004)

Eight isolated Chromium cases cover both variants on all four supported storefront styles, including the historical catalog. They check direct localhost entry, empty/nonempty counter, conditional link, staying on the product, refresh without another event, rejected second-product feedback, explicit navigation and removal. AX/screenshots and source hashes: `.local/procedural-commerce/cart-navigation-v4-final/summary.json`. An earlier development test incorrectly expected over-stock draft quantity to be rejected; the engine deliberately allows ineligible drafts, so the test was corrected without changing commercial semantics. Its evidence remains in `cart-navigation-v4-browser/`.

The v4 end-to-end BrowserGym suite passed all nine design/flow purchases with the mixed inline/menu configuration plus both negative cases, zero action errors. Evidence: `.local/procedural-commerce/stay-on-product-v4/summary.json`; closure checked all 1,192 artifact hashes and 154 relevant source hashes. The 70 focused offline tests pass. No model calls.


## Add-button placement and independent quantity semantics (v5)

The inline Go to cart link is now a green button-like link next to Add to cart inside the purchase form. Basket feedback sits underneath those controls; it no longer inserts a block before the product's catalog content. Menu-only navigation still omits that link. The link remains conditional on a nonempty basket.

New independent runtime/adapter option `cart_addition`:

- `set`: selected product-page quantity replaces the basket quantity (existing behavior).
- `increment`: selected quantity is added to the existing same-offer basket quantity. Selecting 2 and pressing Add twice yields 4.
- `sampled`: resolves set/increment with its own seed namespace, without reading product design, checkout, navigation, shipping or pricing settings.

Cart editing always sets an absolute quantity. Both variants still support one product line per merchant; a different product is rejected until the current line is removed. Product-form delivery/extra choices continue to apply to the resulting whole line. Quantities above stock may exist as ineligible drafts, but cannot be purchased. No pricing/stock/authorization loophole is granted by the additive variant.

The engine records incremental requests as `cart.add`, retaining the submitted delta and the actual before/after cart state. `cart.set` keeps its prior meaning. Runtime serializes mutations under the same lock and invalidates checkout review tokens for both actions. The resolved behavior is private provenance in the runtime manifest, adapter metadata and diagnostics, not a policy-visible mechanism label.

New preview examples (showcase choices only; they are not design dependencies):

- [Nordhem — repeated Add increments](http://localhost:40807/products/product-004)
- [Teknikgården — repeated Add sets the chosen quantity](http://localhost:43817/products/product-004)
- [Vardagslagret — menu navigation, set quantity](http://localhost:42679/products/product-004)

CLI supports `--cart-addition set|increment|sampled|mixed`; mixed is an explicit human showcase. Keep training sampling independent instead of reusing the fixed showcase assignment.

Validation: 16 isolated native browser cases cross four storefront designs, two navigation variants and two addition modes, using the same merchant/world. They check adjacent button geometry, conditional visibility, quantities 1→2→5 vs 1→1→3, actual item subtotal, absolute cart edits, rejection without mutation, refresh without resubmission and removal. Evidence: `.local/procedural-commerce/cart-addition-v5-browser/summary.json`. Three additional unit tests cover raw delta journal evidence, invalid deltas, different-product rejection, absolute updates and independent sampling. No model calls.

V5 checkout regression: all nine storefront/flow purchases and both negative cases passed with incremental addition enabled, zero action errors. Evidence: `.local/procedural-commerce/cart-addition-v5-checkouts/summary.json`; closure verifies 1,192 artifact hashes and 154 relevant source entries. The 73 focused offline tests pass. No model calls.

### Open product-page stock guard (user review)

The user reproduced incremental Add exceeding stock. Checkout correctly rejects the resulting ineligible basket, but product-page additions should reject an excessive resulting quantity earlier and preserve the previous basket, with visible feedback. This is not yet fixed. Current engine intentionally permits ineligible drafts; tighten the product-add contract explicitly, without silently rewriting historical acceptance evidence or conflating the change with layout variation.
