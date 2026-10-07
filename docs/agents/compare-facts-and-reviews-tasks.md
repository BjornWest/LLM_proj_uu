# Compare facts and review summaries in one episode

Product owns the additive task, reference, request compiler and grader. Website
owns publication/setup/execution consumers. Inspect owns observed-prefix joins
and the authorized recording pilot; Evaluation owns integration and promotion.
This capability composes the existing native contracts, without changing their
fact, status, identity, rating or topic-opinion calculations.

## Declaration and callables

Pass this task to `catalog_compare_review_generation.compile_request`/`generate`
inside an existing `website-world-generation-v2` request. Enable surrounding
review publications before sampling; all ordinary world controls remain intact.

```json
{
  "kind": "compare_facts_and_reviews",
  "concept_id": "footwear.walking_shoes",
  "fields": [
    "product.facts.cushioning",
    "product.facts.reference_mass_g",
    "product.facts.fastening"
  ],
  "review": {"operation": "rating_summary"}
}
```

Alternatively, declare `topic_counts` with an accepted `topic` (aspect and exact
or object-subset context) and optional `min_assessed` (default 1). Declare three
to five unique public model scalar fields; SKU, private and collection paths are
rejected before sampling. Unknown, not applicable and false remain distinct.

For a retained world, construct `FieldInventory` and `ReviewInventory` for its
concept, then call `catalog_compare_review_task.make` and `reference`. Two carried
manufactured models are chosen using the existing comparison seed/concept/ID
ordering; stock, price, field values and reviews do not choose subjects. Review
identity indices bind to those same model IDs. Product-level reviews include all
options; canonical review IDs count once across syndication, including silent
ratings for the ratings operation.

The generated result adds `catalog_compare_review_task`,
`catalog_compare_review_reference` and `compare_review_task_binding`. Fewer than
two carried models or absent review-site coverage remain unsupported outcomes,
without repair or retry. Unsupported results have no launchable manual task.
A bound result has identity/site membership only; it is not a public-disclosure
or runtime-readiness certificate.

## Obligations and grading

`required_obligations` has stable model-role IDs, native product identity, field,
grain and source family. Fact records carry declared unit/basis/status policy;
review records carry operation/topic. Three facts plus ratings produce 24 records;
three facts plus topic counts produce 22. Records identify required aggregates,
not expected answers or inferred observations. Inspect separately associates
their dependencies with actual corpus rows and delivered DOM/AX spans.

Construct `CatalogCompareReviewGrader(world, task, reference, bindings,
site_registry, surrounding=...)`. It exposes `task`, `schema`,
`extraction_instructions`, `contract`, and `grade(claims, final_answer)` compatible
with the existing `task_answer.grade_saved_once` interface. Supply complete native
world, actual offer URL bindings, review site registry and surrounding publication
data; never pass the reference to the formatter prompt.

One compound extraction returns `comparison` and `reviews.model_1/model_2`.
The grader invokes the unchanged comparison and two review graders; every part
must pass. Wrong values, units, statuses, identities, missing parts or foreign
links cannot be rescued by a correct other part. Preserve the three raw native
subreports; viewer derivations use a list wrapper around each original derivation.

## Release requirements and limitations

Source controls use authored finite fixtures and real parent graders. They are
not sampled-world, browser or model acceptance. Before the single Sol pilot,
integrate reviewed exact commits and full dependencies/assets, freeze the world,
then check actual public coverage for all required known facts and the complete
necessary review corpus. Missing known facts are a disclosure limitation, not
logical unknown; do not fix native truth or redraw until the answer is convenient.

Website must attach this automatic grader before dispatch, extract once after
policy-session closure, and publish a visible grade. Actual zero-provider reset,
setup/capture, positive/negative controls and HTTP viewer projection must pass
from the Evaluation worktree before the model episode. The address-only release
does not certify this new source union. Effect authority is separate.

Correct answers and source citations do not prove navigation, attention or
recipient delivery. Inspect's per-prefix evidence must establish those joins
separately, retaining unknown mappings and refusing future/wrong-state credit.
No general workflow language, new model batch, automatic retry or resource grant
is introduced by this contract.
