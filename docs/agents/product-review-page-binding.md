# Frozen Reader Panel binding into connected shopping

26 September 2026. Evaluation-readiness work; no new layouts or model runs.

Ownership split: Product owns structured evidence generation/validation and task/oracle
semantics. Curation owns shopper-page rendering, discovery, source links and connected
publication. Shared acceptance checks that the published corpus is the one graded.

`connected_shopping.Runtime` consumes `scenario['product_review_evidence']` unchanged
when supplied. It validates the catalog/corpus before starting servers, retains the
versioned wrapper as `product_review_evidence`, and records public digest and version
in provenance. `product-review-evidence.private.json` is saved only in the trusted
runtime output directory. No private provenance or grader predicates are served.
The CLI also accepts `--product-review-evidence FILE` over an existing product pin;
this is an explicit frozen input, never automatic corpus resampling.

The existing review sites retain their v1 article/community content. New Reader Panel
sections identify a **separate** collection, grouped by exact SKU, with coverage status,
date, rating when given, and the original frozen body verbatim.
They do not infer opinions from star ratings or copy claims onto sibling variants.
No calculated eligibility, contextual-majority result, or task-specific answer appears
on the website. Complete coverage means all published reports in this corpus, not all
possible real-world experience. An unreviewed model remains unknown.

Panel sections are visible on model article overview pages. Canonical report fragments
resolve as `/reviews/{article_id}#{review_id}`. A public `/reader-panel` directory and
links from existing pages provide ordinary navigation; the world index includes report
source links and public text. These copies retain canonical IDs, not additional votes.
`bindings.product_review_reports` supplies those URLs independently of the corpus hash.
Article variants and private task scopes are not conflated.

Legacy scenarios without the evidence key retain their old pages and behavior.
Existing running previews/cards are not replaced. The new first publication uses
Product's frozen `example-v3`, schema `product-review-evidence-v2`, template version 2.
This template version corrects nonuser prose and samples stars correlated with primary
experience; the renderer neither regenerates nor interprets that prose.

Reproduce a fresh publication:

```bash
.venv/bin/python -m environments.connected_shopping \
  --pin .local/coordination/connected-shopping-world/product-pin-v2 \
  --comparison-coverage .local/coordination/comparison-coverage/pin-v1/coverage.public.json \
  --product-review-evidence .local/coordination/product-review-evidence/example-v3/evidence.private.json \
  --output .local/connected-shopping/review-evidence-NEW
```

Tests: `product_review_sites/test_evidence_ui.py` (public fidelity, family isolation,
links, bad corpus rejection and legacy behavior) and
`connected_shopping/test_review_evidence_binding.py` (all 252 reports/21 article pages,
index discoverability, exact provenance and Episode binding rejection on corruption).
Native browser driver `scripts/verify_review_evidence_pages.py` checks six independent
family journeys through search -> article -> source link -> reload -> panel directory,
with two fresh browser contexts at a time. It retains actual nonverbose AX artifacts.
This is scripted readability/access acceptance, not teacher-model performance.

Product retains final task-card publication and independent task/grader acceptance.
Review-count tasks and open-ended language extraction must not be described as working
in the harness merely because the site exposes their facts; each needs its own supported
answer contract and execution path. A teacher cohort remains a distinct next step.

## Current local acceptance

New index http://localhost:41683, PID 76622, output
`.local/connected-shopping/preview-v6-review-evidence/`. All 252 reports are bound to
21 article pages. Twenty-nine initial Python checks passed (23 site/binding, six
connected); after exposing canonical panel-member identity, four affected checks
passed again. Six final native family journeys passed, 72 full report bodies retrieved
through normal scoped `ax_read(view=node)` with nonverbose mode. Exact responses and
screenshots: `.local/connected-shopping/review-evidence-browser-v3/`.

Earlier native attempts are retained: v1 used a reject button still hidden inside
cookie preferences; v2 incorrectly required complete report bodies in the shortened
AX projection. The final driver opens preferences and verifies complete text via
scoped node reads. The semantic capture retains the full text; overview truncation
is not a lost-review defect. No harness changes or model calls were needed.

The new review runtime is available for Product's separate task-card acceptance.
Historical preview-v2/v4, prior cards and frozen corpora remain unchanged.

## Natural-prose refinement (new renders only)

Explicit experience-kind badges were removed from evidence_ui.py after v6 acceptance:
no first-hand/second-hand/intention labels or serialized experience_kind values are
added to the shopper page. The corpus body is still displayed verbatim; author ID,
exact option, source link, date and normal rating remain. Existing v6 process and
artifacts retain their original badges and are not relabelled or restarted. The two
renderer boundary tests pass, including rejection of label shortcuts in served HTML.
New natural template-version3 corpus binding awaits Product's frozen example. This
small change has no claim of a new browser/model cohort or updated live preview.

Product independently accepted the historical v6 runtime: task card
http://localhost:34347/task.html. It correctly grades uncertainty with 74 ineligible
and four unknown candidates; no-match and the old cheapest recommendation fail.
Acceptance evidence: `.local/product-world/connected-review-evidence-acceptance-v1/`.

## Natural-corpus publication

New preview-v7 input: `.local/coordination/product-review-evidence/example-v4/`,
export schema v2 / narrative template version3. Input artifacts and pinned generator
sources checked before launch. CLI output:
`.local/connected-shopping/preview-v7-natural-reviews/`, index http://localhost:40053,
PID 80081. Old v6 and its card remain available unchanged.

This publication has no generated experience-kind badges. Substantive attributed
second-hand statements are kept verbatim rather than removed or treated as first-hand
votes. Ratings are shown when supplied for either kind of experience; the renderer
does not infer experience, stance, or eligibility from the presence of a rating.
Four focused renderer/corpus/task-binding checks passed against example-v4, including
all 252 reports/21 article pages. The fixture test now accepts PRODUCT_REVIEW_EVIDENCE_PIN
so new frozen corpora can reuse the same conformance checks without rewriting old data.
Native evidence is recorded separately in
`.local/connected-shopping/natural-review-browser-v1/`.

Final natural publication acceptance: all six family browser journeys pass. Product
bound http://localhost:37037/task.html and independently verified the unchanged
74-ineligible/four-unknown outcome under the new corpus. The conformance suite
adds 410 world-to-page checks; see connected-world-conformance.md for command and limits.
