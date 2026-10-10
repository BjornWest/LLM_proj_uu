# Bound product-details setup

`atomic_product_publication.prepare_saved` and `short_task_setup.make_plan`
accept optional `product_details_open: bool`. The choice is recorded in the
private setup artifact/plan and applied before the initial policy observation.
The default helper and legacy plan shape stay unchanged when it is omitted.

For separate specification groups, also pass `product_details_heading` as the
exact native public fact heading. Publication checks it against
`task.public_fact.heading`; setup checks it against the bound selected SKU's
public details. The helper finds exactly one existing product-facts disclosure
with that direct summary text. Without a heading, it requires one outer facts
disclosure, as in the story layout or `detailsPresentation=disclosure`.

Setup reads the actual open state and clicks its ordinary summary only when
needed. It waits for the renderer's own persisted disclosure state, retaining
open/closed selection on ordinary later renders. It records the actual summary,
disclosure identity and before/after open state alongside the existing raw setup
baseline. It writes neither browser storage nor DOM state itself.

Missing or ambiguous disclosures fail instead of rewriting the page. Inline or
tabbed facts are retained in their existing design and need a compatible task
setup. Panel preparation supplies no grading authority, fact omission or model
exposure claim; native task/reference and post-setup browser capture remain the
existing consumer's responsibility.
