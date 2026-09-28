# Within-design AX variations: first matched example

For content substitution, reusable action checks and resource-efficient serving,
see [conformance and hosting](procedural-commerce-conformance-and-hosting.md).
The subsequent [real retailer AX comparison](retail-ax-reference-study.md) measures
how these small designs differ from the supplied Elgiganten and Amazon pages.

Local prototype, 2026-09-23. This increment implements configurable structural
variation within **department-market**, not additional base designs. The other
families reject these new settings until they have suitable realizations. No
model calls or deployment were involved.

Open the [side-by-side review](http://localhost:8876/procedural-page-variations.html).
It includes screenshots, filtered AX outlines, full formatted observations, raw
AX, configuration and links to independently interactive copies. Select a page
state and switch between screenshot/outline/full-text views.

## Implemented choices

| Setting | Profile A | Profile B | Agent-visible effect |
| --- | --- | --- | --- |
| `navigation_structure` | `flat` | `disclosure` | Direct category links versus expandable groups containing category/product links |
| `result_structure` | `cards` | `table` | Product articles versus associated headers, rows and cells |
| `product_structure` | `split` | `details-first` | Offer before description, with complementary purchase region, versus description before grouped purchase controls |
| `fact_structure` | `table` | `definitions` | Table rows versus definition terms/descriptions |
| `details_presentation` | `inline` | `disclosure` | Facts immediately available versus available after opening a native disclosure |
| `delivery_control` | `select` | `radio` | Combobox versus named radio options, submitting the same shipping method |

The five new settings are independent explicit overrides in `presentation_options`;
`details_presentation` already existed. Both examples hold short titles and two
product images constant. Default callers retain their existing presentation:
`standard` navigation, cards, split product, fact table and delivery select. The
new axes are **not yet automatically sampled**. Site configurations remain fixed
through navigation. Checkout, cart-add semantics and commercial data are separate
settings.

Public facts stay the same; their reading order, grouping and discovery actions
can change. Native closed disclosures really exclude the fact content from the
initial AX. These changes earn diversity credit for observed effects, not changed
classes or padding. The department navigation, branding and general architecture
remain recognizable across both variants.

## Matched evidence

`.local/procedural-commerce/department-variations-v1/summary.json` records two
isolated scripted BrowserGym runs on world seed 7. Both use Nordhem and
`product-004`. World hashes and complete resulting carts/quotes match exactly:
one item, express delivery, no extra. No order is submitted. Native dropdown and
radio operations both reach the same state.

Captured states: landing, opened navigation, results, initial product, opened
facts and after Add. Every state retains screenshot, raw AX, normalized structure
and the harness-formatted observation. Sources and artifacts have hashes.

Observed structural examples:

- Results: A has 12 product articles; B has one table and 13 rows including its
  header. Both expose the same 12 product names.
- Initial product: A has two comboboxes and no radios; B has one combobox and two
  radios. The remaining combobox selects destination.
- B initially excludes the `Configuration` fact; opening its disclosure exposes
  it in a definition list with five terms. A exposes the corresponding fact in
  its five-row table immediately.

These counts describe full captured AX, not token usage or difficulty. The full
text view uses the harness formatter with a **48,000-character** limit; it is an
inspection artifact, not an actual model request or a claim that a deployed
scoped-AX policy receives the whole tree. The outline intentionally filters noise;
raw AX and full formatted text remain available. No reasoning is inferred.

## Reproduce

Use a fresh output directory to preserve previous evidence:

```bash
LD_LIBRARY_PATH=$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu \
  .venv/bin/python -m data.curation.procedural_commerce.mvp.compare_variations \
  --output .local/procedural-commerce/department-variations-NEW

.venv/bin/python -m pytest --import-mode=importlib -q \
  environments/procedural_commerce/test_department_variations.py
```

Implementation: `environments/procedural_commerce/department_variations.py`,
`presentation.py` and `retailer_designs.py`. The reusable capture driver is
`data/curation/procedural_commerce/mvp/compare_variations.py`; persistent preview
and review-page builders are `preview_variations.py` and
`publish_variation_review.py` in the same directory. The current preview manifest
is `.local/procedural-commerce/variation-preview-v1/manifest.json`. Its mutable
browser sessions are independent of the saved acceptance artifacts.

## Limits and next review

This is one baseline/contrast pair; it does not complete the rubric's eventual
baseline-plus-two-contrasts packet or show population-level variation. Combined
contrasts demonstrate the result of these settings together, not an isolated
difficulty effect for each setting. Offline tests check independent option
overrides and reject unsupported configurations. Broader sampling and equivalent
within-family choices for boutique/technical designs remain future work.

The previously reported incremental Add stock issue remains open: cart drafts can
exceed inventory and checkout catches the invalid quantity. This variation work
does not repair that product-page boundary. The paired example uses one available
unit with `cart_addition=set`.
