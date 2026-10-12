"""Conditional sampling of a concept's stock and prices, given which models make the shortlist.

A requirement names a concept, a limit and the models that must be exactly the
shortlist of the native shortlist task: every model is ranked by the lowest
price among its available matching offers at any retailer, the cutoff is the
price of the model in the limit's place, and every model at or below the
cutoff is on the list. Naming more models than the limit asks for a tie at the
cutoff; naming fewer asks for a world in which no other model has an available
matching offer.

The block is the cheapest-available block of the same concept (`cheapest.py`):
the stock and the price of every retailer/product pair with a competing offer.
A model's lowest available price is the lowest over its pairs, which draw
independently, and models share no pair, so for a cutoff c the probability is
a product over the other models (above c or without any available offer)
times a small sum over how the named models split into below c and at c.
"""
from collections import Counter
from importlib import import_module
import json
from math import exp, fsum, log
from types import SimpleNamespace

from experiments.world_requirement_construction import model as edits

from . import blocks, cheapest, prices
from .blocks import Step, Unmet, pick, times
from .prices import ZeroMass

VERSION = "steered-shortlist-v1"
# The "cutoff" of a shortlist with fewer models than the limit: every model with an available offer is on it.
EVERY = "every_available_model"


def resolve(requirement):
    required = {"schema", "concept_id", "limit", "product_ids", "predicates"}
    optional = {"availability", "comparison_site_id", "surrounding"}
    if (type(requirement) is not dict or not required <= set(requirement) <= required | optional or
            requirement["schema"] != VERSION or type(requirement["concept_id"]) is not str):
        raise ValueError("Declare a concept, predicates, a limit and the models that make the shortlist")
    limit, models = requirement["limit"], requirement["product_ids"]
    if type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError("The limit is an integer from 1 to 10")
    if (type(models) is not list or not models or len(set(map(str, models))) != len(models) or
            any(type(model) is not str or not model for model in models)):
        raise ValueError("Name the distinct models that make the shortlist")
    cheapest.stated(requirement)
    return json.loads(json.dumps(requirement))


def named(world, requirement, api):
    """The requirement with its names checked against the world, and the cheapest-available scope it is read with."""
    requirement = resolve(requirement)
    concepts = {p["public"]["product_id"]: p["public"]["concept_id"] for p in world["products"]}
    if requirement["concept_id"] not in concepts.values():
        raise ValueError("Unknown concept")
    if any(concepts.get(model) != requirement["concept_id"] for model in requirement["product_ids"]):
        raise ValueError("Every named model is a product of the concept")
    return requirement, cheapest.scope(world, requirement, api)


def reference(world, requirement, api):
    """The native shortlist oracle's reading of a world for the requirement."""
    package = api.basic.__package__
    native, declared = import_module(package + ".catalog_shortlist_task"), cheapest.inventory(package, requirement["concept_id"])
    spec = {"kind": native.KIND, "concept_id": requirement["concept_id"], "predicates": requirement["predicates"],
            "availability": requirement.get("availability", cheapest.PURCHASABLE), "limit": requirement["limit"]}
    surrounding = None
    if "comparison_site_id" in requirement:
        spec["comparison_site_id"] = requirement["comparison_site_id"]
        surrounding = cheapest.listed(world, requirement, package)[1](world)
    task = native.make(world, spec, inventory=declared, surrounding=surrounding)
    return task, native.reference(world, task, inventory=declared, surrounding=surrounding)


def footprint(world, requirement, api):
    """What the block decides: the stock and the price of every listed pair with an offer that competes."""
    _, found = named(world, requirement, api)
    return SimpleNamespace(writes={(kind, *pair) for pair in cheapest.competing(world, None, found)
                                   for kind in ("stock", "price")}, reads=set())


def split(spreads, cutoff):
    """One model's lowest available price against a cutoff: the probabilities of below, at and above it.

    `spreads` are the model's pairs. Above includes no available offer at
    all. Each is a sum over which pair is the first to decide it, so that no
    probability is found by subtraction; the weights of those first pairs are
    returned for sampling.
    """
    over = [spread.mass(cutoff, False) for spread in spreads]
    level = [spread.mass(cutoff, True) for spread in spreads]
    under = [spread.before(cutoff) for spread in spreads]
    not_under = [a + b for a, b in zip(over, level)]
    first_at = [times(*over[:i], level[i], *not_under[i + 1:]) for i in range(len(spreads))]
    first_below = [times(*not_under[:i], under[i]) for i in range(len(spreads))]
    return SimpleNamespace(above=times(*over), at=fsum(first_at), below=fsum(first_below),
                           first_at=first_at, first_below=first_below)


def counts(parts, limit):
    """`ways[k][n]`: the probability that the first k named models are at or below the cutoff, n of them below."""
    ways = [[1.0] + [0.0] * (limit - 1)]
    for part in parts:
        ways.append([times(ways[-1][n], part.at) + (times(ways[-1][n - 1], part.below) if n else 0.0)
                     for n in range(limit)])
    return ways


def model(world, requirement, api):
    """The block and the probability that the named models are exactly the shortlist.

    With at least as many named models as the limit, `log_terms[c]` is the
    logarithm of: every other model above c or without an available offer,
    every named model at or below c, and fewer of them below c than the
    limit. The terms for different cutoffs are disjoint. With fewer named
    models than the limit there is one term: each named model has an
    available offer and no other model has.
    """
    requirement, found = named(world, requirement, api)
    places = cheapest.places(world, found, api)
    config, native_round = world["config"]["retailer_price"], api.native.rounded_price
    spread = {pair: cheapest.Spread(cheapest.outcomes(place, (), config, native_round)) for pair, place in places.items()}
    models = {}
    for pair in places:
        models.setdefault(pair[1], []).append(pair)
    chosen, limit = requirement["product_ids"], requirement["limit"]
    if not set(chosen) <= set(models):
        raise ZeroMass("not_listed", "A named model has no competing offer listed in this world")
    others = sorted(set(models) - set(chosen))
    absent = {pair: found.from_index[-1] for pair, found in spread.items()}
    log_terms, parts = {}, {}
    if len(chosen) < limit:
        # The first pair with an available offer decides that a named model has one.
        some = {name: [times(*(absent[pair] for pair in models[name][:i]), spread[pair].to_index[-1])
                       for i, pair in enumerate(models[name])] for name in chosen}
        masses = [absent[pair] for name in others for pair in models[name]] + [fsum(some[name]) for name in chosen]
        if all(masses):
            log_terms[EVERY], parts[EVERY] = fsum(map(log, masses)), some
    else:
        for cutoff in sorted({price for name in chosen for pair in models[name] for price in spread[pair].prices}):
            above = [spread[pair].mass(cutoff, False) for name in others for pair in models[name]]
            if not all(above):
                continue
            found_parts = {name: split([spread[pair] for pair in models[name]], cutoff) for name in chosen}
            ways = counts([found_parts[name] for name in chosen], limit)
            total = fsum(ways[-1])
            if total:
                log_terms[cutoff] = fsum(map(log, above)) + log(total)
                parts[cutoff] = SimpleNamespace(models=found_parts, ways=ways)
    if not log_terms:
        raise ZeroMass("no_outcome", "No stock and price outcome of the concept gives this shortlist in this world")
    top = max(log_terms.values())
    log_probability = top + log(fsum(exp(value - top) for value in log_terms.values()))
    return SimpleNamespace(requirement=requirement, scope=found, places=places, spread=spread, models=models,
                           others=others, parts=parts, log_terms=log_terms, log_probability=log_probability,
                           probability=exp(log_probability), config=config, native_round=native_round,
                           shares={cutoff: exp(value - log_probability) for cutoff, value in log_terms.items()})


def sample(block, rng):
    """Sample the cutoff and every pair's price and stock draws given the shortlist."""
    order = sorted(block.log_terms, key=str)
    cutoff = cheapest.pick_log(rng, order, [block.log_terms[key] for key in order])
    chosen, allowed = block.requirement["product_ids"], {}
    outcomes = lambda pair, accept: [o for o in block.spread[pair].outcomes if accept(o.rank)]
    nothing, something, anything = (lambda r: r is None), (lambda r: r is not None), (lambda r: True)
    for name in block.others:
        for pair in block.models[name]:
            allowed[pair] = nothing if cutoff == EVERY else (lambda r: r is None or r > cutoff)
    if cutoff == EVERY:
        for name in chosen:
            weights = block.parts[EVERY][name]
            first = pick(rng, range(len(weights)), weights)
            for index, pair in enumerate(block.models[name]):
                allowed[pair] = nothing if index < first else something if index == first else anything
    else:
        part = block.parts[cutoff]
        # How many named models are below the cutoff, then which, from the last named model back.
        below = pick(rng, range(len(part.ways[-1])), part.ways[-1])
        over, under, not_under = (lambda r: r is None or r > cutoff), (lambda r: r is not None and r < cutoff), (
            lambda r: r is None or r >= cutoff)
        for position in reversed(range(len(chosen))):
            name, found = chosen[position], part.models[chosen[position]]
            is_below = pick(rng, [False, True], [
                cheapest.exact(part.ways[position][below], found.at),
                cheapest.exact(part.ways[position][below - 1], found.below) if below else 0])
            below -= is_below
            weights = found.first_below if is_below else found.first_at
            first = pick(rng, range(len(weights)), weights)
            for index, pair in enumerate(block.models[name]):
                if is_below:
                    allowed[pair] = not_under if index < first else under if index == first else anything
                else:
                    allowed[pair] = over if index < first else (lambda r: r == cutoff) if index == first else not_under
    return cutoff, {pair: cheapest.settle(block, pair, outcomes(pair, allowed[pair]), rng) for pair in sorted(block.places)}


def listing(found, requirement, limits):
    """The cutoff when recorded leaves give exactly the named shortlist, else None; the native rule written out."""
    best, _ = cheapest.lowest(found, limits)
    lowest = {}
    for (_, product), price in (best or {}).items():
        lowest[product] = min(lowest.get(product, price), price)
    if not lowest:
        return None
    ordered = sorted(lowest.values())
    cutoff = ordered[min(requirement["limit"], len(ordered)) - 1]
    if {product for product, price in lowest.items() if price <= cutoff} != set(requirement["product_ids"]):
        return None
    return cutoff if len(requirement["product_ids"]) >= requirement["limit"] else EVERY


def check(world, requirement, api):
    """Read the requirement off a world with the native shortlist oracle."""
    requirement = resolve(requirement)
    edits.check_price_rule(world, api.native.rounded_price)
    task, found = reference(world, requirement, api)
    if found["status"] != "match" or {m["product_id"] for m in found["selected_models"]} != set(requirement["product_ids"]):
        raise Unmet("The shortlist is not exactly the named models")
    return {"task": task, "reference": found}


def prepare(natural, requirement, api, rng):
    """Sample the block on the natural world; the step replays it and reads the result."""
    block = model(natural, requirement, api)
    cutoff, draws = sample(block, rng)
    concept_id = block.requirement["concept_id"]

    def record(world):
        if cheapest.recorded(world, concept_id, set(block.places)) != cheapest.planned(block, draws):
            raise blocks.streams.PlanMismatch("The producer recorded other stock or price leaves than planned")
        return {"method": "exact_conditional_shortlist_block", "requirement": block.requirement,
                "natural_world_id": natural["world_id"], "probability_given_upstream": block.probability or None,
                "log_probability_given_upstream": block.log_probability, "cutoff": cutoff,
                "repriced": prices.replayed(natural, world, {pair: found.price for pair, found in draws.items()},
                                            {pair: block.places[pair].price_key for pair in draws}),
                "restocked": cheapest.restocked(natural, block, draws),
                "distribution_claim": "As for the cheapest-available block: for every listed retailer/product pair "
                                      "of the concept with an offer that competes, the price draw, the stock "
                                      "condition at every location and every SKU's stock and supplier draws are "
                                      "sampled from their distribution given the requirement and all upstream "
                                      "draws. None of the seed's own draws of these is kept. Upstream draws are "
                                      "not reweighted; use the probability given upstream as the importance "
                                      "weight across seeds."}

    return Step(script=cheapest.scripts(block, draws), probability=block.probability,
                log_probability=block.log_probability,
                writes={(kind, *pair) for pair in block.places for kind in ("stock", "price")}, reads=set(),
                record=record, check=lambda world: check(world, requirement, api))


def steer(session, natural, natural_opened, requirement, api, rng):
    """Plan on the natural world, regenerate through the real producer, verify."""
    return blocks.steer(session, natural, natural_opened, prepare(natural, requirement, api, rng), api)


def trial(natural, requirement, api):
    """The block's reading under another seed, with the requirement's verdict on it."""
    requirement, found = named(natural, requirement, api)
    places = cheapest.places(natural, found, api)
    reading, keys = cheapest.reader(natural, places, api)
    return SimpleNamespace(
        keys=keys, writes={(kind, *pair) for pair in places for kind in ("stock", "price")}, reads=set(),
        reading=reading, winning=lambda seed: listing(reading(seed), requirement, found),
        holds=lambda seed: listing(reading(seed), requirement, found) is not None,
        recorded=lambda world: cheapest.recorded(world, requirement["concept_id"], set(places)),
        satisfied=lambda world: satisfied(world, requirement, api))


def satisfied(world, requirement, api):
    try:
        return bool(check(world, requirement, api))
    except Unmet:
        return False


def empirical(natural, requirement, api, trials, first_seed):
    """How often the requirement holds under other seeds, by cutoff."""
    winning = trial(natural, requirement, api).winning
    found = (winning(seed) for seed in range(first_seed, first_seed + trials))
    return Counter(cutoff for cutoff in found if cutoff is not None)
