# Frozen six-case teacher evaluation binding

Status: six tasks compiled and frozen; offline episode acceptance and local GET-only
policy delivery checks passed. No model evaluation, paid calls, seed search, new grader
or shopping-page changes. Request: `TEACHER-EVAL-LADDER-20260926`.

Task cards: http://localhost:48764/ . Cards 1–6 map to E05/E08/E09/E14/E15/E16.
Their policy directory contains only task input/cards and a neutral task list. Outcomes,
reference answers, resolved requirements and private bindings are outside that directory.

Inputs are existing `.local/connected-shopping/preview-v7-natural-reviews/` and frozen
`.local/coordination/product-review-evidence/example-v4/`, not the newer drink corpus.
Index: http://localhost:40053/ . Corpus public SHA256:
`bd9146bedba284b215b2c2f7761bf6ce7513099a028c3eac7b09f715dc38793d`.

## Realized populations

“Offers” below means all canonical retailer/SKU delivery candidates in the relevant
family, before the task's product predicates. “Attribute matches” ignores stock,
shipping, budget and review judgments. Each request is quantity one sellable unit/pack.
All six cases are retained.

| Case | Family offers / retailers | Attribute-matching offers | Eligible offers / retailers | Unknown offers | Realized answer |
|---|---:|---:|---:|---:|---|
| E05 | 78 / 3 | 2 | 1 / 1 | 0 | Selection, 970 SEK delivered; one winner |
| E08 | 9 / 2 | 0 | 0 / 0 | 0 | No matching wine |
| E09 | 2 / 1 | 0 | 0 / 0 | 0 | Undefined mean: `average`, null value, retailer count 0 |
| E14 | 78 / 3 | 14 | 4 / 2 | 0 | Selection, 925 SEK delivered; two tied exact SKUs |
| E15 | 78 / 3 | 14 | 0 / 0 | 0 | No match under 900 SEK; cheapest available size-40 offer is 925 SEK |
| E16 | 78 / 3 | 14 | 0 / 0 | 4 | Uncertain: exact-SKU review coverage missing for otherwise qualifying offers |

E05 has only one eligible retailer. E08 does not exercise a successful unit-price
optimization. E09's named catalog SKU has no retailer offers; it does not exercise a
nonempty mean, let alone hard multi-retailer arithmetic. These limitations are retained,
not fixed by choosing different identities or sampling again. This is a six-case smoke
subset, not a validated easy-to-hard curriculum or a natural-frequency sample.

E14/E15/E16 form feasible, authored rejection and uncertainty controls respectively.
E05 and both E14 winning options are absent from every comparison site's membership;
retailer-only discovery remains relevant. E15's no-match is an authored 900 SEK budget
control, distinct from E08's incidental attribute no-match.

## Binding rules and public/private agreement

The plan was written before episode evaluation. E05 chooses the lexicographically first
footwear model (`footwear-model-0001`, Aster Stride 0001), with the ladder's fixed EU40,
standard width and black colour. E09 chooses the lexicographically first laptop SKU:
`laptops-model-0016-sku-dcb7d6916a9a`, Boreal Notebook 0016, 32 GB / 512 GB / US English.
Identity binding consults catalog facts only, not offers or review judgments.

E08 fixes white/French/dry/non-sparkling wine, quantity one listed pack, a 700 SEK total
budget, and delivered cost per litre. E14 and E16 retain the exact previously accepted
request/memory bundles. E15 keeps E14's size memory, rewrites the visible budget to
900 SEK, updates all structured views and recomputes its semantic fingerprint. Public
cookie preferences remain visible; auxiliary consent is unscored without host journals.
No inaccessible fit requirements or other hidden preferences were introduced.

Acceptance re-resolves request and memory requirements, checks public wording against
bound attributes, checks initial-accessible and resolved tasks agree, checks fingerprints
and exact runtime/corpus binding, and checks private keys are absent from policy input.
Immutable world, locations, merchant reviews, product reviews and runtime descriptors
remain unchanged. Existing scenario outcome summaries were removed from the task-bound
copies because they described the old task; references live in new private audit files.

## Acceptance and its limits

Three independent offline cases ran concurrently. A fixed-case audit recomputed the
populations from raw offers, catalog attributes, geographic quotes and raw review rows,
bypassing the normal candidate and review-summary adapters. It agreed with all six
Episode references, including ties, empty aggregation and unknown eligibility.

Seven correct structured answers passed (including both E14 ties). Thirty-eight negative
checks rejected wrong statuses, amounts/counts, links or unauthorized effects. Stale task
fingerprints and an incorrect E16 corpus binding were rejected. GET-only local delivery
checks verified all six served task JSON documents against their frozen policy files,
32 supporting URLs and private-route 404s. No browser/model solve was performed.

The accepted scope is structured outcome and required links. Intentionally false
explanations still pass the base grader in all six cases, demonstrating the known limit;
`full_response_evaluated` remains false. Do not describe these as fully graded
**justified** no-match answers. Narrative reasons and source entailment require separate
manual review. No consent reward or browser side-effect coverage is claimed from these
synthetic `effects=[]` acceptance calls.

## Artifacts and reproduction

Private frozen directory: `.local/coordination/teacher-eval-ladder/binding-v1/`.

- `plan.private.json`: predeclared identity/requirement decisions and immutable input hashes.
- `E*.scenario.private.json`, `E*.task.private.json`: six full scenarios and task bundles.
- `E*.acceptance.private.json`: independent candidate rows, references, correct answers,
  grader outputs and explicit explanation-grading limits.
- `acceptance-summary.private.json`, `delivery-check.private.json`: realized populations
  and acceptance/delivery evidence.
- `pins.json`: hashes for compiler/acceptance scripts, loaded implementation sources,
  frozen input descriptors and all private/public artifacts.

Scripts live in `.local/coordination/teacher-eval-ladder/scripts/`. Compilation refuses to
overwrite `binding-v1`; do not delete the frozen directory merely to rerun it. The fixed
acceptance is reproducible with `PYTHONPATH=. .venv/bin/python
.local/coordination/teacher-eval-ladder/scripts/accept.py`; delivery checking uses the
adjacent `verify_delivery.py` and requires the local hosts. Verify `pins.json` against
current sources before interpreting a later rerun as the same implementation.

Task-card server process metadata is in `.local/product-world/teacher-ladder-v1/process.json`.
Curation retains publication ownership for shopping pages. No older runtime or task card
was replaced; E14/E16 intentionally retain their previous semantic episode identities.
