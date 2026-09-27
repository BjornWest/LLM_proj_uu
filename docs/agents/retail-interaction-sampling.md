# Retail interaction sampling

`environments/product_world/interaction_patterns.py` owns opt-in distributions,
validation and the synthetic destination alias. Curation owns connected shopping
rendering, runtime state and native browser acceptance. Patterns change how facts
are reached; they never change product membership, stock, prices or correct answers.
No task, winner or difficulty outcome enters the sampler.

## API and opt-in boundary

```python
from environments.product_world.interaction_patterns import attach_interaction_patterns
variant = attach_interaction_patterns(
    scenario, coverage=comparison_coverage, seed=42,
    config={'profile_weights': {'direct': .3, 'browse': .4, 'compact': .3}},
)
```

The function returns a deep copy with `scenario['interaction_patterns']`. Original
scenario contents are preserved exactly. Without the sidecar, legacy presentation
is unchanged. Alternatively call `generate_interaction_patterns(world, locations,
coverage=..., seed=..., config=...)` and attach the returned object yourself.
`validate_interaction_patterns` checks exact world, geography and coverage bindings,
complete site identity, allowed values and scope restrictions.

The `shopping-interaction-patterns-v1` export contains `source_world_sha256`,
`source_locations_sha256`, `source_comparison_coverage_sha256`, `destination` and
`sites`. World hash means `world['world_sha256']`; coverage hash means `digest(coverage)`.
Missing geography/coverage use null hashes. Without coverage the comparison ID is
`aggregator`; with coverage it is the exact supplied comparison site set.

Each site row has `site_id`, `kind` and these controls:

| Control | Values | Scope |
| --- | --- | --- |
| search_sections | boolean | Retail/comparison search groups with meaningful role/context distinctions |
| result_presentation | cards, list | Retail catalog presentation |
| offer_disclosure | inline, expand | Comparison retailer offer listings |
| specification_disclosure | inline, expand | Retail specifications |
| shipping_disclosure | inline, separate | Retail delivery information/working quote link |
| destination_form | none, single, split | Retail delivery-destination entry |
| related_limit | integer0–12 | Maximum working other-product links on retail pages |

Controls outside their site scope use neutral values. Related links must use actual
available targets, even if fewer than the requested limit exist. Search section
labels and ancestor roles distinguish navigation, suggestions and product matches;
repeated natural terms alone are not proof that an element is the desired product.
Generation does not invent query-conditioned distractor offers or catalog membership.

## Priors and correlation

A site first draws a direct, browse or compact profile (relative weights0.3/0.4/0.3).
Direct profiles usually expose facts inline. Browse profiles tend toward rich search
sections and more related links. Compact profiles more often use lists, expandable
specifications/offers and separate shipping steps. Each site's controls then draw
from that profile, using independent namespaces. Changing one control's override
does not perturb all other draws. Adding/reordering sites does not reassign draws
for existing site IDs.

Override probabilities using `search_sections_probability`, `list_probability`,
`offer_expand_probability`, `spec_expand_probability` or
`shipping_separate_probability`. `destination_form_weights` supplies relative
weights for none/single/split. `related_limits` supplies an integer list sampled
uniformly. Values are checked for range/type/finiteness. These are authored priors,
not measured real-shop frequencies or guarantees of any task outcome.

## Destination postcode decision

The destination object is `{location_id, country, postcode, postcode_parts,
synthetic: true}`. It is a stable alias derived from the exact existing home location,
independent of the UI seed. Country-shaped formatting does **not** assert a real
postal assignment or introduce postcode-level geography. No geocoding/network
request is made. SE/GB/IE/NL/PT support two natural-format parts; the remaining
supported countries use one. Drawing split for a one-part destination falls back
to single. Without locations, there is no alias and no destination gate.

`destination_matches(sidecar, country, postcode=...)` accepts the exact alias,
ignoring ordinary ASCII spaces/hyphens and case. Alternatively pass `parts=[...]`;
each input must match its corresponding part. Country must also match. Invalid,
unknown or different destinations cannot select another route or get a made-up
quote. A matching alias simply permits the already authoritative delivery quote,
which can still be unavailable for that merchant.

The postcode gate is per retail site for destination-dependent **delivery** facts.
Apply it consistently across that site's delivery quote surfaces, including links
and query paths; it is not a global rule hiding independent evidence on other sites.
Listed item prices, branch stock, branch-based pickup/inspection, and historical
order data keep their existing meaning. Related controls must not invent eligibility.

`Episode.policy_input()` supplies the known `{country, postcode}` through public
`environment_context.delivery_destination`. It does not expose profile/control
choices, source hashes or private task facts. The agent need not guess or ask the
user for an address already known by the environment. The underlying task and its
semantic fingerprint are unchanged; the episode identity includes the pattern
hash to distinguish presentation conditions.

## Runtime and pin integration

Runtime exposes the raw object as `rt.interaction_patterns`, publishes
`provenance['interaction_patterns_sha256']` and saves
`interaction-patterns.public.json` beside its manifest. `Episode.from_runtime`
requires the runtime/sidecar/hash to agree. A patterned runtime cannot bind a task
scenario missing the sidecar: that would omit the necessary destination context.
Direct Episode construction also takes `comparison_coverage=` when patterns bind
non-legacy comparison sites. `episode_preview` reads the frozen runtime sidecar.

The first immutable input is `.local/coordination/retail-interaction-patterns/pin-v1/`,
with reproducer `../freeze.py`. It adds one seed42 draw to the accepted location/account
world and preserves its coverage, profiles, reviews, ads and accounts. The full
reference evaluation before and after attachment is identical. The draw has no
split form; forced-split boundary fixtures are separate, not resampled production
draws. Public rendering acceptance is Curation-owned and separately recorded in
`.local/coordination/retail-interaction-patterns/handoff.md`.

## Further obstacles: factual support versus backlog

Existing facts already support out-of-stock size/colour choices, online versus
branch inventory, warehouse transfers, shipping-enabled branches, quantity limits,
account coupon conditions, signed-out accounts, historical tracking/cancellation,
partial comparison coverage, merchant review counts and exact-SKU review evidence.
New presentation can reuse these with the authoritative state/quote APIs.

Separate till prices, stale comparison prices, tax/customs estimates, live opening
hours, real postcode service areas, delivery-slot capacity and membership-only
pricing need new explicit generation/quote contracts. Renderers should not infer
or fabricate them from the present data. Paid browser/model evaluations remain a
separate user-authorized step.
