# Product-review family audit and typed filters

2026-09-26. Local browsing increment, no model calls or deployment.
[Open the visual audit](http://localhost:8876/product-review-family-audit.html) ·
[Open all specialist sites](http://localhost:8876/product-review-sites.html).
The sites retain their original localhost ports; refresh an already open page.

## AX scale, measured through the harness

These are semantic nodes from the actual nonverbose BrowserGym/AX-context pipeline,
not HTML tags, raw Chrome nodes, or tokens in a single request. Generated pages
use twelve reader notes per page. Earlier acceptance screenshots used four, which
explains their smaller counts. The initial model overview remains token bounded.

| Page | Generated nodes | Real reference nodes | Interpretation |
| --- | ---: | ---: | --- |
| Footwear review | 388 | RunRepeat 1699 | Same maximum tree depth (8), much less measurement and comparison content |
| Laptop overview | 100 | Tom's Hardware 567 | Our specification page is 126; reader page 309; don't sum repeated navigation across pages |
| Beer review | 368 | Untappd 669 | Similar activity-feed structure; fewer repeated links and activity details |
| Wine review | 372 | — | Vivino's browser visit was blocked; no valid comparison |
| Cat/dog food review | 392 each | — | Pet-food reference browser visit was blocked; no valid comparison |

Real-reference counts include observed surrounding content and consent UI. Tom's
Hardware had child-frame extraction warnings. They describe captured samples, not
complete site inventories or equivalent tasks. Reference links and original evidence
are in [the initial research](product-review-sites.md).

The new wine catalog has 211 nodes, versus 118 in the old live preview; the shared
pet-food catalog has 282 versus 172. These increases come from working controls,
not artificial filler. Review node counts stayed essentially unchanged: this
increment improved terminology and discovery rather than adding more review content.
Our long-form reviews are still substantially simpler than the real sites.

## Findings and changes

- **Generic “configuration”:** replaced in coverage headings, tables, contents,
  related cards, comparison selectors, alternative options, retailer links and
  footer navigation. Hardware keeps the term; other categories use appropriate
  vocabulary. “Return to model review” became “Return to review.”
- **Shoe placeholder on wine pages:** the universal “Exact value / e.g. wide”
  interface is removed from the visible UI.
- **Unknown filter vocabulary:** public corpus values now appear as checkboxes.
  Multiple selected values within a field mean OR; different fields combine with
  AND. Selection persists across pagination and sorting. This includes grapes,
  colours, recipes, vintages, sizes, countries, pack counts and bottle volumes.
- **Numeric preferences:** ordered numeric attributes such as ABV, RAM and weight
  expose minimum/maximum selectors with values and units. Exact identity/fit
  attributes such as EU shoe size use choices, not “larger is better.”
- **Booleans:** Any/Yes/No choices according to available corpus values.
- **Ingredient exclusion:** separate exclusion checkboxes remove a product if it
  contains any selected ingredient. Missing ingredient information never proves
  absence. Positive ingredient selections and exclusions can combine.
- **Field names and grammar:** human attribute labels and acronym case preserved;
  removed ungrammatical generic sentences such as “Ingredients is listed as.”
- **Unrelated help text:** ingredient-exclusion explanations only appear where
  exclusion facets exist. A stretched boolean dropdown found during visual review
  was corrected; native controls retain accessible labels.

Filters reference the exact product option described in each article. They do not
silently search all variants of a model and then display a review of a different
variant. Old `field/value` URLs remain supported, with the active legacy condition
visible, but new forms generate typed parameters instead.

## Reusable product-language groups

`environments/product_review_sites/presentation.py` separates vocabulary from
layout and data. Twelve small profiles cover the current forty-family intent
registry, with a neutral “version” fallback for future categories. Examples:

| Families | Presentation vocabulary |
| --- | --- |
| Footwear | Pair reviewed; size/fit options; other sizes and colours |
| Laptops, phones, tablets | Configuration; specifications |
| Dog/cat food | Recipe and pack; other recipes and pack sizes |
| Beer | Beer and pack; other pack sizes |
| Wine | Wine reviewed; vintages and bottle sizes |
| Clothing | Size and style; sizing and materials |
| Skincare/haircare | Formula and size |
| Makeup | Shade and finish |
| Replacement parts/accessories | Compatible version; compatibility and contents |
| Books/games | Edition; edition and contents |
| Size-dependent household products | Size and finish; dimensions and materials |

This mapping prepares language reuse; it does **not** claim that the other 34
families are integrated into the review generator. Facts, task semantics and
family-specific measurements still need their own contracts. Page layout does not
choose the vocabulary or change product facts.

`facets.py` derives typed controls from public reviewed facts plus the existing
attribute registry. Range eligibility uses the attribute's declared comparison
semantics. Query parsing accepts repeated values only for choice/exclusion facets;
unknown fields/values, malformed or reversed ranges and duplicated scalar controls
fail explicitly. These checks avoid silently dropping a user's condition.

## Product-generation finding, handled by its owner

The fixed historical world contained a red wine with only Riesling listed as its
grape. That is a source coherence problem, not a renderer label to correct.
[Riesling is a white-wine grape](https://germanwineusa.com/basics/german-wine-types/white-varietals/riesling/).
The product agent repaired conditional grape/colour sampling and complete-composition
validation, preserving white-from-dark-grape and partial-blend semantics. Exact
handoff: `.local/coordination/product-review-sites/family-audit.md`.

The before/after presentation audit retains the original world byte-for-byte.
The refreshed live preview uses a newly generated coherent catalog, saved separately
in `.local/product-review-sites/preview-v2/`; current process manifest is `preview-v3/`.
No old data, reviews or traces were rewritten. This resolves the reported mismatch,
not every possible domain-realism issue.

## Evidence and validation

- **63 tests:** 40 product-review and 23 merchant-review tests. Includes multi-value
  OR/AND, ingredient exclusions, exact sizes versus ranges, invalid input, selected
  state in URLs, per-family vocabulary across every base layout, and forty-family
  presentation mappings. Tests validate public corpus queries, not model reasoning.
- **Eight new native browser cases:** all three layouts on footwear plus the other
  five families. They cover native selections, pagination, comparison, variant
  navigation, exact facts, reader-note filters and mobile width. See
  `.local/product-review-sites/acceptance-v3/suite.json`.
- **Thirteen fixed-corpus page captures:** all six family reviews, five catalogs,
  and the laptop specification/reader pages. Separate fresh browsers, two cases
  concurrently; all mobile-width checks pass. See
  `.local/product-review-sites/family-audit-v1/after-final/`.
- **Live preview check:** captures under `family-audit-v1/live-final/`, using the
  refreshed catalog, confirm the reported counts and updated rendered pages.
- Historical `before/`, initial `after/`, and previous acceptance directories are
  preserved. The final one-line “Return to review” wording change follows the
  fixed-corpus captures; it is covered by fresh native acceptance and does not
  change the captured article/catalog nodes.

No shared harness, runtime adapters, retailer pages or product-world code were
changed by curation. Numeric fields make objective tasks possible, but this UI
increment does not create graders or certify generated opinions as product truth.
