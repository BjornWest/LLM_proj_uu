# Handoff: product-specific procedural commerce

You are helping design product families and their specific requirements for our procedurally generated browser-agent environments. Start with design/schema proposals; coordinate before modifying the shared generator, commerce engine or renderers. Another agent is currently implementing three independently composable checkout flows.

## Read these in order

1. `docs/procedural-commerce-tasks.md` — task families, outcome grading, ambiguity, user context and scope.
2. `docs/procedural-commerce-request-requirements.md` — 16 generic request families, navigation-stage requirements and shared capabilities. Extend these with product-specific requests.
3. `docs/procedural-commerce-dag.md` — sampling dependencies; commercial world, user/request and presentation branches.
4. `docs/shopping-comparison-challenges.md` — the user's real shoe-shopping experience: size/color mismatches, conditional offers, shipping, deadlines, currency and landed price.
5. `docs/agents/procedural-commerce-mvp.md` — what actually exists and its limitations. Its initial layout findings are superseded by `docs/agents/procedural-commerce-ax-designs.md`.
6. `docs/procedural-commerce-layout-catalog.md` and `docs/procedural-site-variation-rubric.md` — renderer designs and AX-visible diversity requirements.

For the broader proposal, read `procedurally-generated-envs.md` and `docs/procedural-commerce-design.md`. These describe ambitions, not all implemented functionality.

## Current implementation

`environments/procedural_commerce/` contains the generator, commerce engine, local four-origin runtime and website renderers. `data/curation/procedural_commerce/mvp/` contains the BrowserGym adapter, diagnostics and scripted acceptance tools. Current product data is intentionally simple, single-configuration household goods. Small/large presets have 12/96 products; the MVP implements compare, prepare-cart and purchase modes. Shoes, fit, device compatibility and category-specific configurations are not implemented yet.

There are three structurally distinct retailer designs and a separate checkout-flow increment in progress. Product extensions must be supported through renderer capabilities without making every site use the same component tree. Do not assume the procedural fixture is deployed on Vercel.

## Agreed principles

- Use canonical product and SKU identities. Distinguish product family, model, purchasable variant and retailer offer. A broad category alone is insufficient to define all attributes.
- Share typed capabilities/traits where sensible: footwear and clothing have fit-related dimensions; electronics configurations have different semantics. A person's shoe size is not analogous to a phone storage preference. Some products have no variant axis.
- Product-specific facts can affect tasks, user preferences, controls and hindrances. Never invent irrelevant fields simply to fit a universal product template.
- Sample products and reference prices with realistic correlation. Request parameters may depend on those and user context, but must not consult realized availability or cheapest offers to guarantee success. Infeasible requests are valid; do not rejection-sample worlds until a solution exists.
- Stock, delivery, destination eligibility and presentation remain distinct factors, with explicit conditional dependencies where realism requires them. Independent random streams do not imply statistically independent outputs.
- Grade outcomes and authorization. Reading a page or taking a particular path is a separate diagnostic, not a reward requirement. Keep hidden oracle facts outside policy-visible pages and requests.
- Hidden user preferences, specific clarification questions and answer fact extraction have been discussed, but user simulation and natural-language grading are not implemented in this MVP.
- Extensibility and meaningful AX structure matter more than decorative styling. Allow unsupported future fields to be absent; do not fabricate their values.

## Suggested first deliverable

Propose a small initial set of product families and a concise matrix of: canonical identity/variant fields; factual attributes; user requirements/preferences; applicable request types; realistic hindrances; sampling dependencies; retailer/aggregator UI requirements; deterministic outcome checks. Mark which traits are shared and which are family-specific. Use concrete examples such as exact shoe model/color/size versus a laptop with acceptable configuration ranges. Identify a minimal first implementation slice before writing code.

Read `AGENTS.md` and `docs/agents/coordination.md`. Send coordination messages only for ownership overlap, blockers or decisions—not routine progress.
