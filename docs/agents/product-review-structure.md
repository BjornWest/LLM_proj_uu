# Product-review reference structure follow-up

2026-09-26. Local native-HTML implementation; no model calls, new tasks, deployment,
or product-world schema changes. These are original synthetic publications,
**not imports of the referenced websites**.

[Open the comparison report](http://localhost:8876/product-review-structure.html).

## What changed

P01, the RunRepeat-inspired directory, now has nested contents links into individual
attributes, a four-product comparison table, and attribute-specific subsections
with small tables. Each subsection distinguishes the reviewed SKU's value from
its frequency in this publication's reviewed-SKU corpus. Ordered fields can show
that corpus's range. These are catalog comparisons, never disguised lab scores.
There are functional links to matching catalog filters, author coverage, recent
articles, and other products. Missing attributes remain missing.

P02, the magazine, now has category-topic disclosures, a latest-coverage navigation
strip, linked contributor pages, a longer main article with comparisons and grouped
specifications, and a publication sidebar. Specifications remain separately
navigable too; the overview no longer requires that navigation to see basic facts.
Reader responses remain a separate article page. This is still a pagination
variant, not an exact reproduction of the Tom's Hardware reference.

P03, the community, adds total/unique-reader/date summaries, a linked rating
histogram, recent-contributor links, publication-wide activity, and reader archives.
The new routes are `/activity`, `/members[/HANDLE]`, and
`/contributors[/NAME]`. Activity supports category/rating filters and pagination;
archives preserve the exact recorded author/reader identity. They are read-only
archives, not simulated accounts. Current generation often gives each reader just
one note; these pages do not invent a rich personal history or social graph.

All layouts have grouped footer navigation and functional links to existing
entities. Existing family vocabulary, multi-value facets and exact-variant scope
remain intact. No fictitious measurement, expert verdict, affiliate quote, product
photo or review prose was copied from a reference.

## Measured shape

Actual BrowserGym extraction, compact nonverbose AX view, 1440×1000 viewport.
Initial disclosures are in their default states. The generated pages show twelve
reader notes per page where reader notes are part of that page.

| Page | Previous AX nodes | Current AX nodes | Current controls | Current depth | Reference nodes / controls / depth |
| --- | ---: | ---: | ---: | ---: | --- |
| Footwear directory review | 388 | 618 | 99 | 8 | RunRepeat: 1699 / 143 / 8 |
| Laptop magazine overview | 100 | 284 | 49 | 8 | Tom's Hardware: 567 / 120 / 7 |
| Beer community profile | 368 | 478 | 91 | 7 | Untappd: 669 / 269 / 6 |
| Wine community profile | 372 | 482 | 91 | 7 | No valid native reference |
| Cat-food directory review | 392 | 667 | 108 | 8 | No valid native reference |

The footwear page now has 36 headings, six tables and 19 rows; its real reference
has 58 headings, 32 tables and 148 rows. Our laptop overview has 18 headings and
three tables. The community beer page has 84 links, versus 265 in the observed
Untappd snapshot. Increasing unrelated DOM wrappers would not close this gap.
The shape is closer, **not equal in richness or fidelity**.

Node totals are not prompt sizes. The initial scoped overview in these captures is
927–952 tokens (local Qwen 3.8 tokenizer); full audit projections are separate
artifacts. Real captures include consent and surrounding page content. Underlying
AX capture does not prove unobstructed clickability. Tom's Hardware emitted
child-frame extraction warnings. Dog-food and wine references returned native 403
pages, so neither is used as an AX target.

## Reference elements the world cannot currently resolve

| Reference element | Present capability / missing contract | Treatment now |
| --- | --- | --- |
| RunRepeat cushioning, durability, traction, fit measurements; hardware battery/performance charts | Catalog specifications exist; independent test observations, conditions, uncertainty and measurements do not | Catalog fact tables and explicitly labelled corpus comparisons; no fake lab results or charts |
| Verdict, pros/cons, awards, “best for” lists | Reader ratings exist; grounded editorial quality/utility judgments do not | Factual coverage and limitations; no quality ranking inferred from catalog numbers |
| Retail offer tables, live lowest price, deals and coupon links | Renderer accepts explicit SKU→retailer URL bindings; these previews have none. Store-world data exists separately, but binding/offer freshness and review-runtime integration are not implemented here | No dead retailer buttons or invented quotes; comparison remains between reviewed products |
| Article photos, close-up galleries, video and test graphs | One category illustration per article; no generated asset set or measured series | Local illustrations only; missing image-heavy subtrees remain a material gap |
| Untappd brewery/venue links, maps, availability, check-in locations | No brewery/venue entities linked to the review export. Store geography sidecar is not a venue contract | No fake destinations; links go to real product/category/reader records |
| Reader profiles and author archives | Handles, bylines, dates and notes exist | Implemented read-only archives and counts from those exact records |
| Friends, follow/toast, badges, personal history, submitting reviews/comments | No authenticated review-site user or social/write state | Not implemented; no inert buttons suggesting those actions work |
| Newsletter, paid membership/paywall, affiliate tracking, social sharing, advertisements | No subscription/payment/ad/social destinations for these publications | Omitted from these original synthetic designs, explicitly not claimed full reference-site imports |
| News, buying guides and other product categories in magazine navigation | Current publication covers only its declared generated families; no independent news/guide corpus | Working category/filter/latest-review navigation; no made-up news links |

The most useful next world extension for task realism is **structured independent
review findings** with SKU scope, measurement conditions and supported claims.
A retailer binding is a separate integration task. Social accounts, videos and
subscriptions are not prerequisites for improving the shopping/research layouts.

## Evidence and reproducibility

- Original real references: `.local/product-review-sites/reference-v1/capture/`.
- Earlier synthetic captures: `.local/product-review-sites/family-audit-v1/live-final/`.
- Frozen public input: `.local/product-review-sites/preview-v3/reviews.json`.
- New 13-page captures: `.local/product-review-sites/structure-v1/capture/`.
- New eight-case native interaction suite: `.local/product-review-sites/structure-v1/acceptance/`.
- Current preview manifest: `.local/product-review-sites/preview-v4/manifest.json`.
- Combined source/artifact validation: `.local/product-review-sites/structure-v1/validation.json`.

69 product/merchant unit and HTTP tests pass. Eight native cases exercise all three
structures and six families, including contributor/member navigation, activity
filters, directory attribute links and community rating links. All 13 capture
cases also check mobile-width overflow. Browser cases run in isolated sessions with
two-process bounded concurrency. No agent inference or grading claims follow from
these scripted checks. Historical exports and captures were preserved.

```bash
.venv/bin/python -m pytest environments/product_review_sites environments/merchant_reviews -q
LD_LIBRARY_PATH=$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu \
  .venv/bin/python scripts/verify_product_review_sites.py --output NEW_DIRECTORY
LD_LIBRARY_PATH=$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu \
  .venv/bin/python scripts/audit_product_review_pages.py \
  --manifest .local/product-review-sites/preview-v4/manifest.json \
  --export .local/product-review-sites/preview-v4/reviews.json --output NEW_CAPTURE_DIRECTORY
```

The renderer is deliberately independent of product generation. New reference-like
structures live in `environments/product_review_sites/structure.py`; public exports
remain `product-review-export-v1`. The saved public hash is unchanged across this
presentation increment. Request logs remain request evidence, not model exposure.
