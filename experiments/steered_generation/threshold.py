"""Conditional sampling of a retailer's free-shipping threshold against one basket's subtotal.

A requirement names a retailer, a SKU and a quantity, and states how the
merchandise subtotal (listed price times quantity) stands to the retailer's
advertised free-shipping threshold, in the words of the native shipping-claim
task: `no_threshold`, `meets_threshold` or `below_threshold`. It can bound the
gap between the two, for a basket that just misses or just reaches the
threshold.

The producer draws, per retailer, whether a threshold is offered and, if so,
its value from a short list; and per retailer/product the price. Those are the
block: two threshold draws, and the price draw unless the requirement is that
no threshold is offered. Nothing else is read.
"""
from collections import Counter
import json
from math import fsum
from types import SimpleNamespace

from experiments.world_requirement_construction import model as edits

from . import blocks, prices
from .blocks import Step, Unmet, bound, pick, times, within
from .prices import UNMATCHED, ZeroMass

VERSION = "steered-free-shipping-v1"
TESTS = ("no_threshold", "meets_threshold", "below_threshold")
PROFILES = {"small": "local_shop", "medium": "regional_chain", "large": "major_retailer"}


def resolve(requirement):
    required = {"schema", "retailer_id", "sku_id", "quantity", "subtotal_test"}
    if (type(requirement) is not dict or not required <= set(requirement) <= required | {"gap_minor"} or
            requirement["schema"] != VERSION or requirement["subtotal_test"] not in TESTS or
            any(type(requirement[key]) is not str or not requirement[key] for key in ("retailer_id", "sku_id")) or
            type(requirement["quantity"]) is not int or requirement["quantity"] < 1):
        raise ValueError("Declare a retailer, a SKU, a quantity and one of " + ", ".join(TESTS))
    if "gap_minor" in requirement and (not bound(requirement["gap_minor"]) or requirement["subtotal_test"] == TESTS[0]):
        raise ValueError("A gap is a non-negative min, max or both, between a subtotal and a threshold that is offered")
    return json.loads(json.dumps(requirement))


def footprint(world, requirement, api):
    """What the block decides: the retailer's threshold, and the price of the product there unless none is offered."""
    requirement = resolve(requirement)
    _, retailer, product = blocks.offer_resource("price", world, requirement)
    writes = {("threshold", retailer, "")}
    return SimpleNamespace(writes=writes if requirement["subtotal_test"] == TESTS[0] else
                           writes | {("price", retailer, product)}, reads=set())


def site(world, requirement, api):
    """Where the retailer's threshold draws and the offer's price draw sit in a world."""
    requirement = resolve(requirement)
    blocks.offer_resource("price", world, requirement)
    retailer = next(r for r in world["retailers"] if r["retailer_id"] == requirement["retailer_id"])
    offer = next((o for o in retailer["offers"] if o["sku_id"] == requirement["sku_id"]), None)
    if offer is None:
        raise ZeroMass("not_listed", "The retailer does not list this SKU in this world")
    policy = world["shipping_policy"]["free_shipping_threshold"]
    pair, base = (retailer["retailer_id"], offer["product_id"]), api.commerce.VERSION + "/" + retailer["retailer_id"]
    return SimpleNamespace(
        requirement=requirement, pair=pair, offer_id=offer["offer_id"], reference=offer["price_trace"]["reference_minor"],
        group=[o for o in retailer["offers"] if o["product_id"] == pair[1]],
        offered=min(1, max(0, policy["enabled_probability_by_profile"][PROFILES[retailer["scale"]]])),
        values=list(policy["threshold_minor_values_equal_weight"]),
        keys={"enabled": base + "/free-threshold-enabled", "value": base + "/free-threshold-value",
              "price": prices.stream_keys([pair], api)[pair]},
        config=world["config"]["retailer_price"], native_round=api.native.rounded_price)


def holds(requirement, threshold, price):
    """The native rule: no threshold; or the subtotal at or above it; or below it. With the stated gap."""
    subtotal = price * requirement["quantity"]
    test = TESTS[0] if threshold is None else TESTS[1] if subtotal >= threshold else TESTS[2]
    return test == requirement["subtotal_test"] and (
        threshold is None or within(requirement.get("gap_minor", {}), abs(subtotal - threshold)))


def model(world, requirement, api):
    """The block's outcomes that satisfy the requirement, and their probability.

    `outcomes` are (mass, threshold value or None, price atom or None). The
    threshold's value is one of an equally weighted list, drawn only when a
    threshold is offered.
    """
    place = site(world, requirement, api)
    requirement = place.requirement
    if requirement["subtotal_test"] == TESTS[0]:
        outcomes = [(1 - place.offered, None, None)]
    else:
        outcomes = []
        for atom in prices.atoms([o["price_trace"]["reference_minor"] for o in place.group], place.config):
            price = edits._price(place.reference, prices.representative(atom), place.config, place.native_round)
            outcomes += [(times(place.offered, 1 / len(place.values), place.values.count(value), atom[0]), value, atom)
                         for value in sorted(set(place.values)) if holds(requirement, value, price)]
    outcomes = [found for found in outcomes if found[0] > 0]
    if not outcomes:
        raise ZeroMass("no_outcome", "No threshold and price of this offer satisfy the requirement in this world")
    return SimpleNamespace(site=place, outcomes=outcomes, probability=fsum(found[0] for found in outcomes))


def listed(world, place):
    """What a world records: the retailer's threshold and the offer's price."""
    retailer = next(r for r in world["retailers"] if r["retailer_id"] == place.pair[0])
    return (retailer["free_shipping_threshold_minor"],
            next(o["price_minor"] for o in retailer["offers"] if o["offer_id"] == place.offer_id))


def check(world, requirement, api):
    """Read the requirement off a world: the recorded threshold and price by the native rule."""
    place = site(world, requirement, api)
    edits.check_price_rule(world, api.native.rounded_price)
    threshold, price = listed(world, place)
    if not holds(place.requirement, threshold, price):
        raise Unmet(f"{place.offer_id}: subtotal {price * place.requirement['quantity']} against threshold {threshold}")
    subtotal = price * place.requirement["quantity"]
    return {"offer_id": place.offer_id, "unit_price_minor": price, "subtotal_minor": subtotal,
            "advertised_threshold_minor": threshold, "subtotal_test": place.requirement["subtotal_test"]}


def prepare(natural, requirement, api, rng):
    """Sample the block on the natural world; the step replays it and reads the result."""
    block = model(natural, requirement, api)
    place = block.site
    _, value, atom = pick(rng, block.outcomes, [found[0] for found in block.outcomes])
    script = {place.keys["enabled"]: [("random", UNMATCHED if value is None else 0.0)]}
    draw = None
    if value is not None:
        script[place.keys["value"]] = [("choice", value)]
        draw = prices.draw_within(atom, place.group, place.config, place.native_round, rng)
        script[place.keys["price"]] = prices.script(draw, place.config)

    def record(world):
        if listed(world, place)[0] != value:
            raise blocks.streams.PlanMismatch(f"{place.pair[0]}: producer recorded another threshold than planned")
        return {"method": "exact_conditional_threshold_and_price_draws", "requirement": place.requirement,
                "natural_world_id": natural["world_id"], "probability_given_upstream": block.probability,
                "offer_id": place.offer_id, "natural_threshold_minor": listed(natural, place)[0],
                "steered_threshold_minor": value,
                "repriced": prices.replayed(natural, world, {place.pair: draw}, {place.pair: place.keys["price"]})
                if draw is not None else [],
                "distribution_claim": "Whether this retailer offers a free-shipping threshold, its value and, "
                                      "unless the requirement is that none is offered, the price draw of this "
                                      "retailer/product pair are sampled from their distribution given the "
                                      "requirement. Every other draw is the seed's own; the requirement depends "
                                      "on no other draw. Use the probability as the importance weight across "
                                      "seeds."}

    return Step(script=script, probability=block.probability, **vars(footprint(natural, requirement, api)),
                record=record, check=lambda world: check(world, requirement, api))


def steer(session, natural, natural_opened, requirement, api, rng):
    """Plan on the natural world, regenerate through the real producer, verify."""
    return blocks.steer(session, natural, natural_opened, prepare(natural, requirement, api, rng), api)


def trial(natural, requirement, api):
    """The threshold and the price from the producer's own draws under another seed; independent of the model."""
    place = site(natural, requirement, api)
    products = {p["public"]["product_id"]: p["public"] for p in natural["products"]}
    skus = {s["sku_id"]: s for p in products.values() for s in p["skus"]}
    sku_id = place.requirement["sku_id"]
    policy = natural["shipping_policy"]["free_shipping_threshold"]

    def reading(seed):
        stream = lambda key: api.population.stream(seed, key)
        offered = stream(place.keys["enabled"]).random() < policy["enabled_probability_by_profile"][
            PROFILES[next(r["scale"] for r in natural["retailers"] if r["retailer_id"] == place.pair[0])]]
        threshold = stream(place.keys["value"]).choice(policy["threshold_minor_values_equal_weight"]) if offered else None
        return threshold, api.commerce._offer_price(seed, place.pair[0], products[place.pair[1]], skus[sku_id],
                                                    place.config)[0]

    # What a real pass with these streams reseeded must record: the threshold, and the price when it is in the block.
    compared = lambda seed: reading(seed)[:len(keys) - 1]

    # Without a threshold the price is no part of the block, so its stream is not redrawn either.
    keys = {place.keys["enabled"], place.keys["value"]} | (
        set() if place.requirement["subtotal_test"] == TESTS[0] else {place.keys["price"]})
    return SimpleNamespace(
        keys=keys, **vars(footprint(natural, requirement, api)), reading=compared, drawn=reading,
        holds=lambda seed: holds(place.requirement, *reading(seed)) if len(keys) == 3 else reading(seed)[0] is None,
        recorded=lambda world: listed(world, place)[:len(keys) - 1],
        satisfied=lambda world: satisfied(world, requirement, api))


def satisfied(world, requirement, api):
    try:
        return bool(check(world, requirement, api))
    except Unmet:
        return False


def empirical(natural, requirement, api, trials, first_seed):
    """How often the requirement holds under other seeds, by (threshold, price)."""
    found, stated = trial(natural, requirement, api), resolve(requirement)
    seen = (found.drawn(seed) for seed in range(first_seed, first_seed + trials))
    return Counter(row for row in seen if holds(stated, *row))
