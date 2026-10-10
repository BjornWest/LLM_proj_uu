# Product specification authoring loop

## Current authorization — 2026-10-02

Bjorn removed recurring quota checks after the reset and authorized three authoring
lanes. Product now authors the kitchen-utensil family and remains design authority;
Curation independently reviews its packages before accepted coverage. One owner
per concept, three concepts maximum in flight and one shared publisher. Follow
`.local/coordination/product-width/third-lane.md` and the current section of
[overnight handoff](overnight-product-width-handoff.md). Earlier quota floors and
two-lane restrictions below are historical, not current instructions.

## Historical quota rule — PRODUCT-WIDTH-QUOTA-15

Bjorn explicitly extended the floor on 2026-10-01: continue until **15% remains**,
with a **16% guard** and **below-17% substantial-dispatch restraint**. This supersedes
older 20/21/22 thresholds and any earlier soft target that would stop sooner.
Keep two authoring lanes and existing fail-closed/window-change rules. Exact
implementation and deployment evidence: `.local/coordination/product-width/quota-extension-15.md`.


## Current parallel-trial exception — 2026-10-01

For `PRODUCT-WIDTH-PARALLEL-01`, Bjorn authorizes two complete concepts in flight. Preserve one author per concept and one owner per shared family module; establish/freeze common foundations before sibling authors use them. All research, prose, DSL, independent semantic review and functional gates below still apply. Curation serializes acceptance and integration. Follow `.local/coordination/product-width/parallel-trial.md` for the four-concept checkpoint and token/quality comparison; the earlier sequential wording is historical during this trial.

Authoring workflow recorded 2026-10-01. This guides Product and Curation after the
shared product-package implementation is accepted. It does not authorize model
experiments, paid services, deployment, or expansion of an agreed run list.

## Start with a family and one concept

Choose the family first, then work through one concept at a time. Establish what
merchants describe and what customers actually care about in that family using
existing knowledge and targeted real website examples. Browse when uncertain about
product reality or terminology. Record the source URL and the specific observation
it supports; a real example establishes plausible features and concerns, not a
sampling probability or a universal manufacturing rule.

Parallel helpers may research examples or review the current specification. Keep
one owner for the concept's authored specification and DSL conversion. Research
results should feed that owner's current concept rather than start competing family
notations or bulk authoring ahead of acceptance.

## Choose useful, verifiable semantics

Select clear task predicates and review topics from the merchant features and
customer concerns. They should make tasks nontrivial while allowing the available
facts or attributed customer evidence to establish the answer. Identify the evidence
needed for each predicate or topic and where a shopper can find it. A private latent
quality tendency is generation input, not visible proof of a shopper's requirement.

Preserve the distinctions among product facts, seller claims, customer experiences,
task requirements and saved preferences. Customer evidence retains its aspect,
context, polarity and source provenance. Review reports must support the task's
actual context; everyday comfort does not automatically establish long-walk comfort.
Keep product/SKU identity separate from retailer listing, price, stock and services.

Depth follows the product. There is no fixed quota of variant axes, review topics,
paraphrases or conditional draws. A simple concept can have a small specification;
a complex concept can need joint choices and more conditional relationships.

## Cross-reference, then write the prose specification

Cross-reference the source observations and prior product specifications before
writing the new prose specification. Reuse established concepts and modules where
their meaning fits, and explain where the new concept differs. Do not carry prior
product facts or assumptions into a different concept merely because its structure
looks similar.

The prose specification should explain the intended product, its relevant facts and
variant choices, applicable restrictions, customer concerns, evidence and proposed
tasks. Give rationale for the chosen relationships and sampling assumptions.
Separate physically prohibited combinations from combinations this recipe happens
not to generate. Separate hard restrictions from soft weight associations. Describe
unknown and not-applicable states where they are needed instead of treating either
as false.

Record product-specific uncertainties in a questions backlog with the affected
concept and the decision needed. Continue independent work where those questions do
not block correctness. If a systemic ambiguity or implementation defect prevents
sound authoring across concepts, pause Curation's dependent authoring and raise the
blocker for Bjorn; do not multiply the unresolved convention across a bulk catalogue.

## Convert to the shared DSL and smoke-check

Convert the reviewed meaning into the shared
[product package notation](product-package-notation.md), using the
[sampling method reference](product-sampling-methods.md). Declare types and units,
stable IDs, explicit producers, dependencies and consumer bindings. Sample meaning
before formulation. Use registered references for stores and other consumers rather
than public-name substring matching.

Compile the actual package and sample a small reproducible set of local seeds.
Inspect complete values, applicability/statuses, joint bundles, subsets, effective
parameters, trace bindings, task predicates and formulations. Check that sparse
variants and retailer listing choices preserve canonical SKU facts. Confirm the
prose specification and executable result agree before accepting the concept and
moving to the next one. A successful smoke check demonstrates local compilation
and sampling, not model performance or deployed-site acceptance.

The local package entry point supports a compilation check followed by a sample:

```bash
.venv/bin/python -m environments.product_world.product_package path/to/concept.json --compile-only
.venv/bin/python -m environments.product_world.product_package path/to/concept.json --seed 0 --inputs path/to/inputs.json
```

Supply inputs required by that package; do not invent a shared default input file.
A failing smoke check returns to the same concept's specification or DSL correction.

## Review cadence when native wake is unavailable

The intended review cadence is hourly. If native scheduled wake is unavailable,
ask Curation to ping Product after every two accepted concepts so Product can review
the accumulated authoring. This fallback is a review trigger, not a quota of
concepts, topics or variants. It does not authorize restarting another agent or
claiming scheduled review without a functioning wake mechanism.

The [executable contract](product-package-executable.md) includes a fixed-seed
`product_package_check` command. Save an explicit input fixture, include declared
review stages, and add a small concept-specific test for meaningful compatibility,
review scope and prose/fact agreement. Generic compilation alone is insufficient
acceptance of a domain design. Sampling-method extensions remain Product-owned.
