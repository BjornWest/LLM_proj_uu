"""Several requirements in one world, when their blocks are independent.

Each part is a requirement one of the block modules can sample by itself. The
parts are sampled separately on the natural world and replayed in a single
pass of the real producer. That is the exact joint conditional sample only
when no part redraws what another redraws or is judged on, which
`blocks.independent` checks from what each block declares; then the
probability that all parts hold is the product of the parts'. Parts that fail
the check are refused as coupled; they need a joint block.
"""
import json
from math import fsum, log, prod

from experiments.world_requirement_construction import model as edits

from . import (blocks, carriers, cheapest, couriers, listed, policies, price_bounds, prices, ratings, reviews,
               sellers, shipments, shortlist, stock, streams, threshold)

VERSION = "steered-requirements-v1"
KINDS = {edits.VERSION: prices, stock.VERSION: stock, price_bounds.VERSION: price_bounds,
         cheapest.VERSION: cheapest, listed.VERSION: listed, shortlist.VERSION: shortlist,
         threshold.VERSION: threshold, reviews.VERSION: reviews, carriers.VERSION: carriers,
         shipments.VERSION: shipments, policies.VERSION: policies, sellers.VERSION: sellers,
         ratings.VERSION: ratings, couriers.VERSION: couriers}


def resolve(requirement):
    if (type(requirement) is not dict or set(requirement) != {"schema", "all"} or requirement["schema"] != VERSION or
            type(requirement["all"]) is not list or len(requirement["all"]) < 2 or
            any(type(part) is not dict or part.get("schema") not in KINDS for part in requirement["all"])):
        raise ValueError("Declare at least two requirements, each of a kind that can be sampled by itself")
    return json.loads(json.dumps(requirement))


def parts(natural, requirement, api):
    """The parts of a requirement, once their blocks are known to be independent.

    Coupling is settled first, from what each block declares, before any part
    is asked for a probability. A part's probability treats everything outside
    its block as fixed, so "zero given upstream" for one part says nothing
    about the whole requirement when another part redraws that upstream.
    """
    found = resolve(requirement)["all"]
    blocks.independent([KINDS[part["schema"]].footprint(natural, part, api) for part in found])
    return found


def prepare(natural, requirement, api, rng):
    """Sample every part on the natural world. A part with probability zero is named by its index."""
    steps = []
    for index, part in enumerate(parts(natural, requirement, api)):
        try:
            steps.append(KINDS[part["schema"]].prepare(natural, part, api, rng))
        except prices.ZeroMass as error:
            error.part = index
            raise
    return steps


def steer(session, natural, natural_opened, requirement, api, rng):
    """Plan every part on the natural world, regenerate once through the real producer, verify each."""
    steps = prepare(natural, requirement, api, rng)
    world, records, counts = blocks.replay(session, natural, natural_opened, steps)
    record = {"method": "independent_blocks", "requirement": resolve(requirement),
              "natural_world_id": natural["world_id"],
              "probability_given_upstream": prod(step.probability for step in steps), "blocks": records, **counts,
              "distribution_claim": "Each block is sampled from its distribution given its own requirement and all "
                                    "upstream draws. No block redraws what another redraws or is judged on, and "
                                    "the producer draws them on separate streams, so together they are a sample "
                                    "given all the requirements, whose probability is the product of the blocks'. "
                                    "Where a block's own claim says every other draw is the seed's own, that "
                                    "means every draw outside these blocks. "
                                    "Upstream draws are not reweighted; use probability_given_upstream as the "
                                    "importance weight across seeds."}
    if any(step.estimated for step in steps):
        # A product of estimates and exact numbers: the relative errors add in squares.
        record["probability_is_estimated"] = True
        record["probability_standard_error"] = record["probability_given_upstream"] * fsum(
            (step.error / step.probability) ** 2 for step in steps if step.error and step.probability) ** .5
    if any(step.log_probability is not None for step in steps):
        record["log_probability_given_upstream"] = fsum(
            log(step.probability) if step.log_probability is None else step.log_probability for step in steps)
        # None when the product is below the float range; the logarithm holds.
        record["probability_given_upstream"] = record["probability_given_upstream"] or None
    streams.relabel(world, record, api)
    return world, [step.check(world) for step in steps], record


def trial(natural, requirement, api):
    """Every part's reading of its block under another seed; refused for coupled parts like `prepare`."""
    return [KINDS[part["schema"]].trial(natural, part, api) for part in parts(natural, requirement, api)]


def empirical(natural, requirement, api, trials, first_seed):
    """How often each part, and all of them together, hold under other seeds' draws."""
    readings = trial(natural, requirement, api)
    alone, together = [0] * len(readings), 0
    for seed in range(first_seed, first_seed + trials):
        held = [found.holds(seed) for found in readings]
        alone = [count + hit for count, hit in zip(alone, held)]
        together += all(held)
    return alone, together


def redraw(session, natural, requirement, api, seed):
    """One pass of the real producer with every part's streams opened under another seed."""
    return blocks.redraw(session, natural, trial(natural, requirement, api), seed)
