"""Conditional sampling of one offer's stock, given basic requirements on it.

A requirement names one retailer and one SKU and states its availability
(in the native oracle's words: in_stock, backorder, unavailable), bounds on the
quantity held at named locations, or both.

For one SKU at one retailer the producer draws, per stock location, a stock
condition (shared by every SKU of the product there), whether the SKU is at
zero, and otherwise a quantity; then, if nothing can be dispatched and the
retailer orders from suppliers, whether this SKU is eligible. Locations draw
independently, so the probability of a requirement is a short chain over the
locations, and the draws can be sampled from their distribution given the
requirement without a rejection loop. The planned draws are fed to the real
producer, which also rebuilds what depends on them: the sibling SKUs' stock
under the new conditions, supplier eligibility and the catalog pages.
"""
import json
from math import fsum
from types import SimpleNamespace

from experiments.world_requirement_construction import model as edits

from . import streams
from . import blocks
from .blocks import Step, Unmet, bound, within
from .prices import UNMATCHED, ZeroMass

VERSION = "steered-offer-stock-v1"
AVAILABILITY = ("in_stock", "backorder", "unavailable")
# What the locations seen so far hold of the SKU.
NOWHERE, NOT_SHIPPABLE, DISPATCH = 0, 1, 2


def resolve(requirement):
    required, optional = {"schema", "retailer_id", "sku_id"}, {"availability", "stock"}
    if (type(requirement) is not dict or not required <= set(requirement) <= required | optional or
            not optional & set(requirement) or requirement["schema"] != VERSION or
            any(type(requirement[k]) is not str or not requirement[k] for k in ("retailer_id", "sku_id"))):
        raise ValueError("Declare one retailer and SKU with an availability, stock bounds or both")
    if "availability" in requirement and requirement["availability"] not in AVAILABILITY:
        raise ValueError("Availability is one of " + ", ".join(AVAILABILITY))
    if "stock" in requirement:
        bounds = requirement["stock"]
        if type(bounds) is not dict or not bounds or any(type(source) is not str for source in bounds):
            raise ValueError("Stock bounds are given per source location")
        if not all(map(bound, bounds.values())):
            raise ValueError("A stock bound is a non-negative min, max or both")
    return json.loads(json.dumps(requirement))


def availability(state, supplier):
    """The native oracle's priority: dispatch, supplier order, then other stock."""
    return ("in_stock" if state == DISPATCH else "backorder" if supplier
            else "in_stock" if state == NOT_SHIPPABLE else "unavailable")


def after(state, stocked, shipping):
    return state if not stocked else DISPATCH if shipping else max(state, NOT_SHIPPABLE)


def atoms(probabilities, zero_probability, quantity_ranges):
    """The outcomes of one location's draws for one SKU, with their probabilities.

    Returns (mass, condition, quantity); quantity None is the zero draw.
    """
    total, result = fsum(probabilities.values()), []
    for condition, weight in probabilities.items():
        empty = min(1, max(0, zero_probability[condition]))
        low, high = quantity_ranges[condition]
        result.append((weight / total * empty, condition, None))
        result += [(weight / total * (1 - empty) / (high - low + 1), condition, quantity)
                   for quantity in range(low, high + 1)]
    return [atom for atom in result if atom[0] > 0]


def amount(atom):
    return atom[2] or 0


def site(world, requirement, api):
    """Where the offer's stock draws sit in a world, and everything upstream of them."""
    requirement = resolve(requirement)
    rid, sid = requirement["retailer_id"], requirement["sku_id"]
    retailer = next((r for r in world["retailers"] if r["retailer_id"] == rid), None)
    products = {s["sku_id"]: p["public"] for p in world["products"] for s in p["public"]["skus"]}
    if retailer is None or sid not in products:
        raise ValueError("Unknown retailer or SKU")
    offer = next((o for o in retailer["offers"] if o["sku_id"] == sid), None)
    if offer is None:
        raise ZeroMass("not_listed", "The retailer does not list this SKU in this world")
    pid, config = offer["product_id"], world["config"]
    rows = {row["source_id"]: row for row in retailer["conditions"] if row["product_id"] == pid}
    bounds = requirement.get("stock", {})
    if set(bounds) - set(rows):
        raise ZeroMass("no_such_source", "The retailer has no such stock location in this world")
    ranges = config["stock"]["quantity_ranges"][retailer["scale"]]
    base = api.commerce.VERSION + "/" + rid + "/"
    sources = []
    for source in retailer["source_locations"]:
        name = source["source_id"]
        allowed = [atom for atom in atoms(rows[name]["probabilities"], config["stock"]["zero_probability"], ranges)
                   if within(bounds.get(name, {}), amount(atom))]
        sources.append(SimpleNamespace(
            source_id=name, shipping=source["shipping_enabled"],
            atoms={False: [a for a in allowed if not amount(a)], True: [a for a in allowed if amount(a)]},
            keys={"condition": base + pid + "/" + name + "/condition", "zero": base + sid + "/" + name + "/zero",
                  "quantity": base + sid + "/" + name + "/quantity"}))
    return SimpleNamespace(
        requirement=requirement, retailer_id=rid, sku_id=sid, product_id=pid, offer_id=offer["offer_id"],
        concept_id=products[sid]["concept_id"], sources=sources, supplier_enabled=retailer["supplier_enabled"],
        eligible=min(1, max(0, config["supplier"]["sku_eligible_probability"])),
        supplier_key=base + sid + "/supplier-eligible", config=config, scale=retailer["scale"],
        probabilities={name: row["probabilities"] for name, row in rows.items()})


def model(world, requirement, api):
    """The offer's stock block and the probability of the requirement in it.

    `forward[i][state]` is the probability that the first i locations satisfy
    their bounds and leave the SKU in `state`. `outcomes` maps each way the
    block can end, (state, supplier eligible), to its probability, keeping
    only the ends that give the required availability; their sum is the
    probability of the requirement given everything upstream of this offer's
    stock draws.
    """
    place = site(world, requirement, api)
    forward = [{NOWHERE: 1.0, NOT_SHIPPABLE: 0.0, DISPATCH: 0.0}]
    for source in place.sources:
        following = dict.fromkeys(forward[-1], 0.0)
        for state, mass in forward[-1].items():
            for stocked, found in source.atoms.items():
                following[after(state, stocked, source.shipping)] += mass * fsum(a[0] for a in found)
        forward.append(following)
    # The producer draws eligibility only when nothing can be dispatched.
    eligible = place.eligible if place.supplier_enabled else 0
    ends = {(DISPATCH, False): forward[-1][DISPATCH]}
    for state in (NOWHERE, NOT_SHIPPABLE):
        ends[(state, True)] = forward[-1][state] * eligible
        ends[(state, False)] = forward[-1][state] * (1 - eligible)
    wanted = place.requirement.get("availability")
    outcomes = {end: mass for end, mass in ends.items()
                if mass > 0 and wanted in (None, availability(*end))}
    if not outcomes:
        if wanted == "backorder" and not place.supplier_enabled:
            raise ZeroMass("supplier_disabled", "The retailer takes no supplier orders in this world")
        raise ZeroMass("no_outcome", "No stock outcome of this offer satisfies the requirement in this world")
    return SimpleNamespace(site=place, forward=forward, outcomes=outcomes, probability=fsum(outcomes.values()))


def plan(world, requirement, api, rng):
    """Sample the offer's stock draws given the requirement.

    Returns the draws of the whole block (a condition and a quantity per
    location, None for the zero draw, and supplier eligibility) and the block
    model. The world's own draws are not consulted, so repeated plans for one
    world are independent samples of the same conditional distribution.
    """
    block = model(world, requirement, api)
    ends = sorted(block.outcomes)
    state, supplier = rng.choices(ends, weights=[block.outcomes[end] for end in ends])[0]
    draws = SimpleNamespace(state=state, supplier=supplier, conditions={}, quantities={})
    for index in reversed(range(len(block.site.sources))):
        source = block.site.sources[index]
        steps = [(previous, stocked) for previous in block.forward[index] for stocked in (False, True)
                 if after(previous, stocked, source.shipping) == state]
        previous, stocked = rng.choices(steps, weights=[
            block.forward[index][p] * fsum(a[0] for a in source.atoms[s]) for p, s in steps])[0]
        found = source.atoms[stocked]
        _, draws.conditions[source.source_id], draws.quantities[source.source_id] = rng.choices(
            found, weights=[a[0] for a in found])[0]
        state = previous
    return draws, block


def scripts(place, draws):
    """The stream results that make the producer's stock lines record `draws`."""
    result = {}
    for source in place.sources:
        quantity = draws.quantities[source.source_id]
        result[source.keys["condition"]] = [("choices", draws.conditions[source.source_id])]
        result[source.keys["zero"]] = [("random", 0.0 if quantity is None else UNMATCHED)]
        if quantity is not None:
            result[source.keys["quantity"]] = [("randint", quantity)]
    if place.supplier_enabled and draws.state != DISPATCH:
        result[place.supplier_key] = [("random", 0.0 if draws.supplier else UNMATCHED)]
    return result


def recorded(world, place):
    """What a world records for the offer: conditions, quantities held, supplier order."""
    retailer = next(r for r in world["retailers"] if r["retailer_id"] == place.retailer_id)
    offer = next(o for o in retailer["offers"] if o["offer_id"] == place.offer_id)
    conditions = {row["source_id"]: row["condition"] for row in retailer["conditions"]
                  if row["product_id"] == place.product_id}
    return {"conditions": conditions, "stock_by_source": dict(offer["stock_by_source"]),
            "supplier_order": offer["supplier_order"]["enabled"]}


def planned(draws):
    return {"conditions": dict(draws.conditions),
            "stock_by_source": {name: quantity or 0 for name, quantity in draws.quantities.items()},
            "supplier_order": draws.supplier}


def check(world, requirement, api):
    """Read the requirement off a world: recorded quantities and the native oracle's availability."""
    place = site(world, requirement, api)
    found = recorded(world, place)
    for source, limits in place.requirement.get("stock", {}).items():
        if not within(limits, found["stock_by_source"][source]):
            raise Unmet(f"{source} holds {found['stock_by_source'][source]}")
    _, reference = edits._reference(world, {"concept_id": place.concept_id}, api)
    judged = next((row["availability"] for row in reference["candidates"] if row["offer_id"] == place.offer_id),
                  "unavailable" if place.offer_id in reference["unavailable_offer_ids"] else None)
    if judged is None:
        raise Unmet("The native oracle does not see the offer")
    if place.requirement.get("availability", judged) != judged:
        raise Unmet("The native oracle judges the offer " + judged)
    return {**found, "availability": judged}


def dependants(natural, world, place):
    """What the producer rebuilt around the offer: sibling offers and catalog pages that differ."""
    def rows(source):
        retailer = next(r for r in source["retailers"] if r["retailer_id"] == place.retailer_id)
        offers = {o["offer_id"]: (o["stock_by_source"], o["supplier_order"]) for o in retailer["offers"]
                  if o["product_id"] == place.product_id and o["offer_id"] != place.offer_id}
        pages = [page for entry in retailer["catalog"] if entry["product_id"] == place.product_id
                 for page in entry["pages"]]
        return offers, pages
    (before, pages_before), (now, pages_now) = rows(natural), rows(world)
    return {"sibling_offers": len(now),
            "sibling_offers_with_other_stock": sum(before[k][0] != now[k][0] for k in now),
            "sibling_offers_with_other_supplier_order": sum(before[k][1] != now[k][1] for k in now),
            "catalog_pages": len(pages_now),
            "catalog_pages_changed": sum(a != b for a, b in zip(pages_before, pages_now))}


def prepare(natural, requirement, api, rng):
    """Sample the block on the natural world; the step replays it and reads the result."""
    draws, block = plan(natural, requirement, api, rng)
    place = block.site

    def record(world):
        if recorded(world, place) != planned(draws):
            raise streams.PlanMismatch(f"{place.offer_id}: producer recorded {recorded(world, place)}, "
                                       f"plan was {planned(draws)}")
        return {"method": "exact_conditional_stock_block", "requirement": place.requirement,
                "natural_world_id": natural["world_id"], "probability_given_upstream": block.probability,
                "offer_id": place.offer_id, "natural": recorded(natural, place), "steered": planned(draws),
                "rebuilt_by_the_producer": dependants(natural, world, place),
                "distribution_claim": "This offer's stock draws (a condition and a quantity per location, and supplier "
                                      "eligibility) are sampled from their distribution given the requirement and "
                                      "all upstream draws, under the model in stock.atoms and stock.model. Every "
                                      "other draw is the seed's own; the product's other SKUs at this retailer are "
                                      "re-evaluated by the producer under the sampled conditions. Upstream draws "
                                      "are not reweighted; use probability_given_upstream as the importance weight "
                                      "across seeds."}

    # The conditions are shared, so the block decides the stock of every SKU of the product here.
    return Step(script=scripts(place, draws), probability=block.probability,
                writes={("stock", place.retailer_id, place.product_id)}, reads=set(), record=record,
                check=lambda world: {**check(world, requirement, api), "offer_id": place.offer_id})


def steer(session, natural, natural_opened, requirement, api, rng):
    """Plan on the natural world, regenerate through the real producer, verify."""
    return blocks.steer(session, natural, natural_opened, prepare(natural, requirement, api, rng), api)


def natural_draws(place, api, seed):
    """This module's reading of the producer's stock lines, drawn under another seed.

    Uses the producer's own stream and weighted-choice functions. `blocks.redraw`
    checks it against the real producer draw for draw; it is then cheap enough
    to estimate frequencies from.
    """
    stream = lambda key: api.population.stream(seed, key)
    stock = place.config["stock"]
    conditions, held = {}, {}
    for source in place.sources:
        name = source.source_id
        conditions[name] = api.population.weighted(stream(source.keys["condition"]), place.probabilities[name])
        zero = stream(source.keys["zero"]).random() < stock["zero_probability"][conditions[name]]
        held[name] = 0 if zero else stream(source.keys["quantity"]).randint(
            *stock["quantity_ranges"][place.scale][conditions[name]])
    on_hand = any(source.shipping and held[source.source_id] > 0 for source in place.sources)
    supplier = (place.supplier_enabled and not on_hand and
                stream(place.supplier_key).random() < place.config["supplier"]["sku_eligible_probability"])
    return {"conditions": conditions, "stock_by_source": held, "supplier_order": supplier}


def end(place, found):
    """The (state, supplier) end of the block that a set of recorded draws reaches."""
    state = NOWHERE
    for source in place.sources:
        state = after(state, found["stock_by_source"][source.source_id] > 0, source.shipping)
    return state, found["supplier_order"]


def judged(place, found):
    """Availability of recorded draws by the native oracle's rule, written out separately from the block model."""
    held = found["stock_by_source"]
    if any(held[source.source_id] > 0 and source.shipping for source in place.sources):
        return "in_stock"
    return "backorder" if found["supplier_order"] else "in_stock" if any(held.values()) else "unavailable"


def holds(place, found):
    """Whether recorded draws satisfy the requirement, without the block model's atoms."""
    return (all(within(limits, found["stock_by_source"][name])
                for name, limits in place.requirement.get("stock", {}).items()) and
            place.requirement.get("availability") in (None, judged(place, found)))


def empirical(natural, requirement, api, trials, first_seed):
    """How often the requirement holds under other seeds' draws, and how the block then ends."""
    place = site(natural, requirement, api)
    ends = {}
    for seed in range(first_seed, first_seed + trials):
        found = natural_draws(place, api, seed)
        if holds(place, found):
            ends[end(place, found)] = ends.get(end(place, found), 0) + 1
    return ends


def block_keys(place):
    return {key for source in place.sources for key in source.keys.values()} | {place.supplier_key}


def trial(natural, requirement, api):
    """This module's reading of the block under another seed, and the same leaves read off a world."""
    place = site(natural, requirement, api)
    return SimpleNamespace(keys=block_keys(place), writes={("stock", place.retailer_id, place.product_id)},
                           reads=set(),
                           reading=lambda seed: natural_draws(place, api, seed),
                           holds=lambda seed: holds(place, natural_draws(place, api, seed)),
                           recorded=lambda world: recorded(world, place),
                           satisfied=lambda world: satisfied(world, requirement, api))


def satisfied(world, requirement, api):
    try:
        return bool(check(world, requirement, api))
    except Unmet:
        return False
