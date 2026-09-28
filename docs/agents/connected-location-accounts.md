# Connected retailer stock and accounts

Curation owns `environments/connected_shopping/{stock,accounts,pages,runtime,http}.py`.
Product owns branch inventory/dispatch, account generation, coupons, order transitions,
and task grading in `environments/product_world/`. Local implementation only; no
model calls or production deployment in this increment.

## Public browsing

Product pages retain exact-SKU selection and show the authoritative online-delivery
quote. The collapsed **Stock in stores** disclosure lists each branch's selected-SKU
quantity, shipping capability, pickup availability/warehouse-transfer requirement,
and inspection availability. Changing quantity or SKU changes these facts together.
Stock is never added across locations. Listing cards use delivery eligibility rather
than mistaking warehouse stock for all online availability. Eligible delivery quotes
name the actual dispatch origin; the Product dispatcher chooses fastest arrival,
then lowest total, independent of the task objective.

With `scenario['accounts']`, each retailer gains an Account menu. Signed-in shoppers
can view saved coupons, order lines, tracking histories and delivery dates. Signed-out
pages reveal no saved orders or coupons. There is no password form or automatic login;
a future trusted user-login transition is separate work.

Coupon codes can be entered on delivery/pickup quotes. The Product AccountSession
checks store, sign-in, family, date, minimum subtotal and redemption state. Discounts
apply to items, not shipping. The UI never automatically chooses a coupon; comparison
listings remain unpersonalized. A quote does not consume the coupon. An invalid code
returns an unavailable discounted quote with the reason; removing it restores the
ordinary quote. Purchase/checkout remains unsupported in this connected runtime.

Order detail leads to a separate cancellation confirmation page. GET only reads.
Cancellation requires an explicit POST confirmation with a runtime/store-bound token;
foreign-origin and cross-site posts, duplicate form fields and oversized bodies are
rejected. Product handles state eligibility, atomic transitions, repeated cancellation
and journal entries. There is no simulated refund/payment claim.

## State and evidence

One Runtime is one synthetic shopper/episode. Browsers attached to it share that
shopper; separate Runtime instances deep-copy state and use separate form tokens.
Do not use a single Runtime as a multi-user public service. New worlds do not reuse
an earlier world's mutable order state. Historical order cancellation does not alter
current inventory.

Account worlds publish provenance `accounts_sha256` and `accounts_version`, and the
launcher saves initial `accounts.private.json`. The public index/manifest contains
no account orders, coupons, task targets or private answers. The account session is
available to the trusted task adapter at `rt.account_pages.session`.

The account-world journal is `connected-shopping-journal-v2` with scope
`research_and_account_management`. `accounts` contains the full private session
snapshot including all attempts; `orders` flattens current historical orders;
`commerce_mutations` records changed cancellation events. An empty mutation list is
not evidence that no historical orders exist. Account-free worlds retain journal-v1.
Old research-only graders must not be silently applied to this new scope.

`load_pin` additionally requires source hashes for `accounts.py` when accounts exist
and `branch_shipping.py` when branch dispatch is enabled. Source/input bytes and new
publication evidence remain separate from historical previews.

## Validation

- Stock HTTP cases: local-only inventory, branch fulfillment with empty warehouse,
  quantity limits, exact-SKU identity and collapsed disclosure.
- Account HTTP cases: discovery, tracking, signed-out privacy, retailer isolation,
  read-only confirmation, invalid/cross-runtime token, idempotence, explicit coupon
  arithmetic and independent initial states.
- HTTP action boundary cases: opt-in behavior, origin/type/duplicate/size rejection.
- Native stock: two isolated worlds in parallel; expand disclosure, follow pickup
  link, change quantity. Evidence `.local/location-accounts-stock-v2/report.json`.
- Native accounts: processing, shipped and signed-out worlds, bounded concurrency2;
  keep then cancel, reload safely, discover/apply coupon, inspect shipment history.
  Evidence `.local/location-accounts-browser-v2/report.json`; v1 remains historical.
  The v2 driver also checks the resulting state with Product’s account-task checker,
  supplying a reference structured answer itself (not evaluating model prose).

These are native Chromium scripted checks, with raw AX/screenshots and journals.
They do not establish model capability or exact harness policy delivery. The first
stock-driver attempt used an unavailable Playwright convenience API; its incomplete
output is retained at `.local/location-accounts-stock-v1`; v2 uses Chromium CDP AX.

```bash
.venv/bin/python -m pytest \
  environments/connected_shopping/test_stock.py \
  environments/connected_shopping/test_accounts.py \
  environments/connected_shopping/test_actions_http.py

LD_LIBRARY_PATH="$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
  .venv/bin/python -m scripts.verify_connected_accounts --output .local/NEW-account-check
```

A fresh output directory is required. Test fixtures deliberately force boundary
conditions; they are not sampled difficulty distributions. Product's separately
frozen world/task bank supplies the human preview and task acceptance.

## Frozen local preview

Publication: `.local/connected-shopping/preview-v11-location-accounts/manifest.json`,
PID 49851, consumes `.local/coordination/location-accounts/pin-v1` without edits.

- [World index](http://localhost:40049/)
- [Account overview](http://localhost:41249/account)
- [Orders and tracking](http://localhost:41249/account/orders)
- [Saved coupons](http://localhost:41249/account/coupons)
- [Local-only footwear example](http://localhost:41249/products/footwear-depth-model-0001-sku-d16152fe82bb)
- [Branch-only online fulfillment example](http://localhost:40331/products/wine-model-0019-sku-26a3f545b4a7)

This draw contains 438 offers, 19 branches (9 enabled for shipping), 4 signed-in
accounts, 8 coupons and 18 historical orders. Product provides 36 track/cancel task
definitions, including blocked outcomes; this is not 36 model-validated episodes.
The display preview is mutable if you confirm cancellation. Validation used separate
worlds and left these live orders unchanged.

Published read-only conformance: 1,402 cases passed at
`.local/connected-shopping/location-accounts-conformance-v1/report.json`.
Account projection: 30 pages plus cross-store rejections passed at
`.local/connected-shopping/location-accounts-projection-v2/report.json` (four workers).
Current focused regression selection: 55 tests passed. Native acceptance covers five
journeys, not every permutation; the account cases include scripted state grading.
Natural answers and live model performance remain untested in this increment.
