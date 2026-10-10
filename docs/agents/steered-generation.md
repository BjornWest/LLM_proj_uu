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
4. **Solve on a model, materialize with the producer, check with the oracle.**
   A block sampler decides the planned draws from a model of the affected
   draws. The real producer then generates the world with that plan, and the
   native oracle and the pricing-rule check judge the result. Those checks
   establish that the world satisfies the requirement and obeys the producer's
   rules. They do not establish the sampling distribution or the probability;
   those rest on the block model and on its comparison with the producer's own
   pricing function (see the evidence below).

Two module attributes are swapped while the producer runs
(`population.stream`, `package_export.sample`). That is acceptable for an
experiment and is not thread-safe. A released version needs two small seams in
the producer instead; see "What a released version needs".

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
  can redraw the block naturally. `stock.redraw` returns the producer's
  recorded result and the reading side by side, and the runner and the tests
  require them to be equal. The reading is then cheap enough for millions of
  redraws, which is what a 1-in-100,000 scenario needs.

## Evidence on seed 73

Saved seed 73 at accepted source `e3fbfadd84d3b16a26895d62abb66f61df433697`:
25 products, 320 SKUs, 12 retailers, 411 offers; 48 retailer/product pairs sell
walking shoes, and seven retailers sell the one walking shoe cheap enough to
ever be cheapest. Receipts and worlds, both at steering commit `c63ba3c1`:
`.local/coordination/world-requirement-construction-20261010/steering/run-v4-prices/`
and `run-v4-stock/` beside it; requirement files in `steering/` and
`steering/stock/`. `run-v3` is the same price evidence at the earlier reviewed
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

## What is not done

- **Two blocks, one at a time.** Prices (who is cheapest) and one offer's
  stock. A world is steered by one requirement; requirements are not yet
  combined. Two stock requirements on different retailers or products, or a
  stock and a price requirement that does not depend on availability, touch
  disjoint draws and would simply multiply. Two SKUs of one product at one
  retailer share the conditions and need a joint chain.
- **Upstream of stock is not steered.** Assortment, SKU listing, the number
  of locations and which of them ship, stock tendencies and whether the
  retailer takes supplier orders are the seed's. Requirements they rule out
  are refused with a reason code, not repaired.
- **Blocks that do not factor.** Both blocks are solved exactly because their
  draws are independent given the upstream. "The cheapest offer is sold out
  while a dearer one is in stock" couples stock and price across retailers:
  availability decides who competes on price. That needs the two models
  joined, a solver with weighted counting, or a bounded search. The
  plan/materialize/check split is built for that; the earlier Z3 pilot
  (`experiments/constrained_world_pilot/`) is not connected.
- **No publication.** Steered worlds are native worlds only:
  `browser_runtime_ready` is false. `unified_generation.generate` accepts a
  `world_factory`, which is where a steered world would enter so that
  surrounding sites, presentation and bindings are built by the ordinary
  pipeline; its sampling audit would have to record the steering.
- **One upstream.** Evidence on the manufactured world is one seed, one
  concept and one SKU; the unit tests add a second, stand-in world.

## What a released version needs

Coordination with Product, who own the producer:

1. A stream seam: `population.stream` consulting an explicit, caller-supplied
   plan, in place of the attribute swap.
2. A manufacture seam: a way to supply already manufactured products, in place
   of the second attribute swap.
3. Preferably, draw sites that declare their distribution (a named Bernoulli,
   categorical, integer range or clamped normal). The price model here mirrors
   `_offer_price` by hand and is checked against it empirically; declared
   sites would make block models generic and remove that duplication.

A measurement for Product, independent of steering: a pass through the
commerce producer with manufacture already done spends most of its time
re-reading the sampling defaults and the concept registry. `population.load()`
runs once per retailer/product entry (in `list_skus`), once per retailer and
twice more: 82 times for the saved seed-73 world. In a side measurement with
the seed-73 inputs and stand-in products (77 loads) a pass took 2.5 s as is
and 0.4 s with one shared `load()` result, and produced the identical world.
Caching it in the producer would make passes that reuse manufacture, which is
every steered pass, about six times cheaper. It does little for a first pass,
which manufacture dominates. This experiment does not patch it.

## Reproduction

```bash
.venv/bin/python -m pytest -q experiments/steered_generation/
```

`test_stock.py` runs the real commerce producer with stand-in products and
takes about 40 seconds.

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
  --samples 3 --validate-trials 30000 --producer-redraws 40 \
  --output /home/bjorn/code/LLM_proj_uu/.local/steering-reproduce
```
