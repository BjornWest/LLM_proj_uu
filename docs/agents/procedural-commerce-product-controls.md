# Product controls v1: size × colour

Implemented local development contract, 2026-09-23. Product and curation owners
agreed the boundary in `.local/coordination/product-controls/product-decision.md`.
No changes to `shopping_intent/`, shared harness, deployment or model routing.
No model calls. This binds authored product data to commerce pages; it does not
implement the future product sampler or integrate generated shopping-intent tasks.

## Identity and semantics

A **model group** has named selection axes and an explicit map from option tuples
to canonical sellable SKUs. Existing commerce `product_id` identifies that SKU;
`offer_id` identifies a retailer's offer for it. Price and inventory stay in the
existing offer/engine, not in the control renderer. Cart quantity counts sellable
units and remains distinct from selectable pack size or other future axes.

Initial agreed fields:

- `size_eu`: canonical number in EU units; stable option IDs are distinct from
  labels (e.g. `eu475`, `EU 47.5`, `47.5`). No automatic US/UK conversion.
- `colour`: canonical string, distinct from option ID and display label.

Both axes must resolve together. The same size may exist in one colour but not
another. Missing tuple, incomplete choice and valid-but-out-of-stock SKU are
separate states. Changing one axis keeps the other; it never silently substitutes
another value. The current group descriptor represents a fixed canonical catalog;
stock is read freshly from the session.

A page needing a concrete colour is **not** evidence that the user has a colour
preference. Unconstrained colour permits any colour in a future outcome evaluator.
The shopping-intent owner may withhold a blocking fit fact such as size pending a
specific question; that private intent is never rendered as product data. The
current commerce evaluator still grades an explicit canonical SKU: broad/family
requests and clarification are not integrated by this change.

## Contract shape

`Runtime(..., product_groups=[...], product_control_styles={...})` accepts:

```json
{
  "schema_version": "commerce-product-controls-v1",
  "group_id": "solvik-stride",
  "family": "footwear",
  "name": "Solvik Stride trainers",
  "axes": [
    {"field": "size_eu", "label": "EU shoe size", "value_type": "number", "unit": "EU",
     "options": [{"id": "eu475", "label": "EU 47.5", "value": 47.5}]},
    {"field": "colour", "label": "Colour", "value_type": "string", "unit": null,
     "options": [{"id": "black", "label": "Black", "value": "black"}]}
  ],
  "variants": [
    {"product_id": "shoe-475-black", "selection": {"size_eu": "eu475", "colour": "black"}}
  ]
}
```

Each listed SKU must already exist in the supplied world and its attributes must
match the canonical values. Unknown schema fields, duplicate tuples/SKUs/option
values and malformed values fail before serving. Group data is separate from the
world argument in this initial bridge; keep **both** with version/source hashes.
The renderer receives only public group data and allowed options, never task or
oracle constraints. Raw HTML is not an accepted option-value mechanism.

Per-retailer styles are independent of the base design:

```python
product_control_styles = {
    "nordhem": {"size_eu": "select", "colour": "radio"},
    "vardagslagret": {"size_eu": "radio", "colour": "select"},
}
```

Omitted styles default to select. All three AX retailer families support these
controls; legacy-catalog explicitly rejects this optional product-group mode.
The renderer places controls inside its own buying area, retaining the surrounding
page, fact-discovery convention and separately configured checkout. No CSS colour
swatch is the sole way to identify an option: labels and checked/selected state
are native AX data. Choosing controls does not change their canonical meanings.

## Native behavior and safety boundaries

1. A direct SKU URL starts with that SKU's size and colour selected.
2. **Update selection** performs a read-only native GET, resolving both controls
   and showing the actual SKU, price, facts and stock. Selection lives in the URL;
   reload preserves it. This first realization uses an explicit button, not JS
   auto-refresh. Other cart/shipping fields revert to product-page defaults on
   this refresh; no cart is edited by it.
3. Missing/incomplete combinations have no Add control or old-SKU quote link.
   Sold-out combinations retain their true SKU/price but cannot be added.
4. If options changed and Add is pressed without Update, the server refreshes the
   proposed selection and asks for review. It does not add the previous hidden
   offer, silently buy at the new price or change the existing cart.
5. Add includes both selection IDs. The server verifies the tuple against the
   submitted offer's SKU, rejects unsupported values and checks current stock
   under the same lock as the cart mutation. Repeated increment cannot exceed
   stock **in this product-group mode**. Older generic pages retain their existing
   draft-stock behavior; this is not a global repair claim.
6. Cart, checkout, receipt and stock deduction use the original engine identity.
   Current single-line-per-retailer cart restriction remains: remove a different
   SKU before adding another. Browsing another variant does not change the cart.

Raw command/private traces are still needed for diagnosis. Read-only variant GETs
and pre-engine rejections are not commerce mutations in the engine event journal;
this change does not establish policy exposure or infer intent from page requests.

## Authored fixture and tests

`environments/procedural_commerce/product_fixture.py` adds one fictional shoe model
alongside the generic products:

| Variant | Price before shipping | Initial stock per retailer |
| --- | --- | --- |
| EU 42, black | 890 SEK | 3 |
| EU 42, blue | 940 SEK | 0 |
| EU 47.5, black | 990 SEK | 2 |
| EU 47.5, blue | No SKU | Not applicable |

Prices and inventory are development test values, not sampled realism. Generic
schematic images are retained; this is not visual colour/appearance grounding.
Every fixture SKU has an offer at all three retailers. A retailer-specific subset
of model variants is a future contract extension; do not present an unhandled
missing offer as a validated unavailable-selection path.

Validation:

- **149 offline tests passed** across commerce and its curation adapter, including
  10 new contract/HTTP cases and one adapter identity/provenance/grading case.
- **Six successful native browser cases:** three page designs × both size-select /
  colour-radio and size-radio / colour-select arrangements. The design cases also
  exercise accordion, express and wizard checkout respectively; this is not all
  possible checkout/layout/control combinations.
- Every case checks incomplete/unlisted/sold-out states, reload, stale selection
  Add, repeated Add stock boundary, cart content and one final receipt for exactly
  two EU 47.5 black pairs. Other-SKU stock and another retailer's cart stay intact.
- Real BrowserGym AX, formatted observations, screenshots, native Playwright trace
  archives, final private state and source/artifact hashes are retained. These are
  scripted fixture checks, not model-performance evidence or delivered-policy
  exposure labels.

Evidence: four successful boutique/technical cases under
`.local/procedural-commerce/product-controls-v1/`; two final department cases under
`.local/procedural-commerce/product-controls-accordion-v2/`. Original department
cases failed because the driver tried filling a hidden accordion address field;
those reports remain unchanged. The corrected driver opens the native section and
updates the checkout summary before confirmation. Only the two affected cases
were rerun. Both driver source versions are retained with their suites.

The consolidated hash check is
`.local/procedural-commerce/product-controls-acceptance-v1.json`.
The local viewing page is
[product-control examples](http://localhost:8876/procedural-product-controls.html).
Live preview visitors share that preview's mutable session; testing purchases can
exhaust its stock. Fresh evaluation runtimes remain isolated.

## Reuse

```bash
.venv/bin/python -m pytest --import-mode=importlib -q \
  environments/procedural_commerce data/curation/procedural_commerce/mvp

LD_LIBRARY_PATH=$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu \
  .venv/bin/python -m data.curation.procedural_commerce.mvp.verify_product_controls \
  --output .local/procedural-commerce/product-controls-NEW

.venv/bin/python -m data.curation.procedural_commerce.mvp.preview_product_controls \
  --output .local/procedural-commerce/product-controls-preview-NEW
```

`ProceduralCommerceTask` accepts the same optional `product_groups` and
`product_control_styles`. Prepare validates them, retains
`commerce-product-controls.json` and its digest, and passes them to Runtime.
Existing private evaluation distinguishes the exact selected SKU, including a
unit regression that accepts EU 47.5 and rejects EU 42 for the same declared task.
The browser suite independently asserts actual receipt identity. No new general
intent grader, generated task cohort, user-memory service or production catalog
registration is claimed.

Keep further product families/capabilities as extensions of the contract. Do not
multiply the full task corpus by every control/layout permutation: semantic tests,
per-control native browser cases and a bounded composition set remain the strategy.
