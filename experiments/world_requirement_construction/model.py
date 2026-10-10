"""Draw-level price edits over an immutable, already sampled world.

The producer prices a product once per retailer: one recorded draw, applied to
every listed SKU through its rounding rule. This operator replaces that draw
and recomputes every SKU from it, so the edited world still obeys the pricing
rule. It is scenario authoring: no probability is claimed for the result.
Native task/reference and commerce APIs are supplied by the pinned runner.
"""
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import json
from math import ceil, floor

VERSION = "authored-retailer-product-price-v2"
KIND = "designated_retailers_cheapest_on_product"
SAMPLED_STATUS = "opt_in_candidate_commerce"
AUTHORED_STATUS = "authored_derivative_construction_only"
DRAW_FIELDS = ("matched_reference_draw", "offset_draw")
META_FIELDS = ("provenance", "status", "limitations", "world_id")


class CannotConstruct(ValueError):
    """This operator cannot construct the requirement with the allowed edits.

    `reason` is a stable code; declining is not a proof of global impossibility.
    """

    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason


def byte_digest(raw):
    return sha256(raw).hexdigest()


def resolve(requirement):
    if type(requirement) is not dict or set(requirement) != {
            "schema", "kind", "concept_id", "product_id", "retailer_ids"}:
        raise ValueError("Declare the exact retailer/product requirement schema")
    if (requirement["schema"] != VERSION or requirement["kind"] != KIND or
            any(type(requirement[k]) is not str or not requirement[k]
                for k in ("concept_id", "product_id"))):
        raise ValueError("Unsupported requirement")
    ids = requirement["retailer_ids"]
    if (type(ids) is not list or not ids or
            any(type(x) is not str or not x for x in ids) or len(set(ids)) != len(ids)):
        raise ValueError("Declare distinct existing retailer IDs")
    return deepcopy(requirement)


def _step(reference, config):
    return next(step for upper, step in config["rounding_bands_sek"]
                if upper is None or reference < upper * 100) * 100


def _price(reference, draw, config, native_round):
    # The producer's exact float expression; Decimal arithmetic can move a
    # half-step at a clamped endpoint.
    return native_round(reference * (1 + draw[1]), reference, config)


def _draw(offer):
    return tuple(offer["price_trace"][field] for field in DRAW_FIELDS)


def price_rule_violations(world, native_round):
    """Every listed price must follow from one recorded draw per retailer/product.

    Mirrors the producer's `_offer_price`: reference from the exact SKU basis
    when one exists, else the product; a matched draw has zero offset; other
    offsets lie inside the clamp; all SKUs of a product at a retailer share
    the draw. The native commerce validator does not check any of this.
    """
    config = world["config"]["retailer_price"]
    products = {p["public"]["product_id"]: p["public"] for p in world["products"]}
    skus = {s["sku_id"]: s for p in products.values() for s in p["skus"]}
    problems = []
    for retailer in world["retailers"]:
        draws = {}
        for offer in retailer["offers"]:
            trace, sku = offer["price_trace"], skus[offer["sku_id"]]
            exact = "reference_price_sek" in sku
            basis = sku["reference_price_sek"] if exact else products[offer["product_id"]]["reference_price_sek"]
            reference = int((Decimal(str(basis)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            match, offset = _draw(offer)
            if (trace["reference_minor"] != reference or
                    trace["reference_basis"] != ("exact_sku" if exact else "product")):
                problems.append(offer["offer_id"] + ": reference differs from its manufacturer basis")
            elif (type(match) is not bool or type(offset) not in (int, float) or
                  (match and offset != 0) or
                  not config["offset_min"] <= offset <= config["offset_max"]):
                problems.append(offer["offer_id"] + ": recorded draw is outside the producer's range")
            elif offer["price_minor"] != _price(reference, (match, offset), config, native_round):
                problems.append(offer["offer_id"] + ": price does not follow from its recorded draw")
            if draws.setdefault(offer["product_id"], (match, offset)) != (match, offset):
                problems.append(offer["offer_id"] + ": draw differs from other SKUs of this product at the retailer")
    return problems


def check_price_rule(world, native_round):
    problems = price_rule_violations(world, native_round)
    if problems:
        raise CannotConstruct("price_rule", "World breaks the producer's pricing rule: " + "; ".join(problems[:3]))


def candidate_draws(references, config):
    """One representative draw for every price the producer can emit.

    Bin centres k*step/reference round to exactly k steps; the clamp endpoints
    cover prices that only a clamped draw reaches.
    """
    lo, hi = config["offset_min"], config["offset_max"]
    if not -1 < lo <= hi:
        raise ValueError("Unsupported native offset bounds")
    probability = config["reference_match_probability"]
    draws = [(True, 0)] if probability > 0 else []
    if probability >= 1:
        return draws
    if config["offset_standard_deviation"] == 0:
        # An unmatched draw of a zero-width normal is always the clamped zero.
        return draws + [(False, max(lo, min(hi, 0.0)))]
    draws += [(False, lo), (False, hi)]
    for reference in sorted(set(references)):
        step = _step(reference, config)
        first, last = ceil(lo * reference / step), floor(hi * reference / step)
        if last - first > 10000:
            raise ValueError("Native price grid exceeds bounded operator support")
        for k in range(first, last + 1):
            offset = k * step / reference
            if lo <= offset <= hi and (k or probability <= 0):
                draws.append((False, offset))
    return draws


def apply_draw(group, draw, config, native_round):
    """Reprice every SKU of one product at one retailer from a single draw."""
    rows = []
    for offer in group:
        price = _price(offer["price_trace"]["reference_minor"], draw, config, native_round)
        rows.append({"offer_id": offer["offer_id"], "before": offer["price_minor"], "after": price})
        offer["price_minor"] = price
        offer["price_trace"].update(zip(DRAW_FIELDS, draw))
    return rows


def _reference(world, requirement, api):
    selection = {"kind": "cheapest_available", "concept_id": requirement["concept_id"]}
    task = api.basic.make(world, selection)
    return task, api.basic.reference(world, task)


def _pairs(rows):
    return {(row["retailer_id"], row["product_id"]) for row in rows}


def check(world, requirement, api):
    """The native oracle over every competing offer, plus the pricing rule."""
    requirement = resolve(requirement)
    check_price_rule(world, api.native.rounded_price)
    task, reference = _reference(world, requirement, api)
    designated = {(rid, requirement["product_id"]) for rid in requirement["retailer_ids"]}
    if reference["status"] != "match" or _pairs(reference["winners"]) != designated:
        raise CannotConstruct("winners", "Cheapest available offers are not exactly the designated retailers' product")
    return task, reference


def _only_declared_changes(parent, world, changed):
    """No leaf outside the declared offers' price and draw fields may differ."""
    def strip(value, keys):
        return {k: v for k, v in value.items() if k not in keys}
    if strip(parent, META_FIELDS + ("retailers",)) != strip(world, META_FIELDS + ("retailers",)):
        return False
    if len(parent["retailers"]) != len(world["retailers"]):
        return False
    for before, after in zip(parent["retailers"], world["retailers"]):
        if strip(before, ("offers",)) != strip(after, ("offers",)) or len(before["offers"]) != len(after["offers"]):
            return False
        for old, new in zip(before["offers"], after["offers"]):
            if old == new:
                continue
            if (old["offer_id"] not in changed or
                    strip(old, ("price_minor", "price_trace")) != strip(new, ("price_minor", "price_trace")) or
                    strip(old["price_trace"], DRAW_FIELDS) != strip(new["price_trace"], DRAW_FIELDS)):
                return False
    return True


def construct(parent, requirement, api, *, parent_bytes_sha256):
    requirement = resolve(requirement)
    api.commerce.validate(parent)
    if parent.get("status") != SAMPLED_STATUS or "authored_derivative" in parent["provenance"]:
        raise CannotConstruct("not_sampled", "This operator only accepts an original sampled parent, not authored chains")
    native_round = api.native.rounded_price
    config = parent["config"]["retailer_price"]
    check_price_rule(parent, native_round)
    _, initial = _reference(parent, requirement, api)
    product_id = requirement["product_id"]
    designated = [(rid, product_id) for rid in requirement["retailer_ids"]]
    available = {pair: [] for pair in designated}
    competitor_floor = None
    for row in initial["candidates"]:
        pair = (row["retailer_id"], row["product_id"])
        if pair in available:
            available[pair].append(row["offer_id"])
        elif competitor_floor is None or row["price_minor"] < competitor_floor:
            competitor_floor = row["price_minor"]
    if not all(available.values()):
        raise CannotConstruct("unavailable", "Every designated retailer needs an available offer of the product; a price edit cannot create stock")
    if _pairs(initial["winners"]) == set(designated):
        raise CannotConstruct("already_holds", "Requirement already holds; retain the original world without authoring")
    groups = {(r["retailer_id"], product_id): [o for o in r["offers"] if o["product_id"] == product_id]
              for r in parent["retailers"] if (r["retailer_id"], product_id) in available}
    # For each designated retailer: every price its cheapest available SKU can
    # take, with the draw that reaches it by the smallest change.
    options = {}
    for pair in designated:
        group = groups[pair]
        current = _draw(group[0])
        buyable = [o for o in group if o["offer_id"] in available[pair]]
        reach = {}
        for draw in [current] + candidate_draws([o["price_trace"]["reference_minor"] for o in group], config):
            price = min(_price(o["price_trace"]["reference_minor"], draw, config, native_round) for o in buyable)
            cost = (draw != current, abs(draw[1] - current[1]))
            if price not in reach or cost < reach[price][0]:
                reach[price] = (cost, draw)
        options[pair] = (min(o["price_minor"] for o in buyable), reach)
    feasible = [price for price in set.intersection(*(set(reach) for _, reach in options.values()))
                if competitor_floor is None or price < competitor_floor]
    if not feasible:
        raise CannotConstruct("no_common_price", "No common producer price below the unchanged competitors")
    # Fewest retailers repriced, then the smallest total price movement, then
    # the lower price. Not a random feasible choice.
    chosen = min(feasible, key=lambda price: (
        sum(reach[price][0][0] for _, reach in options.values()),
        sum(abs(price - before) for before, _ in options.values()), price))
    world = deepcopy(parent)
    edited = {(r["retailer_id"], product_id): [o for o in r["offers"] if o["product_id"] == product_id]
              for r in world["retailers"] if (r["retailer_id"], product_id) in available}
    changes, changed = [], set()
    for pair in designated:
        (differs, _), draw = options[pair][1][chosen]
        if not differs:
            continue
        rows = apply_draw(edited[pair], draw, config, native_round)
        changed.update(row["offer_id"] for row in rows)
        changes.append({"retailer_id": pair[0], "product_id": product_id,
                        "draw": pair[0] + "/" + product_id + "/price",
                        "before": dict(zip(DRAW_FIELDS, _draw(groups[pair][0]))),
                        "after": dict(zip(DRAW_FIELDS, draw)), "offers": rows})
    provenance = {"schema": VERSION, "method": "deterministic_authored_derivative",
                  "parent_world_id": parent["world_id"],
                  "parent_world_digest": api.native.digest(parent),
                  "parent_file_sha256": parent_bytes_sha256,
                  "requirement": requirement, "changes": changes,
                  "distribution_claim": "none; not a natural or prior-conditioned draw",
                  "trace_semantics": "Changed price traces hold the authored draw; the parent's draw is recorded under changes. The seed no longer reproduces these prices."}
    world["provenance"]["authored_derivative"] = provenance
    world["status"] = AUTHORED_STATUS
    # Keep the parent's exact limitation strings in the immutable parent, not as
    # fresh unqualified derivative claims such as "no winner or seed repair".
    world["limitations"] = ["Parent declaration: " + note for note in parent["limitations"]]
    world["limitations"].append("Authored retailer/product price derivative. Parent surrounding, rendering, task, runtime and execution sidecars are unusable here; only rebuilt native artifacts are emitted.")
    world.pop("world_id")
    world["world_id"] = api.native.digest(world)
    task, reference = check(world, requirement, api)
    if not _only_declared_changes(parent, world, changed):
        raise AssertionError("Unexpected background delta")
    return world, task, reference, provenance
