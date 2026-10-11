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
from math import prod

from experiments.world_requirement_construction import model as edits

from . import blocks, price_bounds, prices, stock, streams

VERSION = "steered-requirements-v1"
KINDS = {edits.VERSION: prices, stock.VERSION: stock, price_bounds.VERSION: price_bounds}


def resolve(requirement):
    if (type(requirement) is not dict or set(requirement) != {"schema", "all"} or requirement["schema"] != VERSION or
            type(requirement["all"]) is not list or len(requirement["all"]) < 2 or
            any(type(part) is not dict or part.get("schema") not in KINDS for part in requirement["all"])):
        raise ValueError("Declare at least two requirements, each of a kind that can be sampled by itself")
    return json.loads(json.dumps(requirement))


def prepare(natural, requirement, api, rng):
    """Sample every part on the natural world. A part with probability zero is named by its index."""
    steps = []
    for index, part in enumerate(resolve(requirement)["all"]):
        try:
            steps.append(KINDS[part["schema"]].prepare(natural, part, api, rng))
        except prices.ZeroMass as error:
            error.part = index
            raise
    blocks.independent(steps)
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
    streams.relabel(world, record, api)
    return world, [step.check(world) for step in steps], record


def trial(natural, requirement, api):
    """Every part's reading of its block under another seed; refused for coupled parts like `prepare`."""
    readings = [KINDS[part["schema"]].trial(natural, part, api) for part in resolve(requirement)["all"]]
    blocks.independent(readings)
    return readings


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
