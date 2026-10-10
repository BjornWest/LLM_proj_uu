"""Conditional sampling of the price draws, given a requirement on who is cheapest.

Given everything upstream of prices (products, assortment, stock), the producer
draws one price per retailer/product, independently of every other pair. Each
draw has a small exact distribution over rounded prices, so the probability of
"exactly these retailers are cheapest" is a finite sum, and the price draws can
be sampled from their distribution given that outcome without any rejection
loop. The planned draws are then fed to the real producer; this module never
writes a price itself.
"""
from math import ceil, floor, fsum, prod
from statistics import NormalDist

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


def plan(world, requirement, api, rng):
    """Sample the concept's price draws given that the designated retailers are cheapest.

    Returns the draws that must change, the probability of the requirement
    given this world's upstream draws, and the sampled winning price.

    A pair whose natural draw already satisfies its part (equal to the winning
    price if designated, above it otherwise) keeps that draw; only the others
    are redrawn from their conditional distribution. Keeping a prior draw when
    it lies in the accepted set, and redrawing from the conditional otherwise,
    is itself an exact draw from the conditional, so the result is an exact
    conditional sample that stays as close to the seed's own world as it can.
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
        terms[price] = prod(mass(by_price, (lambda p: p == price) if pair in designated else (lambda p: p > price))
                            for pair, by_price in spread.items())
    probability = fsum(terms.values())
    if probability <= 0:
        raise ZeroMass("no_common_price", "The designated retailers cannot be exactly the cheapest in this world")
    prices = sorted(terms)
    winning = rng.choices(prices, weights=[terms[p] for p in prices])[0]
    draws = {}
    for pair in sorted(pairs):
        entry = pairs[pair]
        accept = (lambda p: p == winning) if pair in designated else (lambda p: p > winning)
        if accept(min(o["price_minor"] for o in entry["buyable"])):
            continue
        options = [atom for price, found in sorted(spread[pair].items()) if accept(price) for atom in found]
        atom = rng.choices(options, weights=[a[0] for a in options])[0]
        draws[pair] = draw_within(atom, entry["group"], config, native_round, rng)
    return draws, probability, winning


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
        raise AssertionError("Steering the price draws changed something other than those prices")
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
              "distribution_claim": "Sample of this seed's price draws from their distribution given the "
                                    "requirement and all upstream draws. Upstream draws are not reweighted; "
                                    "use probability_given_upstream as the importance weight across seeds."}
    world["provenance"]["steered_generation"] = record
    world["status"] = STATUS
    world["limitations"] = list(world["limitations"]) + [
        "Steered conditional sample: the seed alone does not reproduce this world; see provenance.steered_generation."]
    world.pop("world_id")
    world["world_id"] = api.native.digest(world)
    task, reference = edits.check(world, requirement, api)
    return world, task, reference, record


def empirical_probability(natural, requirement, api, trials, first_seed):
    """Frequency of the requirement when the real `_offer_price` redraws the block.

    Independent of `atoms`: it calls the producer's own pricing function under
    other seeds, on this world's products, assortment and stock.
    """
    requirement = edits.resolve(requirement)
    config = natural["config"]["retailer_price"]
    pairs = block(natural, requirement, api)
    designated = {(rid, requirement["product_id"]) for rid in requirement["retailer_ids"]}
    products = {p["public"]["product_id"]: p["public"] for p in natural["products"]}
    skus = {s["sku_id"]: s for p in products.values() for s in p["skus"]}
    hits = 0
    for seed in range(first_seed, first_seed + trials):
        low = {pair: min(api.commerce._offer_price(seed, pair[0], products[pair[1]], skus[o["sku_id"]], config)[0]
                         for o in entry["buyable"]) for pair, entry in pairs.items()}
        floor_price = min(low.values())
        hits += {pair for pair, price in low.items() if price == floor_price} == designated
    return hits / trials
