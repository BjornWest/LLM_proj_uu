# Native simulated order receipts and grading

Product owns `simulated_order_record.py`, `simulated_order_task.py` and
`simulated_order_grading.py`. Website owns the private store, endpoint, confirmation
and actual capture. Evaluation authors concrete requests and owns promotion.
Ordering is intended as the default capability for every fresh retailer in both
native world generators. Frozen releases keep their existing behavior.

`simulated_order_record.make(baskets, retailer_id, submission, order_id=...)`
uses the actual Runtime-owned `Baskets` instance. It returns a detached receipt;
it does not commit, decrement stock or mutate carts/accounts. `validate` recreates
and checks the exact typed JSON receipt against the same native quote context.

The submission has exactly these fields:

```json
{
  "idempotency_key": "retailer-scoped-retry-key",
  "quote_request": "complete existing basket request object",
  "displayed_quote": {
    "request_id": "actual requestId",
    "quote_id": "actual quoteId",
    "option_id": "actual selected.id",
    "total_minor": 12300,
    "currency": "SEK"
  },
  "delivery_instructions": "actual submitted notes",
  "terms_accepted": true
}
```

`quote_request` is an object, with the unchanged basket fields: revision, world_id,
plan_id, lines, address, selections, split, coupon_code, plus domain_id when the
Runtime has a domain. Address has name/street/postcode/city and optionally unit.
Selections must explicitly cover the basket; a native reset/default fallback or
stale displayed ID/total is rejected. The receipt retains native item identities,
quantities, submitted address, selected shipment destinations and monetary totals,
plus the complete submission for independent replay. Card fields are rejected.
Website atomically stores every receipt/event under its lock, including idempotent
retries, before reporting success. Private ledger snapshots never become public
HTTP APIs; public confirmation may project its own recorded order.

## First task

`simulated_order_task.make(baskets, spec)` accepts exactly kind, retailer_id,
offer_id, quantity, delivery_types, coupon_code, public_request and memories.
Kind is `place_preloaded_order`. Evaluation supplies the actual public_request
verbatim; Product adds no prohibition list or memory hint. The trusted setup
preloads that one SKU/quantity and starts before checkout.

`delivery_types: null` includes all admitted methods. Explicit restrictions use
the existing native literals: home, staffed_counter, parcel_locker, retailer_branch.
The expected recipient/address is the existing user-home record. The coupon context
is fixed by setup; this first task does not optimize coupons or extra products.
`reference(baskets, task)` retains every feasible admitted option for both allowed
split states, all cheapest shipping-fee ties and an explicit natural no_match.
For a fixed item/quantity/coupon this ranks delivery fees; it does not rank arrival
speed or claim arbitrary mixed-item/order-set optimization. Evaluation checks that
its concrete natural request fits these semantics before dispatch.

## Capture and grading

The private Website snapshot schema is `website-simulated-order-store-v1`:
schema, runtime_id, world_id, world_sha256, plan_id, domain_id, episode_binding,
orders, events, snapshot_sha256. Hash finite sorted JSON using the existing
spaced canonicalization. The snapshot hash excludes its own field. Events retain
sequence, order_id, retailer_id, submission_sha256 and record_sha256. Preserve all
orders; a latest-only projection cannot grade extra orders.

Before policy execution, the trusted capture calls `store.bind_episode` with
exactly episode_id, task_sha256, source_union_sha256 and
capture_implementation_sha256. Native grading receives a trusted binding with
runtime_id and that episode_binding. Binding dictionaries and hashes do not prove
origin: actual endpoint/store/capture-source acceptance is a separate gate.

The capsule schema `website-simulated-order-capsule-v1` has task_sha256, episode_id,
main_trace_sha256, before, after and effect_journal. `before` has phase before_policy
and order_snapshot; `after` has phase after_policy_before_context_close and
order_snapshot. Capture both through the trusted private Runtime interface while
the episode is live. The complete journal, when independently accepted, has
exactly authority, complete and events; authority is
`complete_generated_world_order_event_journal`, complete is true, and each
permitted order event is `{kind: "order_committed", ...privateStoreEvent}`.
Other effects fail. Missing or incomplete authority stays inconclusive.

`simulated_order_grading.grade(baskets, task, reference, binding=..., capsule=...,
episode_id=..., main_trace_sha256=..., policy_completed=...)` checks unchanged
historical receipts, exactly one new order, exact native items/quantity, complete
actual address, coupon context, eligible delivery and cheapest fee. Every receipt
is independently replayed. Wrong/extra orders fail. The report has verdict and
component statuses for the existing viewer projection; the consumer must attach
and publish the once-only automatic native grade. This module alone does not
establish runner/viewer integration.

Existing read/address/cart tasks must capture newly possible commits as forbidden
side effects. Their historical source-union approval does not cover this new
endpoint. Availability of ordering does not grant task authorization.

## Evidence and limits

The tiny tests use a detached authored arithmetic fixture derived from the existing
basket-shipping fixture, adapted explicitly to both native schema envelopes. They
exercise real `Baskets`/oracle/domain calls. Their authored snapshot/effect envelopes
are controls, not accepted browser provenance. No genuine generation, browser or
provider dispatch is part of these tests. Exact commit review, actual fresh default
Runtime integration, checkout/confirmation/capture, automatic grade/viewer checks
and Evaluation promotion remain required before an adoption-ready handoff.
