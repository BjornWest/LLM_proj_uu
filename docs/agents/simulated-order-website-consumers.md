# Minimal fresh generated-world ordering

Source preparation implements Bjorn's default-capability decision. Every retailer
in fresh accepted-catalog and fresh footwear generation should permit simulated
checkout completion; existing frozen releases keep their original implementation.
This is not restricted to ordering tasks. Individual tasks still authorize and
grade their relevant actions and side effects.

Website owns `simulated_order_store.py`, the copied presentation/quote projection
in `simulated_order_presentation.py`, its presentation and transport JavaScript,
and the fresh Runtime seam, publication and execution consumers. Product owns `simulated_order_record.py`, native
ordering tasks and native grading. Evaluation owns concrete natural requests,
release acceptance and promotion. No new model episode follows from this work.

The private `OrderStore` delegates record construction to
`simulated_order_record.make(baskets, retailer_id, submission, order_id=...)`.
It commits the detached receipt, event and idempotency binding under one lock.
Identical concurrent retries return one record; changed payloads under the same
retailer/key reject. Different completed checkouts remain separate. Failed native
validation creates no receipt. `snapshot()` returns detached complete private
orders/events, world/policy/domain/runtime identity and optional trusted episode
binding; it is never a public endpoint. `bind_episode(binding)` is trusted capture
setup, not a proof of authority. Its actual source/capture protocol must receive
native acceptance before grading; a dictionary alone cannot confer it.

The copied generated renderer replaces only the purchase form, generated
submission branch and simulated confirmation rendering. The original standalone
draft source is untouched. Generated checkout asks for shopping-terms consent and
uses simulated payment without card numbers, expiry or security codes. Confirmation
shows the actual recorded items/quantities, submitted address including unit,
delivery notes, selected carrier/type/location and integer-minor totals. Browser
state holds only the public confirmation; it is not the native ledger.

The copied native basket quote binding establishes complete explicit selections
before displaying the order-capable quote. An ordinary default/reset preview is
requotted with those exact choices; changed service/quote/total rejects the
transition. The copied quote scheduler compares the settled request identity,
including its explicit selection, so a valid default/reset response redraws
without accepting a response for a subsequently edited cart or address.
Completion submits the cached native request/quote/option IDs and
minor-unit total, never renderer-computed pricing. Native record construction
requotes and rejects stale/defaulted selections. Terms are validated by both the
ordinary form and native submission maker.

A submission key is persisted in the existing browser state before dispatch and
reused for the same full submission after a failed response or reload. Card form
fields never enter the request. The cart clears only after a successful receipt;
asynchronous completion removes only its original line identities and quantities,
preserving subsequent edits. Multiple completed receipts remain inspectable by
trusted grading regardless of browser cart state. The shopper's “My orders” page
links their public simulated confirmations; the private ledger is never exposed.

`simulated_order_runtime.py` prepares store initialization, strict public receipt
projection and the submission callback. The exact default Runtime delta is
prepared for both the shared source and frozen cdb28444 baseline, with inverse
checks. The shared-source delta is applied as source preparation; the frozen
baseline and all accepted releases are unchanged. Public confirmation is validated before private
commit so an unrenderable record cannot become a hidden successful order.

`simulated_order_capture.py` prepares private before/after ledger callbacks with
the agreed episode/task/source/capture binding. Its task wrapper preloads items
through ordinary controls before the initial policy observation. Snapshot and
terminal artifacts are exclusive and hashed; source/store/trace identity, phase,
terminal summary and retained artifact bytes are checked before sealing. Every
seal freezes the store under its commit lock and compares the complete actual
ledger with the retained terminal snapshot after Runtime cleanup. A late commit
makes sealing a system failure, retaining both the original capture and actual
ledger; it cannot be omitted or repaired. No commit or episode rebind is accepted
after sealing.
Every
prepared capsule has `effect_journal: null`. Trusted lifecycle callbacks and an
independently accepted complete new source union are still required; authored
offline capture fixtures cannot certify origin or full-run effects.

`simulated_order_publication.prepare_saved` freezes one explicit saved-world
instance with Evaluation's request and memories verbatim. It makes the native
task/reference using the unchanged basket oracle and quantity domain, retaining
all admitted delivery methods, all minimum-fee ties and natural no-match. It
draws no world and changes no stock, prices, source policy, surrounding coverage
or sampled composition. The internal constructor starts at the retailer home;
the task wrapper actually preloads the exact offer/quantity through ordinary
controls and starts policy at its cart. The first consumer accepts no setup
coupon; non-null coupons reject explicitly, with ordinary coupon setup pending.
Unavailable preloaded items fail ordinary setup rather than being inserted into
storage. Reference no-match is retained, never repaired by choosing another item.

`simulated_order_execution.run` binds `AutomaticGrading` before policy dispatch,
including exact task/reference/source files and the displayed goal. It reserves
capture/grading runner options, uses a finite caller-owned lease, and performs
zero answer-extraction requests. Native state grading runs once after policy and
Runtime cleanup, with actual private baseline/terminal ledger captures. Post-policy
quota exhaustion cannot suppress native grading. Canonical external finalization
and the final caller-supplied HTTP viewer projection must succeed before publishing
execution completion. Setup, cleanup, task/context drift or missing projection
are system failures. Null effect journals remain inconclusive in the unchanged
native grader; they never become an empty-event success.

Fresh ordering publication explicitly retains the released subscription quota
guard and its `scripts/product_width_watch.py` dependency. Default execution checks
and binds those same exact sources before using the guard. Frozen-import controls
exercise the authored quota snapshot only, without account RPC, watch entrypoints
or provider calls.

Offline authored checks cover exact renderer/quote inverses, retained surrounding
assets, boolean consent, escaping, unit/notes/totals display, failed submissions,
concurrent clicks, modified carts, exact native response identities and stale
responses. Store checks use explicit native-maker stand-ins and do not prove quote
correctness. Seven additional authored offline lifecycle controls use the real
automatic-grading gate with explicit mock native grading and viewer dependencies;
they verify once-only grading after both cleanups, final-call quota exhaustion,
task-context drift, caller override rejection and absent viewer projection. They
do not establish native receipt correctness or deployed HTTP/browser acceptance.
No browser, provider or genuine world draw has run for this feature.

The first Git candidate `e5a74b62` is blocked by independent review: its default
quote redraw, quota dependency closure and orders-list integration were incomplete.
An additive correction is being prepared; the earlier passing isolated controls
are preserved and do not establish that these composed paths worked. Composed
caller/binding tests now cover initial/reset delivery choices, stale replies,
post-settlement edits, ordinary boolean bindings and public order-list routing.
Those new controls still require the coordinated correction validation window.

Product's reviewed native callable is released at commits `3ccd686b` and
`ff2f27e5`. Website source binding is prepared; native producers and ordinary
variant selectors remain unchanged.

Remaining implementation/acceptance: independently reviewed exact Git closure
and coordinated integration, ordinary fixed-coupon setup, real native quote/commit checks,
authoritative complete before/after ledger capture under the new source union,
actual checkout/confirmation/automatic
grade/HTTP viewer smoke and Evaluation promotion. Old Address/read-only source
union approval does not cover these new ordering endpoints or store.
