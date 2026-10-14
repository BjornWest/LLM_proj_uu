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

The old exact-source fact-review overlay is incompatible with the new summary
seams and SKU grain. Its owner must compose reviewed new pins/registrations before
recording-enabled adoption. Do not simply replace pins or label option aggregates
as model facts. The default `native_fact_probe.js` also needs a scoped update:
its old `.rating-panel` scan silently assigns option aggregates to the product,
without failing or reporting a diagnostic. Dev/runtime composition is held for
both consumers. Recording-enabled runs must use the corrected package or turn
recording off with an explicit saved unsupported reason. No new run is authorized
here; recording support is not claimed by this source-only change.
