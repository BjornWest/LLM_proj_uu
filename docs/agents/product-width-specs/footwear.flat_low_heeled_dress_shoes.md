# Flat and low-heeled dress shoes — domain specification

Status: domain accepted in shared DSL, 2026-10-01; isolated authoring preview only. Registry concept
`footwear.flat_low_heeled_dress_shoes`. This bounded initial recipe covers adult
closed-toe, closed-heel loafers, laced Oxford-style shoes and ballet-style flats.
It does not claim these are every possible flat/low dress-shoe style. Mules,
slingbacks, open toes and dress boots remain deferred.

Primary examples: [G.H.BASS Whitney loafer](https://www.ghbass.com/products/women-whitney-weejuns-penny-loafer-black)
declares slip-on closure and a 12.7 mm heel;
[Allen Edmonds Park Avenue Oxford](https://www.allenedmonds.com/product/mens-park-avenue-oxford-dress-shoe-with-combination-tap-sole-3023025/black-leather-ec4001391?bvstate=pg%3A2%2Fct%3Ar)
has closed lacing and leather/rubber sole details in indexed manufacturer content
(current direct extraction lacks product data);
[Repetto Cendrillon](https://repetto.com/en/products/cendrillon-ballerinas-white-v086ve-050-en?variant=47886863958344)
declares a 10 mm heel. These do not calibrate masses, frequencies or exact
manufactured tuples. Full observations: `.local/product-width/research/flat_dress_shoes.md`.

## Scope and construction

Use an explicit authored nominal heel-height range no higher than 30 mm, distinct
from this wave's planned higher-heel recipe. That boundary is provisional recipe
scope, not a universal fashion taxonomy. A future request using “low heel” needs
an explicit interpretation; height facts alone are unambiguous. Record the boundary
in the questions backlog rather than silently redefining the registry.

Jointly choose style, closure, low heel geometry and reference mass. Loafers use
slip-on construction, Oxford-style shoes closed lacing, ballet-style flats slip-on
construction. All retain enclosed heel contact. Heel-height domains depend on the
style rather than introducing impossible laced ballet flats via independent draws.
Smooth leather, suede and synthetic uppers and rubber or leather outsoles remain
model choices. No material proves comfort, ease of cleaning or indoor grip.
Distinguish rubber, leather and leather-with-rubber-wear-patches outsole packages;
the mixed package does not become an all-rubber sole. Rubber heel caps, lining,
insole and joining method remain unrepresented, rather than inferred from outsole.

Authored nominal heel choices are 10/12.7/20/25 mm for loafers, 15/20/25/30 mm
for Oxfords and 5/10/15 mm for ballet-style flats. Height is not heel-to-toe drop
and no forefoot platform is inferred. Reference masses 300/420/180 g per style
have uniform ±20 g noise, explicitly synthetic one-EU40-shoe values. Reference
price bands overlap at SEK 350–900, 800–1700, 1500–3000 across positioning.
Only positioning/execution profiles are used here; no extra emphasis is required
merely to copy another concept's number of profiles.

Positioning and execution remain independent. Use the shared nominal adult
size/colour/width manufacture; silhouette does not supply a user gender or secret
size requirement. Reference mass uses one EU40 shoe, not a pair or an unnamed
manufacturer basis. Detailed last measurements, platform geometry, toe-box shape,
gendered sizing charts and footbed technologies may be deferred without inventing
them as task evidence. Waterproof test rating remains unknown.

## Text, reviews and task proposals

Descriptions state style/closure, enclosed toe/heel, upper/outsole, nominal heel
height and reference mass. Proposed predicates can request maximum heel height,
closure or upper material; production task/filter registration remains separate.

Applicable customer meanings include comfort during an evening occasion, forefoot
fit in the tested size, uncomfortable heel rubbing during an evening occasion,
outsole abrasion after several months of regular occasion wear, and purchase
value. Evening comfort does not become long-walk or work-shift comfort. Rubbing
does not invent blisters. Abrasion does not become sole separation. Every report
binds a canonical tested SKU and preserves context/polarity across formulations.
Shared 75% rating-only default, concentration1.5 and modest price/value adjustment
remain in force; there is no arbitrary required count of review topics.

## Acceptance and pending choices

Primary examples, authored bundles/price ranges and meaningful style differences
were recorded before DSL conversion. Keep fixed seeds 0–19, validate style and
closure/heel coupling, all nominal units, sparse canonical manufacture and exact
review subjects. Retain sparse/no-match assortment draws. Consumer adoption is
isolated authoring preview only; no existing host or task grader changes.
