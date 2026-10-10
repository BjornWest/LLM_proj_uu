# Executable product packages v1

Implemented 2026-10-01 by Product. This is the authoring execution contract, separate
from production shopping engines, task samplers and existing published worlds.

## Entry points and files

- `environments/product_world/product_package.py`: `ProductPackage(document)`,
  `ProductPackage.load(path)`, `.sample(seed, inputs=..., overrides=...)`,
  `.formulate(pool_id, entities, seed=..., occurrence=..., usage=...)`,
  `.group_listings(entities, listings, policy)` and `.programs[name]`.
- `product_expressions.py`: typed, restricted expressions; no `eval`/`exec`.
- `product_package_check.py`: compile and sample every requested seed, without
  searching for successes, retries or repairing outcomes.
- `data/product_packages/footwear.walking_shoes.json` and
  `footwear.walking_sandals.json`: exported reference packages. Never regenerate
  these over an authored modification automatically.
- `product_package_pilot.py`: explicit opt-in legacy-consumer adapter
  `sample_ported_product(...)`; old factories/hosts remain unchanged.
- `data/product_package_examples/simple_bag.json`: **synthetic compiler fixture**,
  not an accepted replacement-bag specification or width coverage.

The JSON root has `schema_version: "product-package-v1"`, `concept_id`, `fields`,
`steps`, `rules`, `language`, `bindings` and optionally `programs`. Domain rationale,
source URLs, scope/theme memberships and unimplemented consumer mappings belong in
explicit `metadata` with their support status. Compilation does not automatically
register them with retailer allocation, tasks, grading or a site renderer.

## Fields, expressions and ordering

Fields use dotted entity paths. Types: boolean, integer, number, string, enum
(`values`), array/set (`items`), object (`properties`, optional). Numeric fields may
have a `unit`, `min`, `max`. Collections have `min_items`, `max_items`.
`input: true` declares a caller input; `optional: true` allows it to be absent.
`constant` has no random draw. `unknown_values` marks explicit unknown sentinels.
`applicable_when` produces a `not_applicable` status when false. Inputs, constants
and draws cannot overwrite one another or overlap through object parents.

Expressions support literals, declared references, comparisons, membership, boolean
operators, arithmetic and conditional expressions. Pure helpers are `len`, `min`,
`max`, `sum`, `str`, `slice`, `flatten`, `coverage_groups`, `known`, `applicable`.
There are no imports, attribute introspection or arbitrary function calls. Adding
and comparing numeric references requires compatible units; unitless numeric
literals may supply coefficients or a field's domain bound. Unknown is distinct
from false and not applicable. Required unresolved references fail explicitly;
`known`/`applicable` provide explicit status tests. Serialized status envelopes are
reserved and remain unavailable evidence when passed back to an expression.

Write steps in dependency order. Compilation rejects missing/later/cyclic references;
it validates order rather than silently sorting it. `id` is unique throughout a
program. Each step is exactly one `sample`, `derive`, `for_each` or `emit` operation.
A condition's effect is determined by its enclosing declaration, never by prose.

`rules` have an `id`, a boolean `require` expression and optional boolean `when`.
A failed rule is an error, **not** an automatic retry or a SAT search. Use finite
joint bundles or conditional manufacture draws to produce coherent combinations.

## Draws and manufactured variants

See [sampling reference](product-sampling-methods.md) for methods and exact details.
Parameters can reference earlier typed fields. Zero conditional cases uses baseline;
one replaces parameters; multiple matches fail. Cases cannot change step identity,
target or method. Soft `adjustments` multiply named option weights.

Loops use `for_each: {"binding": "group.colour", "from": "product.colours"}` and
nested `steps`. Bindings must be declared `group.*` fields. Local draws also write
`group.*`; `emit` appends a record of expression-bound fields to a declared global
array. Loops are bounded at 10,000 source elements. A filtered emit can use `when`;
a required producer emitting nothing fails. Invalid Cartesian combinations can be
avoided with joint allowed bundles, per-group conditional coverage or guarded emits.
An omitted combination is not automatically a claim of physical impossibility.

Sets are sampled without replacement and serialize in canonical sorted order.
Selection order remains trace only. SKU rows must have unique `sku_id` and their
owning `product_id`; every row represents one exact manufactured configuration.
Retailer allocation/listing/stock are subsequent stages.

A SKU field's `retail_presentation.allowed` can contain `selector`, `separate_page`
and/or `description`. Grouping policy is chosen by a retailer from eligible roles;
`.group_listings` partitions only carried canonical SKUs, includes sold-out ones,
and permits selectors with nonoverlapping sizes. Listing facts cannot replace
canonical SKU facts. Presentation never changes what was manufactured.

## Meaning and text

A language pool has `id`, `meaning`, optional `when`, optional `slots`, and nonempty
`formulations` (strings or `{text, weight}`). Meaning kinds: `catalog_fact`,
`customer_experience`, `task_requirement`, `memory_preference`, `name`.
Customer experience requires `aspect`, `polarity`, `context`, `source`; it is not an
objective product fact. Catalog predicates must hold before rendering.

Slots map simple placeholder names to typed expressions. A formulation may use a
subset of the pool's slots; all placeholders must have bindings, and each binding
must be used somewhere in the pool. Only plain placeholders and numeric `:g` are
supported. Resolve only the selected formulation's slots. Unavailable evidence
cannot become printable prose. `.formulate` returns meaning/context/provenance,
selected realization and slot values separately from text. Select meaning first;
more paraphrases never increase the meaning's sampling probability. An optional
usage counter softly downweights previously used formulations.

Task/memory/store/filter/shipping bindings have `id`, `role`, typed `predicate` and
explicit support status. They are validated and exported; **automatic task-sampler
or grader registration is not implemented here**. Task variables/entity resolution
remain the existing world/task compiler's responsibility.

## Separate review programs and common policies

`programs` maps stage names such as `review` to self-contained field/step/language
programs, sharing schema version and concept identity. Each declares its required
inputs explicitly; stages cannot recursively define more stages. Access them with
`package.programs['review']`. Pass generated product/profile/SKU data as input and
use a distinct seed/stream per reviewer. A review program does not regenerate the
product or overwrite its facts. This same mechanism can describe another isolated
consumer stage without inventing a new expression or sampler language.

Shared `rating` sampling calls the existing shifted beta-binomial with concentration
**1.5**. `review_topics` calls the existing protected-value policy: variable statement
counts including zero, value frequency insulated from number of other topics,
budget execution increases value mentions, premium execution decreases them,
mainstream has no execution-dependent shift. The extreme frequency ratio is **1.5**.
Sentiment is a separate authored draw, commonly conditional on the sampled rating,
profile and applicable facts. A silent review still contributes its sampled rating.
Statement order/contrast composition can reuse `footwear_context_pilot.compose_review`;
do not create a fixed price-first convention.

The synthetic fixture demonstrates the APIs, not complete realistic review content.
Every accepted domain package must cover its selected topics with applicable
meaning/polarity pools or explicitly mark a topic deferred. Customer contexts and
exact tested SKU binding must survive consumer export. Topic selection, star draws
and prose generation are separate; latent execution is never public evidence.

## Small reproducible checks

```bash
.venv/bin/python -m environments.product_world.product_package \
  environments/product_world/data/product_package_examples/simple_bag.json --compile-only
.venv/bin/python -m environments.product_world.product_package_check \
  environments/product_world/data/product_package_examples/simple_bag.json \
  --inputs environments/product_world/data/product_package_examples/simple_bag.inputs.json \
  --seeds 0 1 2 3 --output .local/product-width/acceptance/simple-bag.json
```

For a new concept, supply its own required inputs and domain assertions. The checker
also runs declared stages using generated context plus explicit `--program-inputs`
when needed. It does not silently invent a missing SKU or user fact. Save prose
rationale, JSON package, input fixture, acceptance output and a small semantic test.

Pilot compatibility is checked over seeds 0–19 for both concepts: profile, facts,
reference price, widths/colours/base sizes agree with the original. Canonical
unordered colour representation can change exact sparse SKU draws for the same
seed; no claim of byte-for-byte world equivalence is made. The explicit adapter
also works with existing retail-content and review consumers. No historical world,
public host or frozen task is rebound by this implementation.

## Shared modules by inheritance

`extends` names one JSON package in the allowed authoring directory. Fields merge by
path; new steps append; `replace_steps` maps an inherited step ID to a complete
replacement. Rules, language and bindings append, so their IDs must remain unique.
Cyclic imports, duplicate JSON keys and paths escaping the allowed root are errors.
Use `ProductPackage.load(path, allowed_root=...)` for a deliberately broader package
root. Keep shared family/value pools and concept files together for the ordinary
CLI. Do not treat unrecognized Python callbacks as DSL modules.
