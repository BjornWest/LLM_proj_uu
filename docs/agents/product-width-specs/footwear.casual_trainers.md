# Casual trainers — domain specification

Status: domain accepted after prose, DSL, fixed-seed tests and independent review, 2026-10-01. Registry concept
`footwear.casual_trainers`; family `footwear`. Sources and independent review are
recorded in the adjacent acceptance manifest, not inferred from this status.

Primary example cross-check: [adidas Samba OG](https://www.adidas.com/us/samba-og-shoes/IG9031.html),
[Vans Classic Slip-On Wide](https://www.vans.com/en-us/p/shoes/icons/classic-slip-on-5315/classic-slip-on-checkerboard-wide-shoe-VN0A4BHOTYQ?size=11.5+Men+%3D+13.0+Women),
and [New Balance 574 Core](https://www.newbalance.com/pd/574-core/ML574V3-40377.html)
illustrate respectively leather lace-ups, vulcanized-style slip-ons and mixed-upper
cushioned casual designs. Exact checked URLs/observations are in
`.local/product-width/research/casual_trainers.md`; these examples support recipe
possibilities, not probabilities or universality. Extra-wide widths and patterned
colourways exist but are explicitly deferred in this adult nominal-size wave.

## Product boundary and useful facts

Enclosed, closed-heel footwear sold primarily for casual everyday wear. This is an
intended-use classification, not a prohibition on walking and not a promise of
running suitability. A retro running-inspired silhouette remains a casual trainer
when marketed for everyday wear. Do not inherit the walking pilot's long-walk claims.

Vary upper material (canvas, smooth leather, suede with textile, synthetic mesh),
closure (laces, elastic slip-on), sole construction, cushioning and reference mass.
Jointly choose a rubber cupsole with modest cushioning, a rubber vulcanized-style
sole with minimal cushioning, or a foam midsole/rubber outsole with more cushioning.
These are coherent recipe choices, not exhaustive manufacturing laws. Upper and
closure combinations remain soft possibilities; no canvas-is-always-cheap rule.
The cushioning/lightness/support emphasis used by the accepted footwear profiles
softly weights construction. Positioning biases commercial reference price; latent
execution is independently drawn and informs reviewer variation, never public proof.

Reference mass describes one shoe in EU 40, not every size or an arbitrary pair.
Waterproof performance is explicitly unknown unless separately specified. Tread is
shallow or moderate; neither label guarantees slip resistance. Brand scope must
explicitly include this concept. Store placements reuse footwear/apparel/outdoor
registry memberships; actual retailer allocation remains a separate stage.

## Manufacture and presentation

Nominal adult EU sizes, colour and width are SKU attributes. Manufacturing produces
bounded size sets and colour/width groups, with sparse size coverage allowed. Every
SKU identifies the parent product and the exact combination. Canvas/leather or sole
changes identify different models here; colours do not secretly change construction.
Regular width is available, with optional narrow/wide manufactured variants. Sizes
use selectors; colour/width may be selectors or page partitions according to one
retailer policy. Retailer listings and zero stock cannot rewrite manufactured facts
or hide sold-out variants. No inventory, shipping fee or arrival time is sampled here.

## Public evidence, opinions and proposed tasks

Fact-bound descriptions disclose construction, upper, closure and EU-40 reference
mass; specification rows preserve those exact facts. Customer statement meanings
cover value, everyday-wear comfort, fit across the forefoot, upper upkeep, and
sole durability during everyday use. A reviewer may like the look yet dislike the
fit. Opinions describe a tested canonical SKU and retain context/polarity/provenance;
they are not waterproof certificates or claims about prolonged hiking.

Reuse the shared star distribution (concentration 1.5), protected value-mention
policy, zero-to-three statement selection, and mixed positive/negative sentiments.
Meaning is selected before paraphrase. Silent ratings remain in summaries. A small
natural-language bank is original synthetic text, not copied customer comments.

The exported proposed task/filter predicates match a declared upper or closure,
with `proposal_not_registered` support. Nominal size/width/colour requirements and
everyday-wear evidence thresholds are future consumer bindings: selection must
resolve a real canonical SKU and cannot assume a complete Cartesian grid. Their
optional request fields do not implement that resolution. These proposals do not
create a production grader or establish a review threshold by themselves.

## Acceptance and tunable assumptions

Compile the shared DSL, sample seeds 0–19 without rejection, validate unique SKU
identity and sparse grouping, render every applicable fact pool and review meaning,
and compare output to this specification. Weights, price bands and adult-size grids
are tunable authoring heuristics; neither sources nor the fixed cohort estimate
market probabilities. Broader children's sizing, branded conversion charts and
material-specific configuration surcharges are deferred explicitly.

## Review-policy correction (new acceptance revision)

Default ratings are 75% silent; written lengths retain 4:3:1 weights. Value favourability follows overall stars with independent clipped normal noise (spread 0.22), adjusted by `-0.2 * (relative_price - 0.5)`. Relative price uses the concept's full reference-price band in SEK; the synthetic recorded purchase price is initialized from model reference, not a live retailer quote. This is the agreed pilot calibration, not a claim cheap products have higher quality. Price changes value sentiment only; stars/topics remain separate. Earlier cohorts and source versions are preserved under `.local/product-width/history/review-defaults-v1/`.
