# Wet cat food — exact pouches and distinct feeding-role labels

Status: domain accepted in shared DSL, 2026-10-01; isolated authoring preview only. Concept `cat_food.wet_food`; family
`cat_food`. First recipe covers same-formula pouches, not all cans/trays or mixed
flavour assortments. No clinical or individualized nutritional suitability.

## Research judgment and reuse

Primary notes `.local/product-width/research/wet_cat_food.md` use
[Royal Canin Instinctive Loaf](https://pro.royalcanin.co.uk/products/cat/instinctive-loaf/),
[FELIX7+ Mixed Selection in Jelly](https://www.purina.co.uk/cat/cat-food/product-felix-as-good-as-it-looks-senior-mixed-selection-in-jelly)
and [Applaws Chicken Breast in Broth](https://applaws.com/uk/products/wet-cat-food-chicken-breast-in-broth/).
They establish pouch masses, complete/complementary distinctions, textures and
percentage bases. Applaws' displayed analytical figures total104.1%; retain that
source inconsistency, do not silently correct it or copy it into a joint bundle.
Mixed-flavour counts are missing on the FELIX page; this recipe deliberately uses
one formula per pack. Source marketing/health claims do not become owner outcomes.

Reuse neutral profile/price logic and exact-pack review normalization from dry
food. Use a **new wet-pouch manufacture base**, preserving the accepted dry base.
Do not inherit its bags, zipper, masses, dose or nutrition table. Formula, texture,
label role and target are model facts; exact unit mass/count are SKU facts.

## Model declarations

Species cat; adult/senior targets5:2, labels respectively ages1+years and ages7+years.
These are authored recipe declarations, not universal stages. Texture loaf/jelly/
broth weights1/3/2. Named chicken/salmon ingredient weights3/1; partial unordered
composition also names other animal derivatives, rice, minerals and liquid.
Other animal ingredients are not excluded. Whole-food named-ingredient share
is4% or12%, or unspecified, weights2/1/1; no chunk-only percentage, exhaustive
partition, single-protein/allergen-free or grain-free inference.

Complete/complementary/unspecified role weights5/2/1, independent of attractive
ingredient names. Missing role is not complementary. Known complete means a
manufacturer-style label, not adequacy validation. Complementary declarations
explicitly state alongside a usual complete diet, not replacing it. Unknown-role
review meal contexts also retain the usual complete diet, avoiding an invented
sole-feeding recommendation. Nothing estimates an individual daily ration.

Analytical declaration known/unspecified2:1. Known synthetic as-sold percentage
bundles follow texture: loaf moisture78/protein10/fat5/fibre0.5/ash2; jelly80/12/3/
0.6/2.5; broth82/12/1/0.2/1.4. Every declared partial panel totals<=100%. Unknown
panel leaves every numeric constituent unknown, with an explicit static disclosure.
Moisture is not a guarantee of hydration benefit; energy, total/additive taurine,
analysis method and individual suitability remain unknown. No dry-matter or
residual-carbohydrate calculation. Ingredient share is separate from protein.

Pouch opening tear-notch/precut-tab1:1, both single-use non-reclosable.
No zipper or storage/freshness guarantee. Release of loaf is described as scraping;
jelly/broth as squeezing. These are represented dispensing operations, not feeding
advice or claims that an unrepresented utensil is supplied.

## Joint pack manufacture and price basis

Finite joint packs: one70g pouch, one85g pouch, six85g pouches, twelve85g pouches.
Menu weights2/4/3/2 and count weights35/40/20/5, sampled without replacement.
Total food mass70/85/510/1020g equals unit mass×count. All inner pouches contain the
same represented formula; retail quantity/subscription remain separate. Unit
net mass and unit count can each be selectors or page partitions; total mass and
derived price are canonical facts, not additional identity axes.

One-kilogram synthetic formula anchor bands70–130/110–220/200–400SEK, rounded1SEK.
Pack coefficients0.10/0.12/0.66/1.20 respectively are explicit tunable small-unit/
bulk-price assumptions. Exact selected pack price scales both review price bounds
70/400SEK by the same coefficient, preserving the cheap-formula value effect
without falsely rewarding fewer pouches. No seller quote, delivery or stock.

## Original owner-observed evidence and acceptance

Shared concentration1.5,75% silent ratings and accepted price-dependent value.
Three non-value contexts: owner observes target-stage cat eat/leave a usual serving
at ordinary meals in its usual bowl; owner releases food from the tested pouch into
that bowl via the actual scrape/squeeze operation; owner likes/dislikes smell on
opening a pouch in the usual feeding area. Opening-method handling is separately
contextualized to actual tear-notch/tab. Complementary/unknown meal wording retains
the usual complete diet; none speaks as the cat or proves nutrition/health/freshness.
Every review binds exact unit-mass/count pack and model formula.

Retain seeds0–19; force texture, all role/analysis/share states, both targets/opening
methods and each pack. Render known/unknown catalog pools, check ingredient versus
analysis bases, totals, exact pack price arithmetic and normalization, all four
mass/count grouping policies, sparse/sold-out/empty allocation and owner context.
Proposed life-stage/texture/known-complete filters stay unregistered. No compiler,
production renderer/task/grader changes. Cans/trays, mixed assortments, flavour
selector manufacture, exact feeding/clinical advice, batch/expiry/additive assays,
energy protocols and empirical calibration remain deferred.
