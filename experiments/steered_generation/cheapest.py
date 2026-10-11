"""Joint conditional sampling of a concept's stock and prices, given who is the cheapest available.

A requirement names a concept, a product and the retailers that must be
exactly the ones with the concept's cheapest available offer, on that product.
It can also name offers that must be listed below that winning price; by the
definition of the winner such an offer is unavailable ("a cheaper offer exists
but is sold out").

Which offers compete is decided by stock, so stock and prices are one block.
The coupling stays inside each retailer/product pair: a pair draws one price
offset and its own stock, independently of every other pair, and the
requirement asks a pair only for the price of its cheapest available SKU.
That price has a small exact distribution per pair, so across pairs the
probability is the same finite sum as in `prices.model`, and every draw can be
sampled from its distribution given the requirement without a rejection loop.

A zero here always means impossible. Products over pairs are kept as sums of
logarithms, since a few hundred pairs easily take a possible event below the
smallest float; and a product inside one pair that would underflow from
positive factors is an error (`NumericalLimit`), never a zero. Sampling keeps
the same support: every choice among weighted options goes through
`blocks.pick`, which can return any option with a positive weight.
"""
from bisect import bisect_right
from collections import Counter
from decimal import MAX_EMAX, MIN_EMIN, Decimal, localcontext
from fractions import Fraction
import json
from math import exp, fsum, log, prod
from types import SimpleNamespace

from experiments.world_requirement_construction import model as edits

from . import blocks, prices, stock, streams
from .blocks import NumericalLimit, Step, Unmet, pick, power, times
from .prices import UNMATCHED, ZeroMass
from .stock import DISPATCH, NOT_SHIPPABLE, NOWHERE, after

VERSION = "steered-cheapest-available-v1"


def resolve(requirement):
    required = {"schema", "concept_id", "product_id", "retailer_ids"}
    if (type(requirement) is not dict or not required <= set(requirement) <= required | {"listed_below"} or
            requirement["schema"] != VERSION):
        raise ValueError("Declare a concept, a product, the retailers that are cheapest and optionally offers "
                         "listed below them")
    edits.resolve(winner(requirement))
    below = requirement.get("listed_below", [])
    if (type(below) is not list or "listed_below" in requirement and not below or
            any(type(row) is not dict or set(row) != {"retailer_id", "sku_id"} or
                any(type(value) is not str or not value for value in row.values()) for row in below) or
            len({(row["retailer_id"], row["sku_id"]) for row in below}) != len(below)):
        raise ValueError("Offers listed below the winning price are distinct retailer and SKU pairs")
    return json.loads(json.dumps(requirement))


def winner(requirement):
    """The who-is-cheapest part, in the words of the native oracle's check."""
    return {"schema": edits.VERSION, "kind": edits.KIND,
            **{key: requirement[key] for key in ("concept_id", "product_id", "retailer_ids") if key in requirement}}


def named(world, requirement):
    """The requirement, with every retailer, product and SKU it names checked against the world.

    A malformed requirement or an unknown name is an error here, before any
    question of probability. Also returns each offer listed below the winner
    as its retailer/product pair and SKU.
    """
    requirement = resolve(requirement)
    concepts = {p["public"]["product_id"]: p["public"]["concept_id"] for p in world["products"]}
    skus = {s["sku_id"]: p["public"]["product_id"] for p in world["products"] for s in p["public"]["skus"]}
    known = {r["retailer_id"] for r in world["retailers"]}
    if requirement["concept_id"] not in concepts.values():
        raise ValueError("Unknown concept")
    if not set(requirement["retailer_ids"]) <= known or requirement["product_id"] not in concepts:
        raise ValueError("Unknown retailer or product")
    if concepts[requirement["product_id"]] != requirement["concept_id"]:
        raise ValueError("The product is not of this concept")
    below = []
    for row in requirement.get("listed_below", []):
        if row["retailer_id"] not in known or row["sku_id"] not in skus:
            raise ValueError("Unknown retailer or SKU")
        if concepts[skus[row["sku_id"]]] != requirement["concept_id"]:
            raise ValueError("An offer listed below the winner must be of the same concept")
        below.append(((row["retailer_id"], skus[row["sku_id"]]), row["sku_id"]))
    return requirement, below


def footprint(world, requirement, api):
    """What the block decides: the stock and the price of every listed pair of the concept."""
    requirement, _ = named(world, requirement)
    pairs = prices.competing(world, requirement["concept_id"])
    return SimpleNamespace(writes={(kind, *pair) for pair in pairs for kind in ("stock", "price")}, reads=set())


def site(world, retailer, product_id, api):
    """One retailer/product pair: its offers, its stock locations and the draws' stream keys."""
    config, rid = world["config"], retailer["retailer_id"]
    rows = {row["source_id"]: row for row in retailer["conditions"] if row["product_id"] == product_id}
    ranges = config["stock"]["quantity_ranges"][retailer["scale"]]
    offers = [o for o in retailer["offers"] if o["product_id"] == product_id]
    locations = []
    for source in retailer["source_locations"]:
        name, conditions = source["source_id"], {}
        for mass, condition, quantity in stock.atoms(rows[name]["probabilities"], config["stock"]["zero_probability"],
                                                     ranges):
            conditions.setdefault(condition, {False: [], True: []})[bool(quantity)].append((mass, quantity))
        locations.append(SimpleNamespace(
            source_id=name, shipping=source["shipping_enabled"], probabilities=rows[name]["probabilities"],
            condition_key=stock.stream_keys(api, rid, product_id, offers[0]["sku_id"], name)["condition"],
            # Per condition: its probability, split into one SKU holding nothing here and holding something
            # (kept apart, so that neither is lost when the other rounds to the whole), and the chance of
            # nothing given the condition.
            conditions={condition: SimpleNamespace(
                weight=fsum(m for found in held.values() for m, _ in found),
                zero=fsum(m for m, _ in held[False]), full=fsum(m for m, _ in held[True]),
                empty=fsum(m for m, _ in held[False]) / fsum(m for found in held.values() for m, _ in found),
                held=held) for condition, held in conditions.items()}))
    return SimpleNamespace(
        pair=(rid, product_id), offers=offers, locations=locations, config=config, scale=retailer["scale"],
        supplier_enabled=retailer["supplier_enabled"],
        eligible=min(1, max(0, config["supplier"]["sku_eligible_probability"])) if retailer["supplier_enabled"] else 0,
        keys={o["offer_id"]: {
            "supplier": stock.supplier_key(api, rid, o["sku_id"]),
            **{l.source_id: stock.stream_keys(api, rid, product_id, o["sku_id"], l.source_id) for l in locations}}
            for o in offers},
        price_key=prices.stream_keys([(rid, product_id)], api)[(rid, product_id)], chains={})


def sites(world, requirement, api):
    """The concept's pairs with their stream keys, without the block model's probabilities."""
    requirement, below = named(world, requirement)
    concepts = {p["public"]["product_id"]: p["public"]["concept_id"] for p in world["products"]}
    places = {(r["retailer_id"], product_id): site(world, r, product_id, api) for r in world["retailers"]
              for product_id in dict.fromkeys(o["product_id"] for o in r["offers"])
              if concepts[product_id] == requirement["concept_id"]}
    return SimpleNamespace(requirement=requirement, places=places, below=below)


def weight(location, count, stocked=None):
    """Probability that `count` SKUs hold nothing at a location, and a further one is stocked there or not."""
    return fsum(times(c.weight if stocked is None else c.full if stocked else c.zero, power(c.empty, count))
                for c in location.conditions.values())


def spared(place, count):
    """Probability that `count` SKUs with nothing to dispatch are all left without a supplier order."""
    return power(1 - place.eligible, count)


def nothing(place, count):
    """Probability that `count` SKUs of the pair are all unavailable: held nowhere, no supplier order.

    Locations draw their condition independently, and under a condition every
    SKU draws its own zero and quantity with the same probabilities, so this
    is a product over locations of a sum over conditions.
    """
    return times(spared(place, count), *(weight(location, count) for location in place.locations))


def chain(place, count):
    """The pair's stock with `count` SKUs unavailable and one further SKU, the witness, available.

    `forward[i][state]` is the probability that the first i locations hold
    none of the `count` SKUs and leave the witness in `state`; `ends` maps the
    ways the witness ends up available, (state, supplier order), to their
    probability. Only sums of products of probabilities: an outcome has
    probability zero exactly when it cannot happen.
    """
    if count not in place.chains:
        forward = [{NOWHERE: 1.0, NOT_SHIPPABLE: 0.0, DISPATCH: 0.0}]
        for location in place.locations:
            following = dict.fromkeys(forward[-1], 0.0)
            for state, mass in forward[-1].items():
                for stocked in (False, True):
                    following[after(state, stocked, location.shipping)] += times(mass, weight(location, count, stocked))
            forward.append(following)
        left, order = spared(place, count), place.eligible
        # The producer draws the witness's eligibility only when it has nothing to dispatch.
        ends = {(DISPATCH, False): times(forward[-1][DISPATCH], left),
                (NOT_SHIPPABLE, True): times(forward[-1][NOT_SHIPPABLE], order, left),
                (NOT_SHIPPABLE, False): times(forward[-1][NOT_SHIPPABLE], 1 - order, left),
                (NOWHERE, True): times(forward[-1][NOWHERE], order, left)}
        ends = {end: mass for end, mass in ends.items() if mass > 0}
        place.chains[count] = SimpleNamespace(forward=forward, ends=ends, probability=fsum(ends.values()))
    return place.chains[count]


def outcomes(place, below, price_config, native_round):
    """Every way the pair's cheapest available price can come about, with its probability.

    One outcome per price atom and price level of the pair under that atom:
    the SKUs listed cheaper are unavailable and at least one SKU at the level
    is available; and one per atom for no SKU being available (price None).
    `ceiling` is the highest price among the pair's offers that must be listed
    below the winning price, so the outcome counts only for a winning price
    above it.
    """
    result = []
    for atom in prices.atoms([o["price_trace"]["reference_minor"] for o in place.offers], price_config):
        draw = prices.representative(atom)
        listed = {o["offer_id"]: edits._price(o["price_trace"]["reference_minor"], draw, price_config, native_round)
                  for o in place.offers}
        ceiling = max((listed[offer_id] for offer_id in below), default=None)
        cheaper = []
        for price in sorted(set(listed.values())):
            level = [o for o in place.offers if listed[o["offer_id"]] == price]
            # The first available SKU at the level, in offer order, is the witness.
            mass = times(atom[0], fsum(chain(place, len(cheaper) + index).probability for index in range(len(level))))
            result.append(SimpleNamespace(mass=mass, price=price, atom=atom, ceiling=ceiling,
                                          cheaper=list(cheaper), level=level))
            cheaper += level
        result.append(SimpleNamespace(mass=times(atom[0], nothing(place, len(cheaper))), price=None, atom=atom,
                                      ceiling=ceiling, cheaper=cheaper, level=[]))
    return [found for found in result if found.mass > 0]


def accepts(found, winning, designated):
    """Whether an outcome of a pair fits a winning price: at it for a designated pair, above it or absent otherwise."""
    if found.ceiling is not None and found.ceiling >= winning:
        return False
    return found.price == winning if designated else found.price is None or found.price > winning


class Spread:
    """A pair's outcomes, summed by cheapest available price.

    For a pair with no offer that must be listed below the winner, the two
    sums the requirement needs are tabulated once: the probability of a price
    exactly, and of every price above it together with no available offer.
    Sums run from the top price down, over probabilities only.
    """

    def __init__(self, found):
        self.outcomes = found
        self.table = all(o.ceiling is None for o in found)
        if self.table:
            by_price = {}
            for outcome in found:
                by_price.setdefault(outcome.price, []).append(outcome.mass)
            absent = fsum(by_price.pop(None, []))
            self.prices = sorted(by_price)
            self.at = {price: fsum(by_price[price]) for price in self.prices}
            self.from_index = [absent]
            for price in reversed(self.prices):
                self.from_index.append(self.from_index[-1] + self.at[price])
            self.from_index.reverse()

    def mass(self, winning, designated):
        if not self.table:
            return fsum(o.mass for o in self.outcomes if accepts(o, winning, designated))
        return self.at.get(winning, 0.0) if designated else self.from_index[bisect_right(self.prices, winning)]


def model(world, requirement, api):
    """The concept's stock-and-price block and the probability of the requirement in it.

    For a winning price w, the term is the probability that every designated
    pair's cheapest available price is exactly w, every other pair's is above
    w or absent, and every offer named as listed below the winner is listed
    below w. Pairs draw independently, so each term is a product over pairs,
    kept as `log_terms[w]`; the terms for different w are disjoint events
    whose sum is the probability of the requirement given everything upstream
    of the concept's stock and prices. `shares[w]` is the winning price's
    distribution given the requirement, as floats for comparison; sampling
    works from the logarithms. `probability` is 0.0 when the probability is
    below the float range; `log_probability` always holds.
    """
    found = sites(world, requirement, api)
    requirement, places = found.requirement, found.places
    designated = {(rid, requirement["product_id"]) for rid in requirement["retailer_ids"]}
    if not designated <= set(places):
        raise ZeroMass("not_listed", "A designated retailer does not list the product in this world")
    below = {}
    for pair, sku_id in found.below:
        offer = next((o for o in places[pair].offers if o["sku_id"] == sku_id), None) if pair in places else None
        if offer is None:
            raise ZeroMass("not_listed", "The retailer does not list this SKU in this world")
        below.setdefault(pair, []).append(offer["offer_id"])
    config, native_round = world["config"]["retailer_price"], api.native.rounded_price
    spread = {pair: Spread(outcomes(place, below.get(pair, ()), config, native_round))
              for pair, place in places.items()}
    log_terms = {}
    for price in sorted(set.intersection(*({o.price for o in spread[pair].outcomes} for pair in designated)) - {None}):
        masses = []
        for pair, found in spread.items():
            masses.append(found.mass(price, pair in designated))
            if not masses[-1]:
                break
        else:
            log_terms[price] = fsum(map(log, masses))
    if not log_terms:
        raise ZeroMass("no_outcome", "No stock and price outcome of the concept satisfies the requirement in this world")
    top = max(log_terms.values())
    log_probability = top + log(fsum(exp(value - top) for value in log_terms.values()))
    return SimpleNamespace(requirement=requirement, places=places, designated=designated, spread=spread,
                           log_terms=log_terms, log_probability=log_probability, probability=exp(log_probability),
                           shares={price: exp(value - log_probability) for price, value in log_terms.items()},
                           below=below, config=config, native_round=native_round)


def pick_log(rng, options, logs):
    """One option with probability proportional to exp of its logarithm.

    The exponentials are Decimals of 40 significant digits, whose exponent
    range takes logarithms about 2e18 apart; beyond that a weight would vanish
    and the choice is refused.
    """
    top = max(logs)
    with localcontext() as context:
        context.prec, context.Emin, context.Emax = 40, MIN_EMIN, MAX_EMAX
        weights = [Fraction(Decimal(value - top).exp()) for value in logs]
    if not all(weights):
        raise NumericalLimit("Winning prices are too far apart in probability to choose among")
    return pick(rng, options, weights)


def exact(*factors):
    """A product of probabilities as an exact rational: a sampling weight that cannot underflow."""
    return prod(map(Fraction, factors))


def held(rng, location, condition, stocked=None):
    """One SKU's draw at a location under a condition: a quantity, or None for the zero draw."""
    found = location.conditions[condition].held
    found = found[False] + found[True] if stocked is None else found[stocked]
    return pick(rng, [quantity for _, quantity in found], [mass for mass, _ in found])


def stocking(place, outcome, rng):
    """Sample the pair's stock draws given one outcome for its cheapest available price.

    Returns the condition at every location and, for every SKU, a quantity per
    location (None for the zero draw) and the supplier order (None where the
    producer does not draw it). The SKUs listed cheaper are unavailable, so is
    every SKU at the level before the witness, and the witness is available.
    The requirement says nothing more about the pair's other SKUs given the
    conditions, so they are drawn as the producer draws them.
    """
    unavailable, witness, state, supplier = list(outcome.cheaper), None, None, None
    if outcome.level:
        index = pick(rng, range(len(outcome.level)),
                     [chain(place, len(unavailable) + i).probability for i in range(len(outcome.level))])
        unavailable, witness = unavailable + outcome.level[:index], outcome.level[index]
        found = chain(place, len(unavailable))
        ends = sorted(found.ends)
        state, supplier = pick(rng, ends, [found.ends[end] for end in ends])
    conditions, stocked = {}, {}
    count, end = len(unavailable), state
    for index in reversed(range(len(place.locations))):
        location = place.locations[index]
        if witness is None:
            steps = [(None, condition, None) for condition in sorted(location.conditions)]
            weights = [exact(c.weight, Fraction(c.empty) ** count) for _, c in sorted(location.conditions.items())]
        else:
            steps = [(previous, condition, has) for previous in found.forward[index] for has in (False, True)
                     if after(previous, has, location.shipping) == state for condition in sorted(location.conditions)]
            weights = [exact(found.forward[index][previous], c.full if has else c.zero, Fraction(c.empty) ** count)
                       for previous, c, has in ((previous, location.conditions[condition], has)
                                                for previous, condition, has in steps)]
        state, conditions[location.source_id], stocked[location.source_id] = pick(rng, steps, weights)
    draws = SimpleNamespace(conditions=conditions, offers={}, witness=witness and witness["offer_id"],
                            unavailable=[o["offer_id"] for o in unavailable])
    for offer in unavailable:
        draws.offers[offer["offer_id"]] = {
            "quantities": {l.source_id: held(rng, l, conditions[l.source_id], False) for l in place.locations},
            "supplier": False if place.supplier_enabled else None}
    if witness is not None:
        draws.offers[witness["offer_id"]] = {
            "quantities": {l.source_id: held(rng, l, conditions[l.source_id], stocked[l.source_id])
                           for l in place.locations},
            "supplier": supplier if place.supplier_enabled and end != DISPATCH else None}
    for offer in place.offers:
        if offer["offer_id"] not in draws.offers:
            quantities = {l.source_id: held(rng, l, conditions[l.source_id]) for l in place.locations}
            drawn = place.supplier_enabled and not any(l.shipping and quantities[l.source_id] for l in place.locations)
            draws.offers[offer["offer_id"]] = {"quantities": quantities,
                                               "supplier": rng.random() < place.eligible if drawn else None}
    return draws


def sample(block, rng):
    """Sample the block's stock and price draws from a block model.

    Returns the sampled winning price and, per pair, the price draw and the
    stock draws. No draw of the world the model was built on is consulted, so
    repeated samples are independent draws of the same conditional
    distribution.
    """
    winning = pick_log(rng, sorted(block.log_terms), [block.log_terms[price] for price in sorted(block.log_terms)])
    draws = {}
    for pair in sorted(block.places):
        place = block.places[pair]
        options = [o for o in block.spread[pair].outcomes if accepts(o, winning, pair in block.designated)]
        outcome = pick(rng, options, [o.mass for o in options])
        draws[pair] = SimpleNamespace(
            price=prices.draw_within(outcome.atom, place.offers, block.config, block.native_round, rng),
            stock=stocking(place, outcome, rng), cheapest_available=outcome.price)
    return winning, draws


def planned(block, draws):
    """The leaves the planned draws decide, in the form `recorded` reads them off a world."""
    found = {"conditions": {}, "offers": {}}
    for pair, drawn in draws.items():
        place = block.places[pair]
        found["conditions"].update({"/".join((*pair, name)): value for name, value in drawn.stock.conditions.items()})
        for offer in place.offers:
            row = drawn.stock.offers[offer["offer_id"]]
            found["offers"][offer["offer_id"]] = {
                "retailer_id": pair[0], "product_id": pair[1], "sku_id": offer["sku_id"],
                "price_minor": edits._price(offer["price_trace"]["reference_minor"], drawn.price, block.config,
                                            block.native_round),
                "stock_by_source": {name: quantity or 0 for name, quantity in row["quantities"].items()},
                "supplier_order": bool(row["supplier"])}
    return found


def scripts(block, draws):
    """The stream results that make the producer record the planned draws."""
    result = {}
    for pair, found in draws.items():
        place = block.places[pair]
        result[place.price_key] = prices.script(found.price, block.config)
        for location in place.locations:
            result[location.condition_key] = [("choices", found.stock.conditions[location.source_id])]
        for offer_id, row in found.stock.offers.items():
            for name, quantity in row["quantities"].items():
                keys = place.keys[offer_id][name]
                result[keys["zero"]] = [("random", 0.0 if quantity is None else UNMATCHED)]
                if quantity is not None:
                    result[keys["quantity"]] = [("randint", quantity)]
            if row["supplier"] is not None:
                result[place.keys[offer_id]["supplier"]] = [("random", 0.0 if row["supplier"] else UNMATCHED)]
    return result


def conditions(world, pair):
    return {row["source_id"]: row["condition"] for r in world["retailers"] if r["retailer_id"] == pair[0]
            for row in r["conditions"] if row["product_id"] == pair[1]}


def restocked(natural, block, draws):
    """What the planned stock draws do to each pair."""
    return [{"retailer_id": pair[0], "product_id": pair[1], "cheapest_available_minor": draws[pair].cheapest_available,
             "natural_conditions": conditions(natural, pair), "steered_conditions": draws[pair].stock.conditions,
             "held_unavailable": draws[pair].stock.unavailable, "held_available": draws[pair].stock.witness,
             "offers": len(block.places[pair].offers)} for pair in sorted(draws)]


def check(world, requirement, api):
    """Read the requirement off a world with the native oracle: the winners, and the offers listed below them."""
    requirement = resolve(requirement)
    try:
        task, reference = edits.check(world, winner(requirement), api)
    except edits.CannotConstruct as error:
        if error.reason != "winners":
            raise
        raise Unmet(str(error)) from None
    listed = {o["offer_id"]: o["price_minor"] for r in world["retailers"] for o in r["offers"]}
    offers = {(r["retailer_id"], o["sku_id"]): o["offer_id"] for r in world["retailers"] for o in r["offers"]}
    below = []
    for row in requirement.get("listed_below", []):
        offer_id = offers.get((row["retailer_id"], row["sku_id"]))
        if (offer_id not in reference["unavailable_offer_ids"] or
                listed[offer_id] >= reference["minimum_price_minor"]):
            raise Unmet(f"{row['retailer_id']} does not list {row['sku_id']} unavailable below the winning price")
        below.append({"offer_id": offer_id, "price_minor": listed[offer_id]})
    return {"task": task, "reference": reference, "listed_below": below}


def prepare(natural, requirement, api, rng):
    """Sample the block on the natural world; the step replays it and reads the result."""
    block = model(natural, requirement, api)
    winning, draws = sample(block, rng)
    concept_id = block.requirement["concept_id"]

    def record(world):
        if recorded(world, concept_id) != planned(block, draws):
            raise streams.PlanMismatch("The producer recorded other stock or price leaves than planned")
        return {"method": "exact_conditional_stock_and_price_block", "requirement": block.requirement,
                "natural_world_id": natural["world_id"],
                # None when the probability is below the float range; the logarithm always holds.
                "probability_given_upstream": block.probability or None,
                "log_probability_given_upstream": block.log_probability, "winning_price_minor": winning,
                "repriced": prices.replayed(natural, world, {pair: found.price for pair, found in draws.items()},
                                            {pair: block.places[pair].price_key for pair in draws}),
                "restocked": restocked(natural, block, draws),
                "distribution_claim": "For every listed retailer/product pair of the concept, the price draw, the "
                                      "stock condition at every location and every SKU's stock and supplier "
                                      "draws are sampled from their distribution given the requirement and all "
                                      "upstream draws, under the models in prices.atoms and cheapest.chain. "
                                      "None of the seed's own draws of these is kept. Upstream draws are not "
                                      "reweighted; use the probability given upstream as the importance "
                                      "weight across seeds."}

    return Step(script=scripts(block, draws), probability=block.probability, log_probability=block.log_probability,
                **vars(footprint(natural, requirement, api)), record=record,
                check=lambda world: check(world, requirement, api))


def steer(session, natural, natural_opened, requirement, api, rng):
    """Plan on the natural world, regenerate through the real producer, verify."""
    return blocks.steer(session, natural, natural_opened, prepare(natural, requirement, api, rng), api)


def judged(found, requirement):
    """The winning price when recorded leaves satisfy the requirement, else None.

    The native oracle's rule written out separately from the block model: an
    offer is available when it holds stock anywhere or has a supplier order.
    """
    lowest = {}
    for row in found["offers"].values():
        if any(row["stock_by_source"].values()) or row["supplier_order"]:
            pair = (row["retailer_id"], row["product_id"])
            lowest[pair] = min(lowest.get(pair, row["price_minor"]), row["price_minor"])
    if not lowest:
        return None
    winning = min(lowest.values())
    if {pair for pair, price in lowest.items() if price == winning} != {
            (rid, requirement["product_id"]) for rid in requirement["retailer_ids"]}:
        return None
    by_sku = {(row["retailer_id"], row["sku_id"]): row["price_minor"] for row in found["offers"].values()}
    below = [by_sku.get((row["retailer_id"], row["sku_id"]), winning) for row in requirement.get("listed_below", [])]
    return winning if all(price < winning for price in below) else None


def recorded(world, concept_id):
    """The block's leaves as a world records them: conditions, and every offer's price and stock."""
    concepts = {p["public"]["product_id"]: p["public"]["concept_id"] for p in world["products"]}
    return {"conditions": {"/".join((r["retailer_id"], row["product_id"], row["source_id"])): row["condition"]
                           for r in world["retailers"] for row in r["conditions"]
                           if concepts[row["product_id"]] == concept_id},
            "offers": {o["offer_id"]: {"retailer_id": r["retailer_id"], "product_id": o["product_id"],
                                       "sku_id": o["sku_id"], "price_minor": o["price_minor"],
                                       "stock_by_source": dict(o["stock_by_source"]),
                                       "supplier_order": o["supplier_order"]["enabled"]}
                       for r in world["retailers"] for o in r["offers"] if concepts[o["product_id"]] == concept_id}}


def trial(natural, requirement, api):
    """This module's reading of the producer's stock and price lines for the concept, under another seed.

    Uses the producer's own stream, weighted-choice and pricing functions and
    none of the block model. `blocks.redraw` checks it against the real
    producer leaf for leaf; it is then cheap enough to estimate frequencies
    from.
    """
    block = sites(natural, requirement, api)
    requirement, config = block.requirement, natural["config"]
    products = {p["public"]["product_id"]: p["public"] for p in natural["products"]}
    skus = {s["sku_id"]: s for p in products.values() for s in p["skus"]}

    def reading(seed):
        stream = lambda key: api.population.stream(seed, key)
        found = {"conditions": {}, "offers": {}}
        for pair, place in block.places.items():
            condition = {l.source_id: api.population.weighted(stream(l.condition_key), l.probabilities)
                         for l in place.locations}
            found["conditions"].update({"/".join((*pair, name)): value for name, value in condition.items()})
            for offer in place.offers:
                keys, amounts = place.keys[offer["offer_id"]], {}
                for location in place.locations:
                    name = location.source_id
                    zero = stream(keys[name]["zero"]).random() < config["stock"]["zero_probability"][condition[name]]
                    amounts[name] = 0 if zero else stream(keys[name]["quantity"]).randint(
                        *config["stock"]["quantity_ranges"][place.scale][condition[name]])
                on_hand = any(l.shipping and amounts[l.source_id] > 0 for l in place.locations)
                supplier = (place.supplier_enabled and not on_hand and
                            stream(keys["supplier"]).random() < config["supplier"]["sku_eligible_probability"])
                found["offers"][offer["offer_id"]] = {
                    "retailer_id": pair[0], "product_id": pair[1], "sku_id": offer["sku_id"],
                    "price_minor": api.commerce._offer_price(seed, pair[0], products[pair[1]], skus[offer["sku_id"]],
                                                             config["retailer_price"])[0],
                    "stock_by_source": amounts, "supplier_order": supplier}
        return found

    keys = {place.price_key for place in block.places.values()}
    for place in block.places.values():
        keys.update(l.condition_key for l in place.locations)
        for row in place.keys.values():
            keys.add(row["supplier"])
            keys.update(key for name, found in row.items() if name != "supplier" for key in found.values())
    return SimpleNamespace(
        keys=keys, **vars(footprint(natural, requirement, api)), reading=reading,
        winning=lambda seed: judged(reading(seed), requirement),
        holds=lambda seed: judged(reading(seed), requirement) is not None,
        recorded=lambda world: recorded(world, requirement["concept_id"]),
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
