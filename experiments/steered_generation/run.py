"""Steered generation from an exact Git dependency root.

Run as a module from the repository root:
    python -m experiments.steered_generation.run ...
One natural pass through the real producer, then one cheap steered pass per
requested sample. Each requirement file is either a who-is-cheapest price
requirement or a one-offer stock requirement. No browser, provider or sidecar
publication.
"""
import argparse
from hashlib import sha256
import importlib
import json
from math import sqrt
from pathlib import Path
from random import Random
import subprocess
import time

from experiments.world_requirement_construction import model as edits, run as pinned

from . import prices, stock, streams

HERE = Path(__file__).resolve().parent
OWN = {HERE: ("__init__.py", "streams.py", "prices.py", "stock.py", "run.py"),
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


def frequency_check(case, probability, hits, trials):
    error = sqrt(probability * (1 - probability) / trials)
    case["validation"] = {"trials": trials, "hits": hits, "frequency": hits / trials, "computed": probability,
                          "standard_error": error,
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
            case.update(status="zero_probability_given_upstream", reason=error.reason)
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


def stock_case(args, session, natural, opened, api, requirement, case, folder):
    try:
        block = stock.model(natural, requirement, api)
    except prices.ZeroMass as error:
        case.update(status="zero_probability_given_upstream", reason=error.reason)
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
        # The real producer redraws the block under other seeds; this module's
        # reading of the stock lines must agree with it draw for draw.
        hits = 0
        for seed in range(2 * 10 ** 6, 2 * 10 ** 6 + args.producer_redraws):
            found = stock.redraw(session, natural, requirement, api, seed)
            pinned.ensure(found.recorded == found.reading and found.satisfied == found.reading_satisfied,
                          "Reading of the producer's stock lines disagrees with the producer")
            hits += found.satisfied
        case["producer_redraws"] = {"passes": args.producer_redraws, "identical_to_reading": args.producer_redraws,
                                    "requirement_held": hits}
    if args.validate_trials:
        ends = stock.empirical(natural, requirement, api, args.validate_trials, 10 ** 6)
        hits = sum(ends.values())
        validation = frequency_check(case, block.probability, hits, args.validate_trials)
        # How the block ends given the requirement: model against the reading's redraws.
        distance = sum(abs(block.outcomes.get(e, 0) / block.probability - ends.get(e, 0) / hits)
                       for e in set(block.outcomes) | set(ends)) / 2 if hits else None
        validation.update(ending_total_variation=distance, endings_modelled=len(block.outcomes))
        pinned.ensure(hits < 1000 or distance < 0.1,
                      "Conditional distribution of the block's ending disagrees with the producer's draws")


CASES = {edits.VERSION: ("prices", price_case), stock.VERSION: ("stock", stock_case)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--native-root", type=Path, required=True)
    parser.add_argument("--native-commit", required=True)
    parser.add_argument("--steering-commit", required=True)
    parser.add_argument("--generation-input", type=Path, required=True)
    parser.add_argument("--expected-natural-world-id",
                        help="fail unless the natural pass reproduces this saved world")
    parser.add_argument("--requirement", type=Path, required=True, action="append")
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--validate-trials", type=int, default=0,
                        help="redraw the block this many times under other seeds, outside the producer's "
                             "world loop, and compare the frequency with the computed probability")
    parser.add_argument("--producer-redraws", type=int, default=0,
                        help="stock requirements: run the real producer this many times with the block's "
                             "streams opened under other seeds and compare it with this module's reading")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
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
    output.mkdir(parents=True, exist_ok=False)
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
    pinned.ensure(all(edits.byte_digest(Path(p).read_bytes()) == digest for p, digest in own_paths.items()),
                  "Steering source changed")
    pinned.ensure(session.generate()[0]["world_id"] == natural["world_id"],
                  "An unsteered pass after the steered ones must still reproduce the natural world")
    receipt = {"schema": "steered-generation-v2", "status": "passed_native_only",
               "native_commit": args.native_commit, "native_root": str(root),
               "steering_commit": commit, "steering_source_sha256": own_pins, "native_source_sha256": final_pins,
               "generation_input_sha256": edits.byte_digest(inputs_raw),
               "natural_world_id": natural["world_id"], "summary": natural["summary"],
               "streams_opened_per_pass": len(opened), "distinct_streams": len(set(opened)),
               "natural_pass_seconds": natural_seconds, "unsteered_replay_seconds": replay_seconds,
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
