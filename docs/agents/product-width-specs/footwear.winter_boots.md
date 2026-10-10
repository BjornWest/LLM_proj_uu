# Winter boots — bounded executable authoring recipe

Status: domain accepted in shared DSL, 2026-10-01; isolated authoring preview only. Concept
`footwear.winter_boots`; family `footwear`. This is additive domain authoring, not
production registration or replacement of any existing world.

## Scope and source judgment

Cold-weather insulated boots, not a guarantee of warmth, safe exposure or ice grip.
The bounded research record `.local/product-width/research/winter_boots.md` compares
[SOREL Caribou](https://www.sorel.com/p/caribou-mens-winter-boot-1002871.html),
[Columbia Bugaboot III](https://www.columbia.com/p/mens-bugaboot-iii-boot-1791221.html?color=012)
and [BOGS Bozeman II](https://www.bogsfootwear.com/shop/style/73421-001.html).
They support distinct integrated insulation, removable felt liner and neoprene
upper constructions. Source insulation grams, liner millimetres, advertised
temperature ranges and masses with different reference sizes are not converted
into comparable thermal performance or EU40 measurements.

## Sampling dependencies

Positioning and execution use the neutral shared footwear module. Construction
is a joint draw; it determines component labels, insulation construction and the
reference mass centre. All recipe weights, price bands and masses are authored
tunable choices, not prevalence or source measurements.

| Joint bundle | Upper / lower shell | Insulation | Mass centre |
| --- | --- | --- | --- |
| Textile winter boot (weight 3) | Textile and synthetic / synthetic shell | Integrated synthetic insulation | 580 g |
| Felt-lined boot (weight 3) | Leather / rubber shell | Removable felt inner boot | 800 g |
| Neoprene boot (weight 2) | Neoprene and textile / rubber shell | Neoprene upper insulation | 900 g |

Each bundle permits regular laces and pull-on entry with soft weights. Textile and
felt bundles favour laces 4:1; neoprene favours pull-on 5:1. These cross-bundle
possibilities are plausibility proposals, not observed source combinations.
Mid/high shaft weights are 3:2, independent of bundle; high adds 50 g. Uniform
integer mass noise is ±30 g. The basis is one synthetic EU40 boot. The outsole is
rubber; no quantified traction or certified ice performance is asserted.

Waterproof construction is separately conditional on bundle: membrane lining,
seam-sealed joins or molded shell with sealed joins respectively, each versus
no waterproof construction declared at weights 5:1. This is a manufacturer-style
declaration, not a numeric test rating or a customer dry-foot outcome. A shell
alone does not establish complete waterproof construction. No membrane presence
is inferred for the two non-membrane bundles.

Nominal adult EU sizing, colours, width options, sparse manufactured tuples and
canonical SKU IDs reuse `_footwear_base.json`. Retail stock/availability and offer
pricing remain downstream; sold-out or unavailable configurations are retained.
Reference price bands are budget SEK400–1000, mainstream900–1800, premium1600–3000,
rounded to10. SKU-specific mass and price changes are deferred.

## Public facts and reusable language

Expose cold-weather use, closed upper heel/toe, shaft height, upper/shell/outsole,
insulation kind, removable-liner flag, closure, waterproof-construction declaration,
unknown numeric waterproof and temperature ratings, and reference mass/basis.
Describe only generated facts. A removable inner boot is not a removable insole;
neoprene thickness and insulation mass are not invented. Descriptions distinguish
waterproof declaration from unspecified test rating.

## Customer evidence

Exact tested canonical SKU, shared concentration1.5 ratings, 75% silent ratings,
variable written topic count/order and the accepted price-dependent value policy.
Original meanings: perceived foot warmth on a short cold-weather walk; forefoot
room with winter socks in the tested size; boot entry ease; uncomfortable shaft
rubbing during a short cold-weather walk; value. Warmth does not entail dryness,
ice grip, medical protection, sweat management or a safe temperature limit. Entry
difficulty does not assert closure failure. Rubbing does not assert injury.
Customer opinions can disagree with construction and one another; these are
authored experiences without measured temperature, duration, sock thickness or
individual foot/calf geometry.

## Acceptance and deferred consumers

Fixed seeds0–19 retained without rejection. Validate all three component bundles,
mass arithmetic, shaft/closure domains, removable-liner identity, conditional
waterproof declarations and explicit unknown ratings; test sparse canonical SKU
manufacture and fact-bound wording. Review policy unchanged. Exported predicates
for closure, removable liner and declared waterproof construction reject missing
requested values and remain proposals, not registered filters/oracles.

Deferred: thermal-resistance protocols, temperature guarantees, insulation
quantities, liner dimensions, half sizes/conversions, calf measurements, zipper
mechanisms, gaiters, wet-foot/ice outcomes and physical durability. Winter purpose
and rubber construction are different axes; the neighbouring rubber-boot recipe
does not imply non-overlap or a universal classification rule.
