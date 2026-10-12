"""Conditional sampling of a retailer's shipping policy: its carrier contracts and how fast it dispatches.

A requirement names a retailer and states one or more of: carriers it must or
must not have a contract with, how many carriers it has, whether any of its
contracts offers express or economy delivery, the lowest standard collection
fee among its contracts, the lowest standard home-delivery fee (a contract's
collection fee plus its home difference), and the days its warehouse takes to
dispatch.

The producer draws, per retailer: how many carriers, uniformly in a range set
by the retailer's scale; which ones, as an ordered sample of the world's
carriers without replacement; per contract whether it has an economy and an
express tier, each a coin of its own; per contract a collection fee and a
home difference, each a weighted choice from a table; and the warehouse's
dispatch days, a weighted choice. All sit on named streams and nothing else
in the world reads them, so they are the block: the contract draws when the
requirement is about contracts, the dispatch draw when it is about dispatch.

Contracts draw independently and alike whichever carrier they are with, so
the probability of a requirement is a sum over the number of carriers of the
chance that the set of carriers is as required (a ratio of binomial numbers)
times the chance that so many contracts are as required. The latter folds
the contracts in one at a time, keeping only what the requirement reads of
them: whether a tier was seen, and the lowest fees so far. A sample chooses
the number and that summary, then the contracts back from the last to the
first, then the carriers, and replays all of it through the producer.
"""
import json
from math import comb, fsum
import sys
from types import SimpleNamespace

from . import blocks
from .blocks import Step, Unmet, bound, pick, within
from .prices import UNMATCHED, ZeroMass

VERSION = "steered-retailer-shipping-v1"
TIERS = ("economy", "express")
FEES = ("collection_fee_minor", "home_fee_minor")
STATED = {"carriers", "carrier_count", *TIERS, *FEES, "dispatch_days"}
# What of the requirement is about contracts; the rest is the warehouse's dispatch.
CONTRACTS = STATED - {"dispatch_days"}


def resolve(requirement):
    if (type(requirement) is not dict or not {"schema", "retailer_id"} <= set(requirement) <= {"schema", "retailer_id"} | STATED or
            requirement["schema"] != VERSION or not STATED & set(requirement) or
            type(requirement["retailer_id"]) is not str or not requirement["retailer_id"]):
        raise ValueError("Declare a retailer and one or more of " + ", ".join(sorted(STATED)))
    named = requirement.get("carriers", {"include": []})
    if (type(named) is not dict or not named or set(named) - {"include", "exclude"} or
            any(type(row) is not list or any(type(name) is not str or not name for name in row) or len(set(row)) != len(row)
                for row in named.values()) or set(named.get("include", [])) & set(named.get("exclude", []))):
        raise ValueError("Carriers are lists of carrier ids to include, to exclude or both, none in both")
    if any(key in requirement and not bound(requirement[key]) for key in ("carrier_count", "dispatch_days")):
        raise ValueError("A number of carriers or of dispatch days is a non-negative min, max or both")
    for key in FEES:
        limits = requirement.get(key, {"min": 0})
        if (type(limits) is not dict or not limits or set(limits) - {"min", "max"} or
                any(type(value) is not int for value in limits.values()) or
                "min" in limits and "max" in limits and limits["min"] > limits["max"]):
            raise ValueError("A fee is a whole min, max or both, in minor units")
    if any(key in requirement and type(requirement[key]) is not bool for key in TIERS):
        raise ValueError("A tier is true where some contract must offer it and false where none may")
    return json.loads(json.dumps(requirement))


def footprint(world, requirement, api):
    """What the block decides: the retailer's contracts, its warehouse's dispatch days, or both."""
    requirement = resolve(requirement)
    retailer = requirement["retailer_id"]
    if not any(row["retailer_id"] == retailer for row in world["retailers"]):
        raise ValueError("Unknown retailer")
    return SimpleNamespace(writes={(name, retailer, "") for name, about in (("contracts", CONTRACTS), ("dispatch", {"dispatch_days"}))
                                   if about & set(requirement)}, reads=set())


def site(world, requirement, api):
    """Where a retailer's policy draws sit in a world, and the tables they are drawn from."""
    requirement = resolve(requirement)
    footprint(world, requirement, api)
    retailer = next(row for row in world["retailers"] if row["retailer_id"] == requirement["retailer_id"])
    commerce = sys.modules[api.commerce.generate.__module__]
    defaults, plan = api.population.load()[0], json.loads(commerce.addresses.PLAN.read_text())
    # The tables are read again here; the world says which ones it was drawn from.
    if (api.native.digest(defaults) != world["provenance"]["population_defaults_sha256"] or
            api.native.digest(plan) != world["provenance"]["plan_sha256"]):
        raise ValueError("The sampling defaults or the delivery plan are not the ones this world was generated from")
    selection, policy = defaults["shipping_selection"], world["shipping_policy"]
    carriers = [row["carrier_id"] for row in world["address_context"]["carriers"]]
    if len(carriers) != selection["world_carrier_count"]:
        raise ValueError("The world's carriers are not the pool the retailer's contracts are drawn from")
    named = requirement.get("carriers", {})
    if (set(named.get("include", [])) | set(named.get("exclude", []))) - set(carriers):
        raise ValueError("Unknown carrier")
    rid, base = retailer["retailer_id"], api.commerce.VERSION + "/" + retailer["retailer_id"]
    timing = plan["retailer_population_contract"]["geography_and_delivery_policy"]["dispatch_timing"]
    return SimpleNamespace(
        requirement=requirement, retailer_id=rid, carriers=carriers,
        # The population sampler names a carrier by its place in the pool; the world by its id.
        names={carrier: f"carrier-{index}" for index, carrier in enumerate(carriers)},
        counts=range(selection["carrier_count_ranges_by_scale"][retailer["scale"]][0],
                     selection["carrier_count_ranges_by_scale"][retailer["scale"]][1] + 1),
        tiers={tier: min(1, max(0, selection[tier + "_service_probability"])) for tier in TIERS},
        fees=policy["retailer_carrier_standard_collection_base_fee_minor_probabilities"],
        homes=policy["home_delivery_relative_to_collection_minor_probabilities"],
        days=timing["warehouse_calendar_day_probabilities"],
        keys=SimpleNamespace(count=rid + "/carrier_count", carriers=rid + "/carriers", dispatch=base + "/warehouse-dispatch",
                             tier=lambda carrier, tier: f"{rid}/carrier-{carriers.index(carrier)}/{tier}",
                             fee=lambda carrier: f"{base}/{carrier}/collection-fee",
                             home=lambda carrier: f"{base}/{carrier}/home-fee"))


def shares(weights):
    """A weighted choice's outcomes that can occur, with their probabilities."""
    total = fsum(weights.values())
    return {name: weight / total for name, weight in weights.items() if weight > 0}


def kinds(place):
    """One contract's draws, (economy, express, collection fee key, home difference key), with their probabilities."""
    sides = lambda chance: [(True, chance), (False, 1 - chance)]
    return {(economy, express, fee, home): a * b * c * d
            for economy, a in sides(place.tiers["economy"]) for express, b in sides(place.tiers["express"])
            for fee, c in shares(place.fees).items() for home, d in shares(place.homes).items() if a * b * c * d > 0}


def after(state, kind):
    """What a requirement reads of some contracts once one more is added: tiers seen, and the lowest fees."""
    economy, express, fee, home = state
    collection = int(kind[2])
    delivered = collection + int(kind[3])
    return (economy or kind[0], express or kind[1], collection if fee is None else min(fee, collection),
            delivered if home is None else min(home, delivered))


def folded(place, count):
    """For 0 to `count` contracts, the probability of each summary of them."""
    rows, found = [{(False, False, None, None): 1.0}], kinds(place)
    for _ in range(count):
        row = {}
        for state, mass in rows[-1].items():
            for kind, share in found.items():
                row.setdefault(after(state, kind), []).append(mass * share)
        rows.append({state: fsum(parts) for state, parts in row.items()})
    return rows


def summary(contracts):
    """The summary of a world's recorded contracts, in `after`'s form."""
    if not contracts:
        return False, False, None, None
    return (any("economy" in row["tiers"] for row in contracts), any("express" in row["tiers"] for row in contracts),
            min(row["collection_fee_minor"] for row in contracts),
            min(row["collection_fee_minor"] + row["home_delta_minor"] for row in contracts))


def suits(requirement, state):
    """Whether contracts with this summary are as the requirement states them."""
    economy, express, fee, home = state
    limited = lambda key, value: key not in requirement or value is not None and (
        requirement[key].get("min", value) <= value <= requirement[key].get("max", value))
    return (requirement.get("economy", economy) == economy and requirement.get("express", express) == express and
            limited(FEES[0], fee) and limited(FEES[1], home))


def chosen(place, count):
    """The chance that `count` carriers drawn from the pool include and exclude the named ones."""
    named = place.requirement.get("carriers", {})
    include, exclude = len(named.get("include", [])), len(named.get("exclude", []))
    free = len(place.carriers) - include - exclude
    if not 0 <= count - include <= free or count > len(place.carriers):
        return 0.0
    return comb(free, count - include) / comb(len(place.carriers), count)


def holds(requirement, contracts, days):
    """The requirement read off a retailer's contracts and its warehouse's dispatch days."""
    named, carriers = requirement.get("carriers", {}), [row["carrier_id"] for row in contracts]
    return (set(named.get("include", [])) <= set(carriers) and not set(named.get("exclude", [])) & set(carriers) and
            within(requirement.get("carrier_count", {}), len(contracts)) and suits(requirement, summary(contracts)) and
            within(requirement.get("dispatch_days", {}), days))


def model(world, requirement, api):
    """The block's outcomes that satisfy the requirement, and their probability.

    `outcomes` are (mass, number of carriers, summary of the contracts) where
    the requirement is about contracts; `days` the dispatch days it allows
    with their probabilities where it is about dispatch.
    """
    place = site(world, requirement, api)
    requirement, outcomes, days = place.requirement, None, None
    if CONTRACTS & set(requirement):
        rows = folded(place, place.counts[-1])
        outcomes = [(chosen(place, count) / len(place.counts) * mass, count, state)
                    for count in place.counts if within(requirement.get("carrier_count", {}), count)
                    for state, mass in rows[count].items() if suits(requirement, state)]
        outcomes = [found for found in outcomes if found[0] > 0]
        if not outcomes:
            raise ZeroMass("no_outcome", "No contracts of this retailer satisfy the requirement in this world")
    if "dispatch_days" in requirement:
        days = {name: share for name, share in shares(place.days).items() if within(requirement["dispatch_days"], int(name))}
        if not days:
            raise ZeroMass("no_outcome", "No dispatch time of this retailer's warehouse satisfies the requirement")
    return SimpleNamespace(site=place, outcomes=outcomes, days=days, rows=rows if outcomes else None,
                           probability=(fsum(found[0] for found in outcomes) if outcomes else 1.0) *
                                       (fsum(days.values()) if days else 1.0))


def listed(world, place):
    """What a world records: the retailer's contracts and its warehouse's dispatch days."""
    retailer = next(row for row in world["retailers"] if row["retailer_id"] == place.retailer_id)
    return retailer["contracts"], retailer["source_locations"][0]["dispatch_days"]


def check(world, requirement, api):
    """Read the requirement off a world's recorded contracts and dispatch days."""
    place = site(world, requirement, api)
    contracts, days = listed(world, place)
    if not holds(place.requirement, contracts, days):
        raise Unmet(f"{place.retailer_id}: contracts {json.dumps(contracts)}, dispatch in {days} days")
    return {"retailer_id": place.retailer_id, "contracts": contracts, "warehouse_dispatch_days": days}


def prepare(natural, requirement, api, rng):
    """Sample the block on the natural world; the step replays it and reads the result."""
    block = model(natural, requirement, api)
    place, script, contracts, days = block.site, {}, None, None
    if block.outcomes:
        _, count, state = pick(rng, block.outcomes, [found[0] for found in block.outcomes])
        # The contracts, from the last to the first: each with the summary of those before it.
        found, drawn = kinds(place), []
        for position in range(count, 0, -1):
            options = [(before, kind) for before in block.rows[position - 1] for kind in found if after(before, kind) == state]
            state, kind = pick(rng, options, [block.rows[position - 1][before] * found[kind] for before, kind in options])
            drawn.append(kind)
        drawn.reverse()
        named = place.requirement.get("carriers", {})
        include = named.get("include", [])
        free = [carrier for carrier in place.carriers if carrier not in include and carrier not in named.get("exclude", [])]
        carriers = include + rng.sample(free, count - len(include))
        rng.shuffle(carriers)
        script[place.keys.count] = [("randint", count)]
        script[place.keys.carriers] = [("sample", [place.names[carrier] for carrier in carriers])]
        contracts = []
        for carrier, (economy, express, fee, home) in zip(carriers, drawn):
            script[place.keys.tier(carrier, "economy")] = [("random", 0.0 if economy else UNMATCHED)]
            script[place.keys.tier(carrier, "express")] = [("random", 0.0 if express else UNMATCHED)]
            script[place.keys.fee(carrier)] = [("choices", fee)]
            script[place.keys.home(carrier)] = [("choices", home)]
            contracts.append({"carrier_id": carrier, "tiers": ["standard", *(["economy"] if economy else []),
                                                               *(["express"] if express else [])],
                              "collection_fee_minor": int(fee), "home_delta_minor": int(home)})
    if block.days:
        days = pick(rng, list(block.days), list(block.days.values()))
        script[place.keys.dispatch] = [("choices", days)]

    def record(world):
        recorded = listed(world, place)
        if contracts is not None and recorded[0] != contracts or days is not None and recorded[1] != int(days):
            raise blocks.streams.PlanMismatch(f"{place.retailer_id}: producer recorded another policy than planned")
        before = listed(natural, place)
        return {"method": "exact_conditional_policy_draws", "requirement": place.requirement,
                "natural_world_id": natural["world_id"], "probability_given_upstream": block.probability,
                "retailer_id": place.retailer_id,
                **({"natural_contracts": before[0], "steered_contracts": contracts} if contracts is not None else {}),
                **({"natural_dispatch_days": before[1], "steered_dispatch_days": int(days)} if days is not None else {}),
                "distribution_claim": "This retailer's " + " and ".join(
                    name for name, used in (("carrier contracts (how many carriers, which, each contract's tiers and "
                                             "two fees)", contracts is not None),
                                            ("warehouse dispatch days", days is not None)) if used) +
                                      " are sampled from their distribution given the requirement. Every other draw "
                                      "is the seed's own; the requirement depends on no other draw. Use the "
                                      "probability as the importance weight across seeds."}

    return Step(script=script, probability=block.probability, **vars(footprint(natural, requirement, api)),
                record=record, check=lambda world: check(world, requirement, api))


def steer(session, natural, natural_opened, requirement, api, rng):
    """Plan on the natural world, regenerate through the real producer, verify."""
    return blocks.steer(session, natural, natural_opened, prepare(natural, requirement, api, rng), api)


def trial(natural, requirement, api):
    """The contracts and the dispatch days from the producer's own lines under another seed; independent of the model."""
    place = site(natural, requirement, api)
    retailer = next(row for row in natural["retailers"] if row["retailer_id"] == place.retailer_id)
    selection = api.population.load()[0]["shipping_selection"]
    about = {"contracts": bool(CONTRACTS & set(place.requirement)), "dispatch": "dispatch_days" in place.requirement}

    def reading(seed):
        stream = lambda key: api.population.stream(seed, key)
        contracts, days = listed(natural, place)
        if about["contracts"]:
            count = stream(place.keys.count).randint(*selection["carrier_count_ranges_by_scale"][retailer["scale"]])
            pool = [f"carrier-{index}" for index in range(selection["world_carrier_count"])]
            contracts = []
            for name in stream(place.keys.carriers).sample(pool, count):
                carrier = place.carriers[int(name.split("-")[1])]
                tiers = ["standard"] + [tier for tier in TIERS if stream(f"{place.retailer_id}/{name}/{tier}").random() <
                                        selection[tier + "_service_probability"]]
                contracts.append({"carrier_id": carrier, "tiers": tiers,
                                  "collection_fee_minor": int(api.population.weighted(stream(place.keys.fee(carrier)), place.fees)),
                                  "home_delta_minor": int(api.population.weighted(stream(place.keys.home(carrier)), place.homes))})
        if about["dispatch"]:
            days = int(api.population.weighted(stream(place.keys.dispatch), place.days))
        return contracts, days

    keys = set()
    if about["contracts"]:
        keys |= {place.keys.count, place.keys.carriers} | {
            key for carrier in place.carriers for key in (place.keys.tier(carrier, "economy"), place.keys.tier(carrier, "express"),
                                                          place.keys.fee(carrier), place.keys.home(carrier))}
    if about["dispatch"]:
        keys.add(place.keys.dispatch)
    return SimpleNamespace(
        keys=keys, **vars(footprint(natural, requirement, api)), reading=reading,
        holds=lambda seed: holds(place.requirement, *reading(seed)),
        recorded=lambda world: tuple(listed(world, place)),
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
