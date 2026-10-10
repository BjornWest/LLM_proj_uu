# Product public assertions: producer contract

Decision `WEB-PUBLIC-MEANING-20261001`, 1 October 2026. **Accepted producer/consumer contract; runtime implementation and package migrations are pending.** This records the shared meaning boundary requested by Bjorn. It does not change existing packages, hosts or grades.

## Ownership and adoption

| Owner | Responsibility |
| --- | --- |
| Product / world generation (`01a0cae2-21b9-70b0-9f46-3dd97b9a1c1d`) | Shared metadata schema, validation/resolution/export, semantic identifiers and later task/evidence consumption. |
| Curation / catalog expansion (`01a0a12d-4cf0-7380-8135-c5a9936025af`) | Accurate authored assertions and formulation annotations; independent prose review; pinned package/metadata examples. Coordinate worker adoption. |
| Website generation (`01a0f748-a354-7f51-80fa-001f0aabd6bb`) | Public projection, disclosure choices, rendering, actual publication ledger and discoverability/realization checks. |
| Fact-span / harness owner | Occurrence/state instrumentation and exposure mapping, using these identifiers; no separate semantic inventory. |

The website owner can implement an adapter against this boundary and a pinned contract fixture. Live evidence-dependent use requires the producer validator/export and consumer realization checks, not merely a sidecar that the old compiler ignores. Product owns that implementation; no transfer of compiler ownership is requested. Catalog expansion can continue its current acceptance pipeline, while preparing the annotations below for new concepts. Historic acceptances are not revoked or retroactively credited.

No additional shopper-visible decision is required here. This contract specifies no layout, widget, mandatory heading, omission probability or unnatural wording convention. Existing agreed variation and disclosure rules remain in effect.

## A compact additive representation

Use a companion JSON file with `schema: product-public-content-v1`, `concept_id`, `source_files` (package and recursively imported source SHA-256s), `fields`, `assertions` and `language`. Metadata is versioned and frozen with its package. It introduces no new sampling program or expression language. Its expressions use the existing safe, typed product expression evaluator.

Paths in `source_files` are repository-root-relative POSIX paths, as in the fixture; resolve them against an explicitly configured trusted repository root, never the companion's directory or a process-dependent working directory. Reject traversal, duplicate normalized paths and sources outside that root. Include recursively imported package sources, not only the child JSON. Drafts may live under `.local/product-width/annotations/<concept_id>/`; final companions may live under `environments/product_world/data/product_public_content/<concept_id>.json`. Their directory does not change executable package import rules. Final status promotion changes the child hash, so retain the previous companion and repin the final one; do not rewrite historical receipts.

A companion file avoids silently changing the executable `product-package-v1` grammar and allows catalog authors to prepare annotations before the shared validator is available. It is an authoring artifact, **not browser JSON**. Production loading must explicitly require this capability/version, validate source hashes and reject unsupported metadata. Accepting a package in the old compiler does not validate this file.

`fields` maps exact existing field paths to public semantic definitions. Each definition has a stable semantic `id`, label/value vocabulary where necessary, subject binding, optional component identity, and required qualifiers. Reuse the field's declared type, enum and unit; a conflicting duplicate definition is invalid. Do not infer public status from the presence of a field. Private positioning/execution, sampler weights, task bindings and oracle results remain private. These field definitions can feed factual tables, controls, filters or prose without prescribing any one of them.

`assertions` is a keyed registry of stable assertion identities. Each entry uses one of three forms:

- `field_value`: `field` names a declared public field. The assertion communicates its actual value/status with its required qualifiers. The resolved value uses that field's type and unit.
- `catalog_predicate`: `predicate` uses the existing expression notation to represent the proposition actually communicated. It must evaluate to true for credited content. For example, “closed heel” asserts that specific boolean is true; a generic eligibility predicate mentioning heel, use and construction does not assert all three.
- `customer_experience`: `experience` retains the existing structured `aspect`, `polarity`, `context` and `source` meaning. This is an attributed opinion, not a catalog fact, guarantee or measured outcome. Preserve the review/reviewer identity in resolution; reported experience remains reported.

Every entry declares `subject`, `authority` and any `qualifiers`. `subject` binds an existing product, SKU, brand or other registered entity ID through a typed expression; an optional stable component key narrows that subject. Product-level statements do not become exact-SKU claims merely because rendered on a SKU page. For an exact-SKU review, bind the tested SKU, not a renderer's default variant. SKU compatibility/included-component relations retain their declared structure.

Authorities initially are `catalog_fact` and `attributed_experience`. Manufacturer declarations, measured tests and other authorities need explicit registry support before being credited as such. A test qualifier cannot upgrade an ordinary catalog declaration into a tested result.

A qualifier is either a fixed `literal` or a typed `expr` referring to existing fields. It identifies necessary meaning such as per-bowl capacity, maximum-fill rather than brim capacity, installed-battery body mass rather than supplied-set mass, test conditions, or a specific included component. Preserve required qualifiers in every credited realization; an unqualified number is not equivalent evidence. Measurement basis may live in existing field metadata rather than being redundantly copied into every assertion. Unknown and not-applicable remain distinct typed statuses, never false/zero by default. Only an explicitly worded unknown-status statement can credit that unknown status; unavailable values must not become invented prose.

`language` binds a pool ID to `common_assertions` and, optionally, `formulation_extras`. Common assertions must be communicated by **every** formulation. Extras are indexed by the existing formulation index and are credited only for that chosen formulation. Hash-binding the source fixes the indices; editing or reordering prose requires a new freeze. Unused entries or invalid indices fail validation. An explicitly empty assertion list means the author has audited that wording and declares no catalog/experience assertion; an absent annotation means **unmapped**, not audited empty.

Use common assertions for actual paraphrases. Usually normalize wording or split genuinely different meanings rather than accumulating extras. Extras are useful for an incidental true additional claim in an existing pool and make that coverage dependency explicit. Adding paraphrases does not add meanings or alter semantic selection probability. If a new meaning pool is needed, assign its semantic weight explicitly; do not copy the old weight to each split and multiply its mass. Coverage checks must account for the actually selected formulation, including usage-adjusted wording probabilities where present.

Applicability (`when`, existing `meaning.predicate`), interpolation slots, and assertion truth checks remain separate. Their references identify dependencies; they do not automatically become assertions. The shared validator checks reference/scope/unit/status validity and factual consistency. **It does not prove that arbitrary English entails its annotation.** Catalog authors and independent review must establish that correspondence, including fixed claims without slots and qualifiers stated naturally in context.

## Exact footwear gap and fixture

In the existing walking-shoe introduction, both formulations state name, enclosed construction and everyday walking. Only formulation 1 explicitly states a closed heel. Until a separately approved inference exists, formulation 0 is not credited with that heel claim. Do not assume “enclosed” establishes it merely because both are true in the sampled recipe.

The following registry/binding fragment uses existing fields and expressions. The frozen fixture adds its schema, concept and exact source hashes. It is a contract example, not a retroactive annotation of a live world.

```json
{
  "assertions": {
    "footwear.product.name": {
      "kind": "field_value",
      "field": "product.name",
      "subject": {"kind": "product", "id_expr": "product.product_id"},
      "authority": "catalog_fact"
    },
    "footwear.construction.enclosed": {
      "kind": "catalog_predicate",
      "predicate": "product.facts.construction == 'enclosed shoe'",
      "subject": {"kind": "product", "id_expr": "product.product_id"},
      "authority": "catalog_fact"
    },
    "footwear.use.everyday_walking": {
      "kind": "catalog_predicate",
      "predicate": "product.facts.intended_use == 'everyday walking'",
      "subject": {"kind": "product", "id_expr": "product.product_id"},
      "authority": "catalog_fact"
    },
    "footwear.heel.closed": {
      "kind": "catalog_predicate",
      "predicate": "product.facts.closed_heel == True",
      "subject": {"kind": "product", "id_expr": "product.product_id"},
      "authority": "catalog_fact"
    }
  },
  "language": {
    "description/introduction": {
      "common_assertions": [
        "footwear.product.name",
        "footwear.construction.enclosed",
        "footwear.use.everyday_walking"
      ],
      "formulation_extras": {"1": ["footwear.heel.closed"]}
    }
  }
}
```

The shared mapping also declares these four public fields. This avoids treating an interpolation slot as the only asserted fact. A catalog author may instead make both formulations mention the heel and declare it common in a **new** package version.

## Resolved producer export

Keep the existing formulation result and add a private, versioned `public_content` member when this capability is explicitly enabled:

- `schema`, source/metadata hashes, concept/pool/formulation identity;
- `mapping_status` (`complete` or `unmapped`) and the chosen assertion IDs;
- resolved assertion records: semantic ID, kind, subject/entity/component IDs, authority, value or proposition, status, inherited unit and required resolved qualifiers;
- catalog field dependencies for truth/validation and qualifier resolution, separately from communicated assertions;
- review/reviewer attribution where applicable.

The records are deterministic for the selected formulation and bound entities. No text searching, extra random draws, sampled winner annotations or inferred first-hand status. This envelope is a private producer export for composition/validation; strip it from all browser payloads and serving roots. An unmapped historical result can still render ordinary prose, but cannot establish assertion-level coverage through this interface. Unmapped does not mean the prose told the shopper nothing.

An adapter emitting structured facts uses the same field/subject/unit/qualifier definitions and registers assertions for the actual rendered field values. It need not route every table row through a prose pool. Dynamic price, stock and quote assertions must bind authoritative listing/quote state, not a product MSRP; their owners register those fields separately using the same identity and scope conventions.

## Publication, omission and inference

The website adapter produces a private publication ledger bound to world/source/adapter/render revision. Each occurrence records resolved assertions and a reachable surface/location. Published content may require ordinary interaction, such as expanding a details section. Planned disclosure alone is not proof that the renderer actually realizes it; validate the chosen text/details/controls against the plan. A whole block cannot be credited when only a truncated sentence communicates part of it.

If a site-wide omission excludes a meaning, reject a prose block that would communicate it or select an eligible alternative using the same omission-aware contract. Hiding a specification row while leaving the fact in descriptions, filter values or browser JSON is not omission. Retaining the other, nonomitted assertions elsewhere is allowed. Operational identity, choices, prices and checkout quotes follow their mandatory contracts; optional content omission does not remove them.

No general natural-language or catalog inference engine is part of this first slice. Inference credits require a separately registered, versioned rule with publicly available premise assertions, correct subject/qualifiers, conclusion and accepted authority. A mere applicability condition is not that rule. Without a supported rule, credit only the declared directly communicated assertions. This restriction does not prohibit ordinary reasoning by the shopping agent.

Task/evidence validation joins this ledger across discoverable sources. It checks the relevant candidates or valid public bounds/exclusions, not only the winning SKU. Private truth establishes canonical matching; published evidence establishes what can be justified. Genuine no-match and task-permitted uncertainty remain possible. Missing adapters or unmapped content cannot silently change an exact task into uncertainty or delete difficult candidates.

Fact-span instrumentation reuses semantic/subject/qualifier identity and adds exact text occurrences plus effective state. A substituted-value span is not proof of the complete assertion, its label or required qualifiers. Fixed prose can be public evidence even before span instrumentation supports it; its instrumentation status stays unknown. No need for a visible DOM element or explanatory badge per assertion.

## Catalog-author handoff and acceptance gates

For each new concept, add a concise prose assertion audit before writing the sidecar: public fields and scope, required measurement/component qualifiers, which claims each description/review pool actually states, and any formulation-specific extras. Shared family metadata can be reused with explicit source pins and validated overrides. Keep simple products simple. Review statements must retain their existing topic, polarity, context and attribution; no new explicit “I have first-hand experience” wording is required.

Prepare the companion alongside the authored concept without editing the shared compiler. Do not mark the new capability production-ready using the existing compile-only check. Existing frozen concepts should enter an explicit later migration queue; the walking-shoe example is the first compatibility fixture, not permission to mutate pilot pins. Coordinate any acceptance-gate change through Product first.

The first implementation acceptance must cover:

1. Fixed prose without slots, guard-only facts, common assertions and a chosen extra; the two walking-shoe formulations credit different heel coverage.
2. False predicate, unknown/not-applicable handling, invalid field/reference/index, incomplete mappings and source-hash mismatch.
3. SKU/product/component scope, measurement-basis/unit qualifiers, and reported versus first-hand review attribution.
4. An omitted fact surviving in prose/filter/payload is rejected; allowed equivalent disclosure remains valid and discoverable.
5. Adding equivalent formulations leaves semantic probability unchanged; the publication ledger binds the actual selected wording.
6. Old unannotated packages remain readable without retroactive credits; private metadata does not enter browser output; producer/consumer versions are frozen together.

These are implementation gates, not tests claimed to have passed already. No model calls or historic-host changes are authorized by this decision.

## Pinned contract fixture

The companion and resolved examples are in `.local/coordination/website-product-public-content/walking-shoes-public-content-v1.json` and `walking-shoes-public-content-example.json`. Reproduce the narrow reference/type/truth/formulation check with `PYTHONPATH=. python3 .local/coordination/website-product-public-content/check-contract-example.py`. It samples one fixed seed, enumerates both existing wording choices and checks their three versus four declared assertions. It does not implement the shared validator or prove arbitrary English entailment. The full package remains unmapped outside this audited introduction; do not claim complete catalog coverage from this fixture.
