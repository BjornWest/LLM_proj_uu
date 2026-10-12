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
(`population.stream`, `package_export.sample`, `population.load`). That is
acceptable for an experiment and is not thread-safe. A released version needs
small seams in the producer instead; see "What a released version needs".

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
world in which every listed offer holds one unit at every location, and the
native oracle's candidates on that copy are the offers that can compete at
all, each with the facts or the pack mass the oracle ranks it by. The record
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

## Several requirements in one world

Requirement (`steered-requirements-v1`): a list of requirements, each of one
of the six kinds above, that must all hold.

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
- **Only retail stock and prices.** Reviews and review sites are not steered,
  and neither is which products a comparison site lists (that is the seed's,
  and the requirement can only confine the comparison to it). Delivery fees,
  free-shipping thresholds and delivery options are not modelled.
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
