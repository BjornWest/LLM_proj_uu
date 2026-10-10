"""Bounded two-offer price repair over an immutable, already sampled world.

This is deterministic scenario authoring, not prior-conditioned sampling. Only
two price leaves change; all manufacture, stock and original draw traces remain.
Native task/reference and commerce APIs are supplied by the pinned runner.
"""
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
import json

VERSION = "authored-two-offer-price-tie-v1"


class CannotConstruct(ValueError):
    """This operator cannot construct the requirement with the allowed edits."""


def byte_digest(raw):
    return sha256(raw).hexdigest()


def digest(value):
    return byte_digest(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                  ensure_ascii=False, allow_nan=False).encode())


def resolve(requirement):
    if type(requirement) is not dict or set(requirement) != {
            "schema", "kind", "concept_id", "offer_ids"}:
        raise ValueError("Declare the exact two-offer requirement schema")
    if (requirement["schema"] != VERSION or
            requirement["kind"] != "two_designated_available_cheapest_ties" or
            type(requirement["concept_id"]) is not str):
        raise ValueError("Unsupported requirement")
    ids = requirement["offer_ids"]
    if (type(ids) is not list or len(ids) != 2 or
            any(type(x) is not str or not x for x in ids) or len(set(ids)) != 2):
        raise ValueError("Declare two distinct existing offer IDs")
    return deepcopy(requirement)


def price_domain(offer, config, native_round):
    """Finite output grid of the existing clamped/rounded price operation.

    Includes rounding at the interval endpoints rather than inventing tighter
    raw-price bounds. A price override does not establish its prior probability.
    """
    reference = offer["price_trace"]["reference_minor"]
    if type(reference) is not int or reference <= 0:
        raise ValueError("A positive integer native reference price is required")
    lo = Decimal(str(config["offset_min"]))
    hi = Decimal(str(config["offset_max"]))
    if not -1 < lo <= hi:
        raise ValueError("Unsupported native offset bounds")
    step = next(step for upper, step in config["rounding_bands_sek"]
                if upper is None or reference < upper * 100) * 100
    # Match the existing producer's exact float expression. Decimal arithmetic
    # can move a binary-float half-step and alter round-to-even at a clamped
    # endpoint, changing native support even though the interval is identical.
    low = native_round(reference * (1 + config["offset_min"]), reference, config)
    high = native_round(reference * (1 + config["offset_max"]), reference, config)
    if type(step) is not int or step <= 0 or (high - low) // step > 10000:
        raise ValueError("Native price grid exceeds bounded operator support")
    # max(step, rounded) can add a clamped endpoint off the reference grid.
    # Do not continue a range from that endpoint: it would invent impossible
    # prices whenever the reference has a commercial ending unlike step.
    first = low if low > step else reference + ((step - reference) // step + 1) * step
    support = {low} | set(range(first, high + 1, step))
    if config.get("reference_match_probability", 0) > 0:
        support.add(native_round(reference, reference, config))
    return support


def _reference(world, requirement, api):
    selection = {"kind": "cheapest_available", "concept_id": requirement["concept_id"]}
    task = api.basic.make(world, selection)
    return task, api.basic.reference(world, task)


def check(world, requirement, api):
    """Independent existing oracle checks every competing offer, not a shortlist."""
    requirement = resolve(requirement)
    task, reference = _reference(world, requirement, api)
    expected = set(requirement["offer_ids"])
    winners = {row["offer_id"] for row in reference["winners"]}
    if reference["status"] != "match" or winners != expected:
        raise CannotConstruct("Native winner set does not equal the two designated offers")
    offers = {o["offer_id"]: o for r in world["retailers"] for o in r["offers"]}
    # This requirement strengthens the basic purchasable oracle to physical stock.
    native_availability = {row["offer_id"]: row["availability"] for row in reference["winners"]}
    if any(not any(offers[oid]["stock_by_source"].values()) or
           native_availability[oid] != "in_stock" for oid in expected):
        raise CannotConstruct("Both designated offers must have physical stock and native in_stock status")
    return task, reference


def construct(parent, requirement, api, *, parent_bytes_sha256):
    requirement = resolve(requirement)
    api.commerce.validate(parent)
    if parent.get("status") != "opt_in_candidate_commerce" or "authored_derivative" in parent["provenance"]:
        raise CannotConstruct("This operator only accepts an original sampled parent, not authored chains")
    before = deepcopy(parent)
    _, initial = _reference(parent, requirement, api)
    candidates = {row["offer_id"]: row for row in initial["candidates"]}
    target = set(requirement["offer_ids"])
    if not target <= set(candidates):
        raise CannotConstruct("Targets must already be available and belong to the task concept")
    offers = {o["offer_id"]: o for r in parent["retailers"] for o in r["offers"]}
    if any(not any(offers[oid]["stock_by_source"].values()) or
           candidates[oid]["availability"] != "in_stock" for oid in target):
        raise CannotConstruct("Price-only operator cannot create physical stock")
    if {row["offer_id"] for row in initial["winners"]} == target:
        raise CannotConstruct("Requirement already holds; retain the original world without authoring")
    competitor_prices = [r["price_minor"] for oid, r in candidates.items() if oid not in target]
    if not competitor_prices:
        raise CannotConstruct("This pilot requires a real competing offer")
    config = parent["config"]["retailer_price"]
    domains = [price_domain(offers[oid], config, api.native.rounded_price)
               for oid in requirement["offer_ids"]]
    feasible = {p for p in domains[0] & domains[1] if p < min(competitor_prices)}
    if not feasible:
        raise CannotConstruct("No common native price below unchanged competitors")
    # Closest to the remaining market floor; not a random feasible assignment.
    chosen = max(feasible)
    world = deepcopy(parent)
    edited = {o["offer_id"]: o for r in world["retailers"] for o in r["offers"]}
    changes = []
    for oid, domain in zip(requirement["offer_ids"], domains):
        if edited[oid]["price_minor"] == chosen:
            continue
        changes.append({"offer_id": oid, "field": "price_minor",
                        "before": edited[oid]["price_minor"], "after": chosen,
                        "preserved_original_price_trace_sha256": digest(edited[oid]["price_trace"]),
                        "native_price_grid_min": min(domain),
                        "native_price_grid_max": max(domain)})
        edited[oid]["price_minor"] = chosen
    provenance = {"schema": VERSION, "method": "deterministic_authored_derivative",
                  "parent_world_id": parent["world_id"],
                  "parent_world_digest": api.native.digest(parent),
                  "parent_file_sha256": parent_bytes_sha256,
                  "requirement": requirement, "changes": changes,
                  "distribution_claim": "none; not a natural or prior-conditioned draw",
                  "trace_semantics": "Original price traces describe the parent draw; these explicit overrides describe the derivative."}
    world["provenance"]["authored_derivative"] = provenance
    world["status"] = "authored_derivative_construction_only"
    # Keep the parent's exact limitation strings in the immutable parent, not as
    # fresh unqualified derivative claims such as "no winner or seed repair".
    world["limitations"] = ["Parent declaration: " + note for note in parent["limitations"]]
    world["limitations"].append("Authored two-price derivative. Parent surrounding, rendering, task, runtime and execution sidecars are unusable here; only rebuilt native artifacts are emitted.")
    world.pop("world_id")
    world["world_id"] = api.native.digest(world)
    task, reference = check(world, requirement, api)
    if parent != before:
        raise AssertionError("Construction mutated its caller's parent")
    # Reversal proves no additional native leaf or background entity changed.
    restored = deepcopy(world)
    for r in restored["retailers"]:
        for o in r["offers"]:
            if o["offer_id"] in target:
                o["price_minor"] = offers[o["offer_id"]]["price_minor"]
    restored["provenance"] = deepcopy(parent["provenance"])
    restored["status"] = parent["status"]
    restored["limitations"] = deepcopy(parent["limitations"])
    restored["world_id"] = parent["world_id"]
    if restored != parent:
        raise AssertionError("Unexpected background delta")
    return world, task, reference, provenance
