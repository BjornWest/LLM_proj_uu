# Connected-world conformance suite

Purpose: verify that publicly rendered pages agree with a supplied generated world,
not merely that servers return HTTP 200. No model calls or commerce mutations.
Expected products/options/offers come from the canonical scenario; delivery expectations
come from Product's geographic quote implementation. The checker imports no page
renderer. This checks renderer/adapter conformance, not independent correctness of
Product's underlying quote rules (which need their own tests).

```bash
.venv/bin/python -m scripts.verify_connected_world_conformance \
  --scenario .local/coordination/product-review-evidence/example-v4/scenario.private.json \
  --runtime .local/connected-shopping/preview-v7-natural-reviews \
  --output .local/connected-shopping/conformance-NEW --workers 4

.venv/bin/python -m pytest environments/connected_shopping/test_conformance.py -q
```

The supplied scenario may differ in task wording; its canonical world, geography and
supplied review corpus must match the publication. Snapshot metadata and relevant
geographic source revisions are checked before page requests. Only local published
origins are accepted. Four bounded threads perform independent read-only HTTP checks;
output directories are exclusive and historical reports are never overwritten.

## Current coverage, generated from input rather than hand-authored task IDs

- Every offered SKU at every retailer: exact selected identity, product name, complete
  attribute table, item price, warehouse stock, and selected option-control values.
- Every offered variant selected through a product-group entry URL with explicit
  option parameters. Includes direct deep links and separate product-details pages.
- Default delivery quote for every offer: eligibility, reason codes, item subtotal,
  shipping, complete total and arrival/ready estimate.
- Quantity two for one deterministic offer per retailer; pickup and inspection for
  that offer at every generated branch. Selection is independent of task/eligibility.
- One two-product comparison per covered family/site: exact column identity, attributes,
  units and lowest advertised prices restricted to that comparator's retailer coverage.
  Footwear uses model attributes and explicit advertised model prices; other families
  use exact SKUs. One omitted-product route per comparator must return 404.
- Every supplied Reader Panel report across all its article pages: original body and exact report/subject identity,
  canonical reviewer identity, source permalink, and no explicit experience-kind badges.

Results contain per-case names, URLs, status, response hashes and specific discrepancies.
Failed responses are retained as local HTML. Reports bind the scenario, manifest,
published source map and checker source by hash. They do not modify graders or labels.

## Layering and limits

This HTTP layer scales across generated offers and products without a new browser
session per task. The complementary six-family native review suite verifies real
navigation, consent controls, source anchors and full scoped AX reads. Existing native
comparison and retailer suites cover browser interactions; HTTP option selection is
not proof that a user can operate every control through the browser.

This is a first conformance layer, not an exhaustive world certification. It does not
yet crawl every link/search/filter/pagination state, test every invalid/unlisted option
combination, every quantity/branch/offer cross-product, merchant-rating table, geography
planner page or consent preference. Comparison matrices use bounded pairs, not every
pair. Purchase/cart flows are not supported by this connected research runtime.
Performance/context difficulty and teacher success need separate model evaluation.

## First result and checker sensitivity

Current frozen natural-review world: 410 checks pass (109 product pages, 109 variant
selections, 109 delivery quotes, 44 fulfilment boundaries, 14 matrices, four omitted
routes, 21 panel pages covering 252 reports). Final source evidence:
`.local/connected-shopping/world-conformance-v2/report.json`. Earlier v1 retained.

Sixteen tests exercise the checker, including deliberate wrong SKU, price, stock,
attribute, selected option, eligibility, shipping/total/subtotal, arrival, reason,
review attribution, member ID, source fragment and generated-label leakage. Each
correct control passes first, then the altered response must fail. Existing-output
preservation is checked too. These demonstrate detection of those faults, not complete
coverage of all possible page bugs.
