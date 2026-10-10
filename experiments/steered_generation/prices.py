"""Conditional sampling of the price draws, given a requirement on who is cheapest.

Given everything upstream of prices (products, assortment, stock), the producer
draws one price per retailer/product, independently of every other pair. Each
draw has a small exact distribution over rounded prices, so the probability of
"exactly these retailers are cheapest" is a finite sum, and the price draws can
be sampled from their distribution given that outcome without any rejection
loop. The planned draws are then fed to the real producer; this module never
writes a price itself.
"""
from collections import Counter
from math import ceil, floor, fsum, prod
from statistics import NormalDist
from types import SimpleNamespace

from experiments.world_requirement_construction import model as edits

from .streams import PlanMismatch

# A `random()` result that is never below a match probability smaller than 1.
UNMATCHED = 1 - 2 ** -53
STATUS = "steered_conditional_sample"


class ZeroMass(ValueError):
    """The requirement has probability zero given this world's upstream draws.

    `reason` is a stable code. Other upstream draws may still allow it.
    """

    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason


def atoms(references, config):
    """The outcomes of one retailer/product price draw, with their probabilities.

    Returns (mass, kind, left, right): the matched reference draw, the clamp
    endpoints, and the intervals between neighbouring rounding flips of any
    SKU, inside which every SKU's rounded price is constant. Masses are those
    of the producer's normal draw treated as continuous. Two things are left
    out, both far below one part in a billion: the float plateaus some 1e-16
    wide at each flip, where ties-to-even can give a price of its own, and
    intervals so narrow that their midpoint is itself such a knife-edge.
    """
    lo, hi = config["offset_min"], config["offset_max"]
    if not -1 < lo <= hi:
        raise ValueError("Unsupported native offset bounds")
    matched = min(1, max(0, config["reference_match_probability"]))
    result = [(matched, "matched", 0, 0)]
    spread = config["offset_standard_deviation"]
    if matched < 1 and spread == 0:
        clamped = max(lo, min(hi, 0.0))
        result.append((1 - matched, "point", clamped, clamped))
    elif matched < 1:
        below = NormalDist(0, spread).cdf
        flips = set()
        for reference in set(references):
            step = edits._step(reference, config)
            first, last = ceil(lo * reference / step - .5), floor(hi * reference / step - .5)
            if last - first > edits.SEARCH_LIMIT:
                raise ZeroMass("operator_limit", "Native price grid exceeds this sampler's bounded search")
            flips.update((k + .5) * step / reference for k in range(first, last + 1))
        edges = [lo] + sorted(flip for flip in flips if lo < flip < hi) + [hi]
        if lo == hi:
            # Coincident bounds: every unmatched draw records the lower bound.
            result.append((1 - matched, "point", lo, lo))
        else:
            result.append(((1 - matched) * below(lo), "point", lo, lo))
            result.append(((1 - matched) * below(-hi), "point", hi, hi))
        result += [((1 - matched) * (below(right) - below(left)), "interval", left, right)
                   for left, right in zip(edges, edges[1:])
                   if left < right and not edits.knife_edge(references, (left + right) / 2, config)]
    return [atom for atom in result if atom[0] > 0]


def representative(atom):
    _, kind, left, right = atom
    return (True, 0) if kind == "matched" else (False, left if kind == "point" else (left + right) / 2)


def draw_within(atom, group, config, native_round, rng):
    """A draw from the producer's distribution restricted to one atom."""
    _, kind, left, right = atom
    middle = representative(atom)
    if kind != "interval":
        return middle
    normal = NormalDist(0, config["offset_standard_deviation"])
    low, high = normal.cdf(left), normal.cdf(right)
    quantile = low + rng.random() * (high - low)
    if not 0 < quantile < 1:
        return middle
    draw = (False, normal.inv_cdf(quantile))
    # Float error next to a flip must not move a SKU into the neighbouring price.
    same = left < draw[1] < right and all(
        edits._price(o["price_trace"]["reference_minor"], draw, config, native_round) ==
        edits._price(o["price_trace"]["reference_minor"], middle, config, native_round) for o in group)
    return draw if same else middle


def script(draw, config):
    """The stream results that make the producer's `_offer_price` record `draw`."""
    if draw[0]:
        return [("random", 0.0)]
    raw = 0.0 if config["offset_standard_deviation"] == 0 else float(draw[1])
    return [("random", UNMATCHED), ("gauss", raw)]


def block(world, requirement, api):
    """Retailer/product pairs of the concept with an available offer, per the native oracle."""
    _, reference = edits._reference(world, requirement, api)
    available = {}
    for row in reference["candidates"]:
        available.setdefault((row["retailer_id"], row["product_id"]), set()).add(row["offer_id"])
    pairs = {}
    for retailer in world["retailers"]:
        for offer in retailer["offers"]:
            pair = (retailer["retailer_id"], offer["product_id"])
            if pair in available:
                entry = pairs.setdefault(pair, {"group": [], "buyable": []})
                entry["group"].append(offer)
                if offer["offer_id"] in available[pair]:
                    entry["buyable"].append(offer)
    return pairs


def cheapest(entry, draw, config, native_round):
    return min(edits._price(o["price_trace"]["reference_minor"], draw, config, native_round)
               for o in entry["buyable"])


def distribution(entry, config, native_round):
    """Atoms of one pair grouped by the price of its cheapest available SKU."""
    by_price = {}
    for atom in atoms([o["price_trace"]["reference_minor"] for o in entry["group"]], config):
        by_price.setdefault(cheapest(entry, representative(atom), config, native_round), []).append(atom)
    return by_price


def mass(by_price, accept):
    return fsum(atom[0] for price, found in by_price.items() if accept(price) for atom in found)


def model(world, requirement, api):
    """The price block of a world and the probability of the requirement in it.

    `terms[w]` is the probability that the designated pairs' cheapest available
    price is exactly w while every other pair's is above w. Pairs draw
    independently, so each term is a product, and the terms for different w
    are disjoint events whose sum is the probability of the requirement given
    everything upstream of prices.
    """
    requirement = edits.resolve(requirement)
    config, native_round = world["config"]["retailer_price"], api.native.rounded_price
    pairs = block(world, requirement, api)
    designated = {(rid, requirement["product_id"]) for rid in requirement["retailer_ids"]}
    if not designated <= set(pairs):
        raise ZeroMass("unavailable", "A designated retailer has no available offer of the product in this world")
    spread = {pair: distribution(entry, config, native_round) for pair, entry in pairs.items()}
    terms = {}
    for price in set.intersection(*(set(spread[pair]) for pair in designated)):
        term = prod(mass(by_price, (lambda p: p == price) if pair in designated else (lambda p: p > price))
                    for pair, by_price in spread.items())
        if term > 0:
            terms[price] = term
    if not terms:
        raise ZeroMass("no_common_price", "The designated retailers cannot be exactly the cheapest in this world")
    return SimpleNamespace(pairs=pairs, designated=designated, spread=spread, terms=terms,
                           probability=fsum(terms.values()), config=config, native_round=native_round)


def plan(world, requirement, api, rng):
    """Sample every price draw of the concept given that the designated retailers are cheapest.

    Returns a draw for each pair in the block, the probability of the
    requirement given this world's upstream draws, and the sampled winning
    price. The world's own price draws are not consulted: every pair is drawn
    afresh from its conditional distribution, so repeated plans for one world
    are independent samples of the same conditional distribution.
    """
    block_model = model(world, requirement, api)
    prices = sorted(block_model.terms)
    winning = rng.choices(prices, weights=[block_model.terms[p] for p in prices])[0]
    draws = {}
    for pair in sorted(block_model.pairs):
        accept = (lambda p: p == winning) if pair in block_model.designated else (lambda p: p > winning)
        options = [atom for price, found in sorted(block_model.spread[pair].items()) if accept(price) for atom in found]
        atom = rng.choices(options, weights=[a[0] for a in options])[0]
        draws[pair] = draw_within(atom, block_model.pairs[pair]["group"], block_model.config,
                                  block_model.native_round, rng)
    return draws, block_model.probability, winning


def steer(session, natural, requirement, api, rng):
    """Plan on the natural world, regenerate through the real producer, verify."""
    draws, probability, winning = plan(natural, requirement, api, rng)
    config = natural["config"]["retailer_price"]
    keys = {pair: api.commerce.VERSION + "/" + pair[0] + "/" + pair[1] + "/price" for pair in draws}
    world, opened = session.generate({keys[pair]: script(draw, config) for pair, draw in draws.items()})
    changed, repriced = set(), []
    for retailer in world["retailers"]:
        for offer in retailer["offers"]:
            pair = (retailer["retailer_id"], offer["product_id"])
            if pair in draws:
                if edits._draw(offer) != draws[pair]:
                    raise PlanMismatch(f"{offer['offer_id']}: producer recorded {edits._draw(offer)}, plan was {draws[pair]}")
                changed.add(offer["offer_id"])
    if not edits._only_declared_changes(natural, world, changed):
        raise AssertionError("Steering the price draws changed something other than the block's prices")
    by_id = {o["offer_id"]: o for r in natural["retailers"] for o in r["offers"]}
    for pair in sorted(draws):
        group = [o for r in world["retailers"] if r["retailer_id"] == pair[0]
                 for o in r["offers"] if o["product_id"] == pair[1]]
        repriced.append({"retailer_id": pair[0], "product_id": pair[1], "stream": keys[pair],
                         "natural_draw": dict(zip(edits.DRAW_FIELDS, edits._draw(by_id[group[0]["offer_id"]]))),
                         "steered_draw": dict(zip(edits.DRAW_FIELDS, draws[pair])),
                         "offers": [{"offer_id": o["offer_id"], "natural": by_id[o["offer_id"]]["price_minor"],
                                     "steered": o["price_minor"]} for o in group]})
    record = {"method": "exact_conditional_price_block", "requirement": edits.resolve(requirement),
              "natural_world_id": natural["world_id"],
              "probability_given_upstream": probability, "winning_price_minor": winning,
              "streams_opened": len(opened), "streams_steered": len(draws), "repriced": repriced,
              "distribution_claim": "Every price draw of the concept is sampled from its distribution given the "
                                    "requirement and all upstream draws, under the price model in prices.atoms. "
                                    "Upstream draws are not reweighted; use probability_given_upstream as the "
                                    "importance weight across seeds."}
    world["provenance"]["steered_generation"] = record
    world["status"] = STATUS
    # The producer's own statements (such as "no winner or seed repair")
    # describe the natural draw, not this world.
    world["limitations"] = ["Natural-draw declaration: " + note for note in world["limitations"]] + [
        "Steered conditional sample: the seed alone does not reproduce this world; see provenance.steered_generation."]
    world.pop("world_id")
    world["world_id"] = api.native.digest(world)
    task, reference = edits.check(world, requirement, api)
    return world, task, reference, record


def empirical(natural, requirement, api, trials, first_seed):
    """Redraw the price block with the real `_offer_price` under other seeds.

    Returns how often the requirement held and the winning prices when it did.
    Independent of `atoms`: the producer's own pricing function, on this
    world's products, assortment and stock.
    """
    requirement = edits.resolve(requirement)
    config = natural["config"]["retailer_price"]
    pairs = block(natural, requirement, api)
    designated = {(rid, requirement["product_id"]) for rid in requirement["retailer_ids"]}
    products = {p["public"]["product_id"]: p["public"] for p in natural["products"]}
    skus = {s["sku_id"]: s for p in products.values() for s in p["skus"]}
    winning = Counter()
    for seed in range(first_seed, first_seed + trials):
        low = {pair: min(api.commerce._offer_price(seed, pair[0], products[pair[1]], skus[o["sku_id"]], config)[0]
                         for o in entry["buyable"]) for pair, entry in pairs.items()}
        floor_price = min(low.values())
        if {pair for pair, price in low.items() if price == floor_price} == designated:
            winning[floor_price] += 1
    return winning
