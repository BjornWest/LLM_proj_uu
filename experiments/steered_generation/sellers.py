"""Conditional sampling of who has the cheapest available offer together with that retailer's shipping policy.

A requirement states a ranking, in the cheapest-available requirement's own
words but without a winner (a concept and, optionally, what competes and what
counts as available), and conditions on a shipping policy, in the policy
requirement's words but without a retailer. It holds when one retailer's
product alone is the cheapest available offer and that retailer's policy is
as stated: "the best offer is at a shop that has no express delivery".

That is one of several things that exclude one another: for each retailer
and product of the ranking, "this pair alone is cheapest, and this retailer's
policy is as stated". Stock and prices are drawn apart from policies, so each
alternative's probability is the product of the two blocks', the
requirement's is their sum, and a sample picks an alternative in proportion
to its probability and then samples its two blocks. No retailer's policy is
kept or rejected for being what the seed made it: the winner's is drawn as
required and every other retailer's is the seed's own, which is their
distribution given the requirement.

A requirement may add that the winner offers no free shipping
(`"free_shipping": false`), so that no order there has its delivery waived:
the winner's free-shipping threshold is then a third block of the
alternative, and every other retailer's is the seed's own. What an option
costs for a given offer can still be more than the menu's figure, which is
for the nearest location that ships: an offer held only farther away pays
the distance.
"""
import json
from math import exp, fsum, log
from types import SimpleNamespace

from . import blocks, cheapest, policies, threshold
from .blocks import Step, Unmet
from .cheapest import pick_log
from .prices import ZeroMass

VERSION = "steered-cheapest-seller-policy-v1"
# What a ranking names when it has a winner; left out here, where the winner is what is sampled.
WINNER = {"schema", "product_id", "retailer_ids", "listed_below"}


def resolve(requirement):
    if (type(requirement) is not dict or set(requirement) - {"free_shipping"} != {"schema", "cheapest", "policy"} or
            requirement.get("free_shipping", False) is not False or
            requirement["schema"] != VERSION or type(requirement["cheapest"]) is not dict or
            type(requirement["policy"]) is not dict or WINNER & set(requirement["cheapest"]) or
            "concept_id" not in requirement["cheapest"] or {"schema", "retailer_id"} & set(requirement["policy"])):
        raise ValueError("Declare a ranking without a winner (a concept and what competes) and a policy without a retailer")
    if "delivered" in requirement["cheapest"] and (policies.CONTRACTS & set(requirement["policy"]) or
                                                   "free_shipping" in requirement):
        raise ValueError("Not modelled: a ranking by delivered totals with a statement about the winner's contracts or "
                         "threshold, which those totals are read from")
    # The ranking's and the policy's own words, checked on any winner's and any retailer's name.
    cheapest.resolve(ranking(requirement, ("any", "any")))
    policies.resolve(policy(requirement, "any"))
    return json.loads(json.dumps(requirement))


def ranking(requirement, pair=None):
    """The cheapest-available requirement of the ranking, with a winner where one is given."""
    base = {"schema": cheapest.VERSION, **requirement["cheapest"]}
    return base if pair is None else {**base, "retailer_ids": [pair[0]], "product_id": pair[1]}


def policy(requirement, retailer):
    return {"schema": policies.VERSION, "retailer_id": retailer, **requirement["policy"]}


def unwaived(world, requirement, pair):
    """The free-shipping requirement that a retailer offers no threshold, stated on an offer of the winning product."""
    retailer = next(row for row in world["retailers"] if row["retailer_id"] == pair[0])
    return {"schema": threshold.VERSION, "retailer_id": pair[0], "quantity": 1, "subtotal_test": threshold.TESTS[0],
            "sku_id": next(offer["sku_id"] for offer in retailer["offers"] if offer["product_id"] == pair[1])}


def footprint(world, requirement, api):
    """What the block can decide: the ranking's stock and prices, and the policy of every retailer in it."""
    requirement = resolve(requirement)
    if requirement["cheapest"]["concept_id"] not in world["config"]["concept_ids"]:
        raise ValueError("Unknown concept")
    shared = cheapest.frame(world, ranking(requirement), api)
    about = {name for name, fields in (("contracts", policies.CONTRACTS), ("dispatch", {"dispatch_days"}))
             if fields & set(requirement["policy"])}
    if "free_shipping" in requirement:
        about.add("threshold")
    writes = {(kind, *pair) for pair in shared.places for kind in ("stock", "price")} | {
        (name, retailer, "") for retailer, _ in shared.places for name in about}
    # What the ranking reads, and what the policy of any retailer that may win reads: none of it may be redrawn
    # beside this block, whichever alternative is picked.
    reads = set(shared.scope.reads).union(*(policies.footprint(world, policy(requirement, retailer), api).reads
                                            for retailer in sorted({retailer for retailer, _ in shared.places})))
    return SimpleNamespace(writes=writes, reads=reads - writes)


def model(world, requirement, api):
    """The alternatives that can occur, each a winner with the logarithm of its probability, and their sum."""
    requirement = resolve(requirement)
    footprint(world, requirement, api)
    shared = cheapest.frame(world, ranking(requirement), api)
    suited, found, errors, estimates, missed, spread, sampled, unsettled = {}, [], {}, {}, [], [], {}, []
    for pair in sorted(shared.places):
        if pair[0] not in suited:
            try:
                block = policies.model(world, policy(requirement, pair[0]), api)
                rest = (threshold.model(world, unwaived(world, requirement, pair), api).probability
                        if "free_shipping" in requirement else 1.0)
                suited[pair[0]], errors[pair[0]] = block.probability * rest, block.error * rest
                if block.accepted is not None:
                    estimates[pair[0]] = [block.accepted, policies.PROPOSALS]
            except ZeroMass as error:
                suited[pair[0]] = 0.0
                if error.reason == "not_found":
                    missed.append(pair[0])
        if not suited[pair[0]]:
            continue
        try:
            block = cheapest.model(world, ranking(requirement, pair), api, shared)
        except ZeroMass as error:
            if error.reason == "not_found":
                unsettled.append(list(pair))
            continue
        won = getattr(block, "log_probability", None) or log(block.probability)
        if block.estimated:
            sampled["/".join(pair)] = [block.accepted, cheapest.PROPOSALS]
        # The alternative is a product of the two; either factor may be an estimate with its own error.
        spread.append((pair[0], exp(won), block.error))
        found.append((pair, won + log(suited[pair[0]])))
    if not found and (missed or unsettled):
        # A bounded search that found nothing is not a proof that nothing is there.
        raise ZeroMass("not_found", "For no retailer was an alternative found within the bounded searches of its "
                                    "contracts or of the ranking")
    if not found:
        raise ZeroMass("no_outcome", "No retailer can both have the cheapest available offer and this policy in this world")
    top = max(value for _, value in found)
    total = min(0.0, top + log(fsum(exp(value - top) for _, value in found)))
    # A retailer's policy share enters all its alternatives together; a ranking's estimate its own alternative.
    wins = {retailer: fsum(win for name, win, _ in spread if name == retailer) for retailer in {name for name, _, _ in spread}}
    error = fsum([(wins[retailer] * errors[retailer]) ** 2 for retailer in wins] +
                 [(suited[retailer] * part) ** 2 for retailer, _, part in spread]) ** .5
    return SimpleNamespace(requirement=requirement, shared=shared, alternatives=found, log_terms=dict(found),
                           log_probability=total, probability=exp(total), estimates=estimates, not_found=missed,
                           ranking_estimates=sampled, rankings_not_found=unsettled, error=error,
                           estimated=bool(estimates or missed or sampled or unsettled))


def leader(world, requirement, shared):
    """The retailer and product that alone have the cheapest available offer of the ranking in a world, or None."""
    return alone(cheapest.lowest(cheapest.recorded(world, requirement["cheapest"]["concept_id"], set(shared.places)),
                                 shared.scope)[0])


def alone(best):
    """The one pair with the lowest rank among pairs' best available ranks, or None."""
    winners = [pair for pair, rank in (best or {}).items() if rank == min(best.values())]
    return winners[0] if len(winners) == 1 else None


def check(world, requirement, api):
    """Read the requirement off a world: the winner by the native oracle, its policy by the recorded contracts."""
    requirement = resolve(requirement)
    pair = leader(world, requirement, cheapest.frame(world, ranking(requirement), api))
    if pair is None:
        raise Unmet("No retailer's product alone is the cheapest available offer")
    return {"retailer_id": pair[0], "product_id": pair[1],
            "cheapest": cheapest.check(world, ranking(requirement, pair), api),
            "policy": policies.check(world, policy(requirement, pair[0]), api),
            **({"free_shipping": threshold.check(world, unwaived(world, requirement, pair), api)}
               if "free_shipping" in requirement else {})}


def prepare(natural, requirement, api, rng):
    """Pick a winner in proportion, sample its two blocks on the natural world; the step replays both."""
    block = model(natural, requirement, api)
    pair = pick_log(rng, [pair for pair, _ in block.alternatives], [value for _, value in block.alternatives])
    steps = [cheapest.prepare(natural, ranking(block.requirement, pair), api, rng),
             policies.prepare(natural, policy(block.requirement, pair[0]), api, rng)]
    if "free_shipping" in block.requirement:
        steps.append(threshold.prepare(natural, unwaived(natural, block.requirement, pair), api, rng))
    blocks.independent(steps)
    writes, declared = set().union(*(step.writes for step in steps)), footprint(natural, requirement, api)

    def record(world):
        rows = [step.record(world) for step in steps]
        return {"method": "one_of_exclusive_alternatives", "requirement": block.requirement,
                "natural_world_id": natural["world_id"], "probability_given_upstream": block.probability or None,
                "log_probability_given_upstream": block.log_probability, "alternatives": len(block.alternatives),
                **({"probability_is_estimated": True, "probability_standard_error": block.error,
                    "policy_draws_accepted_by_retailer": block.estimates,
                    "retailers_not_found_in_bounded_search": block.not_found,
                    "ranking_samples_accepted_by_pair": block.ranking_estimates,
                    "rankings_not_found_in_bounded_search": block.rankings_not_found} if block.estimated else {}),
                "chosen": {"retailer_id": pair[0], "product_id": pair[1],
                           "log_probability_given_upstream": block.log_terms[pair]},
                "blocks": rows,
                "distribution_claim": "The requirement is one of several alternatives that exclude one another: a "
                                      "retailer's product alone is the cheapest available offer and that retailer's "
                                      "shipping policy is as stated. One is picked in proportion to its probability "
                                      "and its blocks (the ranking's stock and prices; that retailer's policy; its "
                                      "free-shipping threshold where the requirement states there is none) "
                                      "are sampled given it. Every other retailer's policy is the seed's own. "
                                      "Where a policy is about shown delivery options, or a ranking by delivered "
                                      "totals has a charge that depends on the location, its share is an estimate "
                                      "from a fixed number of draws, so the pick among alternatives and the "
                                      "probability are approximate, and an alternative for which no draw qualified "
                                      "is left out. Use "
                                      "the probability, which is the alternatives' sum, as the importance weight "
                                      "across seeds."}

    def checked(world):
        found = check(world, block.requirement, api)
        if (found["retailer_id"], found["product_id"]) != pair:
            raise AssertionError("Another retailer's product is the cheapest available offer than the one sampled")
        return found

    return Step(script={key: entry for step in steps for key, entry in step.script.items()}, probability=block.probability,
                log_probability=block.log_probability, error=block.error,
                estimated=block.estimated, writes=writes,
                # The alternatives not picked stay as the seed made them, and so must all that any alternative reads.
                reads=(declared.writes | declared.reads).union(*(step.reads for step in steps)) - writes,
                record=record, check=checked)


def steer(session, natural, natural_opened, requirement, api, rng):
    """Plan on the natural world, regenerate through the real producer, verify."""
    return blocks.steer(session, natural, natural_opened, prepare(natural, requirement, api, rng), api)


def trial(natural, requirement, api):
    """The ranking's leaves and every retailer's policy from the producer's own lines under another seed."""
    requirement = resolve(requirement)
    footprint(natural, requirement, api)
    shared = cheapest.frame(natural, ranking(requirement), api)
    reading, keys = cheapest.reader(natural, shared.places, api)
    retailers = sorted({retailer for retailer, _ in shared.places})
    policed = {retailer: policies.trial(natural, policy(requirement, retailer), api) for retailer in retailers}
    # Where the winner must offer no free shipping: every ranked retailer's threshold draws, read on one of its pairs.
    waived = {retailer: threshold.trial(natural, unwaived(natural, requirement, next(
        pair for pair in sorted(shared.places) if pair[0] == retailer)), api) for retailer in retailers
        } if "free_shipping" in requirement else {}
    parts = [*policed.values(), *waived.values()]

    winner = lambda seed: alone(cheapest.lowest(reading(seed), shared.scope)[0])

    def holds(seed):
        pair = winner(seed)
        return pair is not None and policed[pair[0]].holds(seed) and (not waived or waived[pair[0]].holds(seed))

    return SimpleNamespace(
        keys=set(keys).union(*(found.keys for found in parts)), **vars(footprint(natural, requirement, api)),
        reading=lambda seed: (reading(seed), *({retailer: found.reading(seed) for retailer, found in group.items()}
                                               for group in (policed, waived))),
        winner=winner, holds=holds,
        recorded=lambda world: (cheapest.recorded(world, requirement["cheapest"]["concept_id"], set(shared.places)),
                                *({retailer: found.recorded(world) for retailer, found in group.items()}
                                  for group in (policed, waived))),
        satisfied=lambda world: satisfied(world, requirement, api))


def satisfied(world, requirement, api):
    try:
        return bool(check(world, requirement, api))
    except Unmet:
        return False


def empirical(natural, requirement, api, trials, first_seed):
    """How often the requirement holds under other seeds, by the retailer and product that then win."""
    found, seen = trial(natural, requirement, api), {}
    for seed in range(first_seed, first_seed + trials):
        if found.holds(seed):
            pair = found.winner(seed)
            seen[pair] = seen.get(pair, 0) + 1
    return seen
