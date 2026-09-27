# Product stock, accounts and task generation

Generation modules in `environments/product_world/` provide the data/state contract
for [connected retailer stock and accounts](connected-location-accounts.md). This
is deterministic local preparation, with scripted checks; no model capability or
free-text grading claim. Legacy account-free and warehouse-only worlds remain valid.

## Sampling controls

`generate_scenario` opts in explicitly:

```python
scenario = generate_scenario(
    task_options={"family": "footwear", "destination_city": "malmo",
                  "retailer_preferences": "memory", "coupon_disclosure": "none"},
    world_options={"seed": 42},
    location_options={"branch_shipping": {}},
    account_options={"seed": 42, "as_of": "2026-09-27", "config": {}},
)
```

Branch shipping defaults to probability0.45 with dispatch handling0–1 days. Options
are `enabled_probability` and `dispatch_days_max`. Branch capability is sampled
before inventory; it does not depend on whether the branch would solve the task.

Account config defaults: signed-in probability0.7, coupon probability0.75 for each
of2 coupon slots, expired probability0.2, redeemed probability0.1,3 historical orders
per retailer. Order status weights are processing0.4, shipped0.3, delivered0.25,
cancelled0.05. These are explicit configurable priors, not equal outcome classes.
Eligibility, request preferences and inventory determine realized task outcomes;
there is no rejection sampling to guarantee a successful answer or coupon winner.

Task/store scope is sampled before products and stock. Retailer avoidance selects
from the planned stable retailer IDs without looking at offers. Account task targets
select existing historical orders without conditioning on sign-in/cancellability.
A coupon disclosure is bound after accounts exist so its claimed code is factual;
it does not condition generation of those accounts or their prices.

## Inventory and price semantics

`branch_shipping.delivery_sources` quotes warehouse and each branch independently.
Each source must hold the whole requested quantity and serve the destination.
Disabled branch shipping is explicit even when stock exists there. Stock is never
summed between branches and shipping does not simulate transfers between origins.

Standard delivery chooses the fastest eligible origin, then lowest total, then
stable source ID. Source choice is a merchant dispatch policy independent of the
task objective. Freight distance/crossings determine cost and transit; a same-city
branch adds one transit day plus its handling time. The quote exposes its origin,
stock and all alternatives. A warehouse stockout can therefore still permit online
orders. Conversely local pickup may be possible when no online source is eligible.
Pickup stock-transfer semantics remain distinct. Newly sampled `nearest_pickup`
tasks require actual local stock (`requires_stock_transfer=False`).

`AccountSession.quote(base_quote, coupon_code)` checks the signed-in retailer,
expiry, redemption, family and minimum subtotal. Discount applies to items only;
fixed discounts cap at subtotal, percentages round half-up to integer öre. No
stacking, shipping discount, coupon consumption or purchase occurs during quoting.
The reference adapter uses `best_quote`; public UI requires explicit code entry.
Current connected reference supports single-line tasks, not geographic baskets.

## Requests, memories and accounts

`retailer_preferences`: `none`, `auto`, `avoid`, `request`, `memory`, `override`.
Constraints use stable retailer IDs; prose uses generated store names. Different
retailer exclusions accumulate. Explicit permission overrides that retailer's past
avoidance memory. These requirements are never hidden SKU-blocking specifications.

`coupon_disclosure`: `none`, `auto`, `request`, `memory`. No cue is the harder
variant; the account UI still contains the available codes. Easier variants mention
an existing active unredeemed coupon and suggest checking whether it helps. A cue
is not a requirement to use the code. Empty eligible cue pools remain empty. Hard
and easy variants of the same world have the same optimum. A recommended discounted
price requires the code alongside the SKU retailer link for reproducibility.

`accounts.generate_accounts` exports `shopping-accounts-v1`, bound to the exact
world hash and a fixed simulation date. Historical orders reference existing
retailer/SKU pairs, with coherent status dates and tracking events. They do not
reserve today's stock. Signed-out accounts expose no orders/coupons; credentials
and login transitions are not simulated.

`AccountSession` deep-copies initial data. Only processing orders can be cancelled;
shipped/delivered attempts fail and repeated cancellation is idempotent. Cancellation
changes only the targeted historical order and journals all attempts. It does not
claim a refund or change current inventory. Distinct sessions isolate episodes.

## Task binding and validation

`account_tasks.sample_account_task(world, accounts, operation='track'|'cancel',
seed=...)` returns a private task and safe `public` projection. Optional retailer/order
IDs bind a specific existing target. `policy_input(task,start_url=...)` exports only
public text, memories and context. `reference_account_task` computes expected state
and structured status. `check_account_task` verifies these and rejects unrelated
account changes; it does not evaluate explanatory prose.

At runtime, use `rt.account_pages.session` and `rt.snapshot()['accounts']`. Historical
orders in journal-v2 are initial data, not new purchases. Research tasks use changed
`commerce_mutations` as effects, not a zero-orders assertion. Cancellation tasks
start from a fresh session for each independent case. Public cards never contain
reference statuses, coupon inventories, resolved requirements or oracle winners.

Pins include source hashes for `accounts.py` and `branch_shipping.py`, the complete
initial account export, scenario, review evidence, coverage and advertising. Episode
binding verifies account provenance; episode identity includes geography and account
state so distinct account worlds cannot silently share the same task identity.

Fixed first sample: `.local/coordination/location-accounts/pin-v1/`.
It retains all18 historical orders as36 tracking/cancellation cases, alongside hard
and coupon-memory shopping variants. Reproducer and binding scripts are beside the
pin. Existing published worlds and evaluation inputs are not overwritten.
