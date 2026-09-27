# Product-review evidence, reusable templates and task integration

Implemented locally on 26 September 2026. This is a new versioned corpus, not a
reinterpretation of the old generic reader comments. Curation retains v1 generation,
website rendering and connected composition; Product owns the additive evidence
module and task/grader integration. Coordination and frozen inputs:
`.local/coordination/product-review-evidence/`.

## Generation and meaning

`environments/product_review_sites/evidence.py` generates structured reports first,
then renders each body from reusable sentence templates. Current template version 3
uses `evidence_prose.py`: concrete events imply the usage context, with optional short
model mentions and relevant attributes inside natural sentences. For example,
"Halfway through writing a report the fan spun up loudly enough that I put my headphones
on." It does not announce "this is about typing" or recite a specification list.
Missing judgments are omitted, not announced as unassessed. Mentioned attributes are
derived from the actual slots used and checked against the SKU. Traits do not prove
the sampled opinion. The grader reads structured claims, never inferring a judgment
from stars. Original version 1/2 renderers remain available to validate frozen corpora.
A validator recomputes bodies and slot annotations, rejecting drift. This demonstrates
faithful template rendering, not unrestricted natural-language sentiment extraction.

Current aspects:

| Family | Context | Opinion/complaint claims |
| --- | --- | --- |
| Footwear | Long walks | Comfort, heel rubbing |
| Laptops | Typing | Keyboard comfort, bothersome fan noise |
| Dog/cat food | Feeding | Pet acceptance, ease of pack handling |
| Beer | Tasting | Taste enjoyment, perceived bitterness |
| Wine | Tasting | Taste enjoyment, perceived dryness |

Positive supports the named claim; for heel rubbing it means a complaint, not praise.
Negative explicitly contradicts the claim. Mixed and neutral have their own templates.
An absent judgment is `not_assessed`, not an implicit negative or neutral vote.
New reports contain actual use or substantive second-hand experiences, never empty
intention-only filler. They have at least one focal assessment; other aspects may be
omitted. Second-hand reports attribute concrete experiences to another person, including
first-person words inside quotations. These do not become the poster's own use votes.
Both experience kinds can have or omit submitted ratings, so star presence does not
reveal the private experience classification. Generated stars correlate with the
primary stance where present. A comfortable shoe can still rub heels; those statements
are independently represented. Opinions are fictional authored
experiences, not empirical product quality, medical effects or lab measurements.

Independent seed streams select exact reviewed SKUs and reviewer reports without
access to task requirements, price, availability, layout or grading outcomes. Defaults
are one reviewed variant per model and 12 reports per reviewed SKU. Configuration
accepts seed, frozen ISO date, `reviews_per_sku` (0..100), and
`reviewed_variants_per_model` (0..6). Zero reports with complete coverage is a known
zero; an unreviewed sibling SKU remains unknown. No task-conditioned resampling.
The authored opinion distribution is uncalibrated; no realism validation is claimed.

## Export and binding

Wrapper `schema_version: product-review-evidence-v2` contains `public` and
`private_provenance`. Public fields are as_of, source_catalog_sha256, publisher_id,
registry, coverage, reviews, scope and identity_policy. Coverage rows identify an
exact SKU/aspect/context and complete/incomplete status. Registry definitions state
family eligibility and explicit stance meanings. No model-wide inheritance exists.

Each report carries canonical review_id/reviewer_id, publisher_id, article_id, exact
SKU subject, handle, date, source_locator, optional stars, usage_reports, assessments,
mentioned_attributes, template_choices and body. Source locators use article ID and
review-ID fragment, independent of local origins. One active canonical report per
reviewer/SKU is supported; conflicting copies or unsupported revisions are rejected.
The aggregator deduplicates identical canonical copies before counting. The generator
exports only unique canonical records; repeated displays must preserve those IDs.

`generate_scenario(..., product_review_options={...})` now always creates
`scenario['product_review_evidence']` after catalog generation. Legacy frozen scenarios
without this field still work. The optional fifth argument controls this new corpus;
`review_options` continues to configure merchant reviews independently.

Runtime must consume that exact corpus, expose `runtime.product_review_evidence`,
and record `product_review_evidence_sha256` and `product_review_evidence_version` in
provenance. Snapshot filename for task-card binding is
`product-review-evidence.private.json`. Do not regenerate the corpus in a renderer.
`Episode.from_runtime` refuses review-dependent tasks if the served corpus, source
catalog, public hash or version differs. Curation owns page integration; the frozen
template-version-2 corpus is accepted in preview-v6; the natural template-version-3
corpus is now separately published and accepted in preview-v7. V1 community comments remain unscored.
Structured usage/stance fields are source annotations, not instructions to display
classification badges on shopper pages. New pages must convey attribution through
prose and ordinary author/date/rating metadata; author inspectors can expose raw records.

## Tasks, memories and grading

`sample_task(..., product_review_preferences='none'|'auto'|'majority'|'rating')`
adds typed criteria before world generation. Default none preserves existing task
recipes. Auto uses authored weights 1/2 none, 1/4 majority, 1/4 rating. Placement uses
the existing memory mode: explicit request when none, otherwise structured profile
or a prose episode backed by structured memory facts. Review preferences participate
in the task fingerprint. Relevant criteria never hide in prose-only filler.

Majority examples include "most people who mention wearing them on long walks say
they are comfortable". Denominator: distinct actual users in that context, including
those who omit the aspect judgment. Numerator: explicit positive judgments. Majority
means strictly more than half. No hidden minimum sample size; an empty denominator
is insufficient evidence. Rating recipes explicitly require five or more ratings and
a sampled 3, 3.5 or 4-star minimum, checked with exact sum/count arithmetic. These use
all submitted scoped ratings, including second-hand reports that carry a rating;
unrated reports have no star value. The delivered task context states that population.

`shopping_intent.review_evidence.summarize` produces positive/negative/neutral/mixed/
unassessed review counts, canonical source IDs, contextual reviewer counts and rating
sum/count. Published record completeness is not a claim about all real-world users.
Incomplete or unsupported evidence stays unknown. `product_world.outcomes` supplies
these summaries to the existing oracle without dropping unknown candidates. Sparse
exact-SKU coverage may therefore make a global optimum unresolved, which is retained.

`product_world.product_review_tasks.sample_count_task(world, sku_id=..., aspect_id=...)`
adds a separate named-product count-task helper. It uses catalog identity only, never
opinion outcomes; it may also sample an identity without requiring review coverage.
It operates on an existing catalog (unlike task-first shopping criteria), and is not
yet part of the main shopping-query random sampler. `grade_count_task` checks the five
explicit stance totals or justified uncertainty and trusted effects. It does not grade
free-form summaries or infer sentiments from agent prose. General NLP extraction,
review-source link grading, broader review recipes and empirical calibration remain
future work.

## Preview and evidence

Human authoring workshop: http://localhost:48762/ . Family/product selectors show
actual generated prose, underlying structured records, reusable shopping request and
memory examples, count-task examples and optional reference tables. This is an author
inspector, not a shopper website or a new training episode. Served directory is only
`.local/product-world/review-workshop-v2/public/`; no private artifact directory is served.
The older workshop at port 48761 is preserved for comparison.

Frozen example-v4 corpus contains 252 natural-template records over the unchanged pin-v2 catalog.
The adjacent ordinary scenario and majority-preference scenario share that corpus;
the latter remains uncertain where exact-SKU coverage is missing. Recipe and hashes
are recorded alongside the artifacts. Existing published worlds/cards remain intact.

The initial implementation had 145 relevant local tests passing: generation/template
agreement, scope/hash/duplicate rejection, context and polarity accounting, exact
rating arithmetic, task/memory fingerprints, unknown propagation and episode binding,
plus existing scenario/intent/oracle and product-review structure/facet regressions.
Desktop and mobile authoring-preview checks passed for all six family selectors in
two isolated concurrent browser contexts. A mobile selector overflow was fixed and
rechecked. The natural-prose revision passed 44 relevant checks in independent groups,
including quoted first-person attribution, substantive reports, omission of grading
labels, attribute-slot fidelity, and legacy export/page binding. New desktop/mobile
checks cover all six family selectors and absence of experience badges. Evidence is
in `.local/product-world/review-workshop-v2/browser-check.json`.

Independent acceptance of the earlier corpus in preview-v6 is complete: new task card
http://localhost:34347/task.html . All 78 global candidates/quotes are retained; 74 are
ineligible and four remain unknown due to missing exact-SKU reviews. Independent raw
report aggregation agrees with the grader. Correct uncertainty passes; no-match and
the former 925 SEK recommendation fail. The audit checked 252 source URL bindings,
108 rendered footwear reports, and all four unresolved options through native pages.
See `.local/product-world/connected-review-evidence-acceptance-v1/`. This accepted host
remains frozen; the natural example-v4 is a separate input. These are software/browser
checks, not model evaluations, training runs or an NLP answer-extraction acceptance.

Natural-corpus acceptance is also complete. Task card http://localhost:37037/task.html
binds example-v4 to index http://localhost:40053. Same 78 candidates, 74 ineligible and
four unknown; raw-report recomputation agrees with grading. All 252 source bindings,
108 rendered footwear reports and four unknown options' actual pages were checked in
two concurrent browser sessions. Experience badges are absent. The new corpus hash is
bd9146bedba284b215b2c2f7761bf6ce7513099a028c3eac7b09f715dc38793d. Evidence lives in
`.local/product-world/connected-natural-review-acceptance-v1/`; older hosts remain intact.

## Drink observations: template 4 (2026-09-26)

The previous neutral tasting sentences were finished templates, not placeholders.
They often conveyed too little information. New beer/wine reports now sample concrete
`sensory_observations` before prose: `flavour_note`, `body`, and, only when bitterness
is discussed, `bitterness_intensity` and `bitterness_persistence`. For example:

```json
{"flavour_note":"grapefruit","body":"light",
 "bitterness_intensity":"mild","bitterness_persistence":"lingering"}
```

These are attributed perceptions, not ingredients or measured product specifications.
Flavour pools depend on beer style or wine colour; enjoyment is sampled separately.
Every drink report describes flavour and body, including indifferent reviews and
reports that omit a task-relevant aspect. Mixed enjoyment identifies a particular
tradeoff (liked flavour, disliked body). New bitterness/dryness assessments use
present/absent judgments rather than randomly switching between glasses. Mild and
lingering, or pronounced and brief, both support **noticeable bitterness**. Neither
is coded as mixed merely because intensity differs from persistence. Absent bitterness
requires intensity `absent` and persistence `none`; omitted bitterness has neither
observation and remains unassessed. Quoted hearsay still does not enter first-hand
counts. Semantic validation rejects incompatible observations even with a recomputed
corpus hash. Canonical deduplication also rejects conflicting sensory copies.

The new fields are inspectable deterministic facts, but intensity/duration/flavour
predicates are **not yet added to the shopping-task sampler or common answer grader**.
Existing taste/bitterness/dryness requirements and count helpers keep their established
meaning. Do not advertise a new “mild but lingering” task as already supported merely
because the underlying observations now exist. This increment improves prose quality
and prepares that boundary; it does not add an NLP extraction grader.

Only drinks use template 4. The four other families retain byte-identical template-3
records under the same recipe. Old exports retain their original renderers and hashes.
No changes to renderer, connected-runtime or existing live publications were required.

### Small research sample and reusable authoring patterns

Reviewed public user-review examples on 2026-09-26, at group level, not per synthetic
SKU. The sample suggests useful patterns; it is not a prevalence study or a calibrated
review distribution. New sentences are authored synthetic text, not copied reviews.

| Group | Useful pattern observed | Verifiable interpretation / boundary |
|---|---|---|
| Beer | Flavour notes, body, bitterness intensity, finish and enjoyment discussed separately. [BeerAdvocate community reviews](https://www.beeradvocate.com/beer/) | A reviewer can like a bitter beer. Duration is not intensity. Sensory notes are not ingredients. Implemented as template-4 observations plus existing aspect judgments. |
| Footwear | Outing/surface context, comfort alongside squeaking, wear, laces or explicitly untested waterproofing. [REI Paisley user reviews](https://www.rei.com/product/105218/dansko-paisley-shoes-womens?redirect-pup=false) | Contextual comfort can be assessed while an unrelated complaint remains useful; “not tested” is not negative evidence. Existing long-walk/heel aspects remain; new lace/durability predicates were not added. |
| Laptops | Workload, fan noise, battery compromises and concrete workarounds coexist. [Best Buy LOQ customer reviews](https://www.bestbuy.com/site/reviews/lenovo-loq-15-6-full-hd-gaming-laptop-amd-ryzen-5-7235hs-2023-12gb-memory-nvidia-geforce-rtx-4050-512gb-ssd-luna-grey/6617097?page=2) | Loud during gaming does not establish loud during writing. Existing typing-context evidence remains; no inference across workloads. |

Wine shares the drink composition structure with colour-compatible notes and an
independent perceived-dryness judgment. Its vocabulary is authored, not an empirical
model of a particular wine. Further investment should reuse these group-level
structures; do not research or handwrite a corpus for every generated SKU.

New authoring preview: http://localhost:48763/ (workshop-v3), frozen input
`.local/coordination/product-review-evidence/example-v5/`. Public corpus hash:
`9163e285cfa88b6d3f35cfc29f946b26a2406b5443646ea7bc2afe7a6296d753`.
252 reports; only the drink records changed. 58 relevant tests pass, including the
new observation/polarity/tamper tests and existing task/scenario/renderer binding
regressions. Two independent browser sessions checked desktop/mobile layouts, all six
family selectors and inspectable observation fields. Old workshop/world/task-card URLs
remain available. This is a new authoring preview; the connected v7 publication still
uses its frozen example-v4 corpus until Curation publishes a separate binding.
