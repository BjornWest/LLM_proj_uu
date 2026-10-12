"""Conditional sampling of a product's price draws, given who lists it cheapest.

A requirement names a product and the retailers that must be exactly the ones
listing it at the lowest price, where a retailer's price for the product is
the lowest listed price among its SKUs of it, in or out of stock. That is the
price a comparison site shows for the pair, so the comparison can be confined
to the pairs one site lists. Stock plays no part: the block is the price draw
of every compared pair and depends on nothing else, which lets it be combined
with a stock requirement on one of those offers ("the retailer advertised
cheapest has the variant only on supplier order").
"""
from collections import Counter
import json
from math import exp, fsum, log
from types import SimpleNamespace

from experiments.world_requirement_construction import model as edits

from . import blocks, cheapest, prices
from .blocks import Step, Unmet
from .prices import ZeroMass

VERSION = "steered-cheapest-listed-v1"


def resolve(requirement):
    required = {"schema", "product_id", "retailer_ids"}
    if (type(requirement) is not dict or not required <= set(requirement) <= required | {"comparison_site_id", "surrounding"}
            or requirement["schema"] != VERSION):
        raise ValueError("Declare a product, the retailers that list it cheapest and optionally a comparison site")
    # The names and the comparison-site fields are stated as in the cheapest-available requirement.
    cheapest.resolve({**requirement, "schema": cheapest.VERSION, "concept_id": "any"})
    return json.loads(json.dumps(requirement))


def compared(world, requirement, api):
    """The requirement, and the retailer/product pairs whose listed prices are compared."""
    requirement = resolve(requirement)
    products = {p["public"]["product_id"]: p["public"]["concept_id"] for p in world["products"]}
    known = {r["retailer_id"] for r in world["retailers"]}
    if not set(requirement["retailer_ids"]) <= known or requirement["product_id"] not in products:
        raise ValueError("Unknown retailer or product")
    pairs = {(r["retailer_id"], requirement["product_id"]) for r in world["retailers"]
             if any(o["product_id"] == requirement["product_id"] for o in r["offers"])}
    sidecar = None
    if "comparison_site_id" in requirement:
        site, sidecar = cheapest.listed(world, requirement, api.basic.__package__)
        pairs &= site
    return requirement, pairs, sidecar


def footprint(world, requirement, api):
    """What the block decides: the price of every compared pair. It depends on nothing else."""
    _, pairs, _ = compared(world, requirement, api)
    return SimpleNamespace(writes={("price", *pair) for pair in pairs}, reads=set())


def model(world, requirement, api):
    """The compared pairs' price draws and the probability of the requirement in them.

    As `prices.model`, with a pair's price the lowest among all its listed
    SKUs. Products over pairs are kept as logarithms, as in `cheapest.model`.
    """
    requirement, pairs, sidecar = compared(world, requirement, api)
    config, native_round = world["config"]["retailer_price"], api.native.rounded_price
    designated = {(rid, requirement["product_id"]) for rid in requirement["retailer_ids"]}
    if not designated <= pairs:
        raise ZeroMass("not_listed", "A designated retailer's listing of the product is not among those compared")
    groups = {pair: [o for r in world["retailers"] if r["retailer_id"] == pair[0]
                     for o in r["offers"] if o["product_id"] == pair[1]] for pair in sorted(pairs)}
    spread = {pair: prices.distribution({"group": group, "buyable": group}, config, native_round)
              for pair, group in groups.items()}
    log_terms = {}
    for price in sorted(set.intersection(*(set(spread[pair]) for pair in designated))):
        masses = [prices.mass(by_price, (lambda p: p == price) if pair in designated else (lambda p: p > price))
                  for pair, by_price in spread.items()]
        if all(masses):
            log_terms[price] = fsum(map(log, masses))
    if not log_terms:
        raise ZeroMass("no_common_price", "The designated retailers cannot be exactly the cheapest listed in this world")
    top = max(log_terms.values())
    log_probability = top + log(fsum(exp(value - top) for value in log_terms.values()))
    return SimpleNamespace(requirement=requirement, groups=groups, designated=designated, spread=spread,
                           log_terms=log_terms, log_probability=log_probability, probability=exp(log_probability),
                           shares={price: exp(value - log_probability) for price, value in log_terms.items()},
                           config=config, native_round=native_round, sidecar=sidecar)


def sample(block, rng):
    """Sample every compared pair's price draw given the requirement; the world's own draws are not consulted."""
    winning = cheapest.pick_log(rng, sorted(block.log_terms), [block.log_terms[p] for p in sorted(block.log_terms)])
    draws = {}
    for pair, group in block.groups.items():
        accept = (lambda p: p == winning) if pair in block.designated else (lambda p: p > winning)
        options = [atom for price, found in sorted(block.spread[pair].items()) if accept(price) for atom in found]
        atom = blocks.pick(rng, options, [a[0] for a in options])
        draws[pair] = prices.draw_within(atom, group, block.config, block.native_round, rng)
    return winning, draws


def lowest(world, pairs):
    """Each compared pair's lowest listed price, read off a world."""
    found = {}
    for retailer in world["retailers"]:
        for offer in retailer["offers"]:
            pair = (retailer["retailer_id"], offer["product_id"])
            if pair in pairs:
                found[pair] = min(found.get(pair, offer["price_minor"]), offer["price_minor"])
    return found


def check(world, requirement, api):
    """Read the requirement off a world: the listed prices themselves, and the comparison site's own rows."""
    requirement, pairs, sidecar = compared(world, requirement, api)
    edits.check_price_rule(world, api.native.rounded_price)
    found = lowest(world, pairs)
    designated = {(rid, requirement["product_id"]) for rid in requirement["retailer_ids"]}
    # No compared pair at all (a comparison site that lists none of them) is unmet, not an error.
    minimum = min(found.values(), default=None)
    if {pair for pair, price in found.items() if price == minimum} != designated:
        raise Unmet("The retailers listing the product cheapest are not exactly the designated ones")
    observed = {"minimum_listed_price_minor": minimum, "retailer_ids": sorted(rid for rid, _ in designated)}
    if sidecar is not None:
        site = next(s for s in sidecar(world)["sites"] if s["site_id"] == requirement["comparison_site_id"])
        rows = [row for row in site["listings"] if row["product_id"] == requirement["product_id"]]
        shown = min(row["price_minor"] for row in rows)
        if shown != minimum or {row["retailer_id"] for row in rows if row["price_minor"] == shown} != {
                rid for rid, _ in designated}:
            raise Unmet("The comparison site's rows do not show the designated retailers cheapest")
        observed.update(comparison_site_id=site["site_id"], comparison_rows=len(rows))
    return observed


def prepare(natural, requirement, api, rng):
    """Sample the block on the natural world; the step replays it and reads the result."""
    block = model(natural, requirement, api)
    winning, draws = sample(block, rng)
    keys = prices.stream_keys(draws, api)

    def record(world):
        return {"method": "exact_conditional_listed_price_block", "requirement": block.requirement,
                "natural_world_id": natural["world_id"], "probability_given_upstream": block.probability or None,
                "log_probability_given_upstream": block.log_probability, "winning_price_minor": winning,
                "repriced": prices.replayed(natural, world, draws, keys),
                "distribution_claim": "The price draw of every compared retailer/product pair is sampled from its "
                                      "distribution given the requirement, under the price model in prices.atoms. "
                                      "The requirement depends on no other draw; every other draw is the seed's "
                                      "own. Use the probability as the importance weight across seeds."}

    return Step(script={keys[pair]: prices.script(draw, block.config) for pair, draw in draws.items()},
                probability=block.probability, log_probability=block.log_probability,
                **vars(footprint(natural, requirement, api)), record=record,
                check=lambda world: check(world, requirement, api))


def steer(session, natural, natural_opened, requirement, api, rng):
    """Plan on the natural world, regenerate through the real producer, verify."""
    return blocks.steer(session, natural, natural_opened, prepare(natural, requirement, api, rng), api)


def trial(natural, requirement, api):
    """The compared pairs' prices from the real `_offer_price` under another seed; independent of `prices.atoms`."""
    requirement, pairs, _ = compared(natural, requirement, api)
    config = natural["config"]["retailer_price"]
    products = {p["public"]["product_id"]: p["public"] for p in natural["products"]}
    skus = {s["sku_id"]: s for p in products.values() for s in p["skus"]}
    offers = [(r["retailer_id"], o) for r in natural["retailers"] for o in r["offers"]
              if (r["retailer_id"], o["product_id"]) in pairs]
    designated = {(rid, requirement["product_id"]) for rid in requirement["retailer_ids"]}
    reading = lambda seed: {o["offer_id"]: api.commerce._offer_price(
        seed, rid, products[o["product_id"]], skus[o["sku_id"]], config)[0] for rid, o in offers}

    def winning(seed):
        found, low = reading(seed), {}
        for rid, offer in offers:
            pair = (rid, offer["product_id"])
            low[pair] = min(low.get(pair, found[offer["offer_id"]]), found[offer["offer_id"]])
        minimum = min(low.values()) if low else None
        return minimum if low and {pair for pair, price in low.items() if price == minimum} == designated else None

    return SimpleNamespace(
        keys=set(prices.stream_keys(pairs, api).values()), **vars(footprint(natural, requirement, api)),
        reading=reading, winning=winning, holds=lambda seed: winning(seed) is not None,
        recorded=lambda world: {o["offer_id"]: o["price_minor"] for r in world["retailers"] for o in r["offers"]
                                if (r["retailer_id"], o["product_id"]) in pairs},
        satisfied=lambda world: satisfied(world, requirement, api))


def satisfied(world, requirement, api):
    try:
        return bool(check(world, requirement, api))
    except Unmet:
        return False


def empirical(natural, requirement, api, trials, first_seed):
    """How often the requirement holds under other seeds, by winning price."""
    winning = trial(natural, requirement, api).winning
    found = (winning(seed) for seed in range(first_seed, first_seed + trials))
    return Counter(price for price in found if price is not None)
