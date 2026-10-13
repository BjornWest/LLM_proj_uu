# Native answer validation boundary

Prospective contract for the eight affected Website task families. Frozen
recipes, source trees, outputs and grades keep their original implementation.
Actual source-bound lifecycle acceptance is separate from these local controls.

The extractor interprets the final answer: negation, conditions, ambiguity,
absence and categorical meaning. It returns schema-valid semantic values with
exact answer quotes. It must not use the native reference to correct an answer.

The validator checks schema, types, allowed categories, null/evidence consistency
and exact nonempty contiguous quotes. Literal identifiers, URLs, product options,
currency and amounts retain typed/decimal validity; counts retain integer validity.
Answer/evidence text is never reparsed for numeric or monetary meaning.
It does not independently classify English verdicts. A quoted sentence alone is
provenance, not a second semantic interpretation.

The native grader compares the supplied semantic values, identities, arithmetic
and state against the reference. Valid wrong claims fail the outcome checks;
malformed claims reject validation. Missing claims remain missing. Extractor
interpretation accuracy requires separate extraction regression checks.

| Family | Extractor-owned fields | Retained mechanical/native checks |
| --- | --- | --- |
| Shipping claims | `subtotal_test`, `assessment` | Quantity, counts, amounts/currency, offer and policy-route identity, native admitted menu |
| Product reviews | `verdict`, `mean_undefined` | Typed counts and finite means, subject/SKU, same-publication URL, native corpus arithmetic |
| Carrier reviews | `verdict`, `mean_undefined` | Typed counts and finite means, carrier, date/class scope, URL and native corpus arithmetic |
| Basket answers | `split`, `delivery_type` | Item/retailer/service identities, quantities, money, native feasible plan and objective |
| Model comparison | Row/status categories including unknown/NA and no models | Literal fields, value/unit/basis, subject/link identity, native field status; unknown/NA cannot invent values |
| Catalog statistics | `undefined` | Typed population count and finite statistic, currency, citation population, native aggregation |
| Review passages | Passage/no-match/uncertain status | Complete literal passage, exact reader-note route and native topic/subject matching |
| Variant links | `link_encodes_full_selection`, `recipient_must_select` | Exact URL, literal selected/manual options, independently bound recipient capability |

Normalized decimal fields (`mean_rating`, `statistic_sek`) use declared shared
`semantic_fields` to permit equivalent decimal formatting, then enforce finite typed decimal validity and authentic quotes. Validators do
not look for number or currency tokens in the quote. Correctness belongs to the
native comparison; interpretation accuracy belongs to extractor evaluation.

The retained public width alias allows `standard width` to identify native width
`standard`. Executable URL selectors remain literal menu values. Shipping policy
links admit `/info/terms` alongside `/info/shipping` and `/checkout`, with the
existing same-origin route, query and fragment restrictions. Neither correction
rewrites raw claims or repairs wrong native targets.

`undefined_rating_in_quote` remains a compatibility provenance helper only;
new callers do not use it. It proves a quote exists, not an absence assertion.
Categorical product-option schema expansion remains deferred.

The atomic consumer and variant-reset paragraphs below state the prospective
contract after separately owned Website dependencies are composed. Their source
cleanup is not included in this native/shared commit; until then those consumers
may retain the old answer parser. Neither this document nor source review claims
runtime adoption.

Atomic public facts will use extractor-supplied typed scalar/array values and
qualifiers. The consumer will check schema, null consistency and authentic
nonempty quotes. Canonical qualifier menus remain supported; without a menu,
the extractor interprets the stated configuration/scope rather than retaining a
presentation heading as part of the qualifier value. The modern native grader
now compares supplied values directly without stripping English labels; frozen
native bases already compare directly. The reviewed variant-reset dependency
uses the same extractor-owned Boolean boundary. Genuine observed state/action
objectives remain unchanged. Wrong extracted values fail native outcomes; an
erroneous extraction that coincides with the reference is an extractor-quality
issue, not something this validator reinterprets.

Regexes used for captured address normalization, native source/corpus syntax,
identifier/date syntax, runtime rendering and synthetic extractor test generation
are outside final-answer grading and retain explicit audit dispositions.
