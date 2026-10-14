# Public model and option rating summaries

Fresh Website source exposes the existing syndicated all-ratings corpus at two
distinct scopes. No new ratings or private answer fields are published.

- Model summaries retain all options and are labeled model-wide.
- Selecting a reviewed option on a reader page adds an option-specific summary:
  exact configuration/SKU, rating count, written-review count, rating-only count,
  five-star histogram and mean rounded to two decimals, half up.
- The three native `/variants/<encoded SKU>` routes expose the same option
  summary and links to option-filtered reader pages. Editorial links preserve
  `part=readers`.

Option summaries include silent ratings and count each canonical review ID once.
Conflicting copies reject at native validation; the public helper also rejects
conflicting copies if supplied directly (ordinary public exports already dedupe).
Comment star filters, sorting and pagination
do not change the summary's denominator. Option histogram links filter written
comments for the same option; an option can have ratings and no written comments.
Model histogram links clear the option filter and browse comments across all
model options.
With zero ratings, counts/histogram remain zero and the mean is explicitly
undefined, rather than zero.

`review_rating_scopes.sku_rating_summary(product, sku_id)` consumes only the
public product's `skus` and `reviews`. It delegates arithmetic to the existing
Product summary function and does not consult tasks, references or expected
outcomes. `ReviewPage.sku_summary` renders the result; native and legacy review
routes reuse it. Model data and comments are preserved.

Named saved-review preparation (`review_saved_inputs.target_setup`, also used by
task instances) rejects SKU rating-summary tasks on an unsupported layout before
publication. Supported layouts are journal, community, lab-directory,
editorial-magazine and community-feed. It does not automatically select an option
or change the task's start, native reference or grader. The shopper can discover
the option through ordinary controls.

This is prospective source support. Frozen compatibility case
`qwen-compatibility-02-0096` and its original missing-output/native failure remain
unchanged. Native supplied-answer controls established grader plumbing; they did
not establish public solvability on the old renderer. Fresh consumer/runtime
qualification must bind the reviewed source and verify the public route.

Presentation identifiers remain unchanged to preserve deterministic sidecar
replay. Renderer source hashes distinguish this additive output from old pins;
the shared identifier alone does not establish equivalent page content.

Inspect's reviewed corrections at `06e3152` cover both the exact-source
fact-review overlay and the default `native_fact_probe.js`. They preserve
model/SKU identity, include silent ratings and handle rounded and undefined
means on supported product and option routes. Both fixes are composed with
Website source `c58beb3`; release record
`REVIEW-SKU-SOURCE-COMPOSITION-20261014-01` records the passing combined checks.
The recording hold is released for source composition; Harness integrated the
composed source into dev at `17a260ff` as source only, with no working activation. Legacy frozen sources and consumers remain
unchanged. Collection-card aggregate identity remains unmapped with an explicit
inventory diagnostic. The downstream review feature consumer still reads model
grain only; SKU predictor support has not been accepted.

No modern copied-overlay caller is wired in this composition. Reviewed wiring
must bind the three pinned renderer/helper sources and frozen native
dependencies, including the declared caller-wiring review follow-ups. Inspect's
separate legacy basket caller is rejected on modern sources;
`copied_review_classes` refuses a modern pair without its pinned scope source
whether or not recording is enabled. Live Runtime, BrowserGym compact observations,
CDP mappings, acknowledged policy delivery, automatic grading and viewer
qualification remain pending with Evaluation. Regenerate recording package
pins in the final frozen tree; do not transplant worktree-specific paths or
update in-flight episodes. This source release authorizes no new run and does
not establish live recording or model readiness.
