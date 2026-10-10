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
   native oracle and the pricing-rule check judge the result. If the model
   were wrong, the world would fail those checks; it cannot be silently wrong.

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

A pair whose natural draw already fits (at the winning price if designated,
above it otherwise) keeps that draw; only the others are redrawn. Keeping a
prior draw when it fits and redrawing from the conditional when it does not is
itself a draw from the conditional, so the steered world stays as close to the
seed's own world as the requirement allows without biasing the sample.

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

## Evidence on seed 73

Saved seed 73 at accepted source `e3fbfadd84d3b16a26895d62abb66f61df433697`:
25 products, 320 SKUs, 12 retailers, 411 offers; 48 retailer/product pairs sell
walking shoes, and seven retailers sell the one walking shoe cheap enough to
ever be cheapest. Receipt and worlds:
`.local/coordination/world-requirement-construction-20261010/steering/run-v2/`.

| Requirement on that shoe | Probability given upstream | Natural worlds per hit |
| --- | --- | --- |
| `footwear-03` is the sole cheapest seller | 0.101 | about 10 |
| `footwear-02` and `apparel-06` tie as cheapest | 0.0028 | about 350 |
| Those two and `department_store-02` tie | 0.00036 | about 2,700 |
| Five named retailers tie, the other two do not | 0.00069 | about 1,450 |

"Natural worlds per hit" is for this upstream. The five-way tie is likelier
than the three-way one because retailers that all draw the matched reference
price tie automatically.

Cost: the natural pass took 28 s and an unsteered replay 2.0 s. Each steered
world took 2.3 to 2.7 s including planning, the pass through the producer and
all checks, whatever the probability. Three worlds were sampled per
requirement, twelve in all.

The computed probabilities were compared with the frequency obtained by
redrawing the price block 30,000 times with the producer's own `_offer_price`
under other seeds: 0.098, 0.0030, 0.00023 and 0.00090 in table order, each
within two standard errors of the computed value. For the two rarest that is
7 and 27 hits, so the comparison is coarse there.

The natural pass reproduces the saved world's identity, and an unsteered pass
with cached manufacture reproduces it again. Each steered world differs from
the natural one only in the price and price-draw fields of the repriced
retailer/product pairs, satisfies the pricing rule, and has the designated
retailers as its only cheapest sellers under both the native oracle and a
separate full scan.

## What is not done

- **Only prices are steered.** Prices are the last commerce draws, so nothing
  the producer derives depends on them. Stock, assortment and menu draws do
  have dependants (supplier eligibility, catalog pages), which is where
  running the real producer pays off; no block model exists for them yet.
- **Blocks that do not factor.** The price block is solved in closed form
  because pairs are independent. A requirement coupling stock, menu and price
  across retailers needs a solver with weighted counting over the block, or a
  bounded search. The plan/materialize/check split is built for that; the
  earlier Z3 pilot (`experiments/constrained_world_pilot/`) is not connected.
- **No publication.** Steered worlds are native worlds only:
  `browser_runtime_ready` is false. `unified_generation.generate` accepts a
  `world_factory`, which is where a steered world would enter so that
  surrounding sites, presentation and bindings are built by the ordinary
  pipeline; its sampling audit would have to record the steering.
- **One upstream.** Evidence is one seed and one concept.

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

## Reproduction

```bash
.venv/bin/python -m pytest -q experiments/steered_generation/test_steered.py
```

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
  --samples 3 --validate-trials 30000 \
  --output /home/bjorn/code/LLM_proj_uu/.local/steering-reproduce
```
