"""Steered generation from an exact Git dependency root.

Run as a module from the repository root:
    python -m experiments.steered_generation.run ...
One natural pass through the real producer, then one cheap steered pass per
requested sample. A requirement file is a who-is-cheapest requirement (on
prices alone, on stock and prices together with offers listed below the
winner, or on a product's listed prices), a shortlist of models, a one-offer
stock or price requirement, a basket's subtotal against a free-shipping
threshold, what a product's or a carrier's reviews say about a topic, or
several of those to hold together. With `--task` the requirement files are
written here instead: the candidates `variants` lists for a native task
specification on the natural world, all of them or those named with
`--candidate`.
No browser, provider or sidecar publication.
"""
import argparse
from collections import Counter
from hashlib import sha256
import importlib
import json
from math import fsum, sqrt
from pathlib import Path
from random import Random
import subprocess
import time

from experiments.world_requirement_construction import model as edits, run as pinned

from . import (blocks, carriers, cheapest, combined, listed, policies, price_bounds, prices, ratings, reviews, sellers,
               shipments, shortlist, stock, streams, threshold, variants)

HERE = Path(__file__).resolve().parent
OWN = {HERE: ("__init__.py", "streams.py", "blocks.py", "prices.py", "stock.py", "price_bounds.py", "cheapest.py",
              "listed.py", "shortlist.py", "threshold.py", "reviews.py", "programs.py", "pages.py", "carriers.py", "shipments.py",
              "policies.py", "menus.py", "sellers.py", "ratings.py", "combined.py", "variants.py", "run.py"),
       Path(edits.__file__).resolve().parent: ("__init__.py", "model.py", "run.py")}


def pin_own(declared):
    """This experiment's sources must equal their blobs at the declared commit."""
    try:
        commit = subprocess.check_output(
            ["git", "-C", str(HERE), "rev-parse", "--verify", "--quiet", declared + "^{commit}"],
            text=True, stderr=subprocess.DEVNULL).strip()
    except subprocess.CalledProcessError:
        raise ValueError("Steering commit cannot be resolved: " + declared) from None
    top = Path(subprocess.check_output(["git", "-C", str(HERE), "rev-parse", "--show-toplevel"], text=True).strip())
    pins, paths = {}, {}
    for directory, names in OWN.items():
        for name in names:
            relative = (directory / name).relative_to(top).as_posix()
            expected = subprocess.check_output(["git", "-C", str(HERE), "show", commit + ":" + relative])
            if (directory / name).read_bytes() != expected:
                raise ValueError("Steering source differs from its declared commit: " + relative)
            pins[relative] = paths[str(directory / name)] = edits.byte_digest(expected)
    return commit, pins, paths


def write(folder, files):
    folder.mkdir()
    for name, value in files.items():
        (folder / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    return {name: edits.byte_digest((folder / name).read_bytes()) for name in files}


def sample_rng(natural, case, index):
    return Random(int(sha256(f"{natural['world_id']}/{case['requirement_sha256']}/{index}".encode()).hexdigest(), 16))


def absent(error):
    """The status of a requirement no sample was drawn for: proven to have no mass, or not found in a bounded search."""
    return "not_found_in_bounded_search" if error.reason == "not_found" else "zero_probability_given_upstream"


def frequency_check(case, probability, hits, trials, estimate=0.0):
    """Compare a probability with a count over other seeds; `estimate` is its own standard error where it is one."""
    error = sqrt(probability * (1 - probability) / trials + estimate ** 2)
    case["validation"] = {"trials": trials, "hits": hits, "frequency": hits / trials, "computed": probability,
                          "standard_error": error, **({"computed_standard_error": estimate} if estimate else {}),
                          "within_four_standard_errors": abs(hits / trials - probability) <= 4 * error}
    pinned.ensure(case["validation"]["within_four_standard_errors"],
                  "Computed probability disagrees with the producer's draws")
    return case["validation"]


def price_case(args, session, natural, opened, api, requirement, case, folder):
    for index in range(args.samples):
        clock = time.monotonic()
        try:
            world, task, reference, record = prices.steer(session, natural, requirement, api, sample_rng(natural, case, index))
        except prices.ZeroMass as error:
            case.update(status=absent(error), reason=error.reason)
            return
        seconds = time.monotonic() - clock
        minimum, scanned = pinned.direct_scan(world, requirement)
        designated = {(rid, requirement["product_id"]) for rid in requirement["retailer_ids"]}
        pinned.ensure(scanned == designated and minimum == reference["minimum_price_minor"] == record["winning_price_minor"],
                      "Direct full-population scan disagrees with the steered result")
        files = write(folder(index), {"world.private.json": world, "task.private.json": task,
                                      "reference.private.json": reference, "steering.json": record})
        case.update(status="sampled", probability_given_upstream=record["probability_given_upstream"])
        case["samples"].append({
            "folder": folder(index).name, "world_id": world["world_id"], "seconds": seconds,
            "winning_price_minor": minimum, "winner_count": len(reference["winners"]),
            "repriced_retailer_products": len(record["repriced"]),
            "changed_price_leaves": sum(o["natural"] != o["steered"] for r in record["repriced"] for o in r["offers"]),
            "files": files})
    if args.validate_trials:
        probability = case["probability_given_upstream"]
        winning = prices.empirical(natural, requirement, api, args.validate_trials, 10 ** 6)
        hits = sum(winning.values())
        validation = frequency_check(case, probability, hits, args.validate_trials)
        terms = prices.model(natural, requirement, api).terms
        # Winning-price distribution given the requirement: model against real redraws.
        distance = sum(abs(terms.get(p, 0) / probability - winning.get(p, 0) / hits)
                       for p in set(terms) | set(winning)) / 2 if hits else None
        validation.update(winning_price_total_variation=distance, winning_prices_modelled=len(terms))
        pinned.ensure(hits < 1000 or distance < 0.1,
                      "Conditional winning-price distribution disagrees with the real pricing function")


def producer_redraws(args, session, natural, readings, case):
    """The real producer redraws the blocks under other seeds; each block's reading must agree with it."""
    hits = 0
    for seed in range(2 * 10 ** 6, 2 * 10 ** 6 + args.producer_redraws):
        found = blocks.redraw(session, natural, readings, seed)
        pinned.ensure(all(found.identical) and all(found.agreed),
                      "Reading of the producer's draws disagrees with the producer")
        hits += found.satisfied
    case["producer_redraws"] = {"passes": args.producer_redraws, "identical_to_reading": args.producer_redraws,
                                "requirement_held": hits}


def stock_case(args, session, natural, opened, api, requirement, case, folder):
    try:
        block = stock.model(natural, requirement, api)
    except prices.ZeroMass as error:
        case.update(status=absent(error), reason=error.reason)
        return
    except blocks.NumericalLimit as error:
        case.update(status="refused", reason=error.reason, detail=str(error))
        return
    place = block.site
    case.update(status="sampled", probability_given_upstream=block.probability, offer_id=place.offer_id,
                stock_locations=len(place.sources), natural=stock.recorded(natural, place))
    for index in range(args.samples):
        clock = time.monotonic()
        world, found, record = stock.steer(session, natural, opened, requirement, api, sample_rng(natural, case, index))
        seconds = time.monotonic() - clock
        # A reading of the saved leaves that uses neither the block model nor the native oracle.
        pinned.ensure(stock.holds(place, stock.recorded(world, place)), "Direct reading disagrees with the steered result")
        files = write(folder(index), {"world.private.json": world, "observed.json": found, "steering.json": record})
        case["samples"].append({
            "folder": folder(index).name, "world_id": world["world_id"], "seconds": seconds,
            "availability": found["availability"], "stock_by_source": found["stock_by_source"],
            "streams_steered": record["streams_steered"],
            "streams_opened_only_when_steered": record["streams_opened_only_when_steered"],
            "streams_opened_only_naturally": record["streams_opened_only_naturally"],
            "rebuilt_by_the_producer": record["rebuilt_by_the_producer"], "files": files})
    if args.producer_redraws:
        producer_redraws(args, session, natural, [stock.trial(natural, requirement, api)], case)
    if args.validate_trials:
        ends = stock.empirical(natural, requirement, api, args.validate_trials, 10 ** 6)
        hits = sum(ends.values())
        validation = frequency_check(case, block.probability, hits, args.validate_trials, getattr(block, "error", 0.0))
        # How the block ends given the requirement: model against the reading's redraws.
        distance = sum(abs(block.outcomes.get(e, 0) / block.probability - ends.get(e, 0) / hits)
                       for e in set(block.outcomes) | set(ends)) / 2 if hits else None
        validation.update(ending_total_variation=distance, endings_modelled=len(block.outcomes))
        pinned.ensure(hits < 1000 or distance < 0.1,
                      "Conditional distribution of the block's ending disagrees with the producer's draws")


def bound_case(args, session, natural, opened, api, requirement, case, folder):
    try:
        block = price_bounds.model(natural, requirement, api)
    except prices.ZeroMass as error:
        case.update(status=absent(error), reason=error.reason)
        return
    place, limits = block.site, requirement["price_minor"]
    listed = lambda world: next(o["price_minor"] for r in world["retailers"] for o in r["offers"]
                                if o["offer_id"] == place.offer_id)
    case.update(status="sampled", probability_given_upstream=block.probability, offer_id=place.offer_id,
                natural_price_minor=listed(natural), prices_modelled=len(block.by_price))
    for index in range(args.samples):
        clock = time.monotonic()
        world, found, record = price_bounds.steer(session, natural, opened, requirement, api, sample_rng(natural, case, index))
        seconds = time.monotonic() - clock
        # The saved leaf itself, read without the block model.
        pinned.ensure(limits.get("min", 0) <= listed(world) <= limits.get("max", listed(world)) and
                      not edits.price_rule_violations(world, api.native.rounded_price),
                      "Direct reading disagrees with the steered result")
        files = write(folder(index), {"world.private.json": world, "observed.json": found, "steering.json": record})
        offers = record["repriced"][0]["offers"]
        case["samples"].append({
            "folder": folder(index).name, "world_id": world["world_id"], "seconds": seconds,
            "price_minor": found["price_minor"], "offers_of_the_product": len(offers),
            "changed_price_leaves": sum(o["natural"] != o["steered"] for o in offers), "files": files})
    if args.producer_redraws:
        producer_redraws(args, session, natural, [price_bounds.trial(natural, requirement, api)], case)
    if args.validate_trials:
        seen = price_bounds.empirical(natural, requirement, api, args.validate_trials, 10 ** 6)
        hits = sum(seen.values())
        validation = frequency_check(case, block.probability, hits, args.validate_trials, getattr(block, "error", 0.0))
        # The offer's price given the requirement: model against the real pricing function.
        distance = sum(abs(fsum(a[0] for a in block.by_price.get(p, ())) / block.probability - seen.get(p, 0) / hits)
                       for p in set(block.by_price) | set(seen)) / 2 if hits else None
        validation.update(price_total_variation=distance)
        pinned.ensure(hits < 1000 or distance < 0.1,
                      "Conditional price distribution disagrees with the real pricing function")


def cheapest_case(args, session, natural, opened, api, requirement, case, folder):
    try:
        clock = time.monotonic()
        block = cheapest.model(natural, requirement, api)
    except prices.ZeroMass as error:
        case.update(status=absent(error), reason=error.reason)
        return
    except cheapest.NumericalLimit as error:
        case.update(status="refused", reason=error.reason, detail=str(error))
        return
    concept = requirement["concept_id"]
    before = cheapest.recorded(natural, concept)
    case.update(status="sampled", probability_given_upstream=block.probability or None,
                log_probability_given_upstream=block.log_probability, model_seconds=time.monotonic() - clock,
                retailer_products=len(block.places), offers=len(before["offers"]),
                winning_prices_modelled=None if block.shares is None else len(block.shares),
                **({"probability_is_estimated": True, "probability_standard_error": block.error,
                    "proposals": cheapest.PROPOSALS, "proposals_accepted": block.accepted} if block.bounded else {}),
                natural_unavailable_offers=sum(not held(row) for row in before["offers"].values()))
    for index in range(args.samples):
        clock = time.monotonic()
        try:
            world, found, record = cheapest.steer(session, natural, opened, requirement, api,
                                                  sample_rng(natural, case, index))
        except cheapest.NumericalLimit as error:
            case.update(status="refused", reason=error.reason, detail=str(error))
            return
        seconds = time.monotonic() - clock
        # The saved leaves themselves, read without the block model or the native oracle.
        leaves = cheapest.recorded(world, concept)
        minimum = cheapest.judged(leaves, requirement, block.scope)
        # The winning rank is the winners' price unless the requirement ranks otherwise.
        name = "winning_price_minor" if type(minimum) is int else "winning_rank"
        pinned.ensure(minimum is not None and cheapest.plain(minimum) == record.get(name),
                      "Direct reading of the saved leaves disagrees with the steered result")
        if not set(requirement) - {"schema", "concept_id", "product_id", "retailer_ids", "listed_below"}:
            # Every offer competes: the full-population scan that knows nothing of this block applies too.
            designated = {(rid, requirement["product_id"]) for rid in requirement["retailer_ids"]}
            below = [next(row for row in leaves["offers"].values()
                          if (row["retailer_id"], row["sku_id"]) == (named["retailer_id"], named["sku_id"]))
                     for named in requirement.get("listed_below", [])]
            pinned.ensure(pinned.direct_scan(world, requirement) == (minimum, designated) and
                          all(row["price_minor"] < minimum and not held(row) for row in below),
                          "Direct full-population scan disagrees with the steered result")
        files = write(folder(index), {"world.private.json": world, "task.private.json": found["task"],
                                      "reference.private.json": found["reference"], "steering.json": record})
        case["samples"].append({
            "folder": folder(index).name, "world_id": world["world_id"], "seconds": seconds,
            name: cheapest.plain(minimum),
            "winner_count": len(block.scope.settled(found["reference"])["winners"]),
            "listed_below": found["listed_below"],
            "unavailable_offers": sum(not held(row) for row in leaves["offers"].values()),
            "retailer_products_with_nothing_available": sum(
                row["cheapest_available_minor"] is None for row in record["restocked"]),
            "streams_steered": record["streams_steered"],
            "streams_opened_only_when_steered": record["streams_opened_only_when_steered"],
            "streams_opened_only_naturally": record["streams_opened_only_naturally"], "files": files})
    reading = cheapest.trial(natural, requirement, api)
    if args.producer_redraws:
        producer_redraws(args, session, natural, [reading], case)
    if args.validate_trials and block.probability:
        winning = Counter(reading.winning(seed) for seed in range(10 ** 6, 10 ** 6 + args.validate_trials))
        del winning[None]
        hits = sum(winning.values())
        validation = frequency_check(case, block.probability, hits, args.validate_trials, getattr(block, "error", 0.0))
        # Winning-price distribution given the requirement: model against the reading's redraws. Between charge
        # bounds the model has no such distribution (its winning ranks are the bounded block's), so none is compared.
        distance = None if block.shares is None or not hits else sum(
            abs(block.shares.get(p, 0) - winning.get(p, 0) / hits) for p in set(block.shares) | set(winning)) / 2
        validation.update(winning_price_total_variation=distance)
        pinned.ensure(block.shares is None or hits < 1000 or distance < 0.1,
                      "Conditional winning-price distribution disagrees with the producer's draws")


def listed_case(args, session, natural, opened, api, requirement, case, folder):
    try:
        block = listed.model(natural, requirement, api)
    except prices.ZeroMass as error:
        case.update(status=absent(error), reason=error.reason)
        return
    pairs = set(block.groups)
    case.update(status="sampled", probability_given_upstream=block.probability or None,
                log_probability_given_upstream=block.log_probability, compared_retailer_products=len(pairs),
                winning_prices_modelled=None if block.shares is None else len(block.shares), natural_lowest_listed=min(listed.lowest(natural, pairs).values()))
    for index in range(args.samples):
        clock = time.monotonic()
        try:
            world, found, record = listed.steer(session, natural, opened, requirement, api,
                                                sample_rng(natural, case, index))
        except blocks.NumericalLimit as error:
            case.update(status="refused", reason=error.reason, detail=str(error))
            return
        seconds = time.monotonic() - clock
        # The saved price leaves themselves, read without the block model.
        lowest = listed.lowest(world, pairs)
        minimum = min(lowest.values())
        pinned.ensure({pair for pair, price in lowest.items() if price == minimum} == block.designated and
                      minimum == record["winning_price_minor"] and
                      not edits.price_rule_violations(world, api.native.rounded_price),
                      "Direct reading of the saved leaves disagrees with the steered result")
        files = write(folder(index), {"world.private.json": world, "observed.json": found, "steering.json": record})
        case["samples"].append({
            "folder": folder(index).name, "world_id": world["world_id"], "seconds": seconds,
            "winning_price_minor": minimum, "comparison_rows": found.get("comparison_rows"),
            "changed_price_leaves": sum(o["natural"] != o["steered"] for r in record["repriced"] for o in r["offers"]),
            "streams_steered": record["streams_steered"], "files": files})
    reading = listed.trial(natural, requirement, api)
    if args.producer_redraws:
        producer_redraws(args, session, natural, [reading], case)
    if args.validate_trials and block.probability:
        winning = Counter(reading.winning(seed) for seed in range(10 ** 6, 10 ** 6 + args.validate_trials))
        del winning[None]
        hits = sum(winning.values())
        validation = frequency_check(case, block.probability, hits, args.validate_trials, getattr(block, "error", 0.0))
        distance = sum(abs(block.shares.get(p, 0) - winning.get(p, 0) / hits)
                       for p in set(block.shares) | set(winning)) / 2 if hits else None
        validation.update(winning_price_total_variation=distance)
        pinned.ensure(hits < 1000 or distance < 0.1,
                      "Conditional winning-price distribution disagrees with the real pricing function")


def shortlist_case(args, session, natural, opened, api, requirement, case, folder):
    try:
        clock = time.monotonic()
        block = shortlist.model(natural, requirement, api)
    except prices.ZeroMass as error:
        case.update(status=absent(error), reason=error.reason)
        return
    except blocks.NumericalLimit as error:
        case.update(status="refused", reason=error.reason, detail=str(error))
        return
    concept = requirement["concept_id"]
    case.update(status="sampled", probability_given_upstream=block.probability or None,
                log_probability_given_upstream=block.log_probability, model_seconds=time.monotonic() - clock,
                retailer_products=len(block.places), models=len(block.models), cutoffs_modelled=len(block.shares))
    for index in range(args.samples):
        clock = time.monotonic()
        try:
            world, found, record = shortlist.steer(session, natural, opened, requirement, api,
                                                   sample_rng(natural, case, index))
        except blocks.NumericalLimit as error:
            case.update(status="refused", reason=error.reason, detail=str(error))
            return
        seconds = time.monotonic() - clock
        # The saved leaves themselves, read without the block model or the native oracle.
        cutoff = shortlist.listing(cheapest.recorded(world, concept), requirement, block.scope)
        pinned.ensure(cutoff is not None and cutoff == record["cutoff"],
                      "Direct reading of the saved leaves disagrees with the steered result")
        files = write(folder(index), {"world.private.json": world, "task.private.json": found["task"],
                                      "reference.private.json": found["reference"], "steering.json": record})
        selected = found["reference"]["selected_models"]
        case["samples"].append({
            "folder": folder(index).name, "world_id": world["world_id"], "seconds": seconds, "cutoff": cutoff,
            "selected_models": len(selected),
            "models_at_the_cutoff": sum(m["price_minor"] == found["reference"]["cutoff_price_minor"] for m in selected),
            "streams_steered": record["streams_steered"], "files": files})
    reading = shortlist.trial(natural, requirement, api)
    if args.producer_redraws:
        producer_redraws(args, session, natural, [reading], case)
    if args.validate_trials and block.probability:
        seen = Counter(reading.winning(seed) for seed in range(10 ** 6, 10 ** 6 + args.validate_trials))
        del seen[None]
        hits = sum(seen.values())
        validation = frequency_check(case, block.probability, hits, args.validate_trials, getattr(block, "error", 0.0))
        distance = sum(abs(block.shares.get(c, 0) - seen.get(c, 0) / hits)
                       for c in set(block.shares) | set(seen)) / 2 if hits else None
        validation.update(cutoff_total_variation=distance)
        pinned.ensure(hits < 1000 or distance < 0.1, "Conditional cutoff distribution disagrees with the producer's draws")


def threshold_case(args, session, natural, opened, api, requirement, case, folder):
    try:
        block = threshold.model(natural, requirement, api)
    except prices.ZeroMass as error:
        case.update(status=absent(error), reason=error.reason)
        return
    place = block.site
    case.update(status="sampled", probability_given_upstream=block.probability, offer_id=place.offer_id,
                natural=dict(zip(("threshold_minor", "price_minor"), threshold.listed(natural, place))),
                outcomes_modelled=len(block.outcomes))
    for index in range(args.samples):
        clock = time.monotonic()
        world, found, record = threshold.steer(session, natural, opened, requirement, api, sample_rng(natural, case, index))
        seconds = time.monotonic() - clock
        # The saved leaves themselves, by the native rule written out in `threshold.holds`.
        pinned.ensure(threshold.holds(place.requirement, *threshold.listed(world, place)),
                      "Direct reading of the saved leaves disagrees with the steered result")
        files = write(folder(index), {"world.private.json": world, "observed.json": found, "steering.json": record})
        case["samples"].append({"folder": folder(index).name, "world_id": world["world_id"], "seconds": seconds,
                                **{key: found[key] for key in ("unit_price_minor", "subtotal_minor",
                                                               "advertised_threshold_minor", "subtotal_test")},
                                "streams_steered": record["streams_steered"], "files": files})
    if args.producer_redraws:
        producer_redraws(args, session, natural, [threshold.trial(natural, requirement, api)], case)
    if args.validate_trials:
        seen = threshold.empirical(natural, requirement, api, args.validate_trials, 10 ** 6)
        frequency_check(case, block.probability, sum(seen.values()), args.validate_trials)


def policy_case(args, session, natural, opened, api, requirement, case, folder):
    try:
        block = policies.model(natural, requirement, api)
    except prices.ZeroMass as error:
        case.update(status=absent(error), reason=error.reason, detail=str(error))
        return
    place = block.site
    before = policies.listed(natural, place)
    case.update(status="sampled", probability_given_upstream=block.probability, retailer_id=place.retailer_id,
                **({"probability_is_estimated": True, "probability_standard_error": block.error,
                    "proposals": policies.PROPOSALS, "proposals_accepted": block.accepted}
                   if block.accepted is not None else {}),
                natural={"contracts": before[0], "warehouse_dispatch_days": before[1]},
                outcomes_modelled=len(block.outcomes or ()) + len(block.days or ()))
    for index in range(args.samples):
        clock = time.monotonic()
        world, found, record = policies.steer(session, natural, opened, requirement, api, sample_rng(natural, case, index))
        seconds = time.monotonic() - clock
        # The saved leaves themselves, by the rule written out in `policies.holds`.
        pinned.ensure(policies.holds(place.requirement, *policies.listed(world, place)),
                      "Direct reading of the saved leaves disagrees with the steered result")
        files = write(folder(index), {"world.private.json": world, "observed.json": found, "steering.json": record})
        case["samples"].append({"folder": folder(index).name, "world_id": world["world_id"], "seconds": seconds,
                                "contracts": found["contracts"], "warehouse_dispatch_days": found["warehouse_dispatch_days"],
                                **({"shown": found["shown"]} if "shown" in found else {}),
                                "streams_steered": record["streams_steered"], "files": files})
    if args.producer_redraws:
        producer_redraws(args, session, natural, [policies.trial(natural, requirement, api)], case)
    if args.validate_trials:
        hits = policies.empirical(natural, requirement, api, args.validate_trials, 10 ** 6)
        frequency_check(case, block.probability, hits, args.validate_trials, block.error)


def stars_case(args, session, natural, opened, api, requirement, case, folder):
    try:
        block = ratings.model(natural, requirement, api)
    except prices.ZeroMass as error:
        case.update(status=absent(error), reason=error.reason)
        return
    place = block.site
    levels, stars = ratings.written(natural, place)
    case.update(status="sampled", probability_given_upstream=block.probability,
                log_probability_given_upstream=block.log_probability, carrier_id=place.carrier_id,
                natural={"aspect_levels": levels, "average_stars": ratings.average(sum(stars), len(stars))},
                level_choices_modelled=len(block.alternatives))
    for index in range(args.samples):
        clock = time.monotonic()
        world, found, record = ratings.steer(session, natural, opened, requirement, api, sample_rng(natural, case, index))
        seconds = time.monotonic() - clock
        # The saved leaves themselves, by the rule written out in `ratings.holds`.
        pinned.ensure(ratings.holds(place.requirement, *ratings.written(world, place)),
                      "Direct reading of the saved leaves disagrees with the steered result")
        files = write(folder(index), {"world.private.json": world, "observed.json": found, "steering.json": record})
        case["samples"].append({"folder": folder(index).name, "world_id": world["world_id"], "seconds": seconds,
                                "aspect_levels": found["aspect_levels"], "average_stars": found["average_stars"],
                                "streams_steered": record["streams_steered"], "files": files})
    if args.producer_redraws:
        producer_redraws(args, session, natural, [ratings.trial(natural, requirement, api)], case)
    if args.validate_trials:
        hits = ratings.empirical(natural, requirement, api, args.validate_trials, 10 ** 6)
        frequency_check(case, block.probability, hits, args.validate_trials, getattr(block, "error", 0.0))


def seller_case(args, session, natural, opened, api, requirement, case, folder):
    try:
        block = sellers.model(natural, requirement, api)
    except prices.ZeroMass as error:
        case.update(status=absent(error), reason=error.reason, detail=str(error))
        return
    case.update(status="sampled", probability_given_upstream=block.probability or None,
                log_probability_given_upstream=block.log_probability, alternatives_modelled=len(block.alternatives),
                **({"probability_is_estimated": True, "probability_standard_error": block.error,
                    "policy_draws_accepted_by_retailer": block.estimates,
                    "retailers_not_found_in_bounded_search": block.not_found,
                    "ranking_samples_accepted_by_pair": block.ranking_estimates,
                    "rankings_not_found_in_bounded_search": block.rankings_not_found} if block.estimated else {}))
    for index in range(args.samples):
        clock = time.monotonic()
        world, found, record = sellers.steer(session, natural, opened, requirement, api, sample_rng(natural, case, index))
        seconds = time.monotonic() - clock
        # The saved leaves themselves: the winner's recorded contracts and dispatch days by `policies.holds`.
        retailer = next(row for row in world["retailers"] if row["retailer_id"] == found["retailer_id"])
        pinned.ensure(policies.holds(policies.resolve(sellers.policy(block.requirement, found["retailer_id"])),
                                     retailer["contracts"], retailer["source_locations"][0]["dispatch_days"]),
                      "Direct reading of the saved leaves disagrees with the steered result")
        files = write(folder(index), {"world.private.json": world, "observed.json": found, "steering.json": record})
        case["samples"].append({"folder": folder(index).name, "world_id": world["world_id"], "seconds": seconds,
                                "retailer_id": found["retailer_id"], "product_id": found["product_id"],
                                "contracts": found["policy"]["contracts"],
                                "streams_steered": record["streams_steered"], "files": files})
    if args.producer_redraws:
        producer_redraws(args, session, natural, [sellers.trial(natural, requirement, api)], case)
    if args.validate_trials:
        seen = sellers.empirical(natural, requirement, api, args.validate_trials, 10 ** 6)
        frequency_check(case, block.probability, sum(seen.values()), args.validate_trials, block.error)


def reviews_case(args, session, natural, opened, api, requirement, case, folder):
    """A product's reviews, a carrier's, or a carrier's shipments with them: the modules answer to the same names."""
    module = {carriers.VERSION: carriers, shipments.VERSION: shipments}.get(requirement["schema"], reviews)
    try:
        block = module.model(natural, requirement, api)
    except prices.ZeroMass as error:
        case.update(status=absent(error), reason=error.reason)
        return
    place = block.site
    signs = carriers.SIGNS if module is carriers else (reviews.POSITIVE, reviews.NEGATIVE)
    case.update(status="sampled", probability_given_upstream=block.probability or None,
                log_probability_given_upstream=block.log_probability,
                natural=dict(zip(signs, module.counted(place, module.written(natural, place)))),
                counts_modelled=len(block.log_terms),
                **({"carrier_id": place.carrier_id,
                    "shipments_that_could_mention": {sign: len(found) for sign, found in block.groups.items()}}
                   if module is carriers else
                   {"carrier_id": place.carrier_id, "shipments": place.count, "shipment_class_probabilities": block.shares}
                   if module is shipments else
                   {"product_id": place.product_id, "reviews": place.count, "review_class_probabilities": block.shares}))
    for index in range(args.samples):
        clock = time.monotonic()
        try:
            world, found, record = module.steer(session, natural, opened, requirement, api,
                                                sample_rng(natural, case, index))
        except blocks.NumericalLimit as error:
            case.update(status="refused", reason=error.reason, detail=str(error))
            return
        seconds = time.monotonic() - clock
        # The saved review records themselves, by the native rule written out in the module.
        pinned.ensure(module.holds(place.requirement, *module.counted(place, module.written(world, place))),
                      "Direct reading of the saved reviews disagrees with the steered result")
        files = write(folder(index), {"world.private.json": world, "observed.json": found, "steering.json": record})
        case["samples"].append({"folder": folder(index).name, "world_id": world["world_id"], "seconds": seconds,
                                "counts": found["counts"], "verdict": found["verdict"],
                                "review_redraws": record.get("review_redraws", record.get("shipment_redraws")),
                                "streams_steered": record["streams_steered"], "files": files})
    if args.producer_redraws:
        producer_redraws(args, session, natural, [module.trial(natural, requirement, api)], case)
    if args.validate_trials:
        seen = module.empirical(natural, requirement, api, args.validate_trials, 10 ** 6)
        frequency_check(case, block.probability, sum(seen.values()), args.validate_trials)


def held(row):
    """Whether an offer's recorded leaves make it available: stock anywhere or a supplier order."""
    return any(row["stock_by_source"].values()) or row["supplier_order"]


def combined_case(args, session, natural, opened, api, requirement, case, folder):
    for index in range(args.samples):
        clock = time.monotonic()
        try:
            world, found, record = combined.steer(session, natural, opened, requirement, api, sample_rng(natural, case, index))
        except prices.ZeroMass as error:
            case.update(status=absent(error), reason=error.reason, part=getattr(error, "part", None))
            return
        except (blocks.Coupled, cheapest.NumericalLimit) as error:
            case.update(status="refused", reason=error.reason, detail=str(error))
            return
        seconds = time.monotonic() - clock
        parts = [part["probability_given_upstream"] for part in record["blocks"]]
        files = write(folder(index), {"world.private.json": world, "observed.json": found, "steering.json": record})
        errors = [part.get("probability_standard_error", 0.0) for part in record["blocks"]]
        case.update(status="sampled", probability_given_upstream=record["probability_given_upstream"],
                    part_probabilities=parts, methods=[part["method"] for part in record["blocks"]],
                    **({"probability_is_estimated": True, "part_probability_standard_errors": errors,
                        "probability_standard_error": record["probability_standard_error"]}
                       if record.get("probability_is_estimated") else {}))
        case["samples"].append({
            "folder": folder(index).name, "world_id": world["world_id"], "seconds": seconds,
            "streams_steered": record["streams_steered"],
            "streams_opened_only_when_steered": record["streams_opened_only_when_steered"],
            "streams_opened_only_naturally": record["streams_opened_only_naturally"], "files": files})
    if args.producer_redraws:
        producer_redraws(args, session, natural, combined.trial(natural, requirement, api), case)
    if args.validate_trials:
        alone, together = combined.empirical(natural, requirement, api, args.validate_trials, 10 ** 6)
        # A probability below the float range is recorded as None and has no frequency to compare.
        validation = frequency_check(case, case["probability_given_upstream"] or 0.0, together, args.validate_trials,
                                     case.get("probability_standard_error", 0.0))
        validation["parts"] = []
        for probability, hits, estimate in zip(case["part_probabilities"], alone,
                                               case.get("part_probability_standard_errors", [0.0] * len(alone))):
            probability = probability or 0.0
            error = sqrt(probability * (1 - probability) / args.validate_trials + estimate ** 2)
            validation["parts"].append({"hits": hits, "computed": probability, "standard_error": error})
            pinned.ensure(abs(hits / args.validate_trials - probability) <= 4 * error,
                          "A part's computed probability disagrees with the producer's draws")


CASES = {edits.VERSION: ("prices", price_case), stock.VERSION: ("stock", stock_case),
         price_bounds.VERSION: ("price", bound_case), cheapest.VERSION: ("stock_and_prices", cheapest_case),
         listed.VERSION: ("listed_prices", listed_case), shortlist.VERSION: ("shortlist", shortlist_case),
         threshold.VERSION: ("threshold", threshold_case), reviews.VERSION: ("reviews", reviews_case),
         carriers.VERSION: ("carrier_reviews", reviews_case),
         shipments.VERSION: ("carrier_shipments", reviews_case),
         policies.VERSION: ("shipping_policy", policy_case),
         sellers.VERSION: ("cheapest_seller_policy", seller_case),
         ratings.VERSION: ("carrier_stars", stars_case),
         combined.VERSION: ("combined", combined_case)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--native-root", type=Path, required=True)
    parser.add_argument("--native-commit", required=True)
    parser.add_argument("--steering-commit", required=True)
    parser.add_argument("--generation-input", type=Path, required=True)
    parser.add_argument("--expected-natural-world-id",
                        help="fail unless the natural pass reproduces this saved world")
    parser.add_argument("--requirement", type=Path, action="append", default=[])
    parser.add_argument("--task", type=Path,
                        help="a native task specification as JSON; its requirement candidates on the natural world "
                             "are written under OUTPUT/candidates and run")
    parser.add_argument("--candidate", action="append",
                        help="with --task, the name of a candidate to run (repeatable; all of them without it)")
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--validate-trials", type=int, default=0,
                        help="redraw the block this many times under other seeds, outside the producer's "
                             "world loop, and compare the frequency with the computed probability")
    parser.add_argument("--producer-redraws", type=int, default=0,
                        help="run the real producer this many times with the block's streams opened under "
                             "other seeds and compare it with the block module's reading (not for a "
                             "who-is-cheapest requirement on prices alone)")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if bool(args.requirement) == bool(args.task) or args.candidate and not args.task:
        parser.error("give requirement files or a task, and candidate names only with a task")
    started = time.monotonic()
    root = args.native_root.resolve()
    api = pinned.load_native(root, args.native_commit)
    api.package_export = importlib.import_module("experiments.accepted_catalog_commerce.package_export")
    api.population = importlib.import_module("experiments.world_sampling_defaults.model")
    commit, own_pins, own_paths = pin_own(args.steering_commit)
    native_pins = pinned.verify_sources(root, own_paths)
    inputs_raw = args.generation_input.read_bytes()
    session = streams.Session(api, json.loads(inputs_raw))
    clock = time.monotonic()
    natural, opened = session.generate()
    natural_seconds = time.monotonic() - clock
    if args.expected_natural_world_id not in (None, natural["world_id"]):
        raise ValueError("Natural pass does not reproduce the expected world")
    clock = time.monotonic()
    again, _ = session.generate()
    replay_seconds = time.monotonic() - clock
    pinned.ensure(again["world_id"] == natural["world_id"], "An unsteered pass must reproduce the natural world")
    pinned.ensure(not edits.price_rule_violations(natural, api.native.rounded_price), "Natural world breaks the price rule")
    output = args.output.resolve()
    task = None
    if args.task:
        task_raw = args.task.read_bytes()
        found = variants.of(natural, json.loads(task_raw), api)
        if not found:
            # Nothing to run is not a run that passed.
            raise ValueError("No candidates for this task on this world")
        wanted = [row["name"] for row in found] if args.candidate is None else args.candidate
        if set(wanted) - {row["name"] for row in found} or len(set(wanted)) != len(wanted):
            raise ValueError("Unknown or repeated candidate; this task has on this world: " +
                             ", ".join(row["name"] for row in found))
    output.mkdir(parents=True, exist_ok=False)
    if args.task:
        (output / "candidates").mkdir()
        for row in found:
            (output / "candidates" / (row["name"] + ".json")).write_text(
                json.dumps(row["requirement"], indent=2, ensure_ascii=False) + "\n")
        args.requirement = [output / "candidates" / (name + ".json") for name in wanted]
        task = {"path": str(args.task), "sha256": edits.byte_digest(task_raw),
                "candidates": [{key: row[key] for key in ("name", "summary", "log_probability")} for row in found],
                "run": wanted}
    cases = []
    for path in args.requirement:
        requirement_raw = path.read_bytes()
        requirement = json.loads(requirement_raw)
        if type(requirement) is not dict or requirement.get("schema") not in CASES:
            raise ValueError("Unsupported requirement schema: " + str(path))
        block, run_case = CASES[requirement["schema"]]
        case = {"requirement": str(path), "requirement_sha256": edits.byte_digest(requirement_raw),
                "block": block, "samples": []}
        cases.append(case)
        run_case(args, session, natural, opened, api, requirement, case,
                 lambda index, stem=path.stem: output / f"{stem}-sample-{index}")
    final_pins = pinned.verify_sources(root, own_paths)
    pinned.ensure(native_pins.items() <= final_pins.items(), "Consumed native sources changed")
    pinned.ensure(args.generation_input.read_bytes() == inputs_raw, "Generation input changed")
    pinned.ensure(not args.task or args.task.read_bytes() == task_raw, "Task specification changed")
    pinned.ensure(all(edits.byte_digest(Path(p).read_bytes()) == digest for p, digest in own_paths.items()),
                  "Steering source changed")
    pinned.ensure(session.generate()[0]["world_id"] == natural["world_id"],
                  "An unsteered pass after the steered ones must still reproduce the natural world")
    receipt = {"schema": "steered-generation-v3", "status": "passed_native_only",
               "native_commit": args.native_commit, "native_root": str(root),
               "steering_commit": commit, "steering_source_sha256": own_pins, "native_source_sha256": final_pins,
               "generation_input_sha256": edits.byte_digest(inputs_raw),
               "natural_world_id": natural["world_id"], "summary": natural["summary"],
               "streams_opened_per_pass": len(opened), "distinct_streams": len(set(opened)),
               "natural_pass_seconds": natural_seconds, "unsteered_replay_seconds": replay_seconds,
               "sampling_defaults_read_once": session.defaults is not None,
               **({"task": task} if task else {}),
               "cases": cases, "browser_runtime_ready": False, "provider_calls": 0,
               "elapsed_seconds": time.monotonic() - started}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"natural_pass_seconds": round(natural_seconds, 1), "unsteered_replay_seconds": round(replay_seconds, 2),
                      "cases": [{"requirement": Path(c["requirement"]).name, "block": c["block"],
                                 "status": c.get("status"), "reason": c.get("reason"),
                                 "probability_given_upstream": c.get("probability_given_upstream"),
                                 "sample_seconds": [round(s["seconds"], 2) for s in c["samples"]],
                                 "producer_redraws": c.get("producer_redraws"),
                                 "validation": c.get("validation")} for c in cases]}, indent=1))


if __name__ == "__main__":
    main()
