"""Joint conditional sampling of a concept's stock and prices, given who is the cheapest available.

A requirement names a concept, a product and the retailers that must be
exactly the ones with the concept's cheapest available offer, on that product.
It can also name offers that must be listed below that winning price; by the
definition of the winner such an offer is unavailable ("a cheaper offer exists
but is sold out").

The requirement can narrow which offers compete (predicates on the SKU and
its product, as in the native feature task) and what makes one available
(stock anywhere or a supplier order; physical stock only; or physical stock at
a pickup branch in a named city, as in the native branch task), and it can
confine the comparison to the retailer/product pairs a comparison site lists.
"Cheapest" can be another ranking with the price last: the price per kilogram
of food, or stated product facts first (the native unit-price and priority
tasks). And earlier sets of criteria can be required to have no available
match at all, so that a permitted relaxation decides (the native relaxation
task).

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
from bisect import bisect_left, bisect_right
from collections import Counter
from decimal import MAX_EMAX, MIN_EMIN, Decimal, localcontext
from fractions import Fraction
from functools import lru_cache
from importlib import import_module
import json
from math import exp, fsum, log, prod
from random import Random
from types import SimpleNamespace

from experiments.world_requirement_construction import model as edits

from . import blocks, menus, prices, stock, streams
from .blocks import NumericalLimit, Step, Unmet, pick, power, times
from .prices import UNMATCHED, ZeroMass
from .stock import DISPATCH, NOT_SHIPPABLE, NOWHERE, after

VERSION = "steered-cheapest-available-v1"
# What makes an offer available, in the native tasks' words.
PURCHASABLE, PHYSICAL, BRANCH = "purchasable", "positive_stock", "positive_pickup_branch_stock"
# Rankings other than the listed price, each read by its own native task.
RANKINGS = {"priorities": ".catalog_priority_task", "unit_basis": ".catalog_unit_price_task",
            "relaxations": ".catalog_relaxation_task"}


def resolve(requirement):
    required = {"schema", "concept_id", "product_id", "retailer_ids"}
    optional = {"listed_below", "predicates", "availability", "city", "country", "comparison_site_id", "surrounding",
                "selected", "delivered", *RANKINGS}
    if (type(requirement) is not dict or not required <= set(requirement) <= required | optional or
            requirement["schema"] != VERSION):
        raise ValueError("Declare a concept, a product, the retailers that are cheapest and optionally offers "
                         "listed below them, predicates and an availability")
    edits.resolve(winner(requirement))
    below = requirement.get("listed_below", [])
    if (type(below) is not list or "listed_below" in requirement and not below or
            any(type(row) is not dict or set(row) != {"retailer_id", "sku_id"} or
                any(type(value) is not str or not value for value in row.values()) for row in below) or
            len({(row["retailer_id"], row["sku_id"]) for row in below}) != len(below)):
        raise ValueError("Offers listed below the winning price are distinct retailer and SKU pairs")
    stated(requirement)
    return json.loads(json.dumps(requirement))


def stated(requirement):
    """Check how a requirement states who competes, what is available and how offers rank."""
    availability = requirement.get("availability", PURCHASABLE)
    if availability not in (PURCHASABLE, PHYSICAL, BRANCH):
        raise ValueError("Availability is one of " + ", ".join((PURCHASABLE, PHYSICAL, BRANCH)))
    ranking = [name for name in RANKINGS if name in requirement]
    if len(ranking) > 1 or ranking and availability == BRANCH:
        raise ValueError("State at most one of priorities, a unit basis and relaxations, and not with branch stock")
    if ("relaxations" in requirement) != ("selected" in requirement) or type(requirement.get("selected", "")) is not str:
        raise ValueError("Relaxations go with the label of the criteria set that must be the first with a match")
    # The unit-price task alone may leave the predicates out.
    needed = ranking != ["unit_basis"]
    if "predicates" in requirement and (type(requirement["predicates"]) is not list or
                                        needed and not requirement["predicates"]):
        raise ValueError("Predicates are a nonempty list")
    if needed and (availability != PURCHASABLE or ranking) and "predicates" not in requirement:
        raise ValueError("The native tasks that require physical stock or rank by features need at least one predicate")
    if (availability == BRANCH) != ("city" in requirement) or "country" in requirement and availability != BRANCH:
        raise ValueError("A city, and optionally a country, go with availability at a pickup branch and only with it")
    if any(type(requirement[key]) is not str or not requirement[key]
           for key in ("city", "country", "comparison_site_id") if key in requirement):
        raise ValueError("City, country and comparison site are nonempty text")
    if "surrounding" in requirement and ("comparison_site_id" not in requirement or
                                         type(requirement["surrounding"]) is not dict):
        raise ValueError("Surrounding-site controls are a mapping and go with a comparison site")
    if "delivered" in requirement:
        delivered = requirement["delivered"]
        kinds = delivered.get("delivery_types", ["home"]) if type(delivered) is dict else None
        if (type(delivered) is not dict or set(delivered) - {"delivery_options", "delivery_types", "max_total_minor"} or
                type(delivered.get("delivery_options", {})) is not dict or type(kinds) is not list or not kinds or
                any(type(kind) is not str for kind in kinds) or len(set(kinds)) != len(kinds) or set(kinds) - set(menus.TYPES)):
            raise ValueError("Delivered totals take a site recipe's delivery options and the kinds of destination that "
                             "count (home, parcel_locker, staffed_counter; home alone unless stated)")
        if "max_total_minor" in delivered and (type(delivered["max_total_minor"]) is not int or delivered["max_total_minor"] < 0):
            raise ValueError("A cap on the delivered total is a whole non-negative amount in minor units")
        if ranking or availability != PURCHASABLE or "comparison_site_id" in requirement or "predicates" not in requirement:
            raise ValueError("Delivered totals are read for predicates, purchasable offers and every shop, ranked by "
                             "the total alone")


def winner(requirement):
    """The who-is-cheapest part, in the words of the native oracle's check."""
    return {"schema": edits.VERSION, "kind": edits.KIND,
            **{key: requirement[key] for key in ("concept_id", "product_id", "retailer_ids") if key in requirement}}


@lru_cache(maxsize=8)
def inventory(package, concept_id):
    """The native field declarations a concept's predicates are read with."""
    return import_module(package + ".feature_offer_task").FieldInventory(concept_id)


LISTED = {}


def listed(world, requirement, package):
    """The retailer/product pairs a comparison site lists, and the sidecar generator that says so.

    Which products and pairs a site lists is decided by draws keyed by the
    world's seed, the site, the product and the retailer over the listed
    pairs: nothing of it depends on stock or prices, so it is the same for the
    natural world and every steered one.
    """
    surrounding = import_module(package + ".native_review_ecosystem")
    sidecar = lambda found: surrounding.generate(found, requirement.get("surrounding"))
    key = (world["world_id"], requirement["comparison_site_id"], json.dumps(requirement.get("surrounding"), sort_keys=True))
    if key not in LISTED:
        sites = [site for site in sidecar(world)["sites"]
                 if site["site_id"] == requirement["comparison_site_id"] and site["kind"] == "aggregator"]
        if len(sites) != 1:
            raise ValueError("Unknown comparison site")
        if len(LISTED) > 32:
            LISTED.clear()
        LISTED[key] = frozenset((row["retailer_id"], row["product_id"]) for row in sites[0]["listings"])
    return LISTED[key], sidecar


def reading(skus, pairs, sources, supplier, reference, key=None, barred=(), settled=None, delivered=None, reads=(),
            stranded=(), cap=None):
    """One native task's reading of a requirement; see `scope`."""
    return SimpleNamespace(
        skus=set(skus) - set(barred), pairs=pairs, sources=sources, supplier=supplier, reference=reference,
        key=key or (lambda sku_id, price: price), barred=frozenset(barred), delivered=delivered, reads=set(reads),
        # Retailers a recipe's delivery counts cannot serve: no site is built from such a world (see `model`).
        stranded=list(stranded),
        # The most a delivered total may be for its offer to count, where the task states a cap; a winner is under it.
        cap=cap,
        settled=settled or (lambda found: found if found["status"] == "match" else None))


def ranks(found, retailer_id, best=False):
    """What an offer of a retailer is ranked by, as a function of its SKU and listed price.

    The scope's key of the price; of the price with home delivery where the
    requirement compares delivered totals, which differ by retailer. Where a
    retailer's charge depends on which location ships, this is the highest it
    can be, or with `best` the lowest: the two the block model works between
    (see `model`). What an offer is actually charged is `lowest`'s to say,
    from where its stock is.
    """
    if found.delivered is None:
        return found.key
    charge = found.delivered[retailer_id].lowest if best else found.delivered[retailer_id].highest
    return lambda sku_id, price: found.key(sku_id, price + charge(price))


# For a ranking by delivered totals where a charge depends on the location that ships: how many samples of the
# block estimate the share that holds on the charges as they are, how many a sample may take, and the estimates
# made in this process.
PROPOSALS, TRIES, ESTIMATES = 200, 20000, {}


def delivering(world, requirement, api, skus, declared, feature):
    """The reading of a requirement that compares what one unit costs delivered home.

    The native single-item delivery task: among the offers that meet the
    predicates, the lowest payable total over the home-delivery options the
    retailer shows, for one unit and no coupon. A retailer's shown options and
    their tariffs are a fixed function of its contracts under admission plan
    version 2, and the waiver of its free-shipping threshold; both are read
    off the world as it is, so the reading depends on them (`reads`). An
    offer can be delivered when a location that ships holds it or it can be
    ordered from the supplier; pairs of retailers that show no home route do
    not compete.
    """
    package = api.basic.__package__
    native = import_module(package + ".quote_offer_task")
    commerce = api.commerce.__package__
    quotes, baskets, admission = (import_module(commerce + name) for name in (
        ".prepared_quote", ".basket_quote", ".delivery_admission"))
    website = import_module(package + ".delivery_options")
    options = requirement["delivered"].get("delivery_options", {})
    kinds = sorted(requirement["delivered"].get("delivery_types", ["home"]))
    listing = {r["retailer_id"] for r in world["retailers"] for o in r["offers"] if o["sku_id"] in skus}
    places = {rid: menus.oracle(world, rid, options, api, kinds) for rid in sorted(listing)}
    charges = {rid: menus.delivery(place) for rid, place in places.items()}
    delivered = {rid: charge for rid, charge in charges.items() if charge is not None}
    spec = {"kind": native.KIND, "concept_id": requirement["concept_id"], "predicates": requirement["predicates"],
            "delivery_types": kinds, **{key: requirement["delivered"][key] for key in ("max_total_minor",)
                                         if key in requirement["delivered"]}}

    def reference(found, **asked):
        # `asked` is what the native task reads and the block does not rank by: an objective, an arrival deadline.
        settings = next(iter(places.values())).settings if places else website.options({"enabled": True})
        plan = baskets.make_plan(found)
        try:
            sidecar = admission.make_plan(found, plan, seed=found["seed"], plan_version=menus.VERSION,
                                          count_weights=website.producer_weights(settings))
        except ValueError as error:
            if str(error) != menus.UNSUPPORTED:
                raise
            raise Unmet("The recipe's delivery counts have no support for a retailer of this world") from error
        context = quotes.prepare(found, plan=plan, admission_plan=sidecar)
        task = native.make(found, {**spec, **asked}, inventory=declared, quote_context=context)
        return task, native.reference(found, task, inventory=declared, quote_context=context)

    products = {s["sku_id"]: p["public"]["product_id"] for p in world["products"] for s in p["public"]["skus"]}
    return reading(
        skus, {(r["retailer_id"], o["product_id"]) for r in world["retailers"] if r["retailer_id"] in delivered
               for o in r["offers"] if o["sku_id"] in skus},
        {r["retailer_id"]: {s["source_id"] for s in r["source_locations"] if s["shipping_enabled"]} for r in world["retailers"]},
        True, reference, delivered=delivered, cap=requirement["delivered"].get("max_total_minor"),
        stranded=menus.stranded(next(iter(places.values()))) if places else [],
        # With counts that start above one route, every retailer's contracts decide whether a site is built at all.
        reads={(kind, rid, "") for rid in listing for kind in ("contracts", "threshold")} | {
            ("contracts", r["retailer_id"], "") for r in world["retailers"]
            if places and menus.least(next(iter(places.values()))) > 1})


def matching(world, concept, declared, predicates, feature):
    """The concept's SKUs that meet predicates, by the native evaluation."""
    compiled = feature.PredicateSet(declared.fields, predicates, known_paths=declared.known_paths)
    return {s["sku_id"] for p in world["products"] if p["public"]["concept_id"] == concept for s in p["public"]["skus"]
            if compiled.evaluate(p["public"], s, catalog_status=p.get("catalog_status", {}),
                                 sku_status=p.get("sku_status", {}).get(s["sku_id"], {}))["state"] == "match"}


def stocked(world):
    """The world with every listed offer holding one unit at every location.

    A native oracle lists as candidates the offers that are available; on this
    world those are the offers eligible apart from availability, with whatever
    the oracle ranks them by. Whether an eligible offer can actually become
    available is for the block's stock and supplier distributions to say.
    """
    return {**world, "retailers": [{**r, "offers": [{**o, "stock_by_source": dict.fromkeys(o["stock_by_source"], 1)}
                                                    for o in r["offers"]]} for r in world["retailers"]]}


def ranked(world, requirement, api, name, declared, pairs, sidecar, site):
    """The reading of a requirement whose ranking is not the listed price alone.

    Priorities: only SKUs whose prioritised facts are known compete, ranked by
    those facts in order and then by price. Unit basis: ranked by the listed
    price over the pack's net food mass. Both are read off the native
    oracle's candidates on the fully stocked world. Relaxations: the criteria
    set named by `selected` is compared on price, and every SKU meeting an
    earlier set is barred: it must be unavailable.
    """
    package, concept = api.basic.__package__, requirement["concept_id"]
    native, feature = import_module(package + RANKINGS[name]), import_module(package + ".feature_offer_task")
    spec = {"kind": native.KIND, "concept_id": concept, "predicates": requirement.get("predicates", []),
            "availability": requirement.get("availability", PURCHASABLE), name: requirement[name], **site}

    def reference(found):
        surrounding = sidecar(found)
        task = native.make(found, spec, inventory=declared, surrounding=surrounding)
        return task, native.reference(found, task, inventory=declared, surrounding=surrounding)

    supplier = spec["availability"] == PURCHASABLE
    if name == "relaxations":
        scenarios = native.make(world, spec, inventory=declared, surrounding=sidecar(world))["scenarios"]
        labels = [scenario["label"] for scenario in scenarios]
        if requirement["selected"] not in labels:
            raise ValueError("The selected criteria set is one of " + ", ".join(labels))
        chosen = labels.index(requirement["selected"])
        sets = [matching(world, concept, declared, scenario["feature_task"]["predicates"], feature)
                for scenario in scenarios[:chosen + 1]]
        return reading(sets[-1], pairs, None, supplier, reference, barred=set().union(*sets[:-1]),
                       settled=lambda found: (found["scenario_references"][chosen]
                                              if found["selected_index"] == chosen else None))
    rows = reference(stocked(world))[1]["candidates"]
    if name == "priorities":
        signs = [1 if row["direction"] == "min" else -1 for row in requirement["priorities"]]
        first = {row["sku_id"]: tuple(Decimal(str(value)) * sign for value, sign in zip(row["priority_values"], signs))
                 for row in rows}
        return reading(first, pairs, None, supplier, reference, key=lambda sku_id, price: (*first[sku_id], price))
    grams = {row["sku_id"]: row["quantity_g"] for row in rows}
    return reading(grams, pairs, None, supplier, reference, key=lambda sku_id, price: native.ratio(price, grams[sku_id]))


def scope(world, requirement, api):
    """Which offers compete and what makes one available, as the native task for the requirement reads them.

    `skus` are the concept's SKUs that compete (all of them without
    predicates); `pairs` the retailer/product pairs a comparison site confines
    the comparison to (None for all); `sources` gives, per retailer, the stock
    locations that count (None for all); `supplier` says whether a supplier
    order makes an offer available. `key(sku_id, price)` is what an offer is
    ranked by, lowest first; the listed price unless the requirement states
    another ranking. `barred` are SKUs that must be unavailable whatever their
    price. `reference(world)` is the native oracle's reading of a world for
    this requirement, and `settled(reference)` the part of it whose winners
    and candidates decide, or None when the requirement cannot hold.

    Reads only the concept and the fields `stated` checks, so other
    requirement kinds over the same block can use it.
    """
    stated(requirement)
    concept, package = requirement["concept_id"], api.basic.__package__
    items = [p for p in world["products"] if p["public"]["concept_id"] == concept]
    pairs, sidecar, site = None, lambda found: None, {}
    if "comparison_site_id" in requirement:
        (pairs, sidecar), site = listed(world, requirement, package), {
            "comparison_site_id": requirement["comparison_site_id"]}
    ranking = next((name for name in RANKINGS if name in requirement), None)
    if "predicates" not in requirement and not ranking:
        def reference(found):
            if not site:
                return edits._reference(found, requirement, api)
            surrounding = sidecar(found)
            task = api.basic.make(found, {"kind": "cheapest_available", "concept_id": concept, **site},
                                  surrounding=surrounding)
            return task, api.basic.reference(found, task, surrounding=surrounding)

        return reading({s["sku_id"] for p in items for s in p["public"]["skus"]}, pairs, None, True, reference)
    feature, branch = (import_module(package + name) for name in (".feature_offer_task", ".catalog_branch_task"))
    declared = inventory(package, concept)
    if ranking:
        return ranked(world, requirement, api, ranking, declared, pairs, sidecar, site)
    skus = matching(world, concept, declared, requirement["predicates"], feature)
    if "delivered" in requirement:
        return delivering(world, requirement, api, skus, declared, feature)
    spec = {"concept_id": concept, "predicates": requirement["predicates"], **site}
    if requirement.get("availability", PURCHASABLE) != BRANCH:
        spec.update(kind=feature.KIND, availability=requirement.get("availability", PURCHASABLE))

        def reference(found):
            surrounding = sidecar(found)
            task = feature.make(found, spec, inventory=declared, surrounding=surrounding)
            return task, feature.reference(found, task, inventory=declared, surrounding=surrounding)

        return reading(skus, pairs, None, spec["availability"] == PURCHASABLE, reference)
    spec.update(kind=branch.KIND, city=requirement["city"], country=requirement.get("country", "SE"))
    spec = branch.resolve(spec, inventory=declared, concept_ids=world["config"]["concept_ids"])

    def reference(found):
        surrounding = sidecar(found)
        task = branch.make(found, spec, inventory=declared, surrounding=surrounding)
        return task, branch.reference(found, task, inventory=declared, surrounding=surrounding)

    # The native rule: a pickup-enabled branch in the named city whose stock location is a branch.
    sources = {r["retailer_id"]: {
        b["branch_id"] for b in r["geography"]["branches"]
        if b["pickup_enabled"] and branch.text(b["location"]["city"]) == branch.text(spec["city"]) and
        b["location"]["country"] == spec["country"] and
        any(s["source_id"] == b["branch_id"] and s["kind"] == "branch" for s in r["source_locations"])}
        for r in world["retailers"]}
    return reading(skus, pairs, sources, False, reference)


def named(world, requirement, api, found=None):
    """The requirement, with every name and predicate it states checked against the world.

    A malformed requirement, an unknown name or an undeclared predicate is an
    error here, before any question of probability. Returns the requirement,
    each offer listed below the winner as its retailer/product pair and SKU,
    and the requirement's scope.
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
    # Who competes does not depend on stock or prices, so a scope read off the natural world serves a steered one.
    found = found or scope(world, requirement, api)
    below = []
    for row in requirement.get("listed_below", []):
        if row["retailer_id"] not in known or row["sku_id"] not in skus:
            raise ValueError("Unknown retailer or SKU")
        if concepts[skus[row["sku_id"]]] != requirement["concept_id"]:
            raise ValueError("An offer listed below the winner must be of the same concept")
        if row["sku_id"] not in found.skus or found.pairs is not None and (
                row["retailer_id"], skus[row["sku_id"]]) not in found.pairs:
            raise ValueError("An offer listed below the winner must itself compete")
        below.append(((row["retailer_id"], skus[row["sku_id"]]), row["sku_id"]))
    return requirement, below, found


def competing(world, requirement, found):
    """The listed retailer/product pairs of the concept with an offer that competes or is barred."""
    return {(r["retailer_id"], o["product_id"]) for r in world["retailers"] for o in r["offers"]
            if (o["sku_id"] in found.skus or o["sku_id"] in found.barred) and
            (found.pairs is None or (r["retailer_id"], o["product_id"]) in found.pairs)}


def footprint(world, requirement, api):
    """What the block decides: the stock and the price of every listed pair with an offer that competes."""
    requirement, _, found = named(world, requirement, api)
    pairs = competing(world, requirement, found)
    return SimpleNamespace(writes={(kind, *pair) for pair in pairs for kind in ("stock", "price")}, reads=set(found.reads))


def site(world, retailer, product_id, api, found):
    """One retailer/product pair: its offers, its stock locations and the draws' stream keys.

    `competing` are the offers the requirement compares, `counting` the
    locations whose stock makes one available. The other offers and locations
    belong to the pair's draws all the same.
    """
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
        competing=[o for o in offers if o["sku_id"] in found.skus], supplier_counts=found.supplier,
        barred=[o for o in offers if o["sku_id"] in found.barred], rank=ranks(found, rid),
        best=ranks(found, rid, best=True),
        counting=[l for l in locations if found.sources is None or l.source_id in found.sources[rid]],
        supplier_enabled=retailer["supplier_enabled"],
        eligible=min(1, max(0, config["supplier"]["sku_eligible_probability"])) if retailer["supplier_enabled"] else 0,
        keys={o["offer_id"]: {
            "supplier": stock.supplier_key(api, rid, o["sku_id"]),
            **{l.source_id: stock.stream_keys(api, rid, product_id, o["sku_id"], l.source_id) for l in locations}}
            for o in offers},
        price_key=prices.stream_keys([(rid, product_id)], api)[(rid, product_id)], chains={})


def places(world, found, api):
    """Every pair of the block, with its offers, locations and stream keys."""
    retailers = {r["retailer_id"]: r for r in world["retailers"]}
    return {pair: site(world, retailers[pair[0]], pair[1], api, found) for pair in sorted(competing(world, None, found))}


def sites(world, requirement, api):
    """The block's pairs with their stream keys, without the block model's probabilities."""
    requirement, below, found = named(world, requirement, api)
    return SimpleNamespace(requirement=requirement, places=places(world, found, api), below=below, scope=found)


def weight(location, count, stocked=None):
    """Probability that `count` SKUs hold nothing at a location, and a further one is stocked there or not."""
    return fsum(times(c.weight if stocked is None else c.full if stocked else c.zero, power(c.empty, count))
                for c in location.conditions.values())


def spared(place, count):
    """Probability that `count` SKUs with nothing to dispatch are all left without a supplier order.

    One where a supplier order does not make an offer available: it is then no part of the requirement.
    """
    return power(1 - place.eligible, count) if place.supplier_counts else 1.0


def nothing(place, count):
    """Probability that `count` SKUs of the pair are all unavailable.

    Unavailable is held at no location that counts and, where a supplier order
    counts, left without one. Locations draw their condition independently,
    and under a condition every SKU draws its own zero and quantity with the
    same probabilities, so this is a product over locations of a sum over
    conditions.
    """
    return times(spared(place, count), *(weight(location, count) for location in place.counting))


def chain(place, count):
    """The pair's stock with `count` SKUs unavailable and one further SKU, the witness, available.

    `forward[i][state]` is the probability that the first i locations that
    count hold none of the `count` SKUs and leave the witness in `state`;
    `ends` maps the ways the witness ends up available, (state, supplier
    order), to their probability. Where a supplier order does not count the
    witness must hold stock, and its supplier order is left open (None). Only sums of products of probabilities: an outcome has
    probability zero exactly when it cannot happen.
    """
    if count not in place.chains:
        forward = [{NOWHERE: 1.0, NOT_SHIPPABLE: 0.0, DISPATCH: 0.0}]
        for location in place.counting:
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
                (NOWHERE, True): times(forward[-1][NOWHERE], order, left)} if place.supplier_counts else {
                    (state, None): forward[-1][state] for state in (NOT_SHIPPABLE, DISPATCH)}
        ends = {end: mass for end, mass in ends.items() if mass > 0}
        place.chains[count] = SimpleNamespace(forward=forward, ends=ends, probability=fsum(ends.values()))
    return place.chains[count]


def outcomes(place, below, price_config, native_round):
    """Every way the pair's best available rank can come about, with its probability.

    Only the pair's competing offers are compared, by their rank: the listed
    price, unless the requirement ranks otherwise. One outcome per price atom
    and rank level of the pair under that atom: the SKUs ranked ahead are
    unavailable and at least one SKU at the level is available; and one per
    atom for no SKU being available (rank None). The pair's barred SKUs are
    unavailable in every outcome. `ceiling` is the last rank among the pair's
    offers that must be listed below the winner, so the outcome counts only
    for a winning rank after it.
    """
    result = []
    for atom in prices.atoms([o["price_trace"]["reference_minor"] for o in place.offers], price_config):
        draw = prices.representative(atom)
        listed = {o["offer_id"]: place.rank(o["sku_id"], edits._price(
            o["price_trace"]["reference_minor"], draw, price_config, native_round)) for o in place.competing}
        ceiling = max((listed[offer_id] for offer_id in below), default=None)
        ahead = list(place.barred)
        for rank in sorted(set(listed.values())):
            level = [o for o in place.competing if listed[o["offer_id"]] == rank]
            # The first available SKU at the level, in offer order, is the witness.
            mass = times(atom[0], fsum(chain(place, len(ahead) + index).probability for index in range(len(level))))
            result.append(SimpleNamespace(mass=mass, rank=rank, atom=atom, ceiling=ceiling,
                                          cheaper=list(ahead), level=level))
            ahead += level
        result.append(SimpleNamespace(mass=times(atom[0], nothing(place, len(ahead))), rank=None, atom=atom,
                                      ceiling=ceiling, cheaper=ahead, level=[]))
    return [found for found in result if found.mass > 0]


def accepts(found, winning, designated):
    """Whether an outcome of a pair fits a winning rank: at it for a designated pair, after it or absent otherwise."""
    if found.ceiling is not None and found.ceiling >= winning:
        return False
    return found.rank == winning if designated else found.rank is None or found.rank > winning


class Spread:
    """A pair's outcomes, summed by best available rank.

    For a pair with no offer that must be listed below the winner, the two
    sums the requirement needs are tabulated once: the probability of a rank
    exactly, and of every rank after it together with no available offer.
    Sums run from the last rank down, over probabilities only.
    """

    def __init__(self, found):
        self.outcomes = found
        self.table = all(o.ceiling is None for o in found)
        if self.table:
            by_price = {}
            for outcome in found:
                by_price.setdefault(outcome.rank, []).append(outcome.mass)
            absent = fsum(by_price.pop(None, []))
            self.prices = sorted(by_price)
            self.at = {price: fsum(by_price[price]) for price in self.prices}
            self.from_index = [absent]
            for price in reversed(self.prices):
                self.from_index.append(self.from_index[-1] + self.at[price])
            self.from_index.reverse()
            self.to_index = [0.0]
            for price in self.prices:
                self.to_index.append(self.to_index[-1] + self.at[price])

    def mass(self, winning, designated):
        if not self.table:
            return fsum(o.mass for o in self.outcomes if accepts(o, winning, designated))
        return self.at.get(winning, 0.0) if designated else self.from_index[bisect_right(self.prices, winning)]

    def before(self, rank):
        """The probability of a best available rank ahead of the given one; tabulated spreads only."""
        return self.to_index[bisect_left(self.prices, rank)]


def reading_of(requirement):
    """The part of a requirement that says who competes, what is available and how offers rank."""
    return json.dumps({key: value for key, value in requirement.items()
                       if key not in ("schema", "product_id", "retailer_ids", "listed_below")}, sort_keys=True)


def frame(world, requirement, api, charges=None):
    """What every requirement with one reading shares on one world.

    `charges` replaces, for a ranking by delivered totals, the delivery charge
    of the retailers it names (see `couriers.py`, which redraws a retailer's
    contracts beside the ranking); their pairs then compete whether or not
    the retailer shows a home route as its contracts are.

    The scope, the block's pairs and, filled in as they are first needed, the
    spread of each pair when none of its offers is named as listed below the
    winner. Building these is most of a block model's cost, so a caller that
    models many requirements of one reading (other winners, other named
    offers) passes one frame to all of them.
    """
    stated(requirement)
    found = scope(world, requirement, api)
    if charges:
        found.delivered = {**found.delivered, **charges}
        found.pairs = found.pairs | {(r["retailer_id"], o["product_id"]) for r in world["retailers"]
                                     if r["retailer_id"] in charges for o in r["offers"] if o["sku_id"] in found.skus}
    return SimpleNamespace(world=world, reading=reading_of(requirement), scope=found,
                           places=places(world, found, api), plain={})


def model(world, requirement, api, shared=None, estimate=True):
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

    `shared` is a `frame` for this world and this requirement's reading; the
    result is the same with and without it.

    A ranking by delivered totals with a retailer whose charge depends on the
    location that ships has no such product: an offer's rank then depends on
    where its stock is. For one designated pair the block is modelled with
    that pair charged the least it can be and every other pair the most. The
    requirement on the charges as they are implies that one, so samples of
    the latter that also satisfy the former are samples given the
    requirement (`prepare` draws until one does), and the probability is the
    modelled one times the share of `PROPOSALS` such samples that do: an
    estimate, with its standard error in `error`. Without `estimate` the
    bounded block is returned as it is, for a caller that accepts its samples
    on a condition of its own.
    """
    if shared is not None and (shared.world is not world or shared.reading != reading_of(resolve(requirement))):
        raise ValueError("A shared frame serves one world and one reading")
    requirement, named_below, block_scope = named(world, requirement, api, shared and shared.scope)
    if block_scope.stranded:
        raise ZeroMass("no_outcome", "The recipe's delivery counts have no support for a retailer of this world, so no "
                                     "site is built from it: " + ", ".join(block_scope.stranded))
    shared = shared or SimpleNamespace(places=places(world, block_scope, api), plain={})
    sited = shared.places
    designated = {(rid, requirement["product_id"]) for rid in requirement["retailer_ids"]}
    if not all(pair in sited and sited[pair].competing for pair in designated):
        raise ZeroMass("not_listed", "A designated retailer lists no competing offer of the product in this world")
    below = {}
    for pair, sku_id in named_below:
        offer = next((o for o in sited[pair].offers if o["sku_id"] == sku_id), None) if pair in sited else None
        if offer is None:
            raise ZeroMass("not_listed", "The retailer does not list this SKU in this world")
        below.setdefault(pair, []).append(offer["offer_id"])
    config, native_round = world["config"]["retailer_price"], api.native.rounded_price
    bounded = block_scope.delivered is not None and not all(found.uniform for found in block_scope.delivered.values())
    if bounded and (len(designated) != 1 or below):
        raise ValueError("Not modelled: several winners, or offers listed below the winner, where a retailer's delivery "
                         "charge depends on which location ships")
    spread = {}
    for pair, place in sited.items():
        if pair in below:
            spread[pair] = Spread(outcomes(place, below[pair], config, native_round))
        elif bounded and pair in designated:
            lowered = vars(shared).setdefault("best", {})
            if pair not in lowered:
                lowered[pair] = Spread(outcomes(SimpleNamespace(**{**vars(place), "rank": place.best}), (), config, native_round))
            spread[pair] = lowered[pair]
        else:
            if pair not in shared.plain:
                shared.plain[pair] = Spread(outcomes(place, (), config, native_round))
            spread[pair] = shared.plain[pair]
    log_terms = {}
    for price in sorted(set.intersection(*({o.rank for o in spread[pair].outcomes} for pair in designated)) - {None}):
        # A capped task counts no offer above its cap. Between charge bounds the designated pair's rank is the
        # least its total can be, so a total under the cap is a rank under it.
        if block_scope.cap is not None and price > block_scope.cap:
            continue
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
    block = SimpleNamespace(requirement=requirement, places=sited, designated=designated, spread=spread,
                            log_terms=log_terms, log_probability=log_probability, probability=exp(log_probability),
                            shares={price: exp(value - log_probability) for price, value in log_terms.items()},
                            below=below, config=config, native_round=native_round, scope=block_scope,
                            bounded=bounded, estimated=bounded, accepted=None, error=0.0)
    if bounded and not estimate:
        block.shares = None
    elif bounded:
        key = world["world_id"], json.dumps(requirement, sort_keys=True)
        if key not in ESTIMATES:
            # The same draws for the same world and requirement, in this process and the next.
            rng = Random(api.native.digest({"world_id": world["world_id"], "requirement": requirement}))
            ESTIMATES[key] = sum(true(block, sample(block, rng)[1]) for _ in range(PROPOSALS))
        block.accepted = ESTIMATES[key]
        if not block.accepted:
            # Not a proof that it cannot occur: callers report it as not found.
            raise ZeroMass("not_found", f"None of {PROPOSALS} samples of the block has the designated pair cheapest on "
                                        "the delivery charges as they are")
        share = block.accepted / PROPOSALS
        block.log_probability += log(share)
        block.probability *= share
        block.error = block.probability * ((1 - share) / (share * PROPOSALS)) ** .5
        # The winning ranks above are the bounded block's; given the requirement they are not modelled.
        block.shares = None
    return block


def true(block, draws):
    """Whether planned draws satisfy the requirement on what every offer is actually charged for delivery."""
    return judged(planned(block, draws), block.requirement, block.scope) is not None


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
        raise NumericalLimit("Outcomes are too far apart in probability to choose among")
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
    producer does not draw it). The competing SKUs listed cheaper are
    unavailable, so is every SKU at the level before the witness, and the
    witness is available. The requirement says nothing more given the
    conditions: every other SKU, every location that does not count, and a
    supplier order that does not count are drawn as the producer draws them.
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
    count = len(unavailable)
    for index in reversed(range(len(place.counting))):
        location = place.counting[index]
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
    for location in place.locations:
        if location.source_id not in conditions:
            names = sorted(location.conditions)
            conditions[location.source_id] = pick(rng, names, [location.conditions[name].weight for name in names])
    draws = SimpleNamespace(conditions=conditions, offers={}, witness=witness and witness["offer_id"],
                            unavailable=[o["offer_id"] for o in unavailable])
    counts = {location.source_id for location in place.counting}
    held_out = {o["offer_id"] for o in unavailable}
    others = [o for o in place.offers if o["offer_id"] not in held_out and o is not witness]
    for offer in unavailable + ([witness] if witness is not None else []) + others:
        fixed = (lambda name: False) if offer["offer_id"] in held_out else stocked.get if offer is witness else None
        quantities = {l.source_id: held(rng, l, conditions[l.source_id],
                                        fixed(l.source_id) if fixed and l.source_id in counts else None)
                      for l in place.locations}
        if not place.supplier_enabled or any(l.shipping and quantities[l.source_id] for l in place.locations):
            order = None
        elif fixed and place.supplier_counts:
            order = supplier if offer is witness else False
        else:
            order = rng.random() < place.eligible
        draws.offers[offer["offer_id"]] = {"quantities": quantities, "supplier": order}
    return draws


def sample(block, rng):
    """Sample the block's stock and price draws from a block model.

    Returns the sampled winning price and, per pair, the price draw and the
    stock draws. No draw of the world the model was built on is consulted, so
    repeated samples are independent draws of the same conditional
    distribution.
    """
    winning = pick_log(rng, sorted(block.log_terms), [block.log_terms[price] for price in sorted(block.log_terms)])
    return winning, {pair: settle(block, pair, [o for o in block.spread[pair].outcomes
                                                if accepts(o, winning, pair in block.designated)], rng)
                     for pair in sorted(block.places)}


def settle(block, pair, options, rng):
    """One pair's price and stock draws, given the outcomes its best available rank may take."""
    place = block.places[pair]
    outcome = pick(rng, options, [o.mass for o in options])
    return SimpleNamespace(price=prices.draw_within(outcome.atom, place.offers, block.config, block.native_round, rng),
                           stock=stocking(place, outcome, rng), cheapest_available=outcome.rank)


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


def plain(rank):
    """A rank as JSON: a price as it is, a price per gram as two integers, facts and price as a list."""
    if isinstance(rank, Fraction):
        return {"numerator": rank.numerator, "denominator": rank.denominator}
    return [str(part) if isinstance(part, Decimal) else part for part in rank] if isinstance(rank, tuple) else rank


def restocked(natural, block, draws):
    """What the planned stock draws do to each pair."""
    return [{"retailer_id": pair[0], "product_id": pair[1],
             "cheapest_available_minor": plain(draws[pair].cheapest_available),
             "competing_offers": len(block.places[pair].competing),
             "natural_conditions": conditions(natural, pair), "steered_conditions": draws[pair].stock.conditions,
             "held_unavailable": draws[pair].stock.unavailable, "held_available": draws[pair].stock.witness,
             "offers": len(block.places[pair].offers)} for pair in sorted(draws)]


def check(world, requirement, api, found=None):
    """Read the requirement off a world with the native oracle: the winners, and the offers listed below them."""
    requirement, _, found = named(world, requirement, api, found)
    edits.check_price_rule(world, api.native.rounded_price)
    task, reference = found.reference(world)
    decided = found.settled(reference)
    designated = {(rid, requirement["product_id"]) for rid in requirement["retailer_ids"]}
    if decided is None or not decided["winners"] or {
            (w["retailer_id"], w["product_id"]) for w in decided["winners"]} != designated:
        raise Unmet("The best available offers are not exactly the designated retailers' product")
    winning = ranks(found, decided["winners"][0]["retailer_id"])(decided["winners"][0]["sku_id"],
                                                                 decided["winners"][0]["price_minor"])
    listed = {o["offer_id"]: o for r in world["retailers"] for o in r["offers"]}
    offers = {(r["retailer_id"], o["sku_id"]): o["offer_id"] for r in world["retailers"] for o in r["offers"]}
    candidates = {row["offer_id"] for row in decided["candidates"]}
    below = []
    for row in requirement.get("listed_below", []):
        offer_id = offers.get((row["retailer_id"], row["sku_id"]))
        if (offer_id is None or offer_id in candidates or
                ranks(found, row["retailer_id"])(row["sku_id"], listed[offer_id]["price_minor"]) >= winning):
            raise Unmet(f"{row['retailer_id']} does not list {row['sku_id']} unavailable below the winner")
        below.append({"offer_id": offer_id, "price_minor": listed[offer_id]["price_minor"]})
    return {"task": task, "reference": reference, "listed_below": below}


def prepare(natural, requirement, api, rng):
    """Sample the block on the natural world; the step replays it and reads the result."""
    block = model(natural, requirement, api)
    for tries in range(1, TRIES + 1):
        winning, draws = sample(block, rng)
        if not block.bounded or true(block, draws):
            break
    else:
        raise NumericalLimit("Samples that hold on the delivery charges as they are are too rare to reach")
    if block.bounded:
        # The ranks sampled are the bounded block's; what is recorded is what the accepted leaves give.
        best, _ = lowest(planned(block, draws), block.scope)
        winning = min(best.values())
        for pair, drawn in draws.items():
            drawn.cheapest_available = best.get(pair)
    concept_id = block.requirement["concept_id"]

    def record(world):
        if recorded(world, concept_id, set(block.places)) != planned(block, draws):
            raise streams.PlanMismatch("The producer recorded other stock or price leaves than planned")
        return {"method": "exact_conditional_stock_and_price_block" + (
                    "_between_charge_bounds_then_rejection" if block.bounded else ""), "requirement": block.requirement,
                "natural_world_id": natural["world_id"],
                **({"probability_is_estimated": True, "probability_standard_error": block.error,
                    "proposals": PROPOSALS, "proposals_accepted": block.accepted,
                    "block_samples_for_this_sample": tries} if block.bounded else {}),
                # None when the probability is below the float range; the logarithm always holds.
                "probability_given_upstream": block.probability or None,
                "log_probability_given_upstream": block.log_probability,
                # The winning rank: the winners' listed price, unless the requirement ranks otherwise.
                **({"winning_price_minor": winning} if type(winning) is int else {"winning_rank": plain(winning)}),
                "repriced": prices.replayed(natural, world, {pair: found.price for pair, found in draws.items()},
                                            {pair: block.places[pair].price_key for pair in draws}),
                "restocked": restocked(natural, block, draws),
                "distribution_claim": "For every listed retailer/product pair of the concept with an offer that "
                                      "competes under the requirement, the price draw, the "
                                      "stock condition at every location and every SKU's stock and supplier "
                                      "draws are sampled from their distribution given the requirement and all "
                                      "upstream draws, under the models in prices.atoms and cheapest.chain. "
                                      "None of the seed's own draws of these is kept. " + (
                                          "A delivery charge here depends on which location ships: the block was "
                                          "modelled with the winner charged its least and the others their most, "
                                          "samples were drawn until one held on the charges as they are, and the "
                                          "probability is the modelled one times an estimated share. "
                                          if block.bounded else "") + "Upstream draws are not "
                                      "reweighted; use the probability given upstream as the importance "
                                      "weight across seeds."}

    return Step(script=scripts(block, draws), probability=block.probability, log_probability=block.log_probability,
                error=block.error, estimated=block.bounded,
                writes={(kind, *pair) for pair in block.places for kind in ("stock", "price")},
                reads=set(block.scope.reads),
                record=record, check=lambda world: check(world, requirement, api, block.scope))


def steer(session, natural, natural_opened, requirement, api, rng):
    """Plan on the natural world, regenerate through the real producer, verify."""
    return blocks.steer(session, natural, natural_opened, prepare(natural, requirement, api, rng), api)


def lowest(found, limits=None):
    """Each pair's best rank among its available offers, and every compared offer's rank.

    The native oracles' rule written out separately from the block model.
    Among the offers that compete, one is available when it holds stock at a
    location that counts or, where that counts, has a supplier order; offers
    of pairs a comparison site does not list are left out. Returns (None,
    None) when a barred offer is available. Without `limits` (a scope) every
    offer competes on its listed price, every location counts and so does a
    supplier order.
    """
    best, compared = {}, {}
    for row in found["offers"].values():
        barred = limits is not None and row["sku_id"] in limits.barred
        if limits is not None and (row["sku_id"] not in limits.skus and not barred or limits.pairs is not None and
                                   (row["retailer_id"], row["product_id"]) not in limits.pairs):
            continue
        sources = None if limits is None or limits.sources is None else limits.sources[row["retailer_id"]]
        stocked = any(quantity for name, quantity in row["stock_by_source"].items() if sources is None or name in sources)
        available = stocked or row["supplier_order"] and (limits is None or limits.supplier)
        if barred:
            if available:
                return None, None
            continue
        if limits is None:
            rank = row["price_minor"]
        elif limits.delivered is None:
            rank = limits.key(row["sku_id"], row["price_minor"])
        else:
            # The charge as the oracle makes it: from the locations that ship and hold the offer, else the warehouse.
            charged = limits.delivered[row["retailer_id"]]
            holding = [name for name, quantity in row["stock_by_source"].items() if quantity and name in sources]
            rank = limits.key(row["sku_id"], row["price_minor"] + charged.at(row["price_minor"], holding or [charged.warehouse]))
        compared[(row["retailer_id"], row["sku_id"])] = rank
        if available:
            pair = (row["retailer_id"], row["product_id"])
            best[pair] = min(best.get(pair, rank), rank)
    return best, compared


def judged(found, requirement, limits=None):
    """The winning rank when recorded leaves satisfy the requirement, else None.

    The winners are the pairs whose best available rank is the lowest of all;
    see `lowest` for what is compared.
    """
    best, compared = lowest(found, limits)
    if not best:
        return None
    winning = min(best.values())
    if limits is not None and limits.cap is not None and winning > limits.cap:
        return None
    if {pair for pair, rank in best.items() if rank == winning} != {
            (rid, requirement["product_id"]) for rid in requirement["retailer_ids"]}:
        return None
    below = [compared.get((row["retailer_id"], row["sku_id"]), winning) for row in requirement.get("listed_below", [])]
    return winning if all(rank < winning for rank in below) else None


def recorded(world, concept_id, pairs=None):
    """The block's leaves as a world records them: conditions, and every offer's price and stock.

    For the given retailer/product pairs, or every listed pair of the concept.
    """
    concepts = {p["public"]["product_id"]: p["public"]["concept_id"] for p in world["products"]}
    within = lambda retailer, product_id: (concepts[product_id] == concept_id and
                                           (pairs is None or (retailer["retailer_id"], product_id) in pairs))
    return {"conditions": {"/".join((r["retailer_id"], row["product_id"], row["source_id"])): row["condition"]
                           for r in world["retailers"] for row in r["conditions"] if within(r, row["product_id"])},
            "offers": {o["offer_id"]: {"retailer_id": r["retailer_id"], "product_id": o["product_id"],
                                       "sku_id": o["sku_id"], "price_minor": o["price_minor"],
                                       "stock_by_source": dict(o["stock_by_source"]),
                                       "supplier_order": o["supplier_order"]["enabled"]}
                       for r in world["retailers"] for o in r["offers"] if within(r, o["product_id"])}}


def reader(natural, places, api):
    """This module's reading of the producer's stock and price lines for pairs, under another seed.

    Uses the producer's own stream, weighted-choice and pricing functions and
    none of the block model. Returns `reading(seed)`, in the form of
    `recorded`, and the stream keys it opens.
    """
    config = natural["config"]
    products = {p["public"]["product_id"]: p["public"] for p in natural["products"]}
    skus = {s["sku_id"]: s for p in products.values() for s in p["skus"]}

    def reading(seed):
        stream = lambda key: api.population.stream(seed, key)
        found = {"conditions": {}, "offers": {}}
        for pair, place in places.items():
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

    keys = {place.price_key for place in places.values()}
    for place in places.values():
        keys.update(l.condition_key for l in place.locations)
        for row in place.keys.values():
            keys.add(row["supplier"])
            keys.update(key for name, found in row.items() if name != "supplier" for key in found.values())
    return reading, keys


def trial(natural, requirement, api):
    """The block's reading under another seed, with the requirement's verdict on it.

    `blocks.redraw` checks the reading against the real producer leaf for
    leaf; it is then cheap enough to estimate frequencies from.
    """
    block = sites(natural, requirement, api)
    requirement = block.requirement
    reading, keys = reader(natural, block.places, api)
    return SimpleNamespace(
        keys=keys, writes={(kind, *pair) for pair in block.places for kind in ("stock", "price")},
                reads=set(block.scope.reads),
        reading=reading,
        winning=lambda seed: judged(reading(seed), requirement, block.scope),
        holds=lambda seed: judged(reading(seed), requirement, block.scope) is not None,
        recorded=lambda world: recorded(world, requirement["concept_id"], set(block.places)),
        satisfied=lambda world: satisfied(world, requirement, api, block.scope))


def satisfied(world, requirement, api, found=None):
    try:
        return bool(check(world, requirement, api, found))
    except Unmet:
        return False


def empirical(natural, requirement, api, trials, first_seed):
    """How often the requirement holds under other seeds, by winning price."""
    winning = trial(natural, requirement, api).winning
    found = (winning(seed) for seed in range(first_seed, first_seed + trials))
    return Counter(price for price in found if price is not None)
