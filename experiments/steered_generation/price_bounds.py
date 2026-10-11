"""Conditional sampling of one offer's listed price, given bounds on it.

A requirement names one retailer and one SKU and bounds the listed price in
minor units. The producer draws one price offset per retailer/product, so the
block is that single draw, sampled from its distribution given that the named
SKU's rounded price falls within the bounds. The producer then reprices the
product's other SKUs at the retailer from the same draw. Stock plays no part:
the producer prices every listed SKU, in or out of stock.
"""
from collections import Counter
import json
from math import fsum
from types import SimpleNamespace

from experiments.world_requirement_construction import model as edits

from . import blocks, prices
from .blocks import Step, Unmet, bound, within

VERSION = "steered-offer-price-v1"


def resolve(requirement):
    if (type(requirement) is not dict or set(requirement) != {"schema", "retailer_id", "sku_id", "price_minor"} or
            requirement["schema"] != VERSION or not bound(requirement["price_minor"]) or
            any(type(requirement[k]) is not str or not requirement[k] for k in ("retailer_id", "sku_id"))):
        raise ValueError("Declare one retailer and SKU with a min, max or both for its price in minor units")
    return json.loads(json.dumps(requirement))


def site(world, requirement, api):
    """Where the offer's price draw sits in a world."""
    requirement = resolve(requirement)
    rid, sid = requirement["retailer_id"], requirement["sku_id"]
    retailer = next((r for r in world["retailers"] if r["retailer_id"] == rid), None)
    if retailer is None or not any(s["sku_id"] == sid for p in world["products"] for s in p["public"]["skus"]):
        raise ValueError("Unknown retailer or SKU")
    offer = next((o for o in retailer["offers"] if o["sku_id"] == sid), None)
    if offer is None:
        raise prices.ZeroMass("not_listed", "The retailer does not list this SKU in this world")
    pair = (rid, offer["product_id"])
    return SimpleNamespace(
        requirement=requirement, pair=pair, sku_id=sid, offer_id=offer["offer_id"],
        reference=offer["price_trace"]["reference_minor"],
        group=[o for o in retailer["offers"] if o["product_id"] == pair[1]],
        key=prices.stream_keys([pair], api)[pair], config=world["config"]["retailer_price"],
        native_round=api.native.rounded_price)


def model(world, requirement, api):
    """The draw's outcomes that put the offer's price within the bounds, grouped by that price."""
    place = site(world, requirement, api)
    by_price = {}
    for atom in prices.atoms([o["price_trace"]["reference_minor"] for o in place.group], place.config):
        price = edits._price(place.reference, prices.representative(atom), place.config, place.native_round)
        if within(place.requirement["price_minor"], price):
            by_price.setdefault(price, []).append(atom)
    if not by_price:
        raise prices.ZeroMass("no_price", "The producer cannot list this offer at a price within the bounds")
    return SimpleNamespace(site=place, by_price=by_price,
                           probability=fsum(atom[0] for found in by_price.values() for atom in found))


def plan(world, requirement, api, rng):
    """Sample the price draw given the bounds; the world's own draw is not consulted."""
    block = model(world, requirement, api)
    options = [atom for price in sorted(block.by_price) for atom in block.by_price[price]]
    atom = rng.choices(options, weights=[a[0] for a in options])[0]
    place = block.site
    return prices.draw_within(atom, place.group, place.config, place.native_round, rng), block


def check(world, requirement, api):
    """Read the requirement off a world: the listed price, the pricing rule and the native oracle's row."""
    place = site(world, requirement, api)
    edits.check_price_rule(world, api.native.rounded_price)
    price = next(o["price_minor"] for o in place.group if o["offer_id"] == place.offer_id)
    concept = next(p["public"]["concept_id"] for p in world["products"]
                   if p["public"]["product_id"] == place.pair[1])
    _, reference = edits._reference(world, {"concept_id": concept}, api)
    # The oracle lists an offer's price only while the offer is available.
    judged = next((row["price_minor"] for row in reference["candidates"] if row["offer_id"] == place.offer_id), price)
    if judged != price or not within(place.requirement["price_minor"], price):
        raise Unmet(f"{place.offer_id} is listed at {price}")
    return {"offer_id": place.offer_id, "price_minor": price}


def prepare(natural, requirement, api, rng):
    """Sample the block on the natural world; the step replays it and reads the result."""
    draw, block = plan(natural, requirement, api, rng)
    place = block.site

    def record(world):
        return {"method": "exact_conditional_price_draw", "requirement": place.requirement,
                "natural_world_id": natural["world_id"], "probability_given_upstream": block.probability,
                "offer_id": place.offer_id,
                "repriced": prices.replayed(natural, world, {place.pair: draw}, {place.pair: place.key}),
                "distribution_claim": "The price draw of this retailer/product pair is sampled from its distribution "
                                      "given the requirement and all upstream draws, under the price model in "
                                      "prices.atoms. Every other draw is the seed's own; the producer reprices the "
                                      "product's other SKUs at this retailer from the sampled draw. Upstream draws "
                                      "are not reweighted; use probability_given_upstream as the importance weight "
                                      "across seeds."}

    return Step(script={place.key: prices.script(draw, place.config)}, probability=block.probability,
                writes={("price", *place.pair)}, reads=set(), record=record,
                check=lambda world: check(world, requirement, api))


def steer(session, natural, natural_opened, requirement, api, rng):
    """Plan on the natural world, regenerate through the real producer, verify."""
    return blocks.steer(session, natural, natural_opened, prepare(natural, requirement, api, rng), api)


def trial(natural, requirement, api):
    """The offer's price from the real `_offer_price` under another seed; independent of `prices.atoms`."""
    place = site(natural, requirement, api)
    products = {p["public"]["product_id"]: p["public"] for p in natural["products"]}
    skus = {s["sku_id"]: s for p in products.values() for s in p["skus"]}
    price = lambda seed, sku_id: api.commerce._offer_price(
        seed, place.pair[0], products[place.pair[1]], skus[sku_id], place.config)[0]
    return SimpleNamespace(
        keys={place.key}, writes={("price", *place.pair)}, reads=set(),
        price=lambda seed: price(seed, place.sku_id),
        holds=lambda seed: within(place.requirement["price_minor"], price(seed, place.sku_id)),
        reading=lambda seed: {o["offer_id"]: price(seed, o["sku_id"]) for o in place.group},
        satisfied=lambda world: satisfied(world, requirement, api),
        recorded=lambda world: {o["offer_id"]: o["price_minor"] for r in world["retailers"]
                                if r["retailer_id"] == place.pair[0] for o in r["offers"]
                                if o["product_id"] == place.pair[1]})


def satisfied(world, requirement, api):
    try:
        return bool(check(world, requirement, api))
    except Unmet:
        return False


def empirical(natural, requirement, api, trials, first_seed):
    """How often the bounds hold under other seeds, by the offer's price."""
    found = trial(natural, requirement, api)
    return Counter(found.price(seed) for seed in range(first_seed, first_seed + trials) if found.holds(seed))
