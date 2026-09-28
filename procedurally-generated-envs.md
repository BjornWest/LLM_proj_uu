# Procedural Browser-Commerce Environment Plan

## 1. Motivation

Existing browser-agent benchmark pages and tasks are not a good fit for this project.

The current Qwen model plus custom browser harness already solves many existing tasks too easily, while the available tasks also do not adequately represent the shopping behavior we want to study. In particular, there is little useful source material for price-aggregator-driven shopping tasks where the agent must follow retailer links and determine whether the apparent cheapest offer is actually valid.

Real shopping tasks contain recurring complications:

* stale aggregator prices or availability
* wrong product/SKU links
* unavailable variants
* VAT differences
* different currencies
* shipping fees
* destination restrictions
* package-size/configuration differences
* membership-only pricing
* optional or mandatory add-ons
* prices revealed only in cart or checkout
* misleading default variants
* returns and other user preferences

Hand-authoring enough complete retailer websites would require too much Codex usage and would limit dataset diversity.

The proposed solution is a **procedural commerce environment** in which a relatively small number of high-quality storefront implementations can render effectively unlimited generated shopping scenarios.

The important principle is:

> Generate the underlying shopping reality first, then generate ways for the browser agent to discover that reality.

Websites are interfaces into the simulated world rather than being the source of truth themselves.

---

# 2. Overall Architecture

The environment should be hierarchical.

```text
ROOT SEED
    │
    ├── Scenario / task skeleton
    │
    ├── Shopping world
    │
    ├── User profile and initial memory
    │
    ├── Aggregator knowledge
    │
    └── Renderer/presentation configuration
                │
                ↓
         WORLD MANIFEST
                │
     ┌──────────┼───────────┐
     ↓          ↓           ↓
 Aggregator   Retailers   Task prompt
 renderer    / websites
     │          │
     └──── Browser environment
                │
                ↓
             Agent
                │
       ┌────────┴─────────┐
       ↓                  ↓
 task actions       memory actions
       │                  │
       └────────┬─────────┘
                ↓
      deterministic verifiers
```

All stochastic components should ultimately be reproducible from the root seed, but separate generator components should use **independent RNG namespaces**.

For example:

```text
hash(seed, "task_shape")
hash(seed, "products")
hash(seed, "offers")
hash(seed, "shipping")
hash(seed, "aggregator")
hash(seed, "user")
hash(seed, "store_3", "layout")
```

Do not use one sequential RNG stream for the entire generator. Otherwise adding an unrelated random decision to a menu could alter prices, inventory, or the correct solution.

The generated manifest should also be materialized and stored rather than relying only on the seed.

Example:

```text
scenario_38142.json
```

This makes scenarios inspectable, reproducible and searchable and allows the generator implementation itself to evolve without silently changing old evaluation cases.

Generator version should also be recorded.

---

# 3. Scenario Skeleton: Supporting Different Task Shapes and Scales

Different shopping tasks can require very different amounts and patterns of browsing. This should not require separate world implementations.

Before generating detailed world state, generate a **scenario skeleton** defining the coarse structure of the episode.

Possible properties include:

```yaml
task_archetype: cheapest_valid_offer

product_count: 1
retailer_count: 7
offers_per_retailer: 1

required_output_count: 1

target_browser_breadth:
  min_retailers: 3
  max_retailers: 7

navigation_depth: medium
information_dispersion: high
target_difficulty: hard
```

Another task could use:

```yaml
task_archetype: top_k_recommendations

product_count: 15
retailer_count: 10
required_output_count: 3

comparison_dimensions:
  - landed_price
  - size
  - return_policy
```

The skeleton controls **topology and scale**, while the normal world generator supplies the actual facts.

Useful dimensions include:

* number of products
* number of retailers
* offers per retailer
* number of relevant versus distractor offers
* number of required recommendations
* branching factor
* expected retailers that need inspection
* navigation depth
* amount of information hidden behind interaction
* number of product variants
* number of relevant user preferences
* number and type of aggregator discrepancies
* number of plausible but invalid offers

This allows small and large tasks to share the same procedural foundation.

Possible task archetypes include:

* find cheapest valid offer
* return top K valid offers
* compare several product variants
* find cheapest option satisfying user constraints
* choose among several related products
* buy several products
* minimize total landed price across a shopping list
* compare split-order versus single-retailer purchases
* use an existing membership correctly
* update a user preference and then apply it
* distinguish temporary task overrides from durable preferences

The generator should use constraints or rejection sampling to ensure tasks are solvable and satisfy the intended structure.

A top-3 task, for example, must contain at least three valid answers.

---

# 4. Shopping World as Ground Truth

The shopping world contains facts independently of how websites display them.

Core entity types should include at least:

## Product

```yaml
product:
  canonical_id: shoe_183
  family: footwear
  brand: generated_brand
  model: generated_model

  attributes:
    color: grey

  variants:
    size:
      - 47
      - 47.5
      - 48
```

Other product schemas could include:

### Clothing

* size
* fit
* color
* gender/category
* condition

### Electronics

* model
* storage
* memory
* color
* regional version
* bundled accessories
* condition

### Consumables

* package size
* unit count
* flavor/type
* subscription versus one-off purchase

Product identity and equivalence rules must be explicit so that verifiers never need to semantically guess whether two items count as the same product.

---

# 5. Retailers and Offers

Retailer identity should generally be independent from the product categories they happen to sell.

A retailer contains behavioral policies such as:

* currencies
* destination support
* VAT behavior
* shipping calculations
* membership schemes
* free-shipping thresholds
* return policy
* account requirements
* checkout behavior

Offers contain actual commercial state:

```yaml
offer:
  retailer: retailer_7
  sku: sku_14321
  product: product_18

  variant:
    size: 47.5
    color: grey

  base_price: 168
  currency: EUR

  inventory: 0
```

Shipping, fees and other conditions may live in retailer rules rather than directly on individual offers.

---

# 6. Aggregator as an Imperfect View of the World

The aggregator should not simply copy current retailer state.

It maintains its own potentially stale or incorrect knowledge:

```yaml
aggregator_listing:
  retailer: retailer_7
  linked_offer: offer_92

  claimed_price: 159
  claimed_currency: EUR
  claimed_stock: true
  claimed_shipping: free

  linked_url: ...
```

Meanwhile the real offer might contain:

```yaml
price: 168
inventory: 0
```

This naturally produces:

* stale prices
* stale availability
* omitted shipping
* incorrect variants
* wrong SKUs
* outdated promotions

The aggregator is therefore useful as an index but cannot always be trusted.

---

# 7. Commerce Complications / "Annoyances"

Annoyances should not necessarily exist as one post-generation injection step.

Instead, complications emerge from properties and relationships in the generated scenario.

They may exist at several layers.

## World-state complications

Examples:

* variant unavailable
* destination unsupported
* wrong SKU
* product refurbished
* membership required
* minimum-order threshold
* different package quantity

## Aggregator discrepancies

Examples:

* stale price
* stale inventory
* wrong shipping assumption
* wrong variant association
* outdated promotion
* incorrect product mapping

## Retailer behavior

Examples:

* shipping known only after destination entry
* stock checked only on Add to Cart
* membership discount applied during checkout
* VAT added later
* incompatible options disabled only after another selection

## Presentation

Examples:

* "from €99"
* default variant differs from requested variant
* subscription price visually emphasized
* size selection implemented through buttons, dropdowns or modals
* shipping shown through accordion, cart, modal or checkout

A semantic condition should ideally have **multiple possible UI realizations**.

For example:

```text
shipping_requires_destination
```

could manifest as:

* product-page shipping calculator
* cart estimator
* country/postcode modal
* checkout step
* inline widget

This prevents the model from learning one DOM pattern as synonymous with one semantic condition.

---

# 8. Store Behavior Versus Store Presentation

Store behavior and UI layout should be kept separate where practical.

Example world fact:

```text
size 47.5 has zero inventory
```

Store behavior might specify:

```text
inventory is checked only during add-to-cart
```

UI renderer A might display the error in a modal.

UI renderer B might redirect to the cart and show an inline warning.

UI renderer C could update an inventory message next to the selector.

All expose the same underlying truth differently.

---

# 9. Storefront Diversity

The goal is not simply visual diversity.

Because the browser agent can inspect page structure, important variation includes:

* DOM hierarchy
* navigation structure
* product-page organization
* SPA versus multi-page behavior
* URL structure
* forms
* variant selectors
* menus
* modals
* cart drawers versus cart pages
* accordions
* shipping calculators
* stock presentation
* checkout flows
* naming and labels
* product-card structure
* tables versus grids versus lists
* information placement

A relatively small number of genuinely different store architectures may be sufficient initially.

A possible MVP target is approximately 3–5 strongly different storefronts, eventually growing toward roughly 5–8 or more.

Each should be able to render arbitrary compatible retailers/worlds rather than being tied to one generated store.

Teams of coding agents can build independent renderer implementations against a common contract.

---

# 10. Renderer Contract

Storefront developers should not control underlying commercial truth.

For example:

```text
Renderer MAY decide:

- navigation
- DOM structure
- labels
- visual layout
- widgets
- interaction patterns
- information placement

Renderer MAY NOT decide:

- actual price
- inventory
- product identity
- VAT
- shipping eligibility
- shipping cost
- membership state
```

The renderer queries those facts from the scenario/store backend.

This makes independently authored storefronts interchangeable.

---

# 11. Avoiding Information Leakage

Truth unavailable to the shopper must stay server-side.

Do not generate:

```html
<script>
window.offer = {
  actualStock: false,
  shippingToSweden: 14.99
}
</script>
```

and merely hide it visually.

A source-reading agent will exploit it.

Likewise avoid semantic test identifiers such as:

```text
data-testid="wrong-sku"
```

The verifier can access privileged scenario state; the browser cannot.

This needs dedicated automated testing.

---

# 12. User Profiles and Persistent Memory

User state should be sampled independently from shopping-world state wherever possible.

The internal canonical representation can be structured:

```yaml
user:
  sizing:
    shoes:
      preferred: 47.5
      acceptable_range: [47, 48]

  commerce:
    allow_membership_signup: false

  interaction:
    recommendation_count: 3

  preferences:
    return_window:
      direction: maximize
      strength: tiebreaker
```

This canonical representation gives deterministic semantics and is easy to inspect.

However, the agent need not receive the profile as raw structure.

Structured preferences can be rendered into natural language using:

* predetermined paraphrase templates
* multiple formulations per preference
* potentially an LLM during data generation

For example, the same semantic state could surface as:

> I generally prefer stores with longer return periods.

or:

> If everything else is equal, the better return policy is a plus for me.

The structured representation is the ground truth; prose is a presentation layer.

---

# 13. Hybrid Memory Design

A useful split is:

## Structured user profile

Best for mutable current state such as:

* sizes
* membership status
* persistent constraints
* output preferences
* explicitly modelled feature preferences
* willingness to perform certain actions

## Flexible episodic/prose memory

Useful for contextual or difficult-to-schema information.

Examples:

* previous interaction summaries
* unusual personal context
* one-off experiences
* facts not yet promoted into profile fields

The system should not force every possible memory into a predetermined schema.

The structured profile primarily exists where deterministic interpretation and mutation are useful.

---

# 14. Memory Operations

The environment should support actual CRUD-like memory behavior.

Examples:

```text
memory.create(...)
memory.update(...)
memory.delete(...)
memory.query(...)
```

Seeded scenarios can introduce memory events such as:

* create
* update
* delete
* reaffirm
* temporary override
* irrelevant statement that should not become memory

Example:

Initial state:

```yaml
acceptable_shoe_size: [47.5, 47.5]
```

User says:

> Actually, sizes 47 through 48 are fine for me.

Expected mutation:

```text
[47.5, 47.5] -> [47, 48]
```

Another example:

> For this purchase only, refurbished is fine.

should modify the current task state but **not persistent memory**.

Likewise:

> This pair is for my brother; he wears size 43.

must not overwrite the user's own shoe size.

These negative cases are important.

---

# 15. Memory Verification

The generator should know:

```text
initial memory
user utterance
expected semantic delta
```

Example:

```yaml
expected_delta:
  update:
    key: sizing.shoes.acceptable_range
    from: [47.5, 47.5]
    to: [47, 48]

  create: []
  delete: []
```

The verifier compares actual state changes with expected changes.

Verify the **delta**, not merely whether the final desired field exists.

This allows detection of:

* missing updates
* incorrect updates
* stale contradictory values
* unnecessary memories
* accidental overwrites
* inappropriate persistence of temporary information

If free-text memory is supported, the training system should avoid rewarding one canonical prose formulation.

Structured semantics and/or downstream behavioral verification should determine reward instead.

---

# 16. Token Regularization and Memory

The project plans to penalize unnecessarily long agent solutions.

Tokens used specifically to perform legitimate memory maintenance should **not count toward the ordinary solution-length/token regularizer**.

Otherwise the model receives conflicting incentives:

* maintain useful memories accurately
* but minimize the amount of memory information written

Memory quality should instead be governed by its own objective and sensible storage limits.

Pathologically long or irrelevant memories can be penalized separately if necessary.

This should make the task-length regularizer largely agnostic to whether the agent chooses concise structured memories or richer free-text memories.

---

# 17. Hard Constraints Versus Soft Preferences

Do not collapse all user preferences into one arbitrary scalar utility function.

Instead use a partial/lexicographic ordering.

Conceptually:

```text
1. satisfy hard constraints
2. satisfy explicit current task
3. apply explicitly quantified tradeoffs
4. apply soft preferences/tiebreakers
```

Examples:

Hard:

> Never buy refurbished.

Soft:

> I prefer longer return periods.

Quantified tradeoff:

> I'm willing to pay up to €10 more for at least 30-day returns.

This avoids inventing arbitrary exchange rates such as:

```text
7 return days = €3.43
```

---

# 18. Verifying Soft Preferences

The verifier should test observable behavior rather than trying to determine whether the model "thought about" a preference.

Example:

```text
A: €80, 14-day returns
B: €80, 30-day returns
C: €84, 60-day returns
```

Task:

```text
Find the cheapest option.
```

Memory:

```text
Prefer longer returns when otherwise equivalent.
```

Then:

```text
B > A > C
```

The oracle can define a comparator:

```text
compare(A, B, task, user_profile)
    -> A_BETTER | B_BETTER | EQUIVALENT
```

For top-K answers, pairwise ordering can be checked.

If the preference would not change any observable decision, no reward should be given merely for mentioning it.

A useful automatic relevance check is counterfactual:

```text
answer_with_preference
versus
answer_with_preference_removed
```

The generator can classify preference influence as:

* irrelevant
* changes ordering
* changes top-K membership
* changes optimal choice

This also creates useful evaluation metadata.

---

# 19. Generating Natural Preference-Relevant Cases

If prices are sampled independently from a continuous distribution, exact price ties will almost never occur.

Real retail prices are not distributed like that.

Generate realistic price structure using:

* shared MSRP
* discrete currency units
* common price endings
* retailer markups
* standard discounts
* promotions
* marketplace price clustering

This naturally produces equal or near-equal prices and creates more situations where preferences such as returns become relevant.

The generator may deliberately increase the frequency of such cases, but should avoid making every preference artificially decisive.

Some memories should be:

* decisive
* tie-breaking
* relevant but overridden
* completely irrelevant

Otherwise the model learns that every remembered preference is necessarily a puzzle clue.

---

# 20. Deterministic Task Oracle

The verifier should operate directly on privileged world state.

For example:

```text
best_valid_offer(
    world,
    task,
    user_profile
)
```

It can evaluate:

* exact product identity
* acceptable variants
* inventory
* destination availability
* total landed cost
* VAT
* shipping
* required membership state
* user constraints
* preference ordering

The oracle should not inspect screenshots or infer facts from webpage text.

The webpage is for the agent.

The manifest is for the verifier.

---

# 21. Reward Design

Prefer rewarding outcomes rather than prescribed browsing processes.

Potential components:

```text
R_task
R_preference_behavior
R_memory_state
R_efficiency
```

Examples:

### Task reward

* correct SKU
* correct retailer
* valid variant
* correct landed price
* correct top-K membership
* correct ordering

### Preference reward

Only active where preference affects the oracle relation.

### Memory reward

* required updates performed
* stale values replaced
* no inappropriate mutations
* no unnecessary writes

### Efficiency reward

* shorter successful trajectories
* reduced redundant browsing
* token efficiency

Memory-write tokens should be excluded from the ordinary task token regularizer.

Avoid rewards such as:

> visited at least three stores

unless the process itself is genuinely part of the task.

The objective should reward solving the problem, not imitating an expected trajectory.

---

# 22. Difficulty Control

The generator should explicitly expose difficulty parameters.

Possible dimensions:

* retailer count
* product count
* number of plausible offers
* number of invalid attractive offers
* aggregator accuracy
* number of hidden fees
* information dispersion
* checkout depth
* number of interactions needed
* DOM complexity
* amount of irrelevant content
* number of relevant memories
* preference complexity
* task output size
* top-K size

A generated scenario can therefore carry metadata such as:

```yaml
difficulty:
  breadth: 7
  expected_interactions: 18
  misleading_offers: 3
  hidden_information_depth: 2
```

Actual stock-model pass rates can later be used to calibrate or replace these hand-designed difficulty estimates.

This fits naturally with curriculum learning and GRPO task filtering.

---

# 23. Procedural Scale

Large tasks do not require a fundamentally different environment.

The generator can use the same entities at different cardinalities.

If necessary, generation can become hierarchical or lazy:

```text
scenario
  → retailer groups
    → retailers
      → catalog sections
        → products
          → variants
```

However, for early versions it is probably preferable to materialize the entire relevant world into a database/manifest for easier reproducibility and verification.

The important distinction is:

> Task shape determines how much world needs to exist; it does not redefine what a world is.

---

# 24. Independence and Coherence

Factors should be independent wherever independence is realistic and useful.

Examples:

* user profiles should not predict retailer layout
* stale aggregator data should not imply one renderer
* VAT complications should not always appear in one store type
* return-policy preferences should not correlate with product category without reason

However, independence should not be forced where domain semantics require correlation.

For example:

* shoe products need size variants
* electronics may expose capacity configurations
* certain checkout mechanisms may be retailer-wide policies
* package quantity matters primarily for relevant product classes

The correct goal is **conditional independence where possible**, not unconditional random mixing.

---

# 25. Generator Auditing and Shortcut Prevention

This should be designed from the beginning.

For generated datasets, record frequencies of:

* renderer
* product category
* task archetype
* complication type
* aggregator discrepancy
* user preference
* memory event
* correct retailer
* difficulty
* task scale

Also inspect combinations.

Example dangerous shortcut:

```text
80% of stale-price cases happen on renderer C
```

The model can then exploit renderer identity rather than reasoning about price.

Other possible accidental correlations:

* one retailer is disproportionately correct
* membership cases appear mostly for electronics
* hard tasks mostly use one layout
* wrong-SKU offers share one DOM pattern
* one wording template correlates with one expected memory action

Procedural diversity is only useful if these shortcuts are controlled.

---

# 26. Dataset Splits

Procedural generation does not automatically guarantee meaningful generalization.

Maintain several evaluation regimes.

## IID

New:

* seeds
* prices
* names
* products

but familiar component distributions.

## Compositional OOD

Known components, but novel combinations.

Example:

* known renderer
* known shipping rule
* known membership mechanic

combined in a pattern never present during training.

## Behavioral OOD

Withhold entire implementations of semantic behaviors.

Example:

Training exposes shipping calculation through:

* cart
* accordion
* checkout

Evaluation introduces:

* shipping modal

## UI OOD

Withhold complete storefront architectures.

This tests whether the model learned commerce/browser reasoning rather than template-specific patterns.

## External/manual evaluation

If time permits, include a small set of manually authored or real-world-derived tasks to test transfer outside the generator.

---

# 27. Quality Assurance

Every generated scenario should pass checks before use.

Examples:

* requested product exists
* enough valid answers exist
* oracle has a unique answer when uniqueness is required
* top-K task has at least K valid options
* no impossible product configuration
* no incoherent shipping rules
* no privileged data exposed client-side
* retailer renderer faithfully represents underlying state
* aggregator discrepancy matches manifest
* memory mutation expectation is internally consistent

Use automated property tests heavily.

Renderer contract tests should verify that identical world facts remain semantically consistent across different storefront implementations.

---

# 28. Initial MVP

Do not attempt the full system immediately.

A useful MVP might contain:

* 1 price aggregator
* 3 structurally different retailer architectures
* 3 product schemas
* approximately 10 semantic commerce complications
* basic structured user memory
* several memory create/update/no-update cases
* deterministic cheapest-offer verifier
* top-K verifier
* seed namespaces
* materialized scenario manifests

Example product families:

* shoes
* electronics
* packaged consumable

Initial complications could include:

* stale price
* stale stock
* shipping not included
* destination unavailable
* wrong SKU
* wrong variant
* VAT difference
* membership-only discount
* free-shipping threshold
* stock discovered only after interaction

The milestone is:

> Given a seed, generate a coherent shopping scenario, launch all required websites, generate the user/task state, compute the ground-truth solution independently, allow the browser agent to act, and deterministically verify both shopping and memory outcomes.

Once that loop works, increasing product names, layouts, retailer names, products, complications and task scale becomes comparatively cheap.

---

# 29. Multi-Agent Development Strategy

Use coding agents primarily to build reusable infrastructure rather than individual dataset examples.

Good parallel workstreams include:

* aggregator renderer
* independent storefront renderer implementations
* product-schema library
* offer/world generator
* shipping/tax engine
* memory subsystem
* oracle/verifier
* generator QA/property tests
* UI variation/component library

All agents should work against shared typed interfaces/contracts.

A storefront-building agent should not need to understand the entire generator.

It should receive something like:

```text
Here is the Store API.
Here are the facts you may query.
Here are the behaviors this renderer must support.
Here are the facts you are forbidden to invent.
```

This maximizes reuse of Codex work.

---

# 30. Next Technical Questions

The next design phase should focus primarily on:

1. Exact world-manifest schema.
2. Task-skeleton/archetype schema.
3. Storefront API contract.
4. Stateful behavior needed for cart/checkout/variant interactions.
5. Which UI/DOM differences constitute meaningful browser diversity.
6. Product schemas for the first MVP.
7. Which complications need first-class world representation.
8. How renderer developers express different realizations of the same behavior.
9. Deterministic oracle implementation.
10. Memory CRUD interface and representation.
11. Generator validation/property testing.
12. Dataset-factor logging and correlation auditing.
13. Difficulty calibration against the stock Qwen checkpoint.
14. Exact train/validation/OOD split strategy.

The highest-value early prototype is not a large dataset. It is a small end-to-end generator proving that **one semantic world can be rendered through multiple structurally different storefronts and still produce exactly the same deterministic oracle result**.
