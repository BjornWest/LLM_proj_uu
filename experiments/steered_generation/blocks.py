"""What a block of steered draws declares, and one producer pass for several blocks.

A block is the set of draws one requirement resamples. It names the leaves it
decides and the leaves its probability was computed from as resources:
("stock", retailer, product) and ("price", retailer, product). The producer
gives every draw its own stream, so blocks whose resources do not meet are
independent given everything upstream: each can be sampled on its own, all of
them replayed in one pass, and the probability that every requirement holds is
the product of theirs.
"""
from dataclasses import dataclass
from fractions import Fraction
import json
from math import fsum, prod
from types import SimpleNamespace
from typing import Callable

from experiments.world_requirement_construction import model as edits

from . import streams


class Unmet(ValueError):
    """A world does not satisfy the requirement."""


class Coupled(ValueError):
    """Requirements that cannot be sampled as separate blocks.

    They share draws, or one is judged on leaves another redraws. Not a
    statement about probability: a joint block could still sample them.
    """
    reason = "coupled_requirements"


class NumericalLimit(ArithmeticError):
    """A positive probability is too small for a float. Says nothing about possibility."""
    reason = "numerical_limit"


def times(*factors):
    """A product of probabilities that is zero only when one of them is."""
    result = prod(factors)
    if not result and all(factors):
        raise NumericalLimit("A positive probability underflows")
    return result


def power(base, count):
    result = base ** count
    if base and not result:
        raise NumericalLimit("A positive probability underflows")
    return result


# Shares of the total above 2**-30 are resolved comfortably by a 53-bit uniform draw.
FLOAT_RESOLVES = 2 ** 30
# Float weights at least this large are far from the subnormal range, where the
# product of the uniform draw and the total is quantized.
ORDINARY = 2.0 ** -500


def pick(rng, options, weights):
    """One option, with probability proportional to its weight, over a very wide range of weights.

    Pick from finite, nonnegative weights; for all-float inputs whose smallest
    positive weight is at least 2**-500, the total must fit in a finite float,
    as it does for the fourth block's probability weights.

    `rng.choices` draws one 53-bit uniform number, so an option whose share of
    the total is far below 1e-16 may be unreachable or badly quantized, and
    with a subnormal total it can even return an option of weight zero.
    Only options with a positive weight are offered to it, and only weights of
    ordinary size and evenness: floats well above the subnormal range go as
    they are, other even weights after division by their exact total. Very
    uneven weights are taken as exact rationals with a uniform draw of enough
    bits that every positive weight keeps its interval, its relative selection
    error below 2**-64.
    """
    live = [(option, weight) for option, weight in zip(options, weights) if weight > 0]
    if not live:
        raise ValueError("No option has a positive weight")
    names, positive = zip(*live)
    if (all(type(weight) is float for weight in positive) and min(positive) >= ORDINARY and
            min(positive) * FLOAT_RESOLVES > fsum(positive)):
        return rng.choices(names, weights=positive)[0]
    exact = [Fraction(weight) for weight in positive]
    total, smallest = sum(exact), min(exact)
    if smallest * FLOAT_RESOLVES > total:
        return rng.choices(names, weights=[float(weight / total) for weight in exact])[0]
    bits = 64 + (total / smallest).numerator.bit_length()
    point, reached = Fraction(rng.getrandbits(bits), 1 << bits) * total, Fraction(0)
    for option, weight in zip(names, exact):
        reached += weight
        if point < reached:
            return option
    raise AssertionError("The draw fell outside the weights")


@dataclass
class Step:
    """One requirement's sampled draws, ready to replay.

    `script` maps stream keys to planned results. `writes` are the resources
    the draws decide, `reads` those the requirement's probability depends on
    besides. `record(world)` checks that the producer recorded the plan and
    describes the block; `check(world)` reads the requirement off the finished
    world. A block whose probability can fall below the float range gives its
    logarithm as well; `probability` is then 0.0.
    """
    script: dict
    probability: float
    writes: set
    reads: set
    record: Callable
    check: Callable
    log_probability: float = None


def bound(value):
    """Whether a value is a bound: a non-negative integer min, max or both."""
    return (type(value) is dict and bool(value) and not set(value) - {"min", "max"} and
            all(type(v) is int and v >= 0 for v in value.values()) and
            value.get("min", 0) <= value.get("max", value.get("min", 0)))


def within(limits, value):
    return limits.get("min", 0) <= value <= limits.get("max", value)


def offer_resource(kind, world, requirement):
    """The stock or price resource of the retailer and SKU a one-offer requirement names.

    Read from the product the SKU belongs to, so it exists whether or not the
    retailer lists the SKU.
    """
    products = {s["sku_id"]: p["public"]["product_id"] for p in world["products"] for s in p["public"]["skus"]}
    if (requirement["sku_id"] not in products or
            not any(r["retailer_id"] == requirement["retailer_id"] for r in world["retailers"])):
        raise ValueError("Unknown retailer or SKU")
    return kind, requirement["retailer_id"], products[requirement["sku_id"]]


def independent(steps):
    """Fail unless no block decides a leaf another block decides or is judged on.

    Takes anything that declares `writes` and `reads`: sampled steps, or the
    modules' `footprint`, which needs no probability and so also exists for a
    requirement that has none on this world.
    """
    for index, step in enumerate(steps):
        for other_index, other in enumerate(steps):
            shared = step.writes & (other.writes | other.reads) if index != other_index else set()
            if shared:
                kind, retailer, product = sorted(shared)[0]
                raise Coupled(f"Requirements {index + 1} and {other_index + 1} both depend on the {kind} "
                              f"of {product} at {retailer}")


def background(world, writes):
    """Canonical JSON of everything but identity and the leaves the given resources decide.

    Stock of a retailer/product: the condition at each location, every SKU's
    quantities and supplier order, and the warehouse stock on its catalog
    pages. Price: every SKU's price and recorded draw. JSON text, unlike
    Python equality, keeps true, 1 and 1.0 apart.
    """
    def retailer(value):
        rid = value["retailer_id"]
        stock = {product for kind, retailer_id, product in writes if kind == "stock" and retailer_id == rid}
        price = {product for kind, retailer_id, product in writes if kind == "price" and retailer_id == rid}
        if not stock and not price:
            return value

        def offer(row):
            if row["product_id"] in stock:
                row = {k: v for k, v in row.items() if k not in ("stock_by_source", "supplier_order")}
            if row["product_id"] in price:
                row = {**{k: v for k, v in row.items() if k != "price_minor"},
                       "price_trace": {k: v for k, v in row["price_trace"].items() if k not in edits.DRAW_FIELDS}}
            return row

        view = {**value, "offers": [offer(row) for row in value["offers"]]}
        if stock:
            view["conditions"] = [{k: v for k, v in row.items() if k != "condition"}
                                  if row["product_id"] in stock else row for row in value["conditions"]]
            view["catalog"] = [{**entry, "pages": [
                {**{k: v for k, v in page.items() if k != "warehouse_sold_out"},
                 "listings": [{k: v for k, v in row.items() if k != "stock"} for row in page["listings"]]}
                for page in entry["pages"]]} if entry["product_id"] in stock else entry for entry in value["catalog"]]
        return view

    view = {k: v for k, v in world.items() if k not in edits.META_FIELDS}
    view["retailers"] = [retailer(r) for r in world["retailers"]]
    return json.dumps(view, sort_keys=True, ensure_ascii=False, allow_nan=False)


def replay(session, natural, natural_opened, steps):
    """One pass of the real producer with every step's draws replayed.

    Returns the world as the producer left it, each step's record, and the
    pass's stream counts. Nothing outside the steps' resources may differ from
    the natural world.
    """
    independent(steps)
    script = {}
    for step in steps:
        script.update(step.script)
    if len(script) != sum(len(step.script) for step in steps):
        raise AssertionError("Blocks with separate resources planned the same stream")
    world, opened = session.generate(script)
    records = [step.record(world) for step in steps]
    writes = set().union(*(step.writes for step in steps))
    if background(natural, writes) != background(world, writes):
        raise AssertionError("Steering changed something the steered draws do not decide")
    counts = {"streams_opened": len(opened), "streams_steered": len(script)}
    if natural_opened is not None:
        counts.update(streams_opened_only_when_steered=len(set(opened) - set(natural_opened)),
                      streams_opened_only_naturally=len(set(natural_opened) - set(opened)))
    return world, records, counts


def steer(session, natural, natural_opened, step, api):
    """Replay one block; returns the labelled world, what `step.check` read off it, and its record."""
    world, (record,), counts = replay(session, natural, natural_opened, [step])
    streams.relabel(world, {**record, **counts}, api)
    return world, step.check(world), world["provenance"]["steered_generation"]


def redraw(session, natural, readings, seed):
    """One pass of the real producer with the blocks' streams opened under another seed.

    `readings` are the blocks' own readings of the producer (a module's
    `trial`). Returns, per block, whether the producer's leaves equal the
    reading of that seed and whether the requirement's verdict on the world
    equals the reading's; and whether every requirement held.
    """
    independent(readings)
    keys = set().union(*(found.keys for found in readings))
    writes = set().union(*(found.writes for found in readings))
    world, _ = session.generate({key: streams.Reseeded(seed) for key in keys})
    if background(natural, writes) != background(world, writes):
        raise AssertionError("Redrawing the blocks' streams changed something they do not decide")
    verdicts = [found.satisfied(world) for found in readings]
    return SimpleNamespace(identical=[found.recorded(world) == found.reading(seed) for found in readings],
                           agreed=[found.holds(seed) == verdict for found, verdict in zip(readings, verdicts)],
                           satisfied=all(verdicts))
