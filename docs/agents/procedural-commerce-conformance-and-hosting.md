# Procedural commerce: composable testing and efficient hosting

Design decision, 2026-09-23. This specifies the next foundation; it does not claim
a multi-session deployment or a complete action suite is implemented.

## Keep three boundaries explicit

1. **World/product semantics:** canonical identities, typed attributes, applicable
   options, valid combinations, selected configuration, price, stock and shipping.
   Logic is shared and independent of page structure. A renderer cannot decide
   that a shoe size or laptop configuration means a different SKU.
2. **Public presentation contract:** data permitted on this page, selected values,
   allowed commands and their required parameters, validation errors and factual
   feedback. No expected answer, task constraints or oracle state. Publish only
   facts intended to be available at this stage; putting hidden facts in a JSON
   payload still makes them accessible even if the visible page conceals them.
3. **Design implementation:** native controls, hierarchy, navigation, disclosures,
   content order and interaction flow. Designs share semantics, not necessarily
   component trees. Dropdowns/radios/separate variant pages can implement the same
   selection contract with different AX and discovery behavior.

Product extensions need typed capability descriptors, not arbitrary HTML inserted
into a template. Examples: enumerated size/color, compatible configuration choices,
nonselectable facts, and required-but-unselected options. Include stable option
IDs separate from display text. Selecting size/color resolves a canonical
sellable variant; quote/cart/receipt must retain it. Unavailable combinations,
selection changes and back/reload preservation need explicit semantics. Do not
hardcode every category into every design or let omitted controls select a hidden
default. A design declares supported capability versions; unsupported valid worlds
are reported as unsupported, not silently simplified or resampled for success.

The original implementation has public projections, shared commerce logic and separate
designs with generic attributes/traits. An additive [size/colour control prototype](procedural-commerce-product-controls.md) now binds authored option tuples to existing SKUs; it does not yet consume sampled shopping-intent tasks. The richer product-control contract
is proposed, to coordinate with the separate shopping-intent/product work when
implementation would overlap. No change to that other owner's schema is made here.

## A large suite of reusable checks, not a Cartesian task suite

| Layer | What it tests | Scaling unit |
| --- | --- | --- |
| Semantic unit/property tests | Price/stock/variant/authorization invariants, invalid commands, idempotent commits | Commerce mechanism or product capability |
| Content substitution | Long/short/missing optional text, Unicode, escaping, many attributes, stable form identity | Renderer family and boundary payload |
| Browser design contract | Reachable controls, labels/AX associations, native operations and intended discovery path | Design, page role and supported control realization |
| Interaction state machine | Search/filter/page, select/change, Add/edit/remove, navigation/reload, checkout/back/error/confirm | Shared action/state transition, with design-specific drivers |
| Composition smoke | Representative layout × product capability × checkout × behavior interactions | Small deterministic covering set plus high-risk cases |
| Generated-world sampling | Larger catalogs, unusual combinations and action sequences | Fixed reproducible seeds, bounded growing sample |

Every advertised page action must have an expected public effect and privileged
state assertion; navigation/read-only actions should also assert no unintended
commerce mutation. Inventory the actions, states and negative boundaries so a
new control without coverage is visible. Do not equate link count or a successful
HTTP response with action coverage. Test browser controls with real clicks/fills;
private APIs supply independent state assertions, never substitute for the action.
Test drivers may know each design's semantics; those hints are not policy inputs.

Useful shared invariants: content-only substitution preserves commands; equivalent
dropdown/radio choices produce equal cart state; design changes preserve quote
semantics; unavailable selection cannot commit; repeated confirmation cannot buy
twice; two sessions never share carts; back/reload cannot restore stale consent or
stale review authorization. Engine hand-fixture expectations must remain independent
of the implementation under test, rather than computing expected values through
the same function.

Use cheap parameterized tests broadly. Browser-test representative controls and
boundary cases. Cover pairs of independently composable factors, but explicitly
add known higher-order risks (e.g. unavailable variant + increment + back/reload).
Pairwise coverage is useful selection, not proof that all combinations work.
When a generated case fails, retain the seed and full initial evidence, reduce to
a small reproducer, and add the regression at the lowest layer owning the defect.
Do not replay every task after each wording change. Changed dependencies determine
which checks rerun; shared command/engine changes justify broader regressions.

Real browser acceptance must verify AX content/relationships, disclosure states,
operability and semantic effects. Avoid brittle whole-tree equality that bans
intentional diversity. Long content is also a browser hit-target/scrolling concern;
HTML checks alone cannot establish it. Product-specific information should appear
only where applicable. Generic facts and option groups must not unexpectedly
replace the site navigation, checkout flow or unrelated controls.

## Small implemented increment

`environments/procedural_commerce/test_content_substitution.py` adds 36 cheap
cases: three content stress payloads × three page roles × four configurations
(three families plus department contrast). It checks native form contracts,
escaping, required name/fact reachability, unique IDs and heading references.
Boutique facts are checked on its separate details route; landing pages are
allowed to feature collections rather than individual products.

These are HTML-level regression checks, not AX exposure or clickability evidence.
Existing browser suites separately cover checkout, cart interactions, shell
continuity and the recent matched AX comparison. The later [size/colour prototype](procedural-commerce-product-controls.md) adds typed option coverage;
complete action inventory and automatically selected composition coverage are not
yet implemented. The product-page incremental stock guard remains a known gap.

```bash
.venv/bin/python -m pytest --import-mode=importlib -q \
  environments/procedural_commerce/test_content_substitution.py \
  environments/procedural_commerce/test_department_variations.py
```

## Efficient serving target

Do not prebuild one website bundle, container or database per generated retailer.
Store a versioned world descriptor, immutable catalogs and design settings; render
requested pages lazily through a bounded application worker pool. Reuse assets and
templates, paginate catalogs and avoid materializing off-screen pages. Cache
immutable data by world/content/runtime version. Personalized/cart pages must be
session-scoped, never served from a shared public cache.

Maintain a small mutable episode state (cart, selections, orders and append-only
events) separate from the world. Share immutable world data only where it is truly
immutable; use a transaction/lock boundary for commands so concurrent requests do
not lose updates or double-commit. Avoid storing a full world copy per event.
Preserve enough versioned source/data and events for deterministic replay.

A routing gateway can map distinct site origins to the same service. Real origin
separation should remain: collapsing merchants onto paths of one origin changes
cookies, storage and navigation behavior. Bind each browser session to exactly one
episode, with explicit lifetime/reset and cross-session isolation tests. Public
pages never gain privileged grading access through the gateway.

For a Vercel-facing deployment, stateless page rendering can front durable session
state; process memory alone is insufficient across concurrent/serverless workers.
A browser-worker-hosted service is another deployment of the same contract.
Preview-only static exports remain an explicit reduced browsing mode. Task/manual/
Ask execution should use the same world, command and grading semantics, independent
of where rendering runs. This is a target architecture, not a claim of present
Vercel infrastructure or vendor limits.

Current Runtime uses one Python process with four HTTP listeners and one mutable
commerce session; it deep-copies the world and requires exactly three retailers.
It does not run four browser processes, but it is not yet pooled multi-episode
hosting. Its browser cost depends on the harness's session/tab strategy. Measure
server RSS, per-world and per-active-session memory, page/AX size, request latency,
browser RSS and storage growth separately before optimizing. Browser processes
may dominate, but that is a hypothesis to measure locally. Multi-user isolation
and safe expiry come before sharing this runtime across visitors.

Next steps: agree the product capability interface, inventory current actions,
add reusable browser conformance drivers, then extract multi-session serving after
those invariants are covered. No deployment or shared harness changes in this note.
