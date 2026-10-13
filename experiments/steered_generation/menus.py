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
    website = import_module(api.basic.__package__ + ".delivery_options")
    # A recipe's own settings; version 2 is the only one a menu can be read for, so it is what is asked for.
    stated = clause.get("delivery_options", {})
    if type(stated.get("enabled", True)) is not bool or not stated.get("enabled", True) or stated.get("admission_plan", VERSION) != VERSION:
        raise ValueError("Shown options are read for delivery options enabled under admission plan version 2")
    settings = website.options({**stated, "enabled": True, "admission_plan": VERSION})
    admission = import_module(api.commerce.__package__ + ".delivery_admission")
    if website.producer_plan_version(settings) != VERSION or VERSION not in admission.PLAN_VERSIONS:
        raise ValueError("The commerce oracle does not have admission plan version 2")
    backend = admission._backend(world)
    carriers = {row["carrier_id"] for row in world["address_context"]["carriers"]}
    if set(needed(clause)) - carriers or set(clause.get("carriers", {}).get("exclude", [])) - carriers:
        raise ValueError("Unknown carrier")
    retailer = next((row for row in world["retailers"] if row["retailer_id"] == retailer_id), None)
    if retailer is None:
        raise ValueError("Unknown retailer")
    if type(world.get("seed")) is not int or world["seed"] < 0:
        raise ValueError("The world does not record the seed its delivery menus are drawn on")
    return SimpleNamespace(clause=clause, world=world, retailer=retailer, retailer_id=retailer_id, admission=admission,
                           backend=backend, settings=settings, weights=admission._weights(website.producer_weights(settings)),
                           destination=world["user_location"], scope=clause.get("destination_type", "home"))


def priced(place, world, retailer, policy, admitted):
    """The admitted carrier routes in scope with the oracle's tariff for an ordinary parcel any source can ship."""
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
                     "charge_minor": min(row["raw_shipping_minor"] for row in found)})
    return sorted(rows, key=lambda row: (row["charge_minor"], row["route_key"]))


def shown(place, contracts):
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
    return priced(place, view, retailer, policy, set(row["admitted_route_keys"]))


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
