# Canonical answer schema generation

Answer schemas should use a complete declared vocabulary when one exists.
The extractor maps unambiguous answer wording to a canonical option and keeps
its original quote. Validation checks vocabulary membership and provenance;
native grading compares the supplied option with the actual outcome.

`environments/website_world/canonical_claims.py` compiles enum and boolean
fact domains and variant declarations. A small bounded integer retail axis
(such as pack count 1–2), without units, steps or negative bounds, is an option menu; ordinary integer/decimal facts
remain literal numbers. Current string-valued claim APIs are preserved:
canonical labels are strings, including `true`/`false` for boolean fact cells.
Boolean retail labels use native `str()` tuple encoding. Field names cannot trigger
flat money/status special cases; immutable declaration lists are supported.
Missing values remain null with null evidence. An explicitly stated option outside
the domain uses `__unmatched_option__` with its original quote. It remains non-null
and must fail native matching; it must never be discarded as absent. Logical
unknown/NA fact sentinels belong to cell status with a null value. Retail tuple
labels retain their declared identity even when named unspecified.

The compiler reads full declarations already carried by the world or native
field contract. It does not inspect reference answers, SKU values, stock,
prices, matching sets, task predicates or winners. It includes legitimate
options that were not manufactured or sold in the current world. Mixed-product
basket domains union declarations; an applicable open declaration keeps the
field open. No extra product fields are exposed by this change.

Do not guess the closest label for out-of-vocabulary wording. Use the unmatched
marker for a definite assertion; genuine ambiguity remains an explicit ambiguous
interpretation. Do not convert units or size systems during normalization.
A valid but wrong option reaches native failure. A quote proves provenance;
extractor interpretation accuracy still requires its own regression checks.

## Audit and first implementation

The pinned accepted130 source snapshot was audited, including inherited
scalar fields, together with 19 schema-construction modules. Counts are field
occurrences across concepts, including shared inherited declarations; they are
not counts of unique features or publicly displayed rows.

- 1,687 enum and 1,937 boolean declarations.
- 3,556 finite fact domains and 73 compiled finite retail axes (including 5 bounded
  integer menus). Three further pack-count declarations carry units and retain
  literal validation under the conservative measurement rule. Public eligibility/task
  scope still controls extraction.
- 88 retail axes remain declared as strings; some have finite menus established
  elsewhere in sampling steps. This pass does not infer graph value domains.

| Area | Disposition |
| --- | --- |
| Status, verdict, delivery mode, interaction assertions | Already categorical in most schema builders; retain their existing enums/booleans |
| Product option labels | Shared compiler used by listed offers, product reviews, basket answers, shipping claims and variant links |
| Model comparison fact values | Per-field enum/boolean domains from native field declarations, with existing status/unit/basis separation |
| Quote, feature, memory, shortlist, relaxation, branch, unit-price callers | Inherit listed-offer domains; their identity/dependency versions identify the change |
| Names, opaque IDs, URLs, codes and addresses | Keep exact strings and native identity checks; do not enumerate expected targets |
| Prices, measurements, counts, means and durations | Keep numeric/money grounding; remaining string-valued numeric fact cells are a future typed-schema migration; constrained numeric sampling is not a categorical vocabulary |
| Sets/arrays, composite facts and ambiguous units/bases | Preserve existing formats; require a separate typed contract rather than flattening them into guessed labels |
| Legacy string axes with graph-defined menus | Next candidate: export complete producer domain metadata once during construction; avoid per-grader graph interpretation or per-sample narrowing |
| Comparison-stock and variant-reset capture-backed schemas | Still literal; apply the helper through their consumer/native owners in a later composition |
| Shared shopping response/factual-detail schemas | Audit identifies colour/travel-mode opportunities, but their generation is Harness/Evaluation-owned and remains unchanged in this release |

Legacy worlds without complete declarations keep literal validation. Existing
frozen releases, outputs and grades are unchanged. Source tests do not establish
extractor, browser, automatic lifecycle or prod acceptance; Evaluation owns those
prospective checks and must compose the exact shared `semantic_fields` dependency.

Detailed source pins and the full130 audit are under
`.local/coordination/canonical-answer-schemas-20261012/`.
