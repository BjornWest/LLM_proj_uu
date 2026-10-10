# Cart task instance permutations

`task_instance_cart.CartAdapter` implements the shared saved-world
`task_instances.inspect`, `prepare`, and `run` adapter protocol for cart preparation
and existing-cart delivery details. These are state contracts: neither the
answer text nor an answer extractor supplies cart or address state.

For `catalog_cart`, declare `requirements`, `objective`, and `initial_storage`.
The supported objective is `minimum_item_subtotal_minor`: minimize the combined
listed item prices of the additions. This concretizes “cheapest eligible shops”
for cart-only preparation. Shipping fees, delivery speed, delivery selection,
coupons, and payable checkout totals are outside this objective. Quantities count
retail sale units. Existing units remain and do not count as additions.
The exact bounded allocation accounts for shared dispatch stock, overlapping
requirements, existing stock reservations, and final retailer cart line limits.
Search exhaustion stays inconclusive.

For `checkout_details`, declare `scope: existing_cart_only`, `delivery_note`, and
`initial_storage`, optionally `delivery_selection_scope`. The task prepares the
nonempty existing cart without additions. Every retailer containing existing units
must persist the generated home address, including its unit, a valid saved form,
the locally remembered address, and the verbatim note. Other retailer address/note
fields, coupons, order records, cart quantities, non-target saved-form validation
status, legacy delivery choices and split state remain unchanged.

`delivery_selection_scope: valid_home_service` permits any centrally validated
native home service at target retailers. It uses the unchanged bound basket quote
API and requires the captured selection to equal the quote's selected service;
invalid selections that the API resets are rejected. A captured absent selection
may use its native default. Every shipment must deliver home. No service price or
speed ranking applies. This scope matches the natural B19 home-delivery request.

The default scope `preserve` retains strict selection preservation and allows an
initial absent selection to materialize only the renderer's published-preview
default. It rejects baselines with explicit target selections or target addresses
already available for startup quoting, because the ordinary address-save/startup
renderer invalidates or materializes their selections. Non-target selections stay
unchanged in both scopes. Nonempty legacy target delivery choices and malformed
address objects are rejected in both scopes because the native address save
cannot preserve them. Missing native quote context is inconclusive. Terminal
capture cannot establish who selected a service or whole-run effect authority.
Home address memories come from the saved world; the adapter never invents them.

`initial_storage` names an original `before_policy` browser capture with an exact
SHA256. Preparation authenticates and copies its original raw bytes, validates all
retailer storage identities against the saved world/domain, and requires a
nonempty cart. The original path becomes provenance only; native reference and
runtime never reopen it. Current restoration supports cookie-free retailer
draft-state captures; other cookies or storage keys are rejected. Setup restores the saved retailer draft-state strings before
ordinary renderer startup. Subsequent navigation never restores over policy
changes. The policy boundary captures the actual browser state again, and native
grading verifies initial quantities against the separately bound saved baseline.
Failed initial restoration and stale task/reference/baseline bindings are explicit
inconclusive setup errors, projected with a technical error and returned as a
system failure rather than a task verdict.

The adapter never changes the world, manufacturer facts, surrounding pages,
shipping plan, checkout limits, or site controls. Replaced task/reference records
are archived by the shared publisher under the parent manifest digest. The
native cart task, strict raw-state decoder, quantity allocator, physical capacity
checks, captured-task hooks, and home-address matcher are reused.

The runner attaches `AutomaticGrading` before dispatch. Policy and Runtime close
before once-only capsule sealing and grading. The canonical evaluation, native
state report, shared viewer projection, and bound scoped viewer sidecar must all
exist before the result is `graded_and_projected`; an actual HTTP viewer callback
is required. Missing capture/binding/quote evidence projects null task completion with its
infrastructure reason, and publishes native/canonical/scoped HTTP evidence
before returning system failure where appropriate. A clean turn or context limit
with valid setup and actual captures remains a task failure. Provider, runner and
cleanup errors project null with their actual infrastructure reason. Missing work/final
output is a different control from a missing browser capture. No answer extraction, provider
retry, world draw, or obsolete whole-run authority helper is introduced.

Canonical task completion reports the captured state outcome. Authorization and
unauthorized-effect fields remain null; whole-run effects remain unknown. A true
state outcome does not certify purchase/account safety. The scoped viewer uses
its established `structured_claims_correct` field to carry the native state
outcome, with explicit state-scope limitations.

The remaining-suite acceptance packet is external under
`.local/coordination/task-instance-remaining9-20261010/cart-checkout/`. It contains
natural B17/B19 configs, exact saved baseline and recipe bindings, derivative
recipes, bounded-job receipts, original failures, and scripted controls. Both
B17 and B19 final-source readiness require independent review and actual browser
acceptance of the current frozen recipes and public request bindings. Final
controls cover correct state, known wrong state, and valid captures with no
requested work or final output; missing capture remains a separate infrastructure
diagnostic. The additive final receipt records completed controls with their
exact frozen source and HTTP bindings; historical controls do not validate a
changed branch. Scripted controls are tagged `scripted`; they
establish integration readiness, not model performance or prod promotion.
