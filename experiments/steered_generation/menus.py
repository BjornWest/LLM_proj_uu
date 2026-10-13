"""The delivery options a retailer shows and what each costs, as a function of its contracts.

A site built from a world with delivery options on does not show every route
a retailer's contracts allow: the commerce oracle admits a menu per retailer
(`delivery_admission`). Under admission plan version 2 the menu is drawn on
the seed, the retailer and that retailer's real routes, so it is a fixed
function of the retailer's contracts in a given world and does not move when
stock, prices or fees are steered. Version 1 draws on the finished world's
id and cannot be read before the world exists; a statement about shown
options is therefore read for version 2 only.

A clause states, for the carrier routes a retailer shows to the customer's
address (home delivery, or home delivery and collection points; pickup at the
retailer's own branches is not a carrier's), which carriers must and must not
be among them and which carrier has the cheapest one. What a route costs is
the oracle's own tariff for an ordinary parcel that every source can ship,
from the source it is cheapest from, before any free-shipping waiver: the
contract's fee for the tier and the destination, the tier's surcharge and the
distance. Cheapest means strictly cheaper than every other carrier's
cheapest shown route.

Everything here runs the oracle's own lines (`_rows`, `_potential`,
`_carrier_candidates`) on a view of the world with the retailer's contracts
replaced; `official` reads the same off a finished world through the public
plan, and the two are compared whenever a steered world is checked.
"""
from importlib import import_module
import json
from types import SimpleNamespace

VERSION = "retailer-delivery-admission-plan-v2"
SCOPES = ("home", "any")
# The oracle's default terms for a contract's carrier, which is what a plan made without overrides carries.
TERMS = {"bulky_supported": False, "bulky_surcharge_minor": 0, "bulky_extra_days": 0, "arrival_window_days": 0}
UNSUPPORTED = "No positive count mass within the real route bound"
# Per world and count weights: the retailers with routes and no count the recipe can draw for them.
STRANDED = {}


def resolve(clause):
    stated = {"carriers", "cheapest_carrier"}
    if (type(clause) is not dict or not clause or set(clause) - stated - {"delivery_options", "destination_type"} or
            not stated & set(clause) or clause.get("destination_type", "home") not in SCOPES):
        raise ValueError("Shown options state carriers to include or exclude, the cheapest carrier, or both; for home "
                         "delivery or for any carrier route")
    named = clause.get("carriers", {"include": ["carrier"]})
    if (type(named) is not dict or not named or set(named) - {"include", "exclude"} or
            any(type(row) is not list or not row or any(type(name) is not str or not name for name in row) or
                len(set(row)) != len(row) for row in named.values()) or
            set(named.get("include", [])) & set(named.get("exclude", []))):
        raise ValueError("Shown carriers are nonempty lists of carrier ids to include, to exclude or both, none in both")
    cheapest = clause.get("cheapest_carrier", "carrier")
    if type(cheapest) is not str or not cheapest or cheapest in named.get("exclude", []):
        raise ValueError("The cheapest shown carrier is a carrier id that is not excluded")
    if "delivery_options" in clause and type(clause["delivery_options"]) is not dict:
        raise ValueError("Delivery options are a site recipe's settings")
    return json.loads(json.dumps(clause))


def needed(clause):
    """The carriers a retailer must have a contract with for the clause to hold."""
    return sorted(set(clause.get("carriers", {}).get("include", [])) | ({clause["cheapest_carrier"]} if "cheapest_carrier" in clause else set()))


def site(world, retailer_id, clause, api):
    """The oracle's modules, the recipe's count weights and what of the world a retailer's menu is read from."""
    clause = resolve(clause)
    carriers = {row["carrier_id"] for row in world["address_context"]["carriers"]}
    if set(needed(clause)) - carriers or set(clause.get("carriers", {}).get("exclude", [])) - carriers:
        raise ValueError("Unknown carrier")
    found = oracle(world, retailer_id, clause.get("delivery_options", {}), api)
    found.clause, found.scope = clause, clause.get("destination_type", "home")
    return found


def oracle(world, retailer_id, stated, api):
    """The same for a recipe's delivery settings alone, for home delivery."""
    website = import_module(api.basic.__package__ + ".delivery_options")
    # A recipe's own settings; version 2 is the only one a menu can be read for, so it is what is asked for.
    if (type(stated) is not dict or type(stated.get("enabled", True)) is not bool or not stated.get("enabled", True) or
            stated.get("admission_plan", VERSION) != VERSION):
        raise ValueError("Shown options are read for delivery options enabled under admission plan version 2")
    settings = website.options({**stated, "enabled": True, "admission_plan": VERSION})
    admission = import_module(api.commerce.__package__ + ".delivery_admission")
    if website.producer_plan_version(settings) != VERSION or VERSION not in admission.PLAN_VERSIONS:
        raise ValueError("The commerce oracle does not have admission plan version 2")
    backend = admission._backend(world)
    retailer = next((row for row in world["retailers"] if row["retailer_id"] == retailer_id), None)
    if retailer is None:
        raise ValueError("Unknown retailer")
    if type(world.get("seed")) is not int or world["seed"] < 0:
        raise ValueError("The world does not record the seed its delivery menus are drawn on")
    return SimpleNamespace(clause=None, world=world, retailer=retailer, retailer_id=retailer_id, admission=admission,
                           backend=backend, settings=settings, weights=admission._weights(website.producer_weights(settings)),
                           destination=world["user_location"], scope="home")


def least(place):
    """The smallest number of routes the recipe's counts can draw."""
    return min(row["count"] for row in place.weights if row["weight"] > 0)


def stranded(place):
    """The retailers of the world, as their contracts are, that have routes but fewer than the recipe can draw.

    A site has one admission plan for all its retailers, and generation
    rejects a world where the recipe's counts have no support for one of
    them. So a statement about any retailer's shown options can hold only
    where no other retailer is stranded; with counts from one upwards none is.
    """
    key = place.world["world_id"], json.dumps(place.weights, sort_keys=True)
    if key not in STRANDED:
        found = []
        for retailer in place.world["retailers"]:
            mine = {**retailer, "offers": []}
            view = {**place.world, "products": [], "retailers": [mine]}
            policy = {"retailer_id": retailer["retailer_id"],
                      "carrier_terms": [{"carrier_id": row["carrier_id"], **TERMS} for row in retailer["contracts"]]}
            routes = len(place.admission._potential(place.backend, view, mine, policy, place.destination))
            if 0 < routes < least(place):
                found.append(retailer["retailer_id"])
        STRANDED[key] = sorted(found)
    return STRANDED[key]


def priced(place, world, retailer, policy, admitted, detail=False):
    """The admitted carrier routes in scope with the oracle's tariff for an ordinary parcel any source can ship.

    With `detail`, each row also carries the oracle's candidates, one per
    source that could ship the parcel.
    """
    product = {"facts": {"shipping_class": "regular"}}
    offer = {"stock_by_source": {source["source_id"]: 1 for source in retailer["source_locations"]},
             "supplier_order": {"enabled": False, "wait_days": None}}
    rows = []
    for choice in place.admission._potential(place.backend, world, retailer, policy, place.destination):
        key = place.admission.route_key(choice)
        if key not in admitted or choice["destination_type"] == "retailer_branch" or (
                place.scope == "home" and choice["destination_type"] != "home"):
            continue
        found = place.backend._carrier_candidates(world, retailer, policy, product, offer, 1, choice)
        if not found:
            raise AssertionError("An admitted route that no source can ship on")
        rows.append({"route_key": key, "carrier_id": choice["carrier_id"], "tier": choice["tier"],
                     "destination_type": choice["destination_type"], "point_id": choice["point_id"],
                     "charge_minor": min(row["raw_shipping_minor"] for row in found),
                     **({"candidates": found} if detail else {})})
    return sorted(rows, key=lambda row: (row["charge_minor"], row["route_key"]))


def shown(place, contracts, detail=False):
    """A retailer's shown carrier routes if these were its contracts; None where the recipe's counts have no support.

    The world is viewed with this one retailer, its contracts replaced and
    its offers left out: a menu reads the offers only for whether one is
    bulky, and no product of a catalog world is.
    """
    retailer = {**place.retailer, "contracts": contracts, "offers": []}
    view = {**place.world, "products": [], "retailers": [retailer]}
    policy = {"retailer_id": place.retailer_id,
              "carrier_terms": [{"carrier_id": row["carrier_id"], **TERMS} for row in contracts]}
    try:
        row, = place.admission._rows(place.backend, view, {"retailer_policies": [policy]}, place.world["seed"],
                                     place.weights, {}, place.destination, VERSION)
    except ValueError as error:
        if str(error) != UNSUPPORTED:
            raise
        return None
    return priced(place, view, retailer, policy, set(row["admitted_route_keys"]), detail)


def ceiling(place):
    """An amount no home route of the retailer costs more than, whatever its contracts.

    The dearest tariff over every carrier, tier and location that ships, with
    the highest fees the producer draws for a contract.
    """
    policy = place.world["shipping_policy"]
    highest = lambda table: max(int(value) for value in policy[table])
    contracts = [{"carrier_id": row["carrier_id"], "tiers": sorted(policy["service_relations"], key=lambda tier: tier != "standard"),
                  "collection_fee_minor": highest("retailer_carrier_standard_collection_base_fee_minor_probabilities"),
                  "home_delta_minor": highest("home_delivery_relative_to_collection_minor_probabilities")}
                 for row in place.world["address_context"]["carriers"]]
    retailer = {**place.retailer, "contracts": contracts, "offers": []}
    view = {**place.world, "products": [], "retailers": [retailer]}
    terms = {"retailer_id": place.retailer_id,
             "carrier_terms": [{"carrier_id": row["carrier_id"], **TERMS} for row in contracts]}
    every = {place.admission.route_key(choice)
             for choice in place.admission._potential(place.backend, view, retailer, terms, place.destination)}
    home = SimpleNamespace(**{**vars(place), "scope": "home"})
    return max((found["raw_shipping_minor"] for row in priced(home, view, retailer, terms, every, detail=True)
                for found in row["candidates"]), default=0)


def delivery(place, contracts=None):
    """What home delivery of one unit adds to a price at the retailer, as the oracle charges it; None where it shows no
    home route. For the retailer's own contracts, or for others in their place.

    Per shown home route the oracle ships from the location, among those that
    hold the offer and ship, with the lowest tariff, and the offer's charge is
    the lowest over the routes; the ordinary, distance and geographic parts
    are waived where the retailer offers free shipping from a subtotal the
    price reaches and the parcel does not cross a border. A supplier order
    ships from the warehouse. `at(price, held)` is that charge for the
    locations that hold the offer; `lowest(price)` and `highest(price)` bound
    it over every set of locations, and `uniform` says they are equal, so
    that the charge does not depend on where the stock is. Refused: a
    retailer where whether an offer can be delivered depends on which
    location holds it (a location that ships without a route, a warehouse
    that does not ship).
    """
    rows = shown(place, place.retailer["contracts"] if contracts is None else contracts, detail=True)
    if not rows:
        return None
    sources = place.retailer["source_locations"]
    shipping = sorted(source["source_id"] for source in sources if source["shipping_enabled"])
    routes = []
    for row in rows:
        route = {found["source_id"]: (found["raw_shipping_minor"], found["raw_shipping_minor"] if found["foreign"] else
                                      found["tariff_components"]["express_minor"]) for found in row["candidates"]}
        if not sources[0]["shipping_enabled"] or sorted(route) != shipping:
            raise ValueError("Not modelled: a retailer where whether an offer can be delivered depends on which location holds it")
        if any(a[0] == b[0] and a != b for a in route.values() for b in route.values()):
            raise ValueError("Not modelled: locations with one tariff of which only some are waived")
        routes.append(route)
    threshold = place.retailer["free_shipping_threshold_minor"]

    def at(price, held):
        waived = threshold is not None and price >= threshold
        # The oracle's dispatch: per route the location with the lowest tariff before any waiver.
        return min(route[min(held, key=lambda name: route[name][0])][waived] for route in routes)

    subsets = [[name for index, name in enumerate(shipping) if mask >> index & 1] for mask in range(1, 2 ** len(shipping))]
    bounds = lambda pick: (lambda price: pick(at(price, held) for held in subsets))
    return SimpleNamespace(at=at, lowest=bounds(min), highest=bounds(max), warehouse=sources[0]["source_id"],
                           uniform=all(len(set(route.values())) == 1 for route in routes))


def official(world, place):
    """The same off a finished world, through the plans a site is built from; None where generation rejects the world."""
    plan = place.backend.make_plan(world)
    try:
        sidecar = place.admission.make_plan(world, plan, seed=world["seed"], plan_version=VERSION,
                                            count_weights={row["count"]: row["weight"] for row in place.weights})
    except ValueError as error:
        if str(error) != UNSUPPORTED:
            raise
        return None
    place.admission.validate_plan(world, plan, sidecar)
    retailer = next(row for row in world["retailers"] if row["retailer_id"] == place.retailer_id)
    policy = next(row for row in plan["retailer_policies"] if row["retailer_id"] == place.retailer_id)
    admitted = next(row for row in sidecar["retailers"] if row["retailer_id"] == place.retailer_id)["admitted_route_keys"]
    return priced(place, world, retailer, policy, set(admitted))


def cheapest(rows):
    """The carrier whose cheapest shown route is strictly cheaper than every other carrier's, or None."""
    best = {}
    for row in rows:
        best[row["carrier_id"]] = min(best.get(row["carrier_id"], row["charge_minor"]), row["charge_minor"])
    lowest = sorted(best.values())
    if not lowest or len(lowest) > 1 and lowest[0] == lowest[1]:
        return None
    return next(carrier for carrier, charge in best.items() if charge == lowest[0])


def holds(clause, rows):
    """The clause read off a retailer's shown routes."""
    if rows is None:
        return False
    carriers, named = {row["carrier_id"] for row in rows}, clause.get("carriers", {})
    return (set(named.get("include", [])) <= carriers and not set(named.get("exclude", [])) & carriers and
            ("cheapest_carrier" not in clause or cheapest(rows) == clause["cheapest_carrier"]))
