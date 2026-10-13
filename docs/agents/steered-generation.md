# Steered generation: conditioning the producer's draws

Owner: Claude Code (world construction), started 2026-10-10. An isolated
experiment in `experiments/steered_generation/`. It does not change the
producer, the unified generation entrypoint or any released world.

## What it is for

Getting a world in which an unlikely scenario holds, at about the cost of one
ordinary world, and knowing how unlikely the scenario was.

The existing conditioned generation (`unified_generation`,
`conditioned_feature_generation`) proposes whole natural worlds and accepts or
rejects them. That costs one full world per attempt, so a scenario that holds
in one world out of a thousand costs about a thousand worlds. Steering instead
makes the relevant draws themselves conditional on the requirement.

It differs from the edit operator in
[world-requirement-construction](world-requirement-construction.md) in two
ways. The world comes out of the real producer, not out of a patch applied
afterwards, so everything the producer derives from a draw is rebuilt by the
producer. And the result carries a probability.

## How it works

1. **Named draws.** The commerce producer opens a separate named stream for
   every decision (`population.stream(seed, key)`); the seed-73 world opens
   about 7,000 streams over about 6,400 distinct names. Replacing one stream
   leaves every other draw exactly as the seed makes it.
2. **Plan.** A plan maps stream names to the results the producer's calls on
   that stream should return. `streams.steered` swaps the stream factory for
   the duration of one producer call. Planned results are checked against the
   draw's support where the call shows it (integer range, choice options,
   positive weights). A plan the producer does not consume exactly is an error.
3. **Cached manufacture.** Product manufacture is about 26 of the 28 seconds a
   world takes and does not depend on commerce draws. `streams.Manufacture`
   keeps the products of the first pass, so later passes through the real
   producer take about 2 seconds. A plan that changes anything upstream of
   manufacture misses the cache from that point on.
4. **Sampling defaults read once.** The producer calls `population.load()`
   for every retailer/product entry, and each call re-reads and re-validates
   the same files. `streams.Defaults` gives every pass of a session the first
   call's result, which takes a seed-73 pass from about 2 s to about 0.4 s and
   matters more as the world grows (see "Cost against world size"). The
   pinned producer only reads that result. As a check, a pass that completes
   with the configuration changed fails; the registry object is not checked,
   and a session does not see later edits to the files.
5. **Solve on a model, materialize with the producer, check with the oracle.**
   A block sampler decides the planned draws from a model of the affected
   draws. The real producer then generates the world with that plan, and the
   native oracle and the pricing-rule check judge the result. Those checks
   establish that the world satisfies the requirement and obeys the producer's
   rules. They do not establish the sampling distribution or the probability;
   those rest on the block model and on its comparison with the producer's own
   pricing function (see the evidence below).

Three module attributes are swapped while the producer runs
(`population.stream`, `package_export.sample`, `population.load`), and for a
review block the stream factory of the producer that writes those reviews
(`footwear.stream`, the package class's `rng`, the carrier producer's `rng`).
That is acceptable for an experiment and is not thread-safe. A released
version needs small seams in the producer instead; see "What a released
version needs".

## The first block: prices

Requirement: the same outcome description the edit operator uses. The declared
retailers are exactly the cheapest available sellers of a declared product
within its concept.

Given everything upstream of prices, the producer draws one price per
retailer/product, independently of every other pair. `prices.atoms` lists that
draw's outcomes with their probabilities: the matched reference draw, the two
clamp endpoints and the intervals between rounding flips. The probability that
exactly the designated retailers are cheapest is then a finite sum over the
winning price, and `prices.plan` samples the price draws from their
distribution given that outcome. There is no rejection loop.

Every pair of the concept that has an available offer is drawn afresh from its
conditional distribution; the seed's own draws for those pairs are not
consulted. A pair with no available offer cannot be cheapest and keeps the
seed's draw (one of 49 walking-shoe pairs in seed 73). Repeated samples
of one world are therefore independent samples of the same distribution. An
earlier version kept a natural draw whenever it already fit. That is a
conditional draw only if the natural draw is itself fresh each time; with one
frozen natural world reused for several samples it froze those pairs, and it
was removed after the first Codex review.

### What the probability means

`probability_given_upstream` is the probability of the requirement given this
seed's products, assortment and stock. The steered world is a sample of the
price draws from their distribution given the requirement and that upstream.

Upstream draws are **not** reweighted. Across seeds, a set of steered worlds is
therefore not a sample from "all natural worlds in which the requirement
holds": seeds whose upstream makes the requirement likely are under-represented.
Using `probability_given_upstream` as an importance weight corrects that; so
does accepting each seed with probability proportional to it, which is what
`unified_generation` already does for presentation conditions.

Masses treat the producer's normal draw as continuous. Float plateaus about
1e-16 wide at rounding flips, and intervals too narrow to have a midpoint away
from a flip, are left out; together they are far below one part in a billion.

A requirement can have probability zero given the upstream (a designated
retailer has no available offer, or a product whose reference price is too
high to ever be cheapest). That is reported as such, with a reason code; other
seeds may still allow it.

## The second block: one offer's stock

Requirement (`steered-offer-stock-v1`): one retailer and one SKU, with an
availability, bounds on the quantity held at named stock locations, or both.

```json
{"schema": "steered-offer-stock-v1",
 "retailer_id": "apparel-06",
 "sku_id": "footwear-brand-21/footwear.walking_shoes/00-black-standard-39",
 "availability": "in_stock",
 "stock": {"apparel-06-warehouse": {"max": 0}}}
```

Availability uses the native oracle's three words. `in_stock`: some location
that ships holds the SKU, or only locations that do not ship hold it and no
supplier order is offered. `backorder`: nothing can be dispatched and a
supplier order is offered. `unavailable`: no stock anywhere and no supplier
order.

For one SKU at one retailer the producer draws, per stock location, a stock
condition (shared by all SKUs of the product at that location), whether the
SKU is at zero, and otherwise a quantity. If nothing can be dispatched and the
retailer takes supplier orders, it then draws whether this SKU is eligible.
Locations draw independently, so `stock.model` carries three numbers along
the locations (probability of: no stock so far, stock only where it cannot be
dispatched, dispatchable stock) and `stock.plan` samples backwards through
them. Cost is linear in the number of locations; there is no rejection loop.

The block is that offer's draws: the conditions of its product at each of the
retailer's locations, its own zero and quantity draws, and its supplier
eligibility. All of them are drawn afresh for every sample. Everything else is
the seed's own, including the other SKUs' zero and quantity streams. Because
the conditions are shared, the producer re-evaluates those SKUs under the
sampled conditions, and rewrites their supplier orders and the catalog pages.
That is the dependency the edit operator could not follow and the reason for
running the real producer: asking for 45 pairs in a warehouse makes the
warehouse well stocked for the whole product.

`probability_given_upstream` here is given the retailer's assortment and
listing, its locations and which of them ship, the stock tendencies, and
whether the retailer takes supplier orders. Those are not steered. A
requirement they rule out is reported with a reason code (`not_listed`,
`no_such_source`, `supplier_disabled`, `no_outcome`).

How it is checked:

- **Unit tests run the real commerce producer.** Only product manufacture is
  replaced by a stand-in, which leaves a pass at about a second. The model's
  probability equals a full enumeration of the draws written straight from
  the configuration for nine requirements, 4,000 plans for each of four of
  them follow the enumerated conditional distribution, and steered worlds
  satisfy the native oracle.
- **A reading of the producer's stock lines, checked draw for draw.**
  `stock.natural_draws` repeats the producer's stock lines for one offer with
  the producer's own stream and weighted-choice functions. A plan entry
  `streams.Reseeded` opens a stream under another seed, so the real producer
  can redraw the block naturally. `blocks.redraw` compares what the producer
  recorded with the reading, and the runner and the tests require them to be
  equal. The reading is then cheap enough for millions of redraws, which is
  what a 1-in-100,000 scenario needs.

## The third block: one offer's price

Requirement (`steered-offer-price-v1`): one retailer and one SKU, with a
minimum, a maximum or both for its listed price in minor units.

```json
{"schema": "steered-offer-price-v1",
 "retailer_id": "outdoors-02",
 "sku_id": "footwear-brand-21/footwear.walking_shoes/00-black-standard-39",
 "price_minor": {"max": 40000}}
```

The block is the single price draw of that retailer/product. `price_bounds`
keeps the outcomes of `prices.atoms` that put the named SKU's rounded price
within the bounds, and samples among them by probability. The producer
reprices the product's other SKUs at the retailer from the same draw. Stock
plays no part: the producer prices every listed SKU, in or out of stock.

Reason codes: `not_listed`, and `no_price` when no draw the producer can make
gives a price within the bounds (the offset is clamped to ±30% of the
reference price).

It is checked like the others: against the producer's own `_offer_price`
under other seeds, for the probability and for the distribution of the price
when the bounds hold.

## The fourth block: a concept's stock and prices together

Requirement (`steered-cheapest-available-v1`): a concept, a product and the
retailers that must be exactly the ones with the concept's cheapest available
offer, on that product; and optionally offers that must be listed below that
winning price.

```json
{"schema": "steered-cheapest-available-v1",
 "concept_id": "footwear.walking_sandals",
 "product_id": "footwear-brand-20/footwear.walking_sandals/02",
 "retailer_ids": ["footwear-02"],
 "listed_below": [{"retailer_id": "footwear-03",
                   "sku_id": "footwear-brand-20/footwear.walking_sandals/02-grey-standard-38"}]}
```

An offer listed below the cheapest available price is unavailable by
definition, so `listed_below` is "a cheaper offer exists but is sold out". It
says more than that one SKU is out. At a retailer that is not a designated
winner, every SKU of the product priced at or below the winner must be
unavailable too, or the retailer would win or tie; where all sizes share a
price, the retailer has nothing of the product available. A named offer may
also be the winner's own: then every SKU of the pair priced below the winning
price is unavailable and at least one at the winning price is available ("the
winner's cheaper sizes are sold out").

The first block answers "who is cheapest" on prices alone and takes stock as
it is. Here stock decides who competes, so stock and prices are one block:
for every listed retailer/product pair of the concept, the price draw, the
condition at every stock location and every SKU's zero, quantity and
supplier-eligibility draws. None of the seed's own draws of these is kept, so
repeated samples from one natural world are independent draws of the block.

The coupling stays inside each pair. A pair draws its price and its stock
independently of every other pair, and the requirement asks a pair for one
thing: the price of its cheapest available SKU, or that it has none.

- For one outcome of the price draw (`prices.atoms`), sort the pair's SKUs by
  price. The cheapest available price is at a level when every SKU listed
  cheaper is unavailable and at least one SKU at the level is available.
- A SKU is unavailable when no location holds it and it gets no supplier
  order. Locations draw their conditions independently, and under a condition
  every SKU draws with the same probabilities. So the probability that m SKUs
  are all unavailable is a product over locations of a sum over conditions
  (`cheapest.nothing`), and the probability that m are unavailable and one
  more is available is a short chain over the locations (`cheapest.chain`),
  with the stock block's states.
- `cheapest.outcomes` lists a pair's outcomes (price atom, level) with their
  probabilities and `Spread` sums them by price. The term for a winning price
  w is the product over pairs of: exactly w for a designated pair; above w or
  nothing available for any other; and for a pair with an offer named in
  `listed_below`, only the outcomes in which that offer is priced below w. The
  terms are disjoint and their sum is the probability of the requirement given
  everything upstream of the concept's stock and prices: assortment, SKU
  listing, locations, stock tendencies and the supplier setting.
- Zero always means impossible. Every sum is over products of probabilities,
  with no subtraction, so an outcome that cannot happen has probability
  exactly zero. In the other direction three things keep a possible outcome
  from being lost to the float range:
  - A product over a few hundred pairs easily falls below the smallest float
    although every factor is positive (thirteen pairs with nothing available
    were enough in the sixth Codex review's example), so products over pairs
    are kept as sums of logarithms (`log_terms`). The record gives
    `log_probability_given_upstream` always and `probability_given_upstream`
    as a float, or `null` when it is below the float range.
  - Within one pair the factors stay floats. A product of positive factors
    that underflows raises `NumericalLimit`, in the block model and in
    `stock.atoms`, and the runner reports `refused` with reason
    `numerical_limit`. The chance that a SKU holds something at a location is
    kept as its own number, not as one minus the chance that it holds
    nothing, which can round to one. No native configuration comes near
    either limit.
  - Sampling keeps the same support. `rng.choices` draws one 53-bit number, so
    an option whose share is far below 1e-16 may be unreachable or badly
    quantized, and with a subnormal total it can return an option of weight
    zero (eighth review); on the medium world one requirement has winning
    prices at shares like 1e-354 (seventh review). Every choice among weighted
    options therefore goes through `blocks.pick`. Only options with a
    positive weight are offered. Float weights well above the subnormal range
    and of ordinary evenness go to `rng.choices` as before; other even
    weights go to it after division by their exact total; very uneven ones
    are taken as exact rationals with a uniform draw of enough bits that
    every positive weight keeps its interval. The winning price is picked
    from the logarithms (`cheapest.pick_log`), and the weights of the
    backward stock sampling are exact products of the stored values. Exact
    backward products avoid additional float-product underflow during
    sampling; `pick_log` can still raise `NumericalLimit` at sampling time
    when logarithm gaps exceed the supported Decimal exponent range.
    `shares`, the winning price's distribution as floats, is for comparisons
    only.

  This is a numerical implementation of the conditional model, not exact
  arithmetic. Conditioning uses float masses and logarithms, and Decimal
  exponentials rounded to 40 significant digits. Backward products and the
  rational cumulative walk are exact for those stored values; forward and
  backward masses agree up to float rounding. The rational draw preserves
  every positive weight, with relative selection error below 2**-64; ordinary
  selection, the supplier draws of unconstrained SKUs and the draw inside a
  price interval use a 53-bit uniform number, as the producer does. The
  support guarantee holds within the Decimal exponent range (logarithms up to
  about 2e18 apart; beyond it `pick_log` raises `NumericalLimit`), which
  includes every configuration tested. The price model's own approximations
  are stated under "The first block". The guarantee is the fourth block's:
  the one-offer stock block keeps its float sums and `rng.choices`, and only
  gains the refusal in `stock.atoms`.

Sampling follows the same factors backwards: a winning price by its term; per
pair an outcome by its probability and a price draw inside its atom; then the
pair's stock. The first available SKU at the level, in offer order, is the
witness. The conditions and the witness's stock are sampled backwards along
the chain, the unavailable SKUs get zero draws, and every remaining SKU is
drawn as the producer draws it under the sampled conditions.

Reason codes: `not_listed` (a designated retailer does not list the product,
or a retailer does not list a named SKU) and `no_outcome`. An unknown
retailer, product, SKU or concept, or a named offer of another concept, is a
`ValueError`, raised before any listing is looked at, whatever else the
requirement names.

Checks, besides the ones every block gets:

- The producer must record every leaf of the block as planned: conditions,
  and each offer's price, quantities and supplier order (`cheapest.planned`
  against `cheapest.recorded`).
- The native oracle must name exactly the designated winners, list every
  named offer as unavailable, and price it below its minimum.
- `cheapest.trial` restates the producer's stock and price lines for the
  concept with the producer's own stream, weighted-choice and pricing
  functions. Real producer passes under other seeds must equal it leaf for
  leaf; it then gives the frequency of the requirement and the distribution
  of the winning price to compare the model with.
- Unit tests compare the stock probabilities with a brute-force enumeration of
  the conditions from the configuration, on the test world and on a copy of it
  with a scarcer stock configuration in which a quantity draw can itself be
  zero. They compare planned samples with rejection sampling (redraws under
  other seeds that happen to satisfy the requirement) on twelve statistics;
  sold-out offers are rare under the producer's configuration, so that
  comparison runs on the scarce copy. The sixth Codex review mutated the
  sampler three ways (always the first witness, conditions from their prior,
  equality allowed at the ceiling) and each was caught by these tests.

### Who competes and what is available

The native tasks do not all read "the cheapest available offer" alike, and
the requirement can state the reading with optional fields. Each reading is
checked with the native oracle of the task that uses it.

```json
{"schema": "steered-cheapest-available-v1",
 "concept_id": "footwear.walking_shoes",
 "product_id": "...", "retailer_ids": ["..."],
 "predicates": [{"field": "sku.size_eu", "operator": "eq", "value": 42}],
 "availability": "positive_pickup_branch_stock", "city": "Uppsala",
 "comparison_site_id": "comparison-01"}
```

| Field | Meaning | Native oracle |
| --- | --- | --- |
| `predicates` | only SKUs that meet them compete (size, product facts), evaluated with the native `PredicateSet` | `feature_offer_task.reference` |
| `availability: purchasable` (default) | stock at any location or a supplier order | `basic_offer_task`, `feature_offer_task` |
| `availability: positive_stock` | physical stock at any location; a supplier order does not count | `feature_offer_task` |
| `availability: positive_pickup_branch_stock` with `city`, `country` | physical stock at a pickup-enabled branch in the city | `catalog_branch_task.reference` |
| `comparison_site_id`, `surrounding` | only retailer/product pairs the comparison site lists compete | the comparison-scoped `basic_offer_task` and `feature_offer_task` |

The two stricter availabilities need at least one predicate, as their native
tasks do.

In the block these are three static facts (`cheapest.scope`): the SKUs that
compete, the pairs that compete, and per retailer the stock locations that
count, with whether a supplier order counts. The model is unchanged in form.
A pair's levels are taken over its competing SKUs only; "unavailable" is
"held at no location that counts", and where a supplier order counts, "and
left without one". SKUs that do not compete, locations that do not count and
a supplier order that does not count are drawn as the producer draws them
under the sampled conditions. Pairs without a competing offer are outside the
block and keep the seed's own draws.

The comparison scope is static because of how the surrounding sites are
generated: which products and pairs a site lists is decided by draws keyed by
the world's seed, the site, the product and the retailer over the listed
pairs (`ecosystem.py`, `rich_ecosystem.py`), independent of stock and prices.
The natural world and every steered one therefore have the same listings.
The check generates the sidecar for the steered world
(`native_review_ecosystem.generate`) and hands it to the native oracle. On
saved seed 73 the scope computed this way for `comparison-01` equals the 36
pairs stored in the suite's own comparison-scoped task on that world (B01,
H09; `steering/readings/explore.log`).

`cheapest.listed` remembers a site's pairs per world identity, and
`cheapest.inventory` a concept's field declarations. Scope caching assumes
content-bound world identities and unchanged native source declarations;
comparison-site membership is unchanged by steering, while each world's
listing prices and entry offers are regenerated.

### Other rankings

Three native tasks rank the available offers by something other than the
listed price alone, and the requirement can state each (at most one, not with
branch stock):

| Field | Ranking | Native oracle |
| --- | --- | --- |
| `priorities` | stated numeric product facts in order (lowest or highest first), then the listed price; only SKUs whose prioritised facts are known compete | `catalog_priority_task.reference` |
| `unit_basis: net_food_mass_kg` | the listed price over the pack's net food mass | `catalog_unit_price_task.reference` |
| `relaxations` with `selected` | criteria sets in order: the original predicates, then each permitted relaxation; the set named by `selected` must be the first with an available match, and within it the listed price decides | `catalog_relaxation_task.reference` |

In the block an offer's rank is `scope.key(sku, price)`: the price, the pair
(facts, price), or the price per kilogram as an exact fraction. Levels,
winners and "listed below the winner" are all in terms of that rank, so an
offer listed below the winner is one that would rank ahead of it if it were
available. A relaxation adds `scope.barred`: every SKU that meets an earlier
criteria set must be unavailable, whatever its price; in the model such SKUs
count as unavailable in every outcome of their pair, and pairs that hold only
barred SKUs are in the block.

Which offers compete and what they are ranked by is not restated here for
the priority and unit-price tasks. `cheapest.stocked` makes a copy of the
world in which every listed offer holds one unit at every location, and reads
the native oracle's candidates on it, each with the facts or the pack mass
the oracle ranks it by. The stocked copy identifies offers eligible apart
from availability; whether an eligible offer can actually become available is
determined by the block's stock and supplier distributions. The record
gives `winning_price_minor` when the rank is a price and `winning_rank`
otherwise.

## The fifth block: who lists a product cheapest

Requirement (`steered-cheapest-listed-v1`): a product and the retailers that
must be exactly the ones listing it at the lowest price, optionally among the
pairs one comparison site lists.

```json
{"schema": "steered-cheapest-listed-v1",
 "product_id": "footwear-brand-21/footwear.walking_shoes/00",
 "retailer_ids": ["department_store-01"],
 "comparison_site_id": "comparison-01"}
```

A retailer's price for the product is its lowest listed price over all its
SKUs, in or out of stock. That is the price a comparison row shows
(`ecosystem.py`, `minimum_listed_native_offer_snapshot`). The block
(`listed.py`) is the price draw of every compared pair, and it depends on no
stock, so it combines with a one-offer stock requirement on the advertised
retailer as independent blocks. That combination is the comparison-stock
task's hard case, "the retailer advertised cheapest has the variant only on
supplier order", and a unit test checks it with the native
`comparison_sku_task.reference`. That task counts stock at any location as in
stock, so "only on supplier order" is the stock requirement `backorder` with
a maximum of zero at every location.

The model is `prices.model` with every listed SKU counted, products over
pairs kept as logarithms and choices made through `blocks.pick`, as in the
fourth block. It is checked against the real `_offer_price` under other seeds
and against the comparison site's own rows for the steered world.

## The sixth requirement: which models make the shortlist

Requirement (`steered-shortlist-v1`): a concept, predicates, a limit and the
models that must be exactly the native shortlist.

```json
{"schema": "steered-shortlist-v1",
 "concept_id": "footwear.walking_shoes",
 "predicates": [{"field": "sku.size_eu", "operator": "eq", "value": 42}],
 "availability": "positive_stock", "limit": 3,
 "product_ids": ["...", "...", "...", "..."]}
```

The native shortlist task ranks every model by the lowest price among its
available matching offers at any retailer; the cutoff is the price of the
model in the limit's place, and every model at or below it is on the list.
Naming more models than the limit therefore asks for a tie at the cutoff, and
naming fewer asks for a world in which no other model has an available
matching offer.

It is not a new block: `shortlist.py` uses the fourth block's pairs,
outcomes and stock sampling for the same concept, and decides the same
resources. Models share no retailer/product pair, and a model's lowest
available price is the lowest over its pairs, so for a cutoff c:

- every other model must be above c or without an available offer: a product
  over its pairs;
- every named model is below c or at c, each as a sum over which of its
  pairs is the first to decide it (so no probability is found by
  subtraction);
- fewer named models may be below c than the limit, which is a small count
  over the named models (`shortlist.counts`).

The terms for different cutoffs are disjoint. Sampling goes backwards through
the same factors: the cutoff, how many and which named models are below it,
the deciding pair of each model, then each pair's outcome, price and stock as
in the fourth block. With a limit of one this must equal the fourth block
summed over every set of the model's retailers, and a unit test checks that
to twelve places. The check uses `catalog_shortlist_task.reference`.

Shortlist probabilities and conditional samples use the documented
finite-arithmetic and price-model approximations; model-level splits and the
count table use guarded float products and may raise `NumericalLimit` before
cutoff terms are assembled in logarithms.

## The seventh requirement: a basket against the free-shipping threshold

Requirement (`steered-free-shipping-v1`): a retailer, a SKU, a quantity and
how the merchandise subtotal (listed price times quantity) stands to the
retailer's advertised free-shipping threshold, in the native shipping-claim
task's words; optionally a bound on the gap between the two.

```json
{"schema": "steered-free-shipping-v1",
 "retailer_id": "apparel-06",
 "sku_id": "footwear-brand-21/footwear.walking_shoes/00-black-standard-39",
 "quantity": 2, "subtotal_test": "below_threshold",
 "gap_minor": {"max": 10000}}
```

`subtotal_test` is `no_threshold`, `meets_threshold` or `below_threshold`.
The producer draws per retailer whether a threshold is offered (with a
probability by the retailer's scale) and, if so, its value from a short
equally weighted list; `threshold.py` samples those two draws and the offer's
price draw together. A retailer's threshold is a resource of its own,
`("threshold", retailer, "")`, so the requirement combines with stock
requirements and with anything on other retailers, and is coupled with
another requirement on the same retailer's threshold or on the same price.
For `no_threshold` the price is no part of the block. Threshold
probabilities and conditional samples use the existing price-atom model and
the documented finite-arithmetic approximations; repeated threshold values
retain their multiplicity in the producer's choice list.

This is the number the shipping-claim task asks about, not what delivery
costs. Which delivery options exist and what they charge is not steered; see
"What is not done". The unit tests read steered worlds with the native
`catalog_shipping_claim_task.reference`, whose quote context is built with
`basket_quote.make_plan`, `prepared_quote.prepare` and
`catalog_checkout_domain.make` and no route admission.

## The eighth requirement: what a product's reviews say about a topic

Requirement (`steered-review-topic-v1`): a product, a topic of the native
review-summary task (an aspect and its context) and one or more of: the
verdict of the task's count, the number of positive comments, the number of
negative ones, the mean of the product's star ratings, what the first page
of its comments on a review site shows.

```json
{"schema": "steered-review-topic-v1",
 "product_id": "footwear-brand-05/footwear.walking_shoes/00",
 "topic": {"aspect": "wet_paving_grip",
           "context": {"activity": "walking", "surface": "wet paving"}},
 "verdict": "more_negative", "min_assessed": 2,
 "negative": {"min": 3},
 "mean_rating": {"min": 4}}
```

`verdict` is `more_positive`, `more_negative`, `tie` or
`insufficient_evidence`, by the native rule: fewer assessing comments than
`min_assessed` (1 unless stated) is insufficient evidence, otherwise the
larger of the two counts decides. `positive` and `negative` are bounds on
the counts. The task counts written comments: a rating without a comment is
not counted at all, and a comment that does not report on the topic is "not
assessed". `mean_rating` is a `min`, a `max` or both, from 1 to 5, on the mean
of all the product's ratings, with or without a comment, as its rating
summary and the native rating task have it. A bound is the decimal it is
written as: with five ratings, a minimum of 4.2 is met by 21 stars.

This is the first block upstream of the commerce producer: reviews are part
of a product's manufacture. Two producers write them, and `reviews.py` reads
either.

The pilot concepts (walking shoes and walking sandals) get their reviews from
`footwear_context_pilot.sample_reviews`, with one named stream per draw under
the product's own seed. For one review the producer draws a star rating (one
more than a beta-binomial count of four, by the product's execution), a score
for every aspect (a normal draw around a centre set by the stars, shifted for
comfort on a cushioned shoe and for value by the price), the comment's length
(zero three times out of four at the defaults) and the topics of the comment
(value with its own probability, the others by weight without replacement). A
review is positive or negative about a topic when it has a comment, the topic
is among those chosen, and the score is at or above one half or below it. Per
review the rating, the topic's score, the length and the topic choices are
the block.

Every other concept gets its reviews from the review program of its product
package: a list of steps, each a draw or a value derived from earlier ones,
run once per review under that review's own seed, followed by one statement
for every pool of the program's language whose condition holds. `programs.py`
reads such a program whatever the concept. It takes the statements of the
topic, the conditions they are written under, and from the conditions back
through the steps everything those depend on; the draws among them, and the
rating's, are the block. For casual trainers' everyday comfort that is the
rating, the topics and that aspect's own favourable-or-not draw. For a
T-shirt's value it also includes which option the reviewer bought, because
the price paid is the option's. For a tablet's stylus it includes whether
the owner has a pen at all. The probability that one review has a given
rating and says a given thing is then a sum over the outcomes of those draws,
walked in the program's order. The program's own code resolves each draw's
parameters and evaluates each derived value and condition; written here are
the order of the steps as the program's `sample` runs them (a step whose
condition fails is not applicable; a loop that only derives and collects
values runs its steps for each value) and the probability of each outcome of
a resolved draw: a weighted or a uniform choice, a whole number from a range,
the rating, the set of topics, and a normal draw that the program reads only
through `>=` thresholds (the value score, at one half, after the program's
clipping and rounding). Such a draw is followed as the thresholds it
reaches, with one value standing for each case. The thresholds are found on
the expressions as the program parses them, in everything the needed steps
and the topic's statements evaluate, the conditions of the fields they write
included; a mention of the draw that is not the draw alone, `>=`, and a
number written out refuses the program, and so does a field that marks some
value of the draw as unknown, since one value could then not stand for its
neighbours. A threshold is kept as the number the program has, whole or
not. What is read is the distribution each draw is written as; the program
realises a draw from 53-bit uniform numbers in floating point, which follows
that distribution closely for numbers of ordinary size and departs from it at
extremes. The limits are conservative margins that keep rounding and
underflow negligible at the scale this experiment samples at, not the points
at which the sampler fails; outside them a program is refused instead of
approximated: a normal draw whose range, mean, spread, grid or thresholds are
beyond 1e150 in size, or whose spread is below a millionth of its mean's
size; a rating whose beta distribution has a shape parameter below 0.04 or
above a million (Python's gamma sampler underflows with a chance of about
1e-13 at 0.04, rising quickly below; the programs in git have 0.075 at the
least); a weight outside 1e-100 to 1e100, or an outcome of a weighted draw
rarer than one in
a billion of its draw. One review's probabilities must also come out as
probabilities adding up to one. Inside those limits the model is still of
the written distributions: a normal tail beyond about eight spreads, for
one, is in the model and not in what the program's sampler can draw. Because the order of the steps is written here a
second time, every recorded review of a natural world is also followed from
its recorded draws alone, and the world is refused if that gives another
rating or says another thing than the review does.

Either way the reviews of a product draw independently and alike, so the
three numbers (positive, negative, neither) are multinomial with one review's
class probabilities (`reviews.shares`), and the probability of a requirement
is the sum over the counts that satisfy it, kept as logarithms.

The stars. A rating and what the review says are drawn together: the rating
moves the topic's score, so complaints come with low ratings. With a mean
stated, each count's probability is multiplied by the chance that the stars
then total within the bounds. Given the counts, the stars of the reviews of
one class are independent and alike, so their total is a repeated
convolution of that class's rating distribution, and the three classes' totals
are independent (`reviews.starred`). A sample goes on to choose every
review's rating from the exact distribution given the counts and the bounds:
the three totals, then each review's stars in turn given what the rest must
total (`reviews.ratings`). A review with a rating to meet is then redrawn in
two steps: its rating stream until it gives that rating, and its other
streams until the review is of its class. Nothing but the rating passes from
the first step to the second, so the two together are a draw of the review
given both. That needs the rating's chances to be set by no other draw of
the block, which holds for the pilot sampler and for every review program in
git (the rating follows the product's execution alone). Where a program lets
another draw set them, the whole block is redrawn until the review has both
the rating and the class, which is the same conditional draw at a higher
cost.

A sample picks the counts from that distribution, places them on reviews at
random, and then redraws each review's block streams under fresh seeds until
the review is of its class. The rejection is inside one review, where a class
is as likely as `reviews.shares` says (a few percent for a topic's praise or
complaint at the defaults) and does not get rarer with the requirement; what
makes a requirement rare is the counts, and those are chosen exactly. The
record states how many redraws a sample took. Each review gets at most
1,000,000 proposals; for class probability p, the chance of exhausting that
limit is (1 − p)^1,000,000. Exhaustion raises `NumericalLimit`; this is not a
deterministic cutoff at p ≈ 10^-6, and no input so far is near it. Retaining
only successful complete runs can reweight the chosen count mixture when
rejection-limit failures are appreciable. None of
the seed's own block draws is kept, also for reviews that say nothing. Every
other draw of a review is the seed's own (the option bought, the sizing
remarks, the other aspects' normal draws, the phrasing), and reads the
block's draws where the producer makes it: another star rating moves the
other aspects' scores, and other topics change which stock phrases later
reviews use.

The first page. A review site lists a product's written comments a page at
a time: in the order of the review ids, or with the highest or the lowest
star ratings first and ties in the order of the ids
(`native_review_pages.reader_section`; the page size is the site's, 12
unless set). A reader who stops at the first page sees those comments only,
and with the highest ratings first they are the ones likeliest to praise.
`first_page` states the page's size, its order (`highest`, `lowest`,
`identity`) and, for the comments on that page alone, a verdict, a number of
positive or of negative ones, or several:

```json
{"schema": "steered-review-topic-v1",
 "product_id": "footwear-brand-05/footwear.walking_shoes/00",
 "topic": {"aspect": "wet_paving_grip",
           "context": {"activity": "walking", "surface": "wet paving"}},
 "verdict": "more_negative",
 "first_page": {"size": 4, "order": "highest", "verdict": "more_positive"}}
```

The page's verdict is the same rule on the page's comments (`min_assessed`
inside `first_page` is the page's own, 1 unless stated). `pages.py` has the
arithmetic. A review is of some rating and one of four kinds: a comment for
the topic, against it, a comment on something else, or no comment. Take the
ratings in the page's order as levels. Either fewer comments are written
than the page holds and the page is all of them, or the page ends inside one
level: it holds every comment above that level and the first few at it in
the order of the ids. Which comments at that level come first does not
depend on what they say, so the page's comments are independent draws of
their levels' kinds, and so are the reviews outside the page once the number
of further comments at that level is summed over. That sum is an integral
of a polynomial (the factor that depends on the number is a beta integral
over a factorial),
which a Gauss-Legendre rule of enough points gives exactly up to rounding;
the module's docstring has the formula. The probability of a requirement is
the sum over the ways the page and the whole can both be as required, and a
sample draws, in turn, one of those ways, the numbers outside the page, and
which reviews are of which kind, with the page's comments at its last level
placed on the reviews whose ids come first. Every review then has a kind and
a rating to be redrawn to, in the two steps described above. The check reads
the page off the saved reviews by the site's own sort and takes what each
comment says from the native task's reference. A first page is not combined
with a mean rating yet, and it is read for the pilot concepts only: for a
review program, whether a review has a comment at all depends on every
topic's statements, which the reading does not follow yet. Everything is
kept as logarithms, each term one exponent of a sum of logarithms: the
integrand at a point is a product of hundreds of small powers and a large
multinomial number, far outside the floats on its own while their product is
an ordinary probability. At most 200 reviews and a page of 100 are taken.
One review's own probabilities are taken as ordinary floats, as the pilot's
reader gives them; a table with subnormal entries could still lose an
outcome where two of its entries are mixed before a logarithm is taken.

How it meets the producer. A session reseeds the planned review streams of
the product and manufactures that one product again instead of taking it
from the session's store. For a pilot product the plan keys are `("review",
product seed, stream key)` (`streams.reviewed`) and manufacture takes
milliseconds. For a package's review program they are `("program", product
seed, review index, stream key)` (`streams.programmed`): every package opens
its streams through one method of the package class, which the session
replaces for the pass. That method sees the review's seed and the stream's
name and nothing else, and a review's seed is 32 bits, so a planned stream
that some other draw of the pass opened as well would be reseeded with it; a
pass in which a planned stream is opened twice fails. Which program the
producer runs depends on the brand and the product, and the T-shirt package
hands its review program out only after manufacturing and wraps it in checks
that refuse anything but a whole review. So the reading manufactures the
product again by the producer's own call (which must return the entities the
world records), takes the program's document and runs a plain copy of it,
which draws from the same streams. A natural world whose recorded reviews the
copy does not reproduce is refused, and a steered pass whose reviews differ
from the copy's fails. The wrapped program is slow (most of a second per
review), so a steered pass on a T-shirt takes that per review of the
product; on the other concepts it takes milliseconds. The
block's resource is `("reviews", "", product)`: it is independent of every
commerce block and of other products' reviews, and two requirements on one
product's reviews are coupled. `blocks.background` leaves out that product's
reviews and its rating summary and nothing else, so a pass fails if the
commerce world, another product or anything else of this product moved. The
check reads the steered world with the native
`catalog_review_task.reference`, and compares its counts with the recorded
draws read by the rule written out in `reviews.said`.

Limits. On the pilot concepts, not the topics whose score depends on the
option bought or the wearer (`size_fit`, `forefoot_room`). A review program
is refused ("Not modelled") where what the topic depends on includes a loop
that draws or holds another loop, a collected value under a condition of its
own, a draw of another kind than the six above, a normal draw read otherwise
than by `>=` against a number written out (any arithmetic on either side, a
strict comparison or a use of the value itself refuses it; so does a field
that counts some value of the draw as unknown), a step that
reads something the reading's own list of its expressions does not show (a
guard: an unlisted expression that reads only what a listed one reads would
pass it), a statement about
the topic that is neither for nor against, or a review that would be both.
None of the 37 review programs in git does any of these (see the evidence
for the concepts whose data is not in git). The walk branches on every
outcome of every draw the topic depends on, so its cost is the product of
their numbers: at most a few seconds per topic for the programs in git, but
about 50 s where a program draws a whole number from 61 and another from 5.
Only the topic count over all of a product's reviews and the mean of its
stars: not the count of each star, not one option's reviews. No producer
writes a neutral or a mixed comment, or a second statement on a topic under
other circumstances, so those counts are always zero and steering cannot ask
for them: the suite's "opposite opinions in one comment" and "same words,
different circumstances" instances were written by hand onto a saved world.
With a mean stated, whether a count's stars can total within the bounds at
all is decided exactly, from the ratings each class of review can have. A
count that can, but only with a probability below the smallest float, is
left out of the sum; if no count is left and one of them could, the
requirement is refused as a numerical limit and not as impossible. Probabilities
use floating-point logarithms of gamma functions and the complementary error
function; they are exact to that arithmetic. Which reviews a review site
shows, and in what order, is built from the world downstream and is not part
of this.

## The ninth requirement: what a carrier's reviews say about an aspect

Requirement (`steered-carrier-review-topic-v1`): a carrier, an aspect of the
native carrier-review task, the scope the task counts in (a shipping class,
a range of review dates) and one or more of: the verdict, the number of
positive comments, the number of negative ones.

```json
{"schema": "steered-carrier-review-topic-v1",
 "carrier_id": "carrier-01", "aspect": "handoff",
 "shipping_class": "regular", "date_from": "2026-08-14",
 "verdict": "more_negative", "min_assessed": 3}
```

The carrier corpus is drawn in two steps. Every shipment first gets a
history on its own stream, which settles what happened to it: the day and
the window it came in, how it was handed over, the parcel's condition,
tracking and notices. Each is an observation with a sentiment. The review
then comes from a second stream of the shipment: whether there is a comment
(one time in four at the defaults), how many observations it mentions (one
to four, with fixed weights), which (punctuality twice as likely as most,
notices about a third as likely), the wording and the stars.

`carriers.py` takes the histories as upstream and steers the reviews. Its
block is the review stream of every shipment of the carrier in the task's
scope whose history has an observation of the aspect: that review is
positive, negative or neutral about the aspect, by what happened, exactly
when it has a comment that mentions it. The chance of that is the
shipment's own (it depends on what else there is to mention), so a count is
a sum of independent yes/no draws with different probabilities, computed by
a recursion over the shipments; the three counts come from different
shipments and are independent.

A sample picks the counts, then goes through the shipments and decides for
each whether it mentions the aspect given how many of the remaining ones
must, then redraws that shipment's review stream under fresh seeds until the
review does or does not mention it. The whole review is on that stream, so
its stars, its wording and the reviewer's name are redrawn with it.

What it cannot do follows from the choice of block: **what happened to the
shipments is not steered**. A carrier whose handovers all went well has no
complaint about handover to write, and a requirement of one has probability
zero given upstream; so does any count above the number of shipments with
such an observation in scope. The tenth requirement puts the histories into
the block for the two aspects where that has a short closed form. The
candidates tool leaves out verdicts the histories rule out.

The resource is `("carrier_reviews", "", carrier)`: independent of commerce
blocks, of product reviews and of other carriers' reviews, coupled with
another requirement on the same carrier. One thing does reach across
carriers: the producer picks each statement's phrase by how often every
phrase was used before it, over the whole corpus, so redrawing one carrier's
reviews can change the wording (not the aspect, the sentiment or the stars)
of other carriers' reviews. `blocks.background` therefore leaves out, besides
this carrier's reviews and summary and the corpus identity, the wording of
every other carrier review, and compares everything else, including the
histories. The numbers of mentions (0.4, 0.35, 0.2, 0.05) and the aspect
weights are the producer's own constants, which it does not keep in its
configuration; they are written out in `carriers.py` and checked by the
readings against the producer.

The check reads the steered world with the native
`carrier_review_task.reference` in the task's scope and compares it with the
recorded reviews.

Carrier count weights are computed in logarithms, and the sequential choice
of which shipments mention the aspect forms its ratio in logarithms too, so
per-shipment probabilities far below the float range of their products do
not overflow it (`carriers.placed`; the fourteenth review found the earlier
form could).

## The tenth requirement: what happened to a carrier's shipments, and what its reviews say of it

Requirement (`steered-carrier-shipments-topic-v1`): the fields of the ninth,
for the aspects `handoff` and `punctuality`.

```json
{"schema": "steered-carrier-shipments-topic-v1",
 "carrier_id": "carrier-01", "aspect": "handoff",
 "shipping_class": "regular", "date_from": "2026-08-14",
 "verdict": "more_negative", "min_assessed": 3}
```

Here the block is every shipment of the carrier, history and review. Both
aspects are observed exactly when a shipment is not collected and its first
home-delivery attempt does not fail; a noncompliant handoff leaves the
parcel in the lobby and supplies the negative handoff observation. What
decides that and its outcome is a short chain of draws in
`carrier_service_pilot.model.history`, each of fixed probability: which of
the carrier's two services the shipment used (0.7 for the first), whether it
went to a collection point (a quarter of regular shipments when the carrier
has points), whether the first attempt failed (the recipient is at home nine
times in ten; otherwise the parcel must be allowed to be left and the
carrier must get in), the dates (a start 10 to 90 days back, the retailer's
delay, transit, the day chosen, one to three days late when not on time),
and whether the promise was kept, by the carrier's quality level.
`shipments.shares` multiplies these out per service, with the review's
chance of mentioning the aspect given what such a shipment observes, into
the probability that one shipment yields a positive comment in the task's
scope, a negative one, or neither. The date part is an enumeration of the
days, since the review is dated by the first attempt and lateness is the
punctuality observation itself. A carrier's shipments draw independently and
alike, so the counts are multinomial, as for product reviews.

A sample picks the counts, places them on shipments at random and redraws
each shipment's two streams (history and review) under fresh seeds until it
is of its class. The class is read with the producer's own `history`
function under the reseeded stream, and the review's lines as in the ninth;
only the probabilities are this code's arithmetic. Shipment class
probabilities are formed with ordinary floats before the multinomial
calculation takes logarithms; at extreme subnormal text probabilities, a
positive class can round to zero and be treated as impossible. The same
1,000,000-proposal limit and successful-run selection caveat described for
product reviews apply to each shipment. Nothing of the carrier's
own shipments is kept. The carrier's quality levels, its policy and its
services are upstream: a carrier with strong handover keeps its promise 95
times in 100 and complaints stay rare, but they are possible, and the
probability says how rare.

The block writes two resources, the carrier's reviews and its shipments
`("carrier_shipments", "", carrier)`; the reviews-only block of the ninth
requirement declares the shipments as what it reads, so the two are coupled
on one carrier in either order and independent across carriers.
`blocks.background` leaves out, besides what the ninth does, this carrier's
histories and the metrics counted from them, and compares the other
carriers' histories, every carrier's policy and quality levels, and the
commerce world.

The fixed shares in `history` (0.7, 0.25, 0.15, 0.9, 0.5, 0.25, 0.35, 0.8,
the 10 to 90 days) are the producer's own constants, written out in
`shipments.py`; `test_shipments.py` checks each factor by itself against the
producer's draws as well as the class probabilities. Other aspects are not
modelled at this level: tracking and notices have longer chains, and
handling and collection are observed for collected parcels, whose receipt
date depends on opening hours.

## The eleventh requirement: a retailer's shipping policy

Requirement (`steered-retailer-shipping-v1`): a retailer and one or more of
the carriers it must or must not have a contract with, how many carriers it
has, whether any of its contracts offers express or economy delivery, the
lowest standard collection fee among its contracts, the lowest standard
home-delivery fee (a contract's collection fee plus its home difference),
and the days its warehouse takes to dispatch.

```json
{"schema": "steered-retailer-shipping-v1", "retailer_id": "footwear-04",
 "carriers": {"include": ["carrier-03"], "exclude": ["carrier-07"]},
 "carrier_count": {"max": 2}, "express": false,
 "collection_fee_minor": {"min": 5900}, "dispatch_days": {"min": 2}}
```

The producer draws, per retailer, how many carriers (uniformly in a range
set by the retailer's scale: one to three, two to four, three to five), which
ones (an ordered sample of the world's eight carriers without replacement),
per contract whether it has an economy and an express tier (a coin each),
per contract a collection fee and a home difference (each a weighted choice
from a five-row table) and the warehouse's dispatch days (a weighted choice
of none, one or two). All are named streams, and nothing else in the world
reads them: the contracts are recorded on the retailer and used afterwards
by quotes and pages. So they are the block, `policies.py`: the contract
draws when the requirement is about contracts, the dispatch draw when it is
about dispatch, as two resources, `("contracts", retailer, "")` and
`("dispatch", retailer, "")`.

Contracts draw independently and alike whichever carrier they are with. The
probability is a sum over the number of carriers of the chance that the set
of carriers is as required (a ratio of binomial numbers) times the chance
that so many contracts are as required; the latter folds the contracts in
one at a time, keeping only what a requirement reads of them (a tier seen,
the lowest fees so far). A sample chooses the number and that summary, the
contracts back from the last to the first, and the carriers, and replays
all of it through the producer; a plan can now script an ordered sample. The
check reads the recorded contracts and dispatch days. The tables are read
again when a requirement is modelled; a world whose recorded digests of the
sampling defaults and the delivery plan are not the files' is refused.

Limits. Fees are the contract's own standard numbers: what a shopper is
quoted adds the tier's difference, distance and the free-shipping threshold
(`basket_quote`). A branch's dispatch days and whether a carrier takes bulky
parcels are the seed's.

### What the retailer shows of its delivery options

A site built with delivery options on does not show every route a retailer's
contracts allow: the commerce oracle admits a menu per retailer
(`delivery_admission`). Under its plan version 1 the menu is drawn on the
finished world's id, so it is redrawn by any steering and cannot be stated
in advance. Plan version 2 (opt-in: a recipe's `delivery_options` with
`"admission_plan": "retailer-delivery-admission-plan-v2"`) draws on the
seed, the retailer and that retailer's routes, so in a given world a
retailer's menu is a fixed function of its contracts. `menus.py` reads it,
with the oracle's own lines on a view of the world in which the retailer's
contracts are replaced: the admitted carrier routes to the customer's
address, each with the oracle's tariff for an ordinary parcel before any
free-shipping waiver.

The policy requirement takes a `shown` clause, for version 2 only:

```json
{"schema": "steered-retailer-shipping-v1", "retailer_id": "footwear-04",
 "shown": {"cheapest_carrier": "carrier-03",
           "carriers": {"exclude": ["carrier-01"]},
           "destination_type": "home"}}
```

`carriers` are those that must and must not be among the shown routes;
`cheapest_carrier` has a shown route strictly cheaper than every other
carrier's; `destination_type` is `home` (the default) or `any`, which adds
collection points (pickup at the retailer's own branches is no carrier's);
`delivery_options` are the recipe's settings where they are not the
defaults, since the number of shown routes is drawn from its count weights.

A menu has no closed form, so this part is sampled by drawing: contracts
come from their exact distribution given what the requirement states of them
and the carriers the menu needs (a shown carrier is a contracted one), until
the menu they give is as required. The sample is from the block's
distribution given the whole requirement. The probability is the exact one
of the contract statements times the share of 400 such draws that qualify:
an estimate, recorded as one (`probability_is_estimated`, with the counts),
the same for the same world and requirement. A requirement none of the 400
draws meets is reported as not found, which is not a proof that it cannot
occur. On the pilot world a draw takes eight milliseconds, and "carrier X is
the cheapest shown for home delivery" has probability 0.12 to 0.14 at a
medium retailer.

A steered world is checked through the plans a site is built from
(`basket_quote.make_plan`, `delivery_admission.make_plan` with the recipe's
weights and version 2), which must give the menu read from the contracts. The
tests also ask the admitted oracle for quotes of the retailer's real offers:
wherever nothing is waived, the carriers of the home options and the
cheapest among them are the clause's.

### Who is cheapest delivered

The fourth requirement (who has the cheapest available offer) takes
`"delivered": {}`: offers are compared on what one unit costs delivered home,
as the native single-item delivery task compares them
(`quote_offer_task`, cheapest total, home delivery, no coupon).

```json
{"schema": "steered-cheapest-available-v1", "concept_id": "footwear.walking_shoes",
 "predicates": [{"field": "sku.size_eu", "operator": "eq", "value": 42}],
 "delivered": {}, "retailer_ids": ["footwear-01"],
 "product_id": "footwear-brand-12/footwear.walking_shoes/10"}
```

A retailer's delivery charge is a function of the price: the lowest tariff
among the home routes it shows, with the ordinary, distance and geographic
parts waived where it offers free shipping from a subtotal the price
reaches and the parcel does not cross a border. `menus.delivery` reads it
off the retailer's contracts and threshold as the world has them, under
admission plan version 2. The block is the fourth block's own (the
concept's stock and prices), with each pair ranked by price plus its
retailer's charge; an offer competes when a location that ships holds it or
it can be ordered from the supplier, and the pairs of a retailer that shows
no home route do not compete. So the order of offers is not the order of
their listed prices: on the pilot world the pair most likely to be cheapest
delivered wins with probability 0.54, and one retailer's charge is 339
kronor because it ships across a border.

The block declares that it reads the contracts and the threshold of every
retailer that lists a competing offer; a requirement that redraws either
cannot be combined with it, and the twelfth requirement refuses a ranking by
delivered totals together with a statement about the winner's contracts or
threshold. Refused as not modelled: a retailer where what delivery costs, or
whether it is possible, depends on which of its locations holds the stock;
rankings other than the total; physical stock only; a comparison site.

The check is the native task's reference on the steered world (through
`prepared_quote` with the plans a site is built from). The tests also read
the admitted oracle's quotes for every competing offer: who can be
delivered and each total are the block's, on the natural world, with a
threshold lowered until it waives, and on steered worlds.

## The twelfth requirement: who is cheapest, with that retailer's policy

Requirement (`steered-cheapest-seller-policy-v1`): a ranking in the fourth
block's words but without a winner, and a policy in the eleventh's words but
without a retailer. It holds when one retailer's product alone is the
cheapest available offer of the ranking and that retailer's policy is as
stated.

```json
{"schema": "steered-cheapest-seller-policy-v1",
 "cheapest": {"concept_id": "footwear.walking_shoes"},
 "policy": {"express": false, "carrier_count": {"max": 1}}}
```

This is the case "the best offer is at a shop whose delivery the customer
does not like". Without it one would look for a seed in which some retailer
that can win happens to have such a policy, and steer the ranking to it; the
policies the seed drew would then never have been asked anything.
`sellers.py` states it as what it is: one of several things that exclude one
another, "this retailer's product alone is cheapest, and this retailer's
policy is as stated", one for every retailer and product of the ranking.
Stock and prices are drawn apart from policies, so each alternative's
probability is the product of the fourth block's and the eleventh's, the
requirement's is their sum, and a sample picks an alternative in proportion
and samples its two blocks. The winner's policy is drawn as required; every
other retailer's is the seed's own, which is its distribution given the
requirement. The check finds the winner in the saved leaves, then asks the
native oracle and the recorded contracts. As a part of several requirements
it declares everything it could decide: the ranking's stock and prices and
the policy of every retailer in it.

The policy may be about shown options, and the requirement may add
`"free_shipping": false`: the winner offers no free-shipping threshold, so
what its options cost is what a customer pays. That is a third block of the
alternative (the seventh requirement's, with no threshold). Together with
the thirteenth requirement this is "the shop with the best offer delivers
cheapest with a carrier that is badly rated":

```json
{"schema": "steered-requirements-v1", "all": [
  {"schema": "steered-cheapest-seller-policy-v1",
   "cheapest": {"concept_id": "footwear.walking_shoes"},
   "policy": {"shown": {"cheapest_carrier": "carrier-06"}},
   "free_shipping": false},
  {"schema": "steered-carrier-stars-v1", "carrier_id": "carrier-06",
   "average_stars": {"max": 3.6}}]}
```

## The thirteenth requirement: a carrier's stars and how well it serves

Requirement (`steered-carrier-stars-v1`): a carrier and a bound on the
average stars its summary publishes, the level of one or more aspects of its
service (strong, mixed or weak punctuality, handling, handoff,
communication), or both.

```json
{"schema": "steered-carrier-stars-v1", "carrier_id": "carrier-03",
 "average_stars": {"max": 3.7}, "levels": {"punctuality": "weak"}}
```

The producer draws a carrier's four levels, each on its own stream; then
every shipment's history on the shipment's stream, where a level is the
chance that the aspect goes well; then every shipment's review on one more
stream: the comment, and the stars, which are likelier high the more of the
history went well and are held to the comment's tone. The block,
`ratings.py`, is the four level streams and every review stream of the
carrier. The history streams stay the seed's own, so for each of the 81
choices of levels the histories are known (the producer's own `history`,
called with those levels) and with them each review's distribution of stars:
a beta-binomial for the stars as drawn, and the chance that the comment has
praise, complaints or both for the hold. Reviews draw independently, so the
total is a sum of independent numbers. The probability is a sum over the
level choices the requirement allows of the chance of the levels times the
chance of the required average under them. A sample picks the levels in
proportion, then the total, then each review's stars given the total, and
redraws each stream until it gives what was picked.

A low rating therefore comes with worse service, to the extent the producer
ties the two. On the pilot world (32 shipments a carrier, a tenth of a
second to model) a carrier naturally rated 4.38:

| Average at most | Probability | Weak aspects expected, of four |
|---|---|---|
| any | 1 | 0.6 |
| 3.8 | 0.16 | 1.4 |
| 3.6 | 0.063 | 1.7 |
| 3.2 | 0.0036 | 2.4 |
| 3.0 | 0.0006 | 2.7 |
| 2.0 | 2e-11 | 3.7 |

Carriers' natural averages on the pilot and medium worlds lie between 3.8
and 4.6, so "a carrier with really low ratings" in this producer's terms is
one at 3.5 or so; lower is reachable at the same cost but is a carrier whose
reviews are harsher than anything its service explains.

It combines with the twelfth requirement: "the cheapest available offer is at
a retailer that ships with this carrier only, and this carrier is rated at
most 3.9" is two independent blocks. It does not combine with the ninth or
the tenth requirement on the same carrier, whose reviews it redraws.

Limits. The history streams are not redrawn for the stars: the sample and its
probability are given those streams, and what happened to each shipment is
what they give under the sampled levels. The levels are private
parameters; a task sees them through the metrics and the reviews.

### The three together on the medium world

Scripts and outputs under
`.local/coordination/world-requirement-construction-20261010/steering/walkthrough/`
(`case-seller`, `case-carrier`, `case-stars`; not pinned runs), on the medium
world of "A medium world" (21 retailers, 90 products), four seconds a sample:

- "The cheapest available walking shoe is at a retailer with no express
  delivery whose warehouse takes two days to dispatch": probability 0.060;
  under 1,500 other seeds of the same streams it held in 7.0%. In the seed's
  own world two retailers have such a policy and one of them never has the
  cheapest shoe. Over 200 samples nine retailers win: seven of them each
  about as often as its chance of winning times its chance of such a policy
  says (0.10 to 0.21), two once each. The winner's contracts and dispatch
  days are redrawn; the other twenty retailers' are the seed's.
- "... at a retailer that ships with one named carrier only, and that
  carrier's punctuality comments are more negative than positive": 0.0093
  times 0.17, as two independent blocks. Only a small retailer can have one
  carrier, so the two small retailers that can win share the samples.
- "... ships with one named carrier only, and that carrier is rated at most
  3.6", for the carrier the seed rates highest (4.59, one weak-free set of
  levels): 0.0093 times 0.012. In 20 samples the average is 3.34 to 3.59;
  the carrier has one weak aspect in 5, two in 12 and three in 3, and its
  delivery metrics follow (attempts on the promised day 84% to 66% where
  punctuality turns weak).

- With shown options (`case-shown`; admission plan version 2): "the retailer
  with the cheapest available walking shoe shows the carrier the seed rates
  highest as its cheapest home-delivery option, offers no free shipping, and
  that carrier is rated at most 3.6". In the seed's own world no retailer
  shows that carrier cheapest. Probability about 0.046 (an estimate; a
  minute to model, once) times 0.012; 5.4 seconds a sample. In 16 samples
  six retailers win; in the four worlds whose quotes were read, the admitted
  oracle quotes that carrier as the cheapest home option for every one of
  the winner's offers (36 to 60 each), and the carrier's average is 3.44 to
  3.59.

## Requirement candidates for a native task

`variants.of(world, task, api)` takes a native task specification (the
`task` of a generation request) and returns the scenarios of that task that
steering can force on the world, as requirement files with the probability
the block model gives each:

| Task kind | Candidates |
| --- | --- |
| `cheapest_available`, `cheapest_matching_available`, `cheapest_matching_with_memory`, `cheapest_matching_after_clarification`, `cheapest_matching_local_branch_stock`, `recommend_matching_by_priorities`, `cheapest_matching_unit_price` | `likeliest_winner`; `better_offer_unavailable` (the likeliest single offer that would rank ahead of that winner, listed and unavailable); `unlikely_winner` (the pair at the middle of the ranking by probability) |
| `cheapest_matching_with_permitted_relaxations` | `criteria_set_0`, `criteria_set_1`, ...: that set is the first with an available match |
| `shortlist_matching_models` with an integer `limit` | `natural_shortlist`; `tie_at_cutoff`; `another_shortlist`, the last two the likeliest among the first limit + 3 models of the natural ranking, not among all models |
| `comparison_cheapest_exact_sku_stock` (with the bound `sku_id`) | the retailer shown cheapest holds the variant, has it only on supplier order, or has it unavailable |
| `audit_free_shipping_claim` | no threshold; meets; below; just below; just meets |
| `summarize_product_reviews` (topic counts over a product's reviews) | `verdict_more_positive`, `verdict_more_negative`, `verdict_tie`, `verdict_insufficient_evidence`, with the task's `min_assessed`; against the stars, `high_stars_verdict_more_negative` (mean rating of 4 or more) and `low_stars_verdict_more_positive` (2 or less); and, for walking shoes and sandals, the first page against the whole, `first_page_more_positive_verdict_more_negative` and `first_page_more_negative_verdict_more_positive` (four comments to a page, highest ratings first, as in the suite's instance; the task does not say how its site pages) |
| `summarize_carrier_reviews` (topic counts) | the same four verdicts in the task's scope, without those the shipments' histories rule out; for `handoff` and `punctuality` also `redrawn_shipments_verdict_...`, the four verdicts with the carrier's shipments redrawn |

A task is translated field by field, and a task with a field the tool does
not carry into the requirement is refused with a `ValueError` that names the
field, so that nothing that changes the native answer is dropped. That
includes the native price cap (`max_price_minor`), which no block models
yet, and a shortlist task without a limit, which lists every model. A world
in which no model matches gives no shortlist candidate. For the
shipping-claim task `delivery_types` is accepted and not used: it changes
which options the native task counts, not the subtotal test.

The search models one requirement per retailer/product pair of the concept
and one per competing offer. Requirements of one task differ only in who
wins and which offer sits below the winner, so they share a
`cheapest.frame`: the scope, the block's pairs and each pair's table when
none of its offers is named. Only the pair of a named offer is rebuilt, and a
model with a frame is the same as one without. On the medium world (21
retailers, 90 products) that took the tool from 174 to 615 s per task down to
158 to 162 s, which is the natural pass it starts with, and its candidates
were unchanged (`medium/variants/`, `medium/variants-shared/`; B01, B05, B14
and B20's task forms). `python -m experiments.steered_generation.variants` writes
the files for a generation input after one natural pass; the runner then
samples and checks whichever of them is wanted. A comparison site goes with
the surrounding-site controls the world is published with, given as
`surrounding` in the task.

The runner does both steps after one natural pass when it is given the task
instead of requirement files:

```
python3 scripts/run_bounded_job.py -- python -B -m experiments.steered_generation.run \
    --native-root ROOT --native-commit COMMIT --steering-commit COMMIT \
    --generation-input INPUT.json --task TASK.json --candidate verdict_tie \
    --samples 2 --validate-trials 2000 --producer-redraws 2 --output FOLDER
```

It writes every candidate of the task under `FOLDER/candidates/`, runs the
named ones (all of them without `--candidate`; an unknown name is an error
that lists the names, and a task with no candidate on the world is an error
too, both before anything is written), and records the task's digest and the candidates with
their probabilities in the receipt. Each sample folder holds the steered
world, what the check read off it and the steering record. Tried on two
suite tasks (`suite/variants/one-command/`): H10's review task with
`verdict_tie` took 8 s in all, B16's carrier task with
`redrawn_shipments_verdict_more_negative` 30 s.

For the memory and clarification tasks (`cheapest_matching_with_memory`,
`cheapest_matching_after_clarification`) the native module's own `resolve`
joins the remembered or hidden requirement to the stated predicates, and the
candidates are those of the resulting feature task, which is what their
native references read. Cart-preparation tasks (`prepare_matching_carts`,
`prepare_matching_checkout_details`) are not covered: their reference asks
only that matching offers exist, not which is cheapest.

## Several requirements in one world

Requirement (`steered-requirements-v1`): a list of requirements, each of one
of the thirteen kinds above, that must all hold.

```json
{"schema": "steered-requirements-v1",
 "all": [{"schema": "steered-offer-stock-v1", "...": "..."},
         {"schema": "steered-offer-price-v1", "...": "..."}]}
```

Each block declares two sets of resources, a resource being the stock or the
price of one retailer/product:

| Block | Decides (`writes`) | Probability also depends on (`reads`) |
| --- | --- | --- |
| One offer's stock | stock of its retailer/product (all SKUs: the conditions are shared) | nothing |
| One offer's price | price of its retailer/product | nothing |
| Who is cheapest, on prices | price of every pair of the concept with an available offer | stock of every pair of the concept, which decides who competes |
| Who is cheapest, on stock and prices | stock and price of every listed pair of the concept with an offer that competes | nothing |
| Who lists a product cheapest | price of every compared pair of the product | nothing |
| Which models make the shortlist | stock and price of every listed pair of the concept with an offer that competes | nothing |
| A basket against the free-shipping threshold | the retailer's threshold, and the price of the retailer/product unless no threshold is required | nothing |
| What a product's reviews say about a topic | the product's reviews | nothing |
| What a carrier's reviews say about an aspect | the carrier's reviews (and the wording of other carriers' reviews, which nothing is judged on) | the carrier's shipments |
| What happened to a carrier's shipments and what its reviews say | the carrier's shipments and its reviews | nothing |

`blocks.independent` accepts a list of blocks when no block decides a
resource that another decides or depends on. The producer draws separate
resources on separately named streams, so such blocks are independent given
everything upstream. Each is then sampled by itself on the natural world, all
plans are replayed in one pass of the real producer, and the probability that
every requirement holds is the product of the blocks' probabilities. This is
the exact joint conditional sample, at the cost of one pass whatever the
number of requirements.

Anything else is refused with `coupled_requirements` and a sentence naming
the two requirements and the shared resource. In particular:

- two SKUs of one product at one retailer (shared stock conditions);
- who is cheapest for a concept, of either kind, together with a stock
  requirement on any offer of that concept, in either order;
- who is cheapest together with a price bound on a competing pair;
- two price bounds on one retailer/product.

Allowed: stock and price of the same offer; any number of offers at different
retailers or of different products; who is cheapest for one concept with
stock or price requirements on other concepts.

A refusal says the parts cannot be sampled separately. It says nothing about
probability; a joint block could still sample them. The fourth block is such a
joint block for one case, a cheaper offer that is sold out. It does not yet
take a stock or price requirement on a named offer of its own concept.

Coupling is settled first, from each module's `footprint`, which needs no
probability. Only then is each part asked for one. The order matters: a part's
probability treats everything outside its block as fixed, so "zero given
upstream" for one part is no verdict on the whole requirement when another
part redraws that upstream. A shop with nothing in stock cannot be cheapest by
itself, but can together with a requirement that restocks it; that pair is
reported as coupled, not as impossible. (The first version of this code asked
for probabilities first and reported it as impossible; the fourth Codex
review caught it.) When no part redraws what a zero-probability part depends
on, the requirement is reported as zero with that part's index and reason.

`blocks.replay` is now the one place where plans meet the producer, for single
requirements too: it runs the pass, has each block confirm that the producer
recorded its plan, and compares the natural and the steered world with every
leaf the blocks decide masked out (`blocks.background`). Any other difference
is an error.

## Evidence on seed 73

Saved seed 73 at accepted source `e3fbfadd84d3b16a26895d62abb66f61df433697`:
25 products, 320 SKUs, 12 retailers, 411 offers; 48 retailer/product pairs sell
walking shoes, and seven retailers sell the one walking shoe cheap enough to
ever be cheapest. Receipts and worlds are under
`.local/coordination/world-requirement-construction-20261010/steering/`:

| Run | Steering commit | Holds |
| --- | --- | --- |
| `run-v4-prices/`, `run-v4-stock/` | `c63ba3c1` | who is cheapest; one offer's stock |
| `run-v5-basics/` | `832238a6` | one offer's price; combined requirements; two million redraws each |
| `run-v5-cheapest/` | `832238a6` | who is cheapest combined with other concepts; 30,000 redraws |
| `run-v5-regression/` | `832238a6` | every `run-v4` requirement again |
| `run-v6-all/` | `390247b` | every requirement again with the sampling defaults read once; 20,000 redraws |
| `run-v7-all/` | `ac1eacc` | every requirement again after coupling was moved ahead of probabilities; 20,000 redraws |
| `run-v8-sold-out/` | `74ad475` | stock and prices together on sandals, tablets and trainers, alone and combined; 200,000 redraws |
| `run-v8-shoe/` | `74ad475` | stock and prices together on walking shoes; 30,000 redraws |
| `run-v8-regression/` | `74ad475` | every earlier requirement again; 20,000 redraws |
| `run-v9-sold-out/`, `run-v9-shoe/`, `run-v9-regression/` | `7dd4727` | the three `run-v8` runs again after the sixth review's fixes |
| `medium/run-v9-shoes/`, `medium/run-v9-others/` | `7dd4727` | a medium world from dev's producer; see "A medium world" |
| `run-v10-sold-out/`, `run-v10-shoe/`, `run-v10-regression/`, `medium/run-v10-shoes/`, `medium/run-v10-others/` | `50a3a79` | all five again after the seventh review's fixes; fewer redraws on the medium world (3,000 and 40,000) |
| `run-v11-sold-out/`, `run-v11-shoe/`, `run-v11-regression/`, `medium/run-v11-shoes/`, `medium/run-v11-others/` | `311e8ff` (code `d9973a9`) | all five again after the eighth review's fix, with shorter redraw counts (50,000, 10,000, 20,000; 1,000 and 10,000 on the medium world) |
| `readings/run-v1/` | `9cb2610` | the native tasks' readings of who competes and what is available, and who lists a product cheapest; 20,000 redraws |
| `readings/run-v2/` | `cf07fdb` | the same after the rebase onto the approved candidate; 4,000 redraws |
| `medium/readings/run-v1/` | `816f35f` | the readings on the medium world; 4,000 redraws |
| `suite/B11/` .. `suite/B14/`, `suite/B11-seed73/`, `suite/B11-medium/` (`run-v1`) | `d0c3272` | rankings and shortlists on the suite's own inputs and on larger ones |
| `suite/variants/CASE/run-v1/` for twelve suite tasks | `3d99dd0`, `19a2562` | every candidate the tool writes for the task, sampled and checked; 10,000 redraws |
| `suite/variants/B09/`, `H10/` (`run-v1`) | `6040664` | the product-review tasks' candidates; 10,000 redraws |
| `suite/variants/B09-rare/`, `B16/`, `B16-tracking/` (`run-v1`) | `51aefce` | rarer review requirements (200,000 redraws); the carrier-review task's candidates (10,000) |
| `suite/variants/B16-shipments/`, `B16-punctuality/` (`run-v1`) | `e837e7f` | the carrier-review task with the carrier's shipments redrawn; 50,000 redraws |
| `suite/variants/one-command/` | `7450c15` | the runner given a task: two suite tasks, one named candidate each |
| `medium/reviews/run-product/`, `run-carrier/` | `79cb000` (executable sources as at `7450c15`) | the runner given a task: both review task forms on the medium world; 20,000 redraws |

Requirement files are in `steering/`, `steering/stock/`, `steering/price/`,
`steering/cheapest/` and `steering/combined/`. Commit `832238a6` moved the
single-requirement paths onto `blocks.replay`, `390247b` added the shared
sampling defaults, `ac1eacc` changed the order of the coupling check and
`74ad475` added the joint block and moved the stock stream names into shared
helpers, `7dd4727` keeps products over pairs as logarithms and `50a3a79`
guards the stock outcomes and samples through `blocks.pick`; each rerun
reproduces every earlier steered world with the identical world identity (27
of 27, then 48 of 48 six times), with the same probabilities and refusals.
`d9973a9` changes which weights `blocks.pick` hands to the float choice; the
`run-v11` runs reproduce every `run-v10` sample of the fourth block as well,
with the identical world identity (15, 6, 15 and 12 samples) and identical
probabilities; these are observed identities for the tested configurations.
`74ad475` is a commit of the branch based on `e3fbfadd`
(`dev/world-steered-generation-20261010-r1`); `7dd4727` is on the branch based
on dev (`dev/world-steered-generation-20261011-r2`), where the same change is
`676a6e6`. From `run-v9` on the steering code runs from the dev-based checkout
and the seed-73 producer is still the accepted tree at `e3fbfadd`.
`run-v3` is the same price evidence at the earlier reviewed
commit, with identical probabilities and hit counts. `run-v1` and `run-v2`
used the removed keep-if-it-fits rule; their worlds satisfy their
requirements but are not a distributional sample.

### Prices

| Requirement on that shoe | Probability given upstream | Natural worlds per hit |
| --- | --- | --- |
| `footwear-03` is the sole cheapest seller | 0.101 | about 10 |
| `footwear-02` and `apparel-06` tie as cheapest | 0.0028 | about 350 |
| Those two and `department_store-02` tie | 0.00036 | about 2,700 |
| Five named retailers tie, the other two do not | 0.00069 | about 1,450 |

"Natural worlds per hit" is for this upstream. The five-way tie is likelier
than the three-way one because retailers that all draw the matched reference
price tie automatically.

Cost: the natural pass took 27 to 32 s and an unsteered replay 2.0 to 2.3 s.
Each steered world took 2.3 to 3.0 s including planning, the pass through the
producer and all checks, whatever the probability (the higher figures are
from `run-v4`, whose two runs shared the machine). Three worlds were sampled
per requirement, twelve in all.

The model was compared with 30,000 redraws of the price block through the
producer's own `_offer_price` under other seeds:

| Requirement | Computed probability | Hits in 30,000 | Winning-price distance |
| --- | --- | --- | --- |
| Sole `footwear-03` | 0.101 | 2,939 | 0.025 |
| Two-way tie | 0.0028 | 89 | 0.15 |
| Three-way tie | 0.00036 | 7 | 0.24 |
| Five-way tie | 0.00069 | 27 | 0.00 |

Each hit count is within two standard errors of the computed probability.
"Winning-price distance" is the total-variation distance between the model's
distribution of the winning price given the requirement and the one observed
among the hits. It is informative only for the first row; with 89 or 7 hits
spread over up to 30 possible prices, distances of that size are sampling
noise. The five-way tie is almost always at the reference price, in the model
and in all 27 hits. Rare requirements are exactly where a direct empirical
check is weakest; there the evidence is the per-pair price model, which the
unit tests check against the producer's draw expression, together with the
independence of separately named streams.

The natural pass reproduces the saved world's identity, and an unsteered pass
with cached manufacture reproduces it again. Each steered world differs from
the natural one only in the price and price-draw fields of the concept's 48
retailer/product pairs, satisfies the pricing rule, and has the designated
retailers as its only cheapest sellers under both the native oracle and a
separate full scan.

### Stock

All five requirements are on one SKU, size 39 of the same walking shoe, at
different retailers. In the natural world it is in stock everywhere.

| Requirement | Locations | Probability given upstream | Natural worlds per hit |
| --- | --- | --- | --- |
| `outdoors-02` holds at least 45 in its warehouse | 7 | 0.0675 | about 15 |
| `apparel-06`: in stock, but at no location that ships | 6 | 0.0289 | about 35 |
| `footwear-06`: on supplier order only | 3 | 0.0140 | about 71 |
| `department_store-01`: exactly one left in the warehouse, none elsewhere | 8 | 0.0000100 | about 99,600 |
| `footwear-02`: unavailable (none at any of 11 locations) | 11 | 0.0000060 | about 167,700 |

A sixth, a supplier order at `footwear-03`, is refused with
`supplier_disabled`: that retailer takes no supplier orders in this seed.

Cost: 2.3 to 3.5 s per steered world, fifteen worlds in all, including the
1-in-167,700 one. Between 7 and 22 streams were scripted per world out of
about 6,970 opened.

What the producer rebuilt: in all fifteen worlds the stock of the other five
sizes at that retailer differs from the natural world (in fourteen, all five
of them), because the sampled conditions are shared. An offer that is empty
at eleven locations makes "mostly depleted" the likely condition at each, so
the neighbouring sizes thin out as well. Between 0 and 9 streams were opened
that the natural pass never opened, and 3 to 24 natural ones were not opened,
mostly quantity draws that a zero draw switches on or off.

| Requirement | Computed probability | Hits in 2,000,000 | Expected hits |
| --- | --- | --- | --- |
| Warehouse at least 45 | 0.0675 | 134,652 | 135,000 ± 355 |
| In stock, nowhere that ships | 0.0289 | 57,936 | 57,891 ± 237 |
| Supplier order only | 0.0140 | 28,132 | 28,002 ± 166 |
| Last one in the warehouse | 0.0000100 | 18 | 20.1 ± 4.5 |
| Unavailable at 11 locations | 0.0000060 | 9 | 11.9 ± 3.5 |

Hits are counted on `stock.natural_draws` under two million other seeds; the
± is one standard error. Separately, the real producer redrew each block
under 40 other seeds (200 passes): what it recorded for the offer equalled
`natural_draws` in every pass, and the native oracle agreed with the reading
on whether the requirement held. The supplier-order requirement can end two
ways (no stock at all, or stock only where it cannot be dispatched); the
shares of the two among the 28,132 hits are within 0.001 of the model's.

Every steered world differs from the natural one only in stock conditions,
stock quantities, supplier orders and catalog page stock of that one
retailer/product, passes the oracle and a separate direct reading, and an
unsteered pass after all of them still reproduces the natural world.

### One offer's price

Size 39 of the same walking shoe, reference price 510 kr; prices move in steps
of 10 kr between 360 and 660 kr.

| Requirement | Natural price | Probability given upstream | Natural worlds per hit | Hits in 2,000,000 | Expected hits |
| --- | --- | --- | --- | --- | --- |
| `footwear-02` lists it at exactly 510 kr | 480 kr | 0.447 | about 2 | 894,056 | 893,719 ± 703 |
| `outdoors-02` lists it at 400 kr or less | 540 kr | 0.0119 | about 84 | 23,750 | 23,707 ± 153 |
| `department_store-01` lists it at 360 kr, the lowest the producer allows | 510 kr | 0.00134 | about 750 | 2,599 | 2,680 ± 52 |

A fourth, 300 kr or less at `apparel-06`, is refused with `no_price`.

Hits are counted with the producer's own `_offer_price` under two million
other seeds. Among the 23,750 hits of the second row the five possible prices
occur in the model's proportions to within 0.003 (total-variation distance).
In every sampled world the producer repriced all six sizes from the one draw.
The real producer redrew each block under 40 other seeds (120 passes); every
listed price equalled `_offer_price` under that seed.

### Several requirements in one world

All parts are requirements from the tables above unless described.

| Requirements | Parts | Probability given upstream | Natural worlds per hit | Joint hits | Expected |
| --- | --- | --- | --- | --- | --- |
| One offer at `outdoors-02`: at least 45 in the warehouse and 400 kr or less | 2 | 0.000800 | about 1,250 | 1,559 in 2,000,000 | 1,600 ± 40 |
| Three shops: supplier order only, in stock where nothing ships, at least 45 in the warehouse | 3 | 0.0000274 | about 36,600 | 52 in 2,000,000 | 54.7 ± 7.4 |
| All five stock requirements and all three price requirements | 8 | 1.2e-20 | about 9e19 | 0 in 2,000,000 | 0 |
| Two named shops tie as cheapest for the shoe; a t-shirt at `apparel-06` is on supplier order only; a tablet at `marketplace-07` is listed at 7,000 kr or less | 3 | 0.00000205 | about 489,000 | 0 in 30,000 | 0.06 |

A joint hit is a seed under which every part's reading holds at once. Where
there are enough of them (the first two rows) the joint frequency is the
product of the parts', which is the independence the method relies on. The
trial counts of the other two rows give no useful joint-frequency check: the
last row would need about half a million redraws per expected hit, and the
eight-part one cannot practically be checked that way at all. There the
evidence is each part's own frequency, which was recounted in the same redraws
and agrees with its computed probability in every case, and the declared
independence of the blocks. In the last row the three parts were hit 89, 220
and 2,828 times in 30,000 (expected 85 ± 9, 226 ± 15, 2,867 ± 51).

Two combinations are refused with `coupled_requirements`: the two-way tie
together with the supplier-order requirement on a walking shoe (availability
decides who competes), and sizes 39 and 40 of the shoe both unavailable at
`footwear-02` (shared conditions).

Cost: one pass whatever the number of parts. At `832238a6` a sample took 2.2
to 2.5 s for two or three parts and 2.9 to 4.0 s for eight (84 to 86 streams
scripted). With the sampling defaults read once (`run-v6-all`) every single
requirement takes 0.47 to 0.64 s, a combination of two or three 0.56 to
0.73 s and the eight-part one 0.94 to 1.0 s; an unsteered replay takes 0.37 s.

The real producer redrew the blocks of each combination under 40 other seeds
(160 passes): for every part, what the producer recorded equalled the part's
reading, and the verdict on the world equalled the reading's.

### The cheapest available offer, with stock

`run-v8-sold-out/` and `run-v8-shoe/`, three samples each; `run-v9-sold-out/`
and `run-v9-shoe/` repeat them at `7dd4727` with the same sampled winning
prices and the same hit counts, and probabilities equal to fifteen digits (the
world identities differ, since the record gained the logarithm).
`run-v10-sold-out/` and `run-v10-shoe/` repeat them at `50a3a79`: the same
hit counts and refusals, probabilities equal to fourteen digits, and other
samples, since the winning price is now drawn through `cheapest.pick_log`;
every one of them passes the same checks. The table gives the `run-v8`
timings; `run-v10` samples took 0.52 to 0.82 s with five runs sharing the
machine. "Redraws" are the
block's reading of the producer's stock and price lines under other seeds
(200,000 for sandals, tablets and trainers, 30,000 for walking shoes, whose
concept has 322 offers); expected hits are the computed probability times the
redraws, with one standard error.

| Requirement | Pairs / offers in the concept | Probability given upstream | Sample | Hits in redraws | Expected | Winning-price TV |
| --- | --- | --- | --- | --- | --- | --- |
| Walking shoe: `footwear-02` alone is cheapest available (`shoe-footwear-02`) | 49 / 322 | 0.1013 | 0.58 to 0.65 s | 3,053 | 3,039 ± 52 | 0.023 |
| The same, with `footwear-03`'s offer of the shoe listed below it (`shoe-sold-out-footwear-03`) | 49 / 322 | 8.29e-5 (1 in 12,063) | 0.61 to 0.68 s | 0 | 2.5 ± 1.6 | too few hits |
| Sandal: `footwear-02` alone is cheapest, `footwear-03`'s offer listed below it (`sandal-sold-out-footwear-03`) | 9 / 35 | 0.00328 (1 in 305) | 0.49 to 0.51 s | 638 | 655 ± 26 | 0.077 |
| Sandal: two retailers listed below the winner (`sandal-two-sold-out`) | 9 / 35 | 1.05e-6 (1 in 952,493) | 0.52 s | 0 | 0.2 ± 0.5 | too few hits |
| Tablet: one shop, its cheaper model listed below the winning one (`tablet-sold-out-same-shop`) | 2 / 4 | 0.1402 | 0.51 to 0.52 s | 28,026 | 28,042 ± 155 | 0.021 |
| Trainer: a winner at more than three times the natural winning price, the natural winner listed below it (`trainer-unlikely-apparel-06`) | 4 / 35 | 2.66e-14 | 0.51 to 0.77 s | 0 | 0 | too few hits |
| Walking shoe: the winner's own offer listed below the winner (`refused-own-size-footwear-02`) | | refused, `no_outcome` | | | | |

In every sample the native oracle names exactly the designated winner, lists
each named offer as unavailable and prices it below the minimum, and a direct
scan of the saved leaves agrees. In the shoe and sandal samples the retailer
listed below the winner has no size of the product available, as the
requirement implies where all sizes share a price. A steered sample scripts
between 12 streams (tablets) and about 3,450 (walking shoes); the block model
takes 0.01 to 0.08 s.

The real producer redrew the concept's stock and price streams under 40 other
seeds for each of the six sampled requirements (240 passes): every recorded
condition, price, quantity and supplier order equalled the block's reading,
and the verdict on the world equalled the reading's. The requirement held in
7, 0, 1, 0, 7 and 0 of the 40 passes.

What the redraws support: the probability to within a few percent where it is
above about 1 in 1,000 (three requirements), and the distribution of the
winning price there; the winning-price distances are at the size sampling
noise gives for those hit counts. For the rarer requirements the redraws
cannot distinguish the computed probability from a wrong one; they rest on
the same model and code path as the likelier ones, on the unit tests'
comparison with rejection sampling on a stock-poor world, and on the producer
recording every planned leaf.

Combined with other concepts (`combined/sold-out-sandal-and-other-concepts`):
the sandal requirement, a t-shirt on supplier order at `apparel-06` and a
tablet at 7,000 kr or less at `marketplace-07`. Probability 2.35e-6 (1 in
424,694), 0.68 to 1.02 s per sample; part hits in 200,000 redraws 638, 1,525
and 19,004 against 655 ± 26, 1,504 ± 39 and 19,114 ± 132 expected; no joint
hit, with 0.5 expected. The sandal requirement with a stock requirement on a
sandal offer (`combined/refused-sold-out-sandal-and-stock`) is refused with
`coupled_requirements`.

### The native tasks' readings, and who lists a product cheapest

`readings/run-v1/` at `9cb2610` (the work branch before its rebase onto the
approved fourth-block candidate; kept reachable as tag
`steering-evidence-readings-run-v1`), on saved seed 73, which is the world of
the suite's comparison-scoped tasks B01 and H09; three samples each, 20,000
redraws, 10 producer redraws each (all equal to the reading).
`readings/run-v2/` repeats it at `cf07fdb`, the rebased code, with 4,000
redraws: all 30 samples with the identical world identity and identical
probabilities. Requirement files were chosen by `readings/explore.py` from
the block models' own probabilities.

| Requirement on walking shoes | Reading | Competing pairs | Probability given upstream | Sample | Hits | Expected |
| --- | --- | --- | --- | --- | --- | --- |
| A retailer alone is cheapest available among the pairs `comparison-01` lists (`site-winner`) | comparison site | 27 | 0.393 | 0.75 to 0.80 s | 7,883 | 7,868 ± 69 |
| The same with another listed retailer's offer below it (`site-sold-out`) | comparison site | 27 | 4.3e-11 | 0.78 to 0.83 s | 0 | 0 |
| A retailer alone is cheapest in EU 42 with physical stock (`size42-winner`) | size, physical stock | 35 | 0.108 | 0.60 to 0.63 s | 2,150 | 2,165 ± 44 |
| The same with another retailer's size 42 listed below it (`size42-sold-out`) | size, physical stock | 35 | 0.00172 (1 in 581) | 0.61 to 0.62 s | 27 | 34.4 ± 5.9 |
| EU 42, moderate cushioning, at most 340 g, physical stock: the B05 predicates (`features-winner`) | size and two facts, physical stock | 4 | 0.201 | 0.54 to 0.65 s | 4,106 | 4,012 ± 57 |
| The same with another matching offer listed below it (`features-sold-out`) | size and two facts, physical stock | 4 | 0.00319 (1 in 314) | 0.59 to 0.72 s | 75 | 63.7 ± 8.0 |
| Cheapest EU 42 held at a pickup branch in Uppsala: the B20 reading (`branch-winner`) | size, branch stock | 35 | 0.142 | 0.66 to 0.70 s | 2,821 | 2,847 ± 49 |
| The same with another retailer's size 42 listed below it (`branch-sold-out`) | size, branch stock | 35 | 0.0158 (1 in 63) | 0.63 to 0.64 s | 314 | 316 ± 18 |
| A retailer lists a shoe cheapest among those `comparison-01` shows (`advertised-cheapest`) | fifth block | 3 | 0.252 | 0.52 to 1.69 s | 4,995 | 5,040 ± 61 |
| The same, with one size there only on supplier order: the B04 case (`advertised-cheapest-on-supplier-order`) | fifth block with a stock requirement | | 8.0e-6 (1 in 125,083) | 0.57 to 0.63 s | 0 joint; parts 4,995 and 0 | parts 5,040 ± 61 and 0.6 |

Every sample passed the native oracle of its reading (`feature_offer_task`,
`catalog_branch_task`, the comparison-scoped `basic_offer_task`) and the
direct reading of the saved leaves by the same rule. The combination was
checked by its two parts' own checks; the native comparison-stock oracle is
applied to that combination in the unit tests, not in the pinned runner.

The same ten kinds of requirement on the medium world of "A medium world"
(`medium/readings/run-v1/` at `816f35f`, dev's producer; requirement files
chosen by `medium/readings/explore.py`; 4,000 redraws, 5 producer redraws
each): all sampled and checked, 1.4 to 3.0 s per sample. Hits against
expected: comparison-site winner 683 against 668 ± 24 (105 competing pairs),
with a listed offer below it 18 against 20.4 ± 4.5; size 42 with physical
stock 541 against 531 ± 22 (167 pairs), sold out 20 against 19.4 ± 4.4; the
B05 predicates the same counts (the same shoe wins under both); branch stock
in Uppsala 1,125 against 1,140 ± 29, sold out 262 against 264 ± 16; advertised
cheapest 995 against 1,026 ± 28; with the variant only on supplier order
(1 in 1,547) 1 joint hit against 2.6 ± 1.6.

### Other rankings and shortlists

Pinned runs at `d0c3272` through dev's producer in the steering checkout,
launched by `suite/launch.sh`. The first four use the 34-task suite's own
generation inputs and task specifications for B11 to B14 (`suite/B11/` to
`suite/B14/`, each with its `suite-task.json`); B11's own world has only two
shoe models in size 42, so its three-model shortlist with a tie cannot exist
there and the B11 task is also run on the seed-73 and medium inputs
(`suite/B11-seed73/`, `suite/B11-medium/`). Requirement files were chosen by
`suite/explore.py`. Three samples each, 10 producer redraws each (all equal
to the reading); `summarize-suite.py` prints these figures.

| World | Requirement | Probability given upstream | Sample | Redraws | Hits | Expected |
| --- | --- | --- | --- | --- | --- | --- |
| B12 (7 retailers, 300 offers) | the first relaxation, up to 340 g, is the first criteria set with a match (nothing in the world meets the original 220 g) | 0.410 | 0.86 to 0.88 s | 20,000 | 8,229 | 8,203 ± 70 |
| B12 | the second relaxation, up to 450 g, decides: all ten size-42 variants meeting the first are out of stock | 1.7e-20 | 0.79 to 0.86 s | 20,000 | 0 | 0 |
| B13 (2 retailers, 15 offers) | cheapest per kilogram: the likeliest winner | 0.995 | 0.57 to 0.65 s | 100,000 | 99,518 | 99,510 ± 22 |
| B13 | cheapest per kilogram: an unlikely winner | 2.0e-4 (1 in 4,945) | 0.54 to 0.62 s | 100,000 | 24 | 20.2 ± 4.5 |
| B14 (8 retailers, 456 offers) | lightest size-42 shoe in stock, then price: the likeliest winner | 0.559 | 0.80 to 0.83 s | 20,000 | 11,167 | 11,181 ± 70 |
| B14 | the same with an offer that would rank ahead listed below it | 0.106 | 0.77 to 0.87 s | 20,000 | 2,159 | 2,119 ± 44 |
| B14 | a heavier shoe wins: every lighter one in the size is out of stock | 1.0e-47 | 0.79 to 0.83 s | 20,000 | 0 | 0 |
| B11 (4 retailers, 72 offers) | the shortlist is the two models that exist in the size, fewer than the limit of three | 0.111 | 0.50 to 0.53 s | 20,000 | 2,184 | 2,228 ± 45 |
| Seed-73 input (12 retailers, 411 offers; 9 models in the size) | the natural three-model shortlist | 0.811 | 0.69 to 0.74 s | 20,000 | 16,258 | 16,228 ± 55 |
| Seed-73 input | four models for a limit of three: a tie at the cutoff | 0.0248 (1 in 40) | 0.67 to 0.75 s | 20,000 | 500 | 495 ± 22 |
| Seed-73 input | another three-model shortlist | 5.6e-24 | 0.69 to 0.71 s | 20,000 | 0 | 0 |
| Medium input (21 retailers, 2,849 offers; 29 models in the size) | the natural three-model shortlist | 0.811 | 2.3 to 2.5 s | 4,000 | 3,266 | 3,246 ± 25 |
| Medium input | four models for a limit of three: a tie at the cutoff | 0.0294 (1 in 34) | 2.4 to 2.6 s | 4,000 | 111 | 118 ± 11 |
| Medium input | another three-model shortlist | 3.2e-12 | 4.0 to 4.2 s | 4,000 | 0 | 0 |

Every sample passed the native oracle of its task (`catalog_relaxation_task`,
`catalog_unit_price_task`, `catalog_priority_task`, `catalog_shortlist_task`)
and the direct reading of the saved leaves by the same rule. In the tie
samples the native shortlist has four models, two of them at the cutoff. The
two natural-shortlist probabilities agree to four digits by coincidence
(0.811405 and 0.811428); each is confirmed by its own redraws.

These worlds come from dev's producer, so they are not the suite's frozen
worlds: the inputs and the task specifications are the suite's, the world
identities are not, and nothing here has been published or bound to a task
instance.


### The suite's tasks, through the candidates tool

For twelve tasks of the 34-task suite, `variants` was run on the task's own
specification and generation input (`suite/variants/CASE/task.json`,
`generation-input.private.json`), and the pinned runner then sampled and
checked every candidate it wrote (`suite/variants/CASE/run-v1/`, launched by
`suite/variants/launch.sh`; three samples, 10,000 redraws and 5 producer
redraws per candidate; `summarize.py` prints these figures). Steering
commits `3d99dd0` and, for B07 and B08, `19a2562`; the steering runtime files
are the same at both. Dev's producer in the steering checkout.

| Task | World (retailers / products / offers) | Candidate | Probability given upstream | Sample | Hits in 10,000 redraws | Expected |
| --- | --- | --- | --- | --- | --- | --- |
| B01: cheapest available on a comparison site | 12 / 25 / 411 | `likeliest_winner` | 0.393 | 0.70 to 0.87 s | 3,888 | 3,934 ± 49 |
|  |  | `better_offer_unavailable` | 4.3e-11 | 0.77 to 0.84 s | 0 | 0 |
|  |  | `unlikely_winner` | 4.8e-44 | 0.71 to 0.74 s | 0 | 0 |
| H09: the same task as B01 | 12 / 25 / 411 | `likeliest_winner` | 0.393 | 0.69 to 0.82 s | 3,888 | 3,934 ± 49 |
|  |  | `better_offer_unavailable` | 4.3e-11 | 0.73 to 0.82 s | 0 | 0 |
|  |  | `unlikely_winner` | 4.8e-44 | 0.73 to 0.86 s | 0 | 0 |
| B04: comparison site's cheapest retailer, exact variant's stock | 8 / 23 / 294 | `advertised_cheapest_in_stock` | 0.302 | 0.72 to 0.94 s | 2,979 | 3,022 ± 46 |
|  |  | `advertised_cheapest_unavailable` | 0.087 | 0.74 to 0.85 s | 873 | 870 ± 28 |
|  |  | `advertised_cheapest_on_supplier_order` | 0.0217 | 0.66 to 1.04 s | 259 | 217 ± 15 |
| B05: cheapest in stock with size and two facts | 12 / 25 / 411 | `likeliest_winner` | 0.201 | 0.54 to 0.63 s | 2,046 | 2,006 ± 40 |
|  |  | `unlikely_winner` | 0.2 | 0.57 to 0.63 s | 2,025 | 2,003 ± 40 |
|  |  | `better_offer_unavailable` | 0.00319 | 0.54 to 0.57 s | 34 | 32 ± 6 |
| B07: cheapest matching, requirements from memory | 9 / 16 / 206 | `likeliest_winner` | 0.253 | 0.45 to 0.47 s | 2,473 | 2,531 ± 43 |
|  |  | `unlikely_winner` | 0.237 | 0.45 to 0.47 s | 2,360 | 2,369 ± 43 |
|  |  | `better_offer_unavailable` | 0.00711 | 0.43 to 0.58 s | 63 | 71 ± 8 |
| B08: cheapest matching after a clarification | 10 / 21 / 171 | `likeliest_winner` | 0.508 | 0.45 to 0.52 s | 5,094 | 5,079 ± 50 |
|  |  | `better_offer_unavailable` | 0.0941 | 0.43 to 0.55 s | 1,009 | 941 ± 29 |
|  |  | `unlikely_winner` | 0.00677 | 0.47 to 0.48 s | 82 | 68 ± 8 |
| B11: shortlist of three models | 4 / 23 / 72 | `natural_shortlist` | 0.111 | 0.52 to 0.69 s | 1,101 | 1,114 ± 31 |
| B12: permitted relaxations | 7 / 21 / 300 | `criteria_set_1` | 0.41 | 1.08 to 1.55 s | 4,129 | 4,102 ± 49 |
|  |  | `criteria_set_2` | 1.7e-20 | 0.80 to 0.87 s | 0 | 0 |
| B13: cheapest per kilogram | 2 / 14 / 15 | `likeliest_winner` | 0.995 | 0.84 to 0.92 s | 9,944 | 9,951 ± 7 |
|  |  | `unlikely_winner` | 1 in 4,945 | 0.83 to 1.04 s | 1 | 2.0 ± 1.4 |
| B14: lightest, then cheapest | 8 / 28 / 456 | `likeliest_winner` | 0.559 | 0.79 to 0.88 s | 5,596 | 5,591 ± 50 |
|  |  | `better_offer_unavailable` | 0.106 | 0.80 to 0.93 s | 1,093 | 1,060 ± 31 |
|  |  | `unlikely_winner` | 1.0e-47 | 0.76 to 0.81 s | 0 | 0 |
| B18: free-shipping claim | 8 / 28 / 480 | `no_threshold` | 0.75 | 0.45 to 0.47 s | 7,483 | 7,500 ± 43 |
|  |  | `below_threshold` | 0.214 | 0.44 to 0.46 s | 2,155 | 2,143 ± 41 |
|  |  | `meets_threshold` | 0.0357 | 0.44 to 0.48 s | 362 | 357 ± 19 |
|  |  | `just_meets_threshold` | 0.00261 | 0.45 to 0.51 s | 30 | 26 ± 5 |
| B20: cheapest collectable at a branch in the city | 5 / 22 / 124 | `likeliest_winner` | 0.735 | 0.58 to 0.84 s | 7,403 | 7,354 ± 44 |
|  |  | `unlikely_winner` | 0.0605 | 0.46 to 0.54 s | 572 | 605 ± 24 |

All 96 samples satisfied their requirement by the direct reading of the saved
leaves and by the native oracle of the task's reading (for B04 by its two
parts' checks, and for B18 by the threshold rule; the native comparison-stock
and shipping-claim oracles are applied in the unit tests). Every redraw count
is within four standard errors. The largest deviation is B04's
`advertised_cheapest_on_supplier_order`, 259 joint hits against 217 ± 15 (2.8
standard errors); its two parts by themselves are 4,111 against 4,110 ± 49
and 560 against 529 ± 22. Among some thirty comparisons in this table one
that far out is not surprising, and nothing else points the same way, but it
is the figure to look at first if a later run disagrees.

For B11 the tool emits only `natural_shortlist`: there are two eligible
models, so its search constructs neither a three-model alternative nor a
four-model cutoff tie; smaller shortlists remain possible. B01's and H09's
natural world has no listed offer that is
likely to sit unavailable below the likeliest winner, hence 4.3e-11. B07 and
B08 are read through the feature task their native modules resolve them to.
What is steered is the world's stock and prices; a task's memories, prompts
and start state are not part of this.

These are dev-producer worlds from the suite's inputs, not the suite's frozen
worlds, and nothing here is published or bound to a task instance.

### Reviews

The suite's five product-review tasks are two task forms: B09, H05, H06 and
H07 share one generation input and one task specification (the first walking
shoe, grip on wet paving, 100 reviews per product), and H10 has its own (the
sixth walking shoe, 2 reviews per product). For both, `variants` wrote the
candidates from the task specification and the pinned runner sampled and
checked each (`suite/variants/B09/`, `suite/variants/H10/`, launched by
`launch-reviews.sh`; three samples, 10,000 redraws and 5 producer redraws per
candidate; `summarize-reviews.py` prints the table). Steering commit
`6040664`, dev's producer in the steering checkout.

| Task | World (retailers / products; reviews) | Candidate | Probability given upstream | Natural counts | Samples (positive, negative; redraws; seconds) | Hits in redraws | Expected |
| --- | --- | --- | --- | --- | --- | --- | --- |
| B09 | 10 / 32; 100 reviews | `verdict_insufficient_evidence` | 0.0013 | 2 positive, 3 negative | 0, 0; 0, 0; 0, 0; 103–107 redraws; 1.66–1.70 s | 11 of 10,000 | 13 ± 4 |
| B09 | 10 / 32; 100 reviews | `verdict_more_negative` | 0.51 | 2 positive, 3 negative | 3, 5; 2, 4; 2, 4; 176–334 redraws; 1.67–1.77 s | 5102 of 10,000 | 5098 ± 50 |
| B09 | 10 / 32; 100 reviews | `verdict_more_positive` | 0.334 | 2 positive, 3 negative | 3, 2; 4, 2; 5, 3; 197–338 redraws; 1.69–1.79 s | 3385 of 10,000 | 3338 ± 47 |
| B09 | 10 / 32; 100 reviews | `verdict_tie` | 0.155 | 2 positive, 3 negative | 4, 4; 2, 2; 1, 1; 157–249 redraws; 1.65–1.78 s | 1502 of 10,000 | 1550 ± 36 |
| H10 | 8 / 23; 2 reviews | `verdict_insufficient_evidence` | 0.87 | 0 positive, 1 negative | 0, 0; 0, 0; 0, 0; 2 redraws; 0.41–0.42 s | 8716 of 10,000 | 8702 ± 34 |
| H10 | 8 / 23; 2 reviews | `verdict_more_negative` | 0.0421 | 0 positive, 1 negative | 0, 1; 0, 1; 0, 1; 5–44 redraws; 0.40–0.42 s | 414 of 10,000 | 421 ± 20 |
| H10 | 8 / 23; 2 reviews | `verdict_more_positive` | 0.0857 | 0 positive, 1 negative | 1, 0; 1, 0; 1, 0; 7–21 redraws; 0.41–0.46 s | 850 of 10,000 | 857 ± 28 |
| H10 | 8 / 23; 2 reviews | `verdict_tie` | 0.002 | 0 positive, 1 negative | 1, 1; 1, 1; 1, 1; 14–100 redraws; 0.40–0.42 s | 20 of 10,000 | 20 ± 4 |

All 24 samples satisfied their requirement by the native review task's
reference and by the direct reading of the saved review records; every
producer redraw equalled the block's reading. On B09's world a sample takes
about 1.7 s, the natural pass 372 s (its other concepts' reviews dominate
manufacture). H10's world has two reviews per product, so three of its four
verdicts are the unusual ones.

Rarer requirements on B09's world, written by hand
(`suite/variants/B09-rare/candidates/`, launched by `launch-run.sh`;
200,000 redraws each), at steering commit `51aefce`:

| Task | World (retailers / products; reviews) | Candidate | Probability given upstream | Natural counts | Samples (positive, negative; redraws; seconds) | Hits in redraws | Expected |
| --- | --- | --- | --- | --- | --- | --- | --- |
| B09-rare | 10 / 32; 100 reviews | `even_and_many` | 8.79e-05 | 2 positive, 3 negative | 8, 8; 8, 8; 8, 8; 422–756 redraws; 1.66–1.70 s | 15 of 200,000 | 18 ± 4 |
| B09-rare | 10 / 32; 100 reviews | `many_complaints` | 1.15e-06 | 2 positive, 3 negative | 2, 15; 1, 16; 2, 15; 393–532 redraws; 1.69–1.76 s | 0 of 200,000 | 0.2 ± 0.5 |
| B09-rare | 10 / 32; 100 reviews | `nobody_mentions_it` | 0.0013 | 2 positive, 3 negative | 0, 0; 0, 0; 0, 0; 102–109 redraws; 1.63–1.72 s | 262 of 200,000 | 261 ± 16 |
| B09-rare | 10 / 32; 100 reviews | `praise_only` | 0.00032 | 2 positive, 3 negative | 8, 0; 8, 0; 8, 0; 297–362 redraws; 1.61–1.77 s | 70 of 200,000 | 64 ± 8 |

`many_complaints` (at least 15 complaints and at most 2 praises among 100
reviews) is expected 0.2 times in 200,000 redraws, so its zero hits say
nothing about its probability; the samples and their checks are its
evidence, and the probability rests on the model that the other rows test.

The carrier-review task (B16: the first carrier, handover, regular shipping
class, reviews from 2026-08-14 on, at least three assessing comments), and
the same task form on tracking with at least two (`suite/variants/B16/`,
`B16-tracking/`, launched by `launch-carriers.sh`; 10,000 redraws), at
`51aefce`:

| Task | World (retailers / products; reviews) | Candidate | Probability given upstream | Natural counts | Samples (positive, negative; redraws; seconds) | Hits in redraws | Expected |
| --- | --- | --- | --- | --- | --- | --- | --- |
| B16 | 7 / 30; 8 shipments in the block | `verdict_insufficient_evidence` | 0.978 | 2 positive, 0 negative, 0 neutral | 1, 0; 0, 0; 0, 0; 8–22 redraws; 0.48–0.51 s | 9769 of 10,000 | 9777 ± 15 |
| B16 | 7 / 30; 8 shipments in the block | `verdict_more_positive` | 0.0223 | 2 positive, 0 negative, 0 neutral | 3, 0; 3, 0; 3, 0; 24–55 redraws; 0.49–0.53 s | 231 of 10,000 | 223 ± 15 |
| B16-tracking | 7 / 30; 10 shipments in the block | `verdict_insufficient_evidence` | 0.765 | 1 positive, 1 negative, 0 neutral | 1, 0; 0, 0; 0, 0; 10–19 redraws; 0.50–0.53 s | 7657 of 10,000 | 7647 ± 42 |
| B16-tracking | 7 / 30; 10 shipments in the block | `verdict_more_positive` | 0.204 | 1 positive, 1 negative, 0 neutral | 2, 0; 5, 0; 2, 0; 38–70 redraws; 0.53–0.55 s | 2016 of 10,000 | 2038 ± 40 |
| B16-tracking | 7 / 30; 10 shipments in the block | `verdict_tie` | 0.0315 | 1 positive, 1 negative, 0 neutral | 1, 1; 1, 1; 1, 1; 11–26 redraws; 0.50–0.52 s | 327 of 10,000 | 315 ± 17 |

On B16's own input the carrier has eight shipments in scope with a handover
observation and all eight went well, so only two verdicts can occur; "more
negative" and "tie" have probability zero given the histories, and the tool
does not offer them. Of that world's eight carriers one has any bad handover
in scope. This is the limit stated under the ninth requirement, met on the
suite's own task.

The same task with the carrier's shipments redrawn (the tenth requirement),
and the same on punctuality with at least two assessing comments
(`suite/variants/B16-shipments/`, `B16-punctuality/`, launched by
`launch-shipments.sh`; `variants` now writes both families of candidates;
50,000 redraws), at steering commit `e837e7f`:

| Task | World (retailers / products; reviews) | Candidate | Probability given upstream | Natural counts | Samples (positive, negative; redraws; seconds) | Hits in redraws | Expected |
| --- | --- | --- | --- | --- | --- | --- | --- |
| B16-shipments | 7 / 30; 32 shipments, all redrawn | `redrawn_shipments_verdict_insufficient_evidence` | 0.977 | 2 positive, 0 negative | 1, 0; 0, 0; 0, 0; 32–264 redraws; 0.52–0.65 s | 48812 of 50,000 | 48838 ± 34 |
| B16-shipments | 7 / 30; 32 shipments, all redrawn | `redrawn_shipments_verdict_more_negative` | 0.000147 | 2 positive, 0 negative | 1, 2; 1, 2; 1, 2; 142–3610 redraws; 0.52–0.67 s | 9 of 50,000 | 7.4 ± 2.7 |
| B16-shipments | 7 / 30; 32 shipments, all redrawn | `redrawn_shipments_verdict_more_positive` | 0.023 | 2 positive, 0 negative | 4, 0; 3, 0; 3, 0; 190–344 redraws; 0.52–0.55 s | 1178 of 50,000 | 1152 ± 34 |
| B16-shipments | 7 / 30; 32 shipments, all redrawn | `redrawn_shipments_verdict_tie` | 3.86e-05 | 2 positive, 0 negative | 2, 2; 2, 2; 2, 2; 1563–6782 redraws; 0.61–0.80 s | 1 of 50,000 | 1.9 ± 1.4 |
| B16-shipments | 7 / 30; 8 shipments in the block | `verdict_insufficient_evidence` | 0.978 | 2 positive, 0 negative, 0 neutral | 1, 0; 0, 0; 0, 0; 8–14 redraws; 0.53–0.54 s | 48817 of 50,000 | 48884 ± 33 |
| B16-shipments | 7 / 30; 8 shipments in the block | `verdict_more_positive` | 0.0223 | 2 positive, 0 negative, 0 neutral | 3, 0; 3, 0; 3, 0; 17–83 redraws; 0.52–0.53 s | 1183 of 50,000 | 1116 ± 33 |
| B16-punctuality | 7 / 30; 32 shipments, all redrawn | `redrawn_shipments_verdict_insufficient_evidence` | 0.731 | 1 positive, 0 negative | 0, 0; 1, 0; 1, 0; 34–50 redraws; 0.52–0.65 s | 36612 of 50,000 | 36556 ± 99 |
| B16-punctuality | 7 / 30; 32 shipments, all redrawn | `redrawn_shipments_verdict_more_negative` | 0.00102 | 1 positive, 0 negative | 0, 2; 1, 2; 1, 2; 1019–1950 redraws; 0.58–0.62 s | 54 of 50,000 | 51 ± 7 |
| B16-punctuality | 7 / 30; 32 shipments, all redrawn | `redrawn_shipments_verdict_more_positive` | 0.249 | 1 positive, 0 negative | 2, 0; 2, 0; 2, 0; 50–184 redraws; 0.53–0.57 s | 12418 of 50,000 | 12443 ± 97 |
| B16-punctuality | 7 / 30; 32 shipments, all redrawn | `redrawn_shipments_verdict_tie` | 0.019 | 1 positive, 0 negative | 1, 1; 1, 1; 1, 1; 94–891 redraws; 0.53–0.57 s | 916 of 50,000 | 950 ± 31 |
| B16-punctuality | 7 / 30; 8 shipments in the block | `verdict_insufficient_evidence` | 0.706 | 1 positive, 0 negative, 0 neutral | 1, 0; 0, 0; 0, 0; 8–15 redraws; 0.52–0.54 s | 35185 of 50,000 | 35315 ± 102 |
| B16-punctuality | 7 / 30; 8 shipments in the block | `verdict_more_positive` | 0.294 | 1 positive, 0 negative, 0 neutral | 2, 0; 2, 0; 2, 0; 18–24 redraws; 0.50–0.53 s | 14815 of 50,000 | 14685 ± 102 |

With the shipments in the block all four verdicts can occur on B16's own
input. "More negative" with at least three assessing comments has
probability 1.5e-4 (one world in about 6,800) and "tie" 3.9e-5 (one in about
26,000); each sample takes 0.5 to 0.8 s, of which up to 6,800 redraws of
single shipments are a small part. The rows without the prefix are the
reviews-only candidates again at this commit. All 36 samples satisfied their
requirement by the native task's reference and by the direct reading of the
saved shipments and reviews; the largest deviation among the twelve redraw
counts is 2.0 standard errors (the reviews-only `verdict_more_positive`,
1,183 against 1,116 ± 33). The two rarest rows have one and nine hits, so
their counts test little; their probabilities rest on the factors that
`test_shipments.py` checks one by one.

On the medium world's input with 24 reviews per product (21 retailers, 90
products, 2,849 offers; `medium/reviews/`, one runner command per task with
`--task`, 20,000 redraws, steering commit `79cb000`, whose executable
sources equal `7450c15`): the product-review
task form on the first walking shoe with at least two assessing comments
(four verdicts, probabilities 0.53, 0.32, 0.11 and 0.042) and the carrier
task form of B16 (two reviews-only candidates; four with the shipments
redrawn, down to 2.1e-4 for "more negative" and 6.2e-5 for "tie"). All ten
candidates were sampled three times and checked; the redraw counts are
within 1.7 standard errors (the largest, 10,520 against 10,636 ± 71). The natural pass takes 370 s there, a pass with
manufacture reused 0.9 s and a sample about 2 s.

Every concept, and the stars (`steering/reviews-r10/`, steering commit
`16ca53f`, one runner command per task with `--task`). The world is the
suite's ordinary review task's input again (seed 78, five concepts, 100
reviews per product; natural pass 426 to 437 s). Four review tasks on it, one
per producer of reviews: the suite's own (grip on wet paving, the walking
shoe Vallheden Strand), everyday comfort of a casual trainer, marks made with
a pen on a tablet, and value of a T-shirt, the last three with at least two
assessing comments asked for. Each has six candidates: the four verdicts, and
the verdict against the stars twice.

| Task | Verdicts, likeliest to rarest | More negative, mean rating 4 or more | More positive, mean rating 2 or less | Seconds per sample |
| --- | --- | --- | --- | --- |
| Shoe, grip | 0.51, 0.33, 0.16, 0.0013 | 2.5e-17 | 2.0e-10 | 1.9 to 3.3 |
| Trainer, comfort | 0.84, 0.087, 0.075, 0.0023 | 0.084 | 4.9e-58 | 2.2 to 4.4 |
| Tablet, pen | 0.76, 0.13, 0.080, 0.032 | 0.026 | 1.9e-51 | 3.6 to 14 |
| T-shirt, value | 0.92, 0.041, 0.035, 0.0018 | 1.5e-41 | 0.0051 | 98 to 110 |

All 66 samples (three per candidate, two for the T-shirt) satisfied their
requirement by the native task's reference, by the direct reading of the
saved reviews, and, where a mean is stated, by the product's rating summary:
the high-star samples have means of 4.0 to 4.27 with two to seven complaints
against none to four comments of praise, the low-star ones 1.87 to 2.0.
Redraws through the producer equalled the reading's in all 54 passes. The
frequencies over other seeds (2,000 redraws for the shoe, 1,500 for the
trainer, 600 for the tablet, 300 for the T-shirt) are within four standard
errors of the computed probabilities for all 24 candidates; for the rare
ones that only says that they did not occur. How likely the verdict against
the stars is depends on the product: this trainer and this tablet are well
made, so a mean of four stars is the usual case and complaints under it are
as likely as complaints at all; the shoe is middling, and a hundred ratings
averaging four or more with more complaints than praise among them is a
2.5e-17 event for it. The T-shirt's samples take as long as its hundred reviews do
through the producer's wrapped review program, about a second each.

The other concepts. The producer supports 130 concepts; the data of 39 are
in git (37 with a review program, and the two pilot concepts), and the rest
read files that exist only in the shared working tree. A world of all 130
from that tree (seed 5, eight reviews per product, 378 products; a scratch
check from the shared tree, not a pinned run, and not reproducible from a
commit) has a product for 126 of them. At `16ca53f` the reading followed 700
topics of the first 118 concepts before its time limit (every one of the 36
git concepts with a product among them), each compared with 1,200 whole
reviews drawn by the program under seeds of their own (largest deviation of
a class's frequency 3.1 standard errors over about 2,100 comparisons), and
refused 58 topics in 22 concepts whose data is not in git, for four
reasons: the value threshold written `.5`, the same threshold repeated inside
the statements' conditions, a whole-number draw, and a loop that collects
rows. The reading now follows all four. Checked again on the saved world for
those 22 concepts: 19 are read in full (143 topics, against 300 to 1,200
whole reviews each, largest deviation 2.7 standard errors); two pet concepts
are read at about 50 s a topic (14 topics checked), and for the third (padded
harnesses) the check was stopped after 25 minutes without a result, which is
the cost named under "Limits". The eight concepts the first pass did not
reach are unchecked.

The first page (`steering/pages-r11/shoe-grip`, steering commit `a11fe02`,
one runner command with `--task`): the suite's review task on the same input
again (the walking shoe Vallheden Strand, 100 reviews, grip on wet paving),
now with eight candidates. The six earlier ones have their earlier
probabilities. With four comments to a page and the highest ratings first,
"the first page is more positive and all the comments together are more
negative" has probability 0.286 for this shoe: the page takes the
best-rated comments, which are the likeliest to praise, so this is the usual
way for a product with more complaints than praise to look, and the suite's
instance of it is no rare find. The reverse, a first page of complaints over
a whole that praises, is 7.0e-4. Three samples of each were checked against
the page read off the saved reviews in the site's order and the native
task's classes (one comment of praise and none against on the page, under
four to six complaints in all; one complaint and no praise on the page,
under three or four comments of praise in all); a sample takes 2.2 to 2.4 s
after a natural pass of 385 s. Over 2,000 redraws the first held 608 times
against 572 expected (1.8 standard errors) and the second never against 1.4
expected. Redraws through the producer equalled the reading's in all six
passes.

All of these are dev-producer worlds from the suite's inputs, not the
suite's frozen worlds, and nothing here is published or bound to a task
instance.

### A medium world

The world sizes asked for (Bjorn, 2026-10-11): a medium world has 4 to 8
task-relevant stores and ideally twice that again as backdrop, and 100 or more
products, of which 20 to 30 are in the task's niche and 5 to 10 compete.

`steering/medium/`: the generation input of the saved world
`.local/website-comparison-scoped-world-20261006-v1/` (seed 62, `world_size`
4, five concepts, 8 reviews per product), generated by dev's producer in the
steering checkout at `7dd4727` with real manufactured products: 21 retailers,
90 products, 1,181 SKUs, 2,849 offers, 37,516 streams per pass. Walking shoes:
20 retailers, 30 products, 193 retailer/product pairs, 1,569 offers, 64 of
them unavailable in the natural world. Requirement files were chosen by
`medium/explore.py` from the block model's own probabilities.

Cost: the first pass, which manufactures the products, 168 s; an unsteered
replay 0.7 to 0.8 s; the block model 0.05 to 0.6 s; a steered sample with all
checks 1.5 to 2.8 s, measured with two runs sharing the machine.

| Requirement | Pairs / offers in the concept | Probability given upstream | Sample | Redraws | Hits | Expected |
| --- | --- | --- | --- | --- | --- | --- |
| Walking shoe: `marketplace-07` alone is cheapest available | 193 / 1,569 | 0.1266 | 2.0 to 2.1 s | 8,000 | 1,030 | 1,013 ± 30 |
| The same, with `department_store-07`'s offer of the shoe listed below it | 193 / 1,569 | 0.00288 (1 in 347) | 1.9 to 2.2 s | 8,000 | 27 | 23.1 ± 4.8 |
| The same, with a second retailer's offer listed below it | 193 / 1,569 | 1.83e-5 (1 in 54,633) | 2.0 to 2.6 s | 8,000 | 0 | 0.1 |
| Walking shoe: the pair at the middle of the ranking by probability wins | 193 / 1,569 | 6.7e-104 | 1.9 to 2.8 s | 8,000 | 0 | 0 |
| Tablet: `marketplace-03` alone is cheapest available | 40 / 61 | 0.8256 | 1.5 to 1.8 s | 100,000 | 82,424 | 82,560 ± 120 |
| The same, with `marketplace-00`'s offer of the tablet listed below it | 40 / 61 | 0.0131 (1 in 76) | 1.7 to 2.8 s | 100,000 | 1,363 | 1,312 ± 36 |
| Trainer: a winner with another retailer's offer listed below it | 37 / 384 | 0.000698 (1 in 1,433) | 1.7 to 1.8 s | 100,000 | 77 | 69.8 ± 8.4 |
| T-shirt: a winner with another retailer's offer listed below it | 40 / 152 | 0.000499 (1 in 2,004) | 1.5 to 2.2 s | 100,000 | 53 | 49.9 ± 7.1 |
| The sold-out shoe requirement, a sandal unavailable at one retailer and a trainer at 85% of its reference price or less at another | | 5.43e-7 (1 in 1,841,302) | 2.5 to 2.6 s | 8,000 | 0 joint; parts 27, 34, 283 | parts 23.1 ± 4.8, 39.2 ± 6.2, 307 ± 17 |

Every sample passed the same checks as on seed 73: the producer recorded every
planned leaf, the native oracle names exactly the designated winner with each
named offer unavailable and cheaper, a direct scan of the saved leaves agrees,
and nothing outside the block's resources differs from the natural world. The
real producer redrew each requirement's streams under 10 other seeds (90
passes), equal to the block's reading leaf for leaf. The winning-price
distances are 0.004 (tablet winner), 0.030 (tablet sold out) and 0.051 (shoe
winner); the others have too few hits to say much.

The redraws dominate the run time, not the sampling: one redraw of the shoe
concept's 1,569 offers takes about 80 ms in the block's reading, so 8,000 of
them take eleven minutes per requirement. They are a check on the model, not a
cost of a sample.

`medium/run-v10-shoes/` and `medium/run-v10-others/` repeat the nine
requirements at `50a3a79` with 3,000 and 40,000 redraws: the same
probabilities to fourteen digits, every sample passing the same checks, 1.4
to 3.1 s per sample with five runs sharing the machine. Hits against
expected: shoe winner 384 against 380 ± 18, sold-out shoe 7 against 8.7 ±
2.9, tablet winner 32,806 against 33,024 ± 76, sold-out tablet 549 against
525 ± 23, trainer 26 against 27.9 ± 5.3, t-shirt 21 against 20.0 ± 4.5. The
tablet winner is 2.9 standard errors low in these 40,000 redraws; they are
the first 40,000 of the 100,000 in the table above, which end 1.1 low.

This is one medium world. It is the size asked for in retailers and in the
niche (20 retailers and 30 products sell walking shoes); it has 90 products,
not 100 or more, and the 38-concept saved world
(`.local/website-38-concept-world-20261006-v1/`, 30 retailers, 621 products)
has not been steered.

### Cost against world size

A side measurement, not part of the pinned runner: the real commerce producer
at seed 73 over the five concepts of the saved world, with stand-in products
of 13 SKUs each, at four values of the `world_size` control. "Steered sample"
is one stock requirement (a shoe size unavailable at an 11-location retailer)
including planning and all checks. Script, log and launcher receipt:
`steering/scale-v2.py`, `scale-v2.log`, `scale-v2-bounded/`, run at `390247b`.

| `world_size` | Products | Retailers | Offers | Streams per pass | `load()` calls | Pass as the producer is | Steered sample as it is | Pass, defaults read once | Steered sample, defaults read once |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 29 | 14 | 1,151 | 14,977 | 108 | 2.5 s | 2.6 s | 0.39 s | 0.49 s |
| 2 | 63 | 25 | 4,032 | 49,375 | 352 | 8.0 s | 8.1 s | 0.61 s | 0.82 s |
| 4 | 125 | 33 | 11,549 | 139,204 | 972 | 23.2 s | 25.1 s | 1.2 s | 1.8 s |
| 8 | 234 | 46 | 28,742 | 337,992 | 2,377 | 66.2 s | 72.2 s | 2.5 s | 3.8 s |

Both variants produce the identical natural and steered world at every size.
The cost of a steered sample is the cost of a pass plus the checks (two
canonical dumps of the world, the identity digest and the oracle); both
grow with the number of offers.

What this does not measure: product manufacture, which is paid once per
upstream on the first pass. On the saved seed-73 world it is about 27 s for 25
products, so of the order of two to five minutes at sizes 4 to 8 if it stays
proportional; that is an extrapolation, not a measurement. The stand-in
products also carry no review or description text, so real worlds are larger
on disk than these.

The joint stock-and-price block does more work per sample than a one-offer
block, since it models and redraws the whole concept. The same worlds, with
the requirement "the runner-up retailer/product of the shoe concept is the
only cheapest available one, and the natural winner's offer is listed below
it"; sampling defaults read once. Script, log and launcher receipt:
`steering/scale-v3.py`, `scale-v3.log`, `scale-v3-bounded/`, run at `74ad475`.

| `world_size` | Products | Retailers | Offers | Shoe retailers | Shoe products | Shoe retailer/product pairs | Shoe offers | Unsteered pass | Block model | Steered sample, all included | Streams steered |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 29 | 14 | 1,151 | 12 | 13 | 69 | 852 | 0.40 s | 0.12 s | 0.63 to 0.64 s | 8,804 |
| 2 | 63 | 25 | 4,032 | 24 | 25 | 199 | 2,473 | 0.61 s | 0.40 s | 1.3 to 1.4 s | 25,777 |
| 4 | 125 | 33 | 11,549 | 33 | 51 | 548 | 6,763 | 1.2 s | 1.3 s | 3.2 to 3.6 s | 73,106 |
| 8 | 234 | 46 | 28,742 | 45 | 88 | 1,254 | 15,535 | 2.4 s | 3.2 s | 7.2 to 8.2 s | 166,629 |

The requirement held in all twelve samples. Its probability is of the order
of 1e-20 at sizes 1 to 4 and 3e-9 at size 8: the stand-in products list 13
sizes at one price, so an offer listed below the winner means all 13 sizes
sold out at that retailer.

In the terms of "A medium world" above: the task's concept in a medium world
has at most 24 retailers and 30 products, which is the `world_size` 2 row for
the block (24 retailers, 25 products, 199 pairs). The measured medium world
with real products (193 pairs) takes about two seconds per sample. Its pairs
list fewer SKUs (8 on average against 12 with the stand-ins), and its world
carries review and description text that the checks also digest.

## What is not done

- **Requirements on named offers inside a who-is-cheapest concept.** The
  joint block samples who is cheapest together with sold-out cheaper offers.
  A stock or price requirement on a named offer of the same concept ("the
  winner has at most two left", "the sold-out offer is on supplier order at
  another shop") is still refused as coupled. It would enter the joint block
  as a restriction on that pair's outcomes; not built.
- **Two SKUs of one product at one retailer** in two one-offer stock
  requirements share the conditions and are refused. They need a joint chain
  over the locations, as the joint block has for its own purpose.
- **One-offer stock samples share the seed's sibling draws.** The stock block
  samples the named SKU's draws and the shared conditions; the product's other
  SKUs at the retailer keep the seed's own zero and quantity draws, evaluated
  under the sampled conditions. Each sample is a valid conditional sample, but
  repeated samples from one natural world are correlated through those kept
  draws. The joint block redraws every SKU and has no such correlation.
- **Upstream of stock is not steered.** Assortment, SKU listing, the number
  of locations and which of them ship, stock tendencies and whether the
  retailer takes supplier orders are the seed's. Requirements they rule out
  are refused with a reason code, not repaired.
- **The earlier Z3 pilot** (`experiments/constrained_world_pilot/`) is not
  connected.
- **Reviews, in part.** Steered: what a product's reviews say about a topic,
  for any concept, with or without a bound on the mean of its stars; and
  which of a carrier's reviews mention an aspect. Not steered: the count of
  each star; one option's reviews; on walking shoes and sandals the two
  topics that depend on the option bought or the wearer; what a review
  site's first page shows for concepts other than those two. Not reachable by steering at all, because
  no producer draws them: a neutral or a mixed comment, and a second
  statement on a topic under other circumstances (the suite's "opposite
  opinions in one comment" and "same words, different circumstances"). Those
  need the review samplers to write such comments first. What happened to a carrier's shipments is
  steered for handover and punctuality only; for the other aspects it bounds
  what the reviews can be made to say. A carrier's quality levels and
  services are the seed's. Which reviews a review
  site shows, and which products a comparison site lists, are the seed's.
- **Delivery cost.** A retailer's free-shipping threshold can be steered
  against a basket's subtotal, and so can its contracts and, under admission
  plan version 2, the delivery options it shows and which carrier's is
  cheapest, and who is cheapest delivered for one unit sent home with the
  contracts as the seed drew them. Not modelled: who is cheapest delivered
  together with redrawn contracts or thresholds (the two are one block
  then); delivery to a collection point, by a deadline or fastest first;
  the order-set task, whose optimum is over baskets. Under plan version 1,
  which existing recipes use, a retailer's shown routes are redrawn by any
  steered change (`delivery_admission.py` draws on the finished world's
  id), so nothing about them can be stated there.
- **No publication.** Steered worlds are native worlds only:
  `browser_runtime_ready` is false. `unified_generation.generate` accepts a
  `world_factory`, which is where a steered world would enter so that
  surrounding sites, presentation and bindings are built by the ordinary
  pipeline; its sampling audit would have to record the steering.
- **Two upstreams with real products.** Seed 73 (12 retailers, 25 products)
  and one medium world (21 retailers, 90 products). The unit tests add three
  stand-in worlds and the scaling measurements four more, with stand-in
  products.

## What a released version needs

Coordination with Product, who own the producer:

1. A stream seam: `population.stream` consulting an explicit, caller-supplied
   plan, in place of the attribute swap.
2. A manufacture seam: a way to supply already manufactured products, in place
   of the second attribute swap.
3. `population.load()` read once per generation. Done in dev's producer on
   2026-10-11 (`9fd8a123`, `ebd3ef3e`; see "Producer defaults integration"),
   after the measurement below. The session's third swap now only shares the
   snapshot across passes and can go.
4. Preferably, draw sites that declare their distribution (a named Bernoulli,
   categorical, integer range or clamped normal). The price model here mirrors
   `_offer_price` by hand and is checked against it empirically; declared
   sites would make block models generic and remove that duplication.

A measurement for Product, independent of steering: a pass through the
commerce producer with manufacture already done spends most of its time
re-reading the sampling defaults and the concept registry. `population.load()`
runs once per retailer/product entry (in `list_skus`), once per retailer and
twice more: 82 times for the saved seed-73 world, and about a thousand times
at world size 4. "Cost against world size" has the figures. Reading it once in
the producer would make every pass that reuses manufacture several times
cheaper, and does little for a first pass, which manufacture dominates. This
experiment works around it inside its own session and does not patch the
producer.

## Producer defaults integration (2026-10-11)

The central commerce producer now loads one validated defaults/registry snapshot
per world and passes it explicitly to population sampling, retailer home-location
weighting, SKU listing and provenance hashing. A fresh independent generation
reads fresh defaults; there is no process-global producer cache. The repeated-read
cost figures above describe the original producer and remain historical evidence.
`streams.Defaults` still shares the initial snapshot across an experimental
session's repeated worlds; its module swap and thread-safety limitation remain.

## Reproduction

```bash
.venv/bin/python -m pytest -q experiments/steered_generation/
```

`test_stock.py`, `test_combined.py` and `test_cheapest.py` run the real
commerce producer with stand-in products; the whole directory takes a little
over a minute.

From the repository root of a checkout at the steering commit:

```bash
python3 /home/bjorn/code/LLM_proj_uu/scripts/run_bounded_job.py --memory-mib 3072 \
  --receipt /home/bjorn/code/LLM_proj_uu/.local/steering-reproduce-bounded -- \
  timeout 900s /home/bjorn/code/LLM_proj_uu/.venv/bin/python -B -m experiments.steered_generation.run \
  --native-root /home/bjorn/code/LLM_proj_uu-worktrees/eval-diverse-offers-20261008-r1 \
  --native-commit e3fbfadd84d3b16a26895d62abb66f61df433697 \
  --steering-commit EXACT_REVIEWED_STEERING_COMMIT \
  --generation-input /home/bjorn/code/LLM_proj_uu/.local/coordination/task-testing-20261008/Evaluation-diverse-offers-acceptance-v1/feature-recipe/pin/generation-input.private.json \
  --expected-natural-world-id EXPECTED_WORLD_ID \
  --requirement /home/bjorn/code/LLM_proj_uu/.local/coordination/world-requirement-construction-20261010/steering/tie2.json \
  --requirement /home/bjorn/code/LLM_proj_uu/.local/coordination/world-requirement-construction-20261010/steering/stock/backorder-footwear-06.json \
  --requirement /home/bjorn/code/LLM_proj_uu/.local/coordination/world-requirement-construction-20261010/steering/price/under-400-outdoors-02.json \
  --requirement /home/bjorn/code/LLM_proj_uu/.local/coordination/world-requirement-construction-20261010/steering/combined/three-shops.json \
  --samples 3 --validate-trials 30000 --producer-redraws 40 \
  --output /home/bjorn/code/LLM_proj_uu/.local/steering-reproduce
```
