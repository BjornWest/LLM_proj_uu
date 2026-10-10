# Pet-food manufacture base — pack identity and price basis

Status: prose draft before DSL, 2026-10-01. Supporting module, not a registered
concept. Reuse neutral positioning/execution profiles; inherit no footwear,
clothing, electrical or nutrition assumptions.

One model has one formula and declared target. A manufactured bag's net food mass
is a SKU axis, separate from retailer quantity, stock and subscription. The first
dry-food recipe samples a nonempty sparse menu from 400g, 1kg, 2.8kg and 6kg.
Weights3/4/3/1 and menu-count weights35/40/20/5 are tunable authoring choices.
Canonical IDs use stable pack keys. Retailers may expose the mass as a selector
or separate page; their allocation never invents a missing manufactured pack.

The model reference price is an explicit synthetic **one-kilogram anchor**, not a
quote for every pack. Budget/mainstream/premium anchor bands40–80/70–140/130–230SEK,
rounded1SEK. Pack prices multiply that anchor by0.5/1/2.52/4.8 respectively.
Thus larger bags have lower reference prices per kilogram in this bounded recipe;
these coefficients are assumptions, not observed market estimates. Every exact SKU
retains its net mass, price multiplier and derived reference price. The last two
are facts, not extra grouping axes. Retail prices remain a later stage.

Review purchase price uses the **selected pack's** synthetic reference price.
Its price-position bounds use the same multiplier against40/230SEK, preserving the
accepted cheap-product boost at fixed satisfaction without confusing a smaller bag
with a cheaper formula. No shopper's actual transaction price is inferred. Pack
prices are SEK quantities multiplied by a dimensionless coefficient; no unit
stripping, custom sampler or shared-compiler change is needed.

Wet-food trays/cans, unit count/multipacks and treats require separate manufacture
menus before adoption. They must not inherit these dry-bag sizes merely by reusing
the profile/identity machinery. This module describes an authoring preview, not
production shopping quotes, dietary suitability or connected-world adoption.
