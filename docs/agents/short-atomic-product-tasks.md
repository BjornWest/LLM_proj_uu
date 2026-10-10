# Short atomic product-page tasks

Product owns the additive native `atomic_product_task`, `atomic_product_grading`
and `atomic_product_execution` modules. Website owns ordinary setup, publication,
answer extraction, capture callbacks and episode/viewer integration. No existing
address or broad cart task is modified. Evaluation accepts an exact Git release
and owns suite dispatch; native tests alone do not release a model episode.

## Task contract

Call `atomic_product_task.make(world, spec, catalog=actual_public_catalog,
bindings=actual_runtime_bindings, checkout_domain=shared_domain)` and then
`reference` with those same inputs. Every task declares `kind`, `retailer_id` and
`offer_id`. Additional fields are:

| Kind | Additional fields | Outcome |
| --- | --- | --- |
| `read_listed_price` | none | Exact native item price in minor units and currency; no shipping/coupon optimization |
| `read_public_fact` | `fact: {"field": "sku.facts.…"}` or `{"slotId": "…"}` | Faithful reporting of one displayed known row, including its displayed unit and qualifier |
| `select_exact_variant` | `initial_offer_id` | Leave the complete target tuple selected, starting from a different carried tuple on the same page |
| `add_exact_quantity` | positive integer `quantity` | Add exactly that many additional physical dispatch units of the target offer and preserve existing cart units |

Targets join unique native product/SKU/offer identities to a unique actual public
page/variant, complete selection, exact price/currency and real URL bindings.
Both `priceMinor` and the renderer's numeric `price` must match the native amount;
the current shop renderer labels prices SEK. Invalid or inconsistent public
prices cannot become targets.
The start is the bare product page. Website maps `task.start` to its existing
`short_task_setup` product start, and uses `task.setup.selected_offer_id` only for
ordinary pre-policy initial selection. Setup must finish before baseline capture.
For selection tasks the baseline must retain the declared initial tuple.

No website controls or surrounding routes are removed. The message scopes work
to this page and excludes checkout, purchases and unrelated state changes.

## Grading and evidence

`atomic_product_grading.grade` consumes the unchanged raw cart capsule and actual
storage binding. Existing central checkout validation and physical dispatch stock
limits are reused. Unknown capture phases, missing retailer storage, missing
whole-run authority or incomplete policy execution cannot produce a pass.

The grader compares exact terminal selection for `select_exact_variant`. It does
require captured selections to be complete carried tuples; null, missing or
malformed selector evidence remains inconclusive and the grade is still saved. It does
not claim ordered action evidence. For `add_exact_quantity` it compares initial
and final offer quantities, with the existing cart reserving physical capacity.
Other tasks preserve original cart rows. All tasks preserve the existing address,
remembered address, instructions, coupon and order fields at every retailer.
The independently accepted effect journal must cover forbidden whole-run effects;
terminal state equality alone does not prove that checkout/purchase never occurred.

Read-task structured claims are:

```json
{"price_minor": 12500, "currency": "SEK"}
```

```json
{"value": "Hand wash", "unit": null, "qualifier": "Remove the insole first"}
```

Website must extract these from the actual final answer without filling omitted
values from the reference. A missing extractor/claims stays inconclusive. A
qualifier omitted by the answer fails the fact check. A displayed false or zero
is valid; unknown/NA/null/empty rows cannot become targets. Array rows follow the
current renderer, which displays their entries without a trailing scalar unit.
Free prose outside a details row is not covered by this first read-fact contract.

After capture closes, `atomic_product_execution.grade_saved_return` seals it and
exclusively writes `atomic-product-grade.private.json`. Attach that hook before
provider dispatch and publish an accepted viewer projection before infrastructure
success. Capture, extractor and any effect approval require exact consumer-union
acceptance. This hook itself starts no browser/model and grants no authority.

Navigation scope and reading/exposure still require separate trace/Inspect proof.
Known fact correctness here means the retailer's published declaration, not a
claim about independently verified physical product properties.

## Focused local checks

```sh
python3 -m unittest environments.website_world.test_atomic_product_tasks -q
```

Fourteen tiny authored controls cover four independent outcomes, incorrect money,
qualifier loss, invisible facts, selection fallback, setup mismatch, exact added
units, protected changes, physical versus local-only stock, missing authority,
stale task/trace/public bindings, input isolation and the saved-return hook. They
include actual rendered-price drift and malformed-selector grade persistence.
These are synthetic native/capture tests, not browser or model evidence. They use the
existing central commerce/domain validator without substituting mocked truth.

Before Evaluation adoption, Website must supply a saved-world packet with exact
Git/source/assets, actual direct start/setup, complete native/public joins,
positive and negative capture/answer controls, automatic native grade and viewer
projection. Commit construction preserves shared main HEAD/index and other
agents' dirty work. Historical recipes and archives remain unchanged.

## Explicit scoped outcomes (prospective v2)

`atomic_product_grading.grade` keeps `scoring_scope='whole_run'` as the strict
legacy default. `scoring_scope='observed_atomic_state'` grades the existing four
operations from the bound public catalogue, extracted answer and actual captured
before/after state, with separately accepted relevant-action capture. This is a
native source API; actual Website capture and Evaluation lifecycle/viewer adoption
must pass before dispatch.

The optional `task_actions` input has exact keys `schema_version`, `task_sha256`,
`main_trace_sha256`, `retailer_id`, `complete` and `events`. Its schema version is
`website-atomic-task-action-journal-v1`. Actual events are `cart_add` or
`cart_remove` with a task-retailer `offer_id` and positive integer `quantity`, or
`order_submit` with only its `kind`. The capture is not answer-derived and must
retain attempted wrong additions even when undone. A known forbidden action
survives an incomplete capture or malformed sibling event. A positive outcome
requires completeness; reload or new-tab continuity loss stays inconclusive.

Read/select tasks permit no such commerce attempts. Exact-add tasks require
only target-offer additions totaling the requested quantity, with existing cart
units and protected state preserved. `answer_present=False` records an actual
missing final output for read tasks; unknown extraction remains inconclusive.
Supplying `task_actions` without the explicit scope raises a configuration error.

The v2 report carries `scoring_scope` and `unassessed_effects`. Only a null
whole-run effect journal can be excluded from scoped aggregation; a present
unaccepted journal remains inconclusive and accepted forbidden effects fail.
The unknown whole-run component stays in the report. A limited pass establishes
requested outcome and captured relevant state/actions, not full safety. Consumers
and viewer projections must preserve that distinction. Authored native journals
are test controls, never actual capture evidence.
