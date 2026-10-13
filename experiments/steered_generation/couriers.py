"""Conditional sampling of who is cheapest delivered together with the carrier that delivers it there.

A requirement states a ranking by delivered totals with one designated
retailer and product (the cheapest-available requirement with `delivered`)
and a carrier. It holds when that retailer's product alone is the cheapest
delivered home, the retailer's cheapest shown home-delivery option is the
named carrier's, and so is the option the winning total is made with, alone:
"the cheapest delivered offer comes with this carrier". The last is not
implied by the one before where the retailer waives delivery from a subtotal
the winning price reaches: every option that is not express then costs
nothing and two carriers shown tie.

A ranking by delivered totals reads the winner's contracts, through what the
retailer shows and charges, so the retailer's contracts and the concept's
stock and prices are one block here. They are drawn independently, which
gives a sample by acceptance. Contracts are drawn from their distribution
given that they show the carrier cheapest (`policies`). Stock and prices are
drawn from the ranking's block between bounds that hold whatever the
contracts are: the designated pair charged nothing for delivery, and the
retailer's other products the most any contract can charge (`menus.ceiling`),
every other retailer as the ranking does. A pair of draws is accepted when
the designated pair is cheapest on the charges as they are with the drawn
contracts and the carrier's option alone makes the winning total, after any
waiver. The requirement implies both conditions the draws were made
under, so accepted pairs are samples given the requirement. The probability
is the product of the two conditions' probabilities and the accepted share
of a fixed number of pairs: an estimate, labelled as one.
"""
import json
from math import exp, log
from random import Random
from types import SimpleNamespace

from . import blocks, cheapest, menus, policies, streams
from .blocks import NumericalLimit, Step, Unmet
from .prices import ZeroMass

VERSION = "steered-cheapest-delivered-carrier-v1"
# How many pairs of draws estimate the accepted share, how many a sample may take, and the estimates of this process.
PROPOSALS, TRIES, ESTIMATES = 200, 20000, {}


def resolve(requirement):
    if (type(requirement) is not dict or set(requirement) != {"schema", "cheapest", "carrier_id"} or
            requirement["schema"] != VERSION or type(requirement["cheapest"]) is not dict or
            "schema" in requirement["cheapest"] or type(requirement["carrier_id"]) is not str or not requirement["carrier_id"]):
        raise ValueError("Declare a ranking by delivered totals with its winner, and a carrier")
    ranked = cheapest.resolve(ranking(requirement))
    if "delivered" not in ranked or len(ranked["retailer_ids"]) != 1 or "listed_below" in ranked:
        raise ValueError("The ranking is by delivered totals, with one designated retailer and no offers listed below it")
    if ranked["delivered"].get("delivery_types", ["home"]) != ["home"]:
        raise ValueError("Not modelled: the carrier of the cheapest offer delivered to a collection point")
    return json.loads(json.dumps(requirement))


def ranking(requirement):
    return {"schema": cheapest.VERSION, **requirement["cheapest"]}


def shown(requirement):
    """The policy requirement that the winner shows the carrier's home option cheapest, under the ranking's recipe."""
    options = requirement["cheapest"]["delivered"].get("delivery_options")
    return {"schema": policies.VERSION, "retailer_id": requirement["cheapest"]["retailer_ids"][0],
            "shown": {"cheapest_carrier": requirement["carrier_id"],
                      **({} if options is None else {"delivery_options": options})}}


def site(world, requirement, api):
    """The winner's contract draws, and the ranking's block between the bounds no contracts can leave."""
    requirement = resolve(requirement)
    need, policy = ranking(requirement), shown(requirement)
    retailer = need["retailer_ids"][0]
    place = policies.site(world, policy, api)
    limit = menus.ceiling(place.menu)
    bounds = SimpleNamespace(at=None, lowest=lambda price: 0, highest=lambda price: limit, uniform=False,
                             warehouse=place.menu.retailer["source_locations"][0]["source_id"])
    shared = cheapest.frame(world, need, api, charges={retailer: bounds})
    return SimpleNamespace(requirement=requirement, need=need, policy=policy, retailer=retailer, place=place,
                           shared=shared, ceiling=limit)


def footprint(world, requirement, api):
    """What the block decides: the ranking's stock and prices and the winner's contracts; and what it reads besides."""
    found = site(world, requirement, api)
    writes = {(kind, *pair) for pair in found.shared.places for kind in ("stock", "price")} | {("contracts", found.retailer, "")}
    return SimpleNamespace(writes=writes, reads=(set(found.shared.scope.reads) |
                                                 policies.footprint(world, found.policy, api).reads) - writes)


def charged(found, contracts):
    """The ranking's scope with the winner charged as these contracts make it; None where they show no home route."""
    charge = menus.delivery(found.place.menu, contracts)
    scope = found.shared.scope
    return None if charge is None else SimpleNamespace(**{**vars(scope), "delivered": {**scope.delivered, found.retailer: charge}})


def met(found, contracts, leaves):
    """The requirement read off the winner's contracts and the block's leaves.

    The contracts show the carrier cheapest; the designated pair alone is
    cheapest delivered on the charges they make; and for every offer of the
    pair at the winning total the carrier's option is strictly the cheapest
    after any waiver, as the native task's winning rows have it.
    """
    scope = charged(found, contracts)
    if scope is None or not policies.displayed(found.place, contracts):
        return False
    winning = cheapest.judged(leaves, found.need, scope)
    if winning is None:
        return False
    charge, ships = scope.delivered[found.retailer], scope.sources[found.retailer]
    for row in leaves["offers"].values():
        if (row["retailer_id"], row["product_id"]) != (found.retailer, found.need["product_id"]) or row["sku_id"] not in scope.skus:
            continue
        holding = [name for name, quantity in row["stock_by_source"].items() if quantity and name in ships]
        if not holding and not row["supplier_order"]:
            continue
        holding = holding or [charge.warehouse]
        if (scope.key(row["sku_id"], row["price_minor"] + charge.at(row["price_minor"], holding)) == winning and
                charge.carrier(row["price_minor"], holding) != found.requirement["carrier_id"]):
            return False
    return True


def contracted(found, block, rng):
    """One draw of the winner's contracts given that they show the carrier cheapest: the plan and the contracts."""
    for _ in range(policies.TRIES):
        script, contracts = policies.draw(block, rng)
        if policies.displayed(found.place, contracts):
            return script, contracts
    raise NumericalLimit("Contracts that show what is required are too rare to reach by drawing them")


def model(world, requirement, api):
    """The two conditions the draws are made under, the accepted share of pairs of draws, and the probability."""
    found = site(world, requirement, api)
    contracts = policies.model(world, found.policy, api)
    block = cheapest.model(world, found.need, api, found.shared, estimate=False)
    key = world["world_id"], json.dumps(found.requirement, sort_keys=True)
    if key not in ESTIMATES:
        # The same draws for the same world and requirement, in this process and the next.
        rng = Random(api.native.digest({"world_id": world["world_id"], "requirement": found.requirement}))
        ESTIMATES[key] = sum(met(found, contracted(found, contracts, rng)[1], cheapest.planned(block, cheapest.sample(block, rng)[1]))
                             for _ in range(PROPOSALS))
    accepted = ESTIMATES[key]
    if not accepted:
        # Not a proof that it cannot occur: callers report it as not found.
        raise ZeroMass("not_found", f"None of {PROPOSALS} pairs of draws has the designated offer cheapest delivered "
                                    "with the carrier")
    share = accepted / PROPOSALS
    total = log(contracts.probability) + block.log_probability + log(share)
    # Two estimated shares, of the contracts that show the carrier and of the pairs accepted; their relative errors add in squares.
    relative = ((contracts.error / contracts.probability) ** 2 + (1 - share) / (share * PROPOSALS)) ** .5
    return SimpleNamespace(site=found, contracts=contracts, block=block, accepted=accepted, log_probability=total,
                           probability=exp(total), error=exp(total) * relative, estimated=True)


def check(world, requirement, api):
    """Read the requirement off a world: the policy by the plans a site is built from, the winner and its carrier by the
    native delivery task."""
    requirement = resolve(requirement)
    need = ranking(requirement)
    shown_now = policies.check(world, shown(requirement), api)
    ranked = cheapest.check(world, need, api)
    if any(row["delivery"]["carrier_id"] != requirement["carrier_id"] for row in ranked["reference"]["winners"]):
        raise Unmet("The cheapest delivered option is another carrier's")
    return {"retailer_id": need["retailer_ids"][0], "product_id": need["product_id"], "carrier_id": requirement["carrier_id"],
            "total_minor": ranked["reference"]["optimal_score"][0], "contracts": shown_now["contracts"],
            "shown": shown_now["shown"], "reference": ranked["reference"], "task": ranked["task"]}


def prepare(natural, requirement, api, rng):
    """Draw pairs until one is accepted on the natural world; the step replays both parts and reads the result."""
    whole = model(natural, requirement, api)
    found, block = whole.site, whole.block
    for pairs in range(1, TRIES + 1):
        script, contracts = contracted(found, whole.contracts, rng)
        _, draws = cheapest.sample(block, rng)
        leaves = cheapest.planned(block, draws)
        if met(found, contracts, leaves):
            break
    else:
        raise NumericalLimit("Accepted pairs of draws are too rare to reach")
    concept, declared = block.requirement["concept_id"], footprint(natural, requirement, api)
    # The ranks sampled are the bounded block's; what is recorded is what the accepted leaves and contracts give.
    best, _ = cheapest.lowest(leaves, charged(found, contracts))
    for pair, drawn in draws.items():
        drawn.cheapest_available = best.get(pair)

    def record(world):
        if policies.listed(world, found.place)[0] != contracts or cheapest.recorded(world, concept, set(block.places)) != leaves:
            raise streams.PlanMismatch("The producer recorded other contracts or stock and price leaves than planned")
        return {"method": "independent_draws_between_bounds_then_joint_acceptance", "requirement": found.requirement,
                "natural_world_id": natural["world_id"], "probability_given_upstream": whole.probability,
                "log_probability_given_upstream": whole.log_probability, "probability_is_estimated": True,
                "probability_standard_error": whole.error, "proposals": PROPOSALS, "proposals_accepted": whole.accepted,
                "pairs_drawn_for_this_sample": pairs, "delivery_charge_ceiling_minor": found.ceiling,
                "winning_total_minor": min(best.values()), "steered_contracts": contracts,
                "natural_contracts": policies.listed(natural, found.place)[0],
                "restocked": cheapest.restocked(natural, block, draws),
                "distribution_claim": "The winner's carrier contracts and, for every pair of the concept that competes, "
                                      "its price draw and stock draws are sampled from their distribution given the "
                                      "requirement: contracts given that they show the carrier cheapest, stock and "
                                      "prices between bounds on the winner's delivery charge that hold for any "
                                      "contracts, and the pair accepted when the designated offer is cheapest "
                                      "delivered on the charges as they are and the carrier's option alone makes that "
                                      "total after any waiver. The probability is those two conditions' "
                                      "probabilities times an estimated accepted share. Every other draw is the "
                                      "seed's own; the requirement also reads the other retailers' contracts and "
                                      "thresholds. Use the probability as the importance weight across seeds."}

    return Step(script={**script, **cheapest.scripts(block, draws)}, probability=whole.probability,
                log_probability=whole.log_probability, error=whole.error, estimated=True, **vars(declared),
                record=record, check=lambda world: check(world, requirement, api))


def steer(session, natural, natural_opened, requirement, api, rng):
    """Plan on the natural world, regenerate through the real producer, verify."""
    return blocks.steer(session, natural, natural_opened, prepare(natural, requirement, api, rng), api)


def trial(natural, requirement, api):
    """The winner's contracts and the block's leaves from the producer's own lines under another seed."""
    found = site(natural, requirement, api)
    drawn = policies.trial(natural, found.policy, api)
    reading, keys = cheapest.reader(natural, found.shared.places, api)
    concept = found.need["concept_id"]
    return SimpleNamespace(
        keys=set(keys) | set(drawn.keys), **vars(footprint(natural, requirement, api)),
        reading=lambda seed: (drawn.reading(seed)[0], reading(seed)),
        holds=lambda seed: met(found, drawn.reading(seed)[0], reading(seed)),
        recorded=lambda world: (policies.listed(world, found.place)[0],
                                cheapest.recorded(world, concept, set(found.shared.places))),
        satisfied=lambda world: satisfied(world, requirement, api))


def satisfied(world, requirement, api):
    try:
        return bool(check(world, requirement, api))
    except Unmet:
        return False


def empirical(natural, requirement, api, trials, first_seed):
    """How often the requirement holds under other seeds."""
    found = trial(natural, requirement, api)
    return sum(found.holds(seed) for seed in range(first_seed, first_seed + trials))
