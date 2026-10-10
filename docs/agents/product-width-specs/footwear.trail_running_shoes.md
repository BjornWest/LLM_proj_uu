# Trail-running shoes — domain specification

Status: domain accepted in shared DSL, 2026-10-01; isolated authoring preview only. Registry concept `footwear.trail_running_shoes`.
Adult enclosed running footwear intended for unpaved trails. This intended use does
not prohibit road sections and does not certify traction on wet rock, ice or mud.

Primary examples: [HOKA Speedgoat 6](https://au.hoka.com/products/m-speedgoat-6-1147791-cdn-cdn)
declares toe reinforcement and 5 mm lugs; [Salomon Speedcross 6 GORE-TEX](https://www.salomon.com/en-gb/product/speedcross-6-gore-tex-lg9214/L41738600?sizeId=L41738600027)
declares a membrane and quick lacing; [Brooks Cascadia 19](https://www.brooksrunning.com/en_us/mens/shoes/trail-shoes/cascadia-19/1104571D169.095.html?dwvar_1104571D169.095_color=169)
declares an underfoot rock plate. A cross-sold Cascadia 20 GTX waterproof promotion
does not become a fact about Cascadia 19. Detailed observations and limits are in
`.local/product-width/research/trail_running_shoes.md`; these sources establish
possibilities, not frequencies or our synthetic EU40 reference masses.

## Distinct construction and facts

Reuse the accepted running-session target (short/fast, daily training, long distance)
as a soft emphasis, with independent positioning and execution. Joint construction
choices produce a lighter moderate-foam/3 mm-lug design, a balanced moderate-foam/
4 mm-lug design, or substantial-foam/5 mm-lug design. These are bounded plausible
recipes, not universal coupling laws; the selected target does not eliminate any.
Rubber outsole and nominal lug depth describe construction, not measured grip.

Upper material is mesh with synthetic reinforcement or woven synthetic fabric.
Choose protective toe reinforcement independently of an underfoot rock plate;
these protect different regions and must not be one boolean. A declared waterproof
membrane may be present; absent does not imply that the shoe absorbs water, and
presence does not supply a tested waterproof rating. Keep rating explicitly unknown.
Membrane construction adds a small authored mass increment, not a durability score.
Nominal drop is 0/4/6/8/10 mm. EU40 one-shoe mass varies by construction plus noise;
no manufacturer weight lacking that measurement basis is silently relabelled.

Fastening is laces or a quick-lace cord, without claiming interchangeability of their
adjustments. The whole recipe remains a closed-heel shoe. More cushioning does not
prove stability on steep trails, toe protection does not prove injury prevention,
and rock plates do not prove comfort. Price bands are positioning-conditioned
commercial heuristics; inventory and retailer services remain downstream.

## Manufacture, text and review scope

Reuse canonical adult nominal size/colour/width manufacture, including sparse tuples,
and exact tested-SKU review attribution. Extra-wide widths, half sizes, gait-related
medical fitting and conversion charts are deferred. Construction/drop/membrane are
model facts here; varying them produces a separate model rather than a hidden change
when selecting a colour. Retailer grouping/listing/stock remains separate.

Fact-bound descriptions disclose intended use, upper, sole, lug depth, closure, drop,
reference mass and membrane/rock-plate presence. Proposed task predicates can request
a minimum declared lug depth or membrane presence; no downstream registration is
claimed. Nominal-size tuple resolution and review-derived thresholds remain deferred.

Customer meanings cover trail-run comfort, forefoot fit, traction on dry loose
paths, pressure from small stones underfoot, and value. All are attributed experiences
in the stated context, not seller guarantees. Dry-loose traction must never become
wet-rock grip through a paraphrase. Stone pressure is independent of toe impact.
Shared concentration-1.5 stars, protected value mentions, silent ratings, variable
statement counts and mixed sentiment are preserved. Language follows selected
meaning; no inferred distance or terrain is added by a wording draw.

## Acceptance and pending extensions

Twenty retained fixed seeds, construction/lug/mass coupling, independent toe/plate
flags, nominal numeric units, canonical sparse SKU identities, fact formulation,
and exact context/subject checks. Sources are bounded real examples and establish
possibilities rather than probabilities. Recipe weights are openly tunable.
Detailed lug shape, traction tests, drainage/stack measurements, deep-mud-specific
models and membranes as manufacturer-selected configurations are deferred.

## Review-policy correction (new acceptance revision)

Default ratings are 75% silent; written lengths retain 4:3:1 weights. Value favourability follows overall stars with independent clipped normal noise (spread 0.22), adjusted by `-0.2 * (relative_price - 0.5)`. Relative price uses the concept's full reference-price band in SEK; the synthetic recorded purchase price is initialized from model reference, not a live retailer quote. This is the agreed pilot calibration, not a claim cheap products have higher quality. Price changes value sentiment only; stars/topics remain separate. Earlier cohorts and source versions are preserved under `.local/product-width/history/review-defaults-v1/`.
