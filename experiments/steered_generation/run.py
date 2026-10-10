"""Steered price generation from an exact Git dependency root.

Run as a module from the repository root:
    python -m experiments.steered_generation.run ...
One natural pass through the real producer, then one cheap steered pass per
requested sample. No browser, provider or sidecar publication.
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

from . import prices, streams

HERE = Path(__file__).resolve().parent
OWN = {HERE: ("__init__.py", "streams.py", "prices.py", "run.py"),
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
                        help="redraw the price block this many times with the real pricing function "
                             "and compare the frequency with the computed probability")
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
        case = {"requirement": str(path), "requirement_sha256": edits.byte_digest(requirement_raw), "samples": []}
        cases.append(case)
        for index in range(args.samples):
            rng = Random(int(sha256(f"{natural['world_id']}/{case['requirement_sha256']}/{index}".encode()).hexdigest(), 16))
            clock = time.monotonic()
            try:
                world, task, reference, record = prices.steer(session, natural, requirement, api, rng)
            except prices.ZeroMass as error:
                case.update(status="zero_probability_given_upstream", reason=error.reason)
                break
            seconds = time.monotonic() - clock
            minimum, scanned = pinned.direct_scan(world, requirement)
            designated = {(rid, requirement["product_id"]) for rid in requirement["retailer_ids"]}
            pinned.ensure(scanned == designated and minimum == reference["minimum_price_minor"] == record["winning_price_minor"],
                          "Direct full-population scan disagrees with the steered result")
            folder = output / f"{path.stem}-sample-{index}"
            folder.mkdir()
            files = {"world.private.json": world, "task.private.json": task,
                     "reference.private.json": reference, "steering.json": record}
            for name, value in files.items():
                (folder / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
            case.update(status="sampled", probability_given_upstream=record["probability_given_upstream"])
            case["samples"].append({
                "folder": folder.name, "world_id": world["world_id"], "seconds": seconds,
                "winning_price_minor": minimum, "winner_count": len(reference["winners"]),
                "repriced_retailer_products": len(record["repriced"]),
                "changed_price_leaves": sum(o["natural"] != o["steered"] for r in record["repriced"] for o in r["offers"]),
                "files": {name: edits.byte_digest((folder / name).read_bytes()) for name in files}})
        if args.validate_trials and case.get("status") == "sampled":
            probability = case["probability_given_upstream"]
            winning = prices.empirical(natural, requirement, api, args.validate_trials, 10 ** 6)
            hits = sum(winning.values())
            error = sqrt(probability * (1 - probability) / args.validate_trials)
            terms = prices.model(natural, requirement, api).terms
            # Winning-price distribution given the requirement: model against real redraws.
            distance = sum(abs(terms.get(p, 0) / probability - winning.get(p, 0) / hits)
                           for p in set(terms) | set(winning)) / 2 if hits else None
            case["validation"] = {"trials": args.validate_trials, "hits": hits, "frequency": hits / args.validate_trials,
                                  "computed": probability, "standard_error": error,
                                  "within_four_standard_errors": abs(hits / args.validate_trials - probability) <= 4 * error,
                                  "winning_price_total_variation": distance,
                                  "winning_prices_modelled": len(terms)}
            pinned.ensure(case["validation"]["within_four_standard_errors"],
                          "Computed probability disagrees with the real pricing function")
            pinned.ensure(hits < 1000 or distance < 0.1,
                          "Conditional winning-price distribution disagrees with the real pricing function")
    final_pins = pinned.verify_sources(root, own_paths)
    pinned.ensure(native_pins.items() <= final_pins.items(), "Consumed native sources changed")
    pinned.ensure(args.generation_input.read_bytes() == inputs_raw, "Generation input changed")
    pinned.ensure(all(edits.byte_digest(Path(p).read_bytes()) == digest for p, digest in own_paths.items()),
                  "Steering source changed")
    receipt = {"schema": "steered-price-generation-v1", "status": "passed_native_only",
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
                      "cases": [{"requirement": Path(c["requirement"]).name, "status": c.get("status"),
                                 "probability_given_upstream": c.get("probability_given_upstream"),
                                 "sample_seconds": [round(s["seconds"], 2) for s in c["samples"]],
                                 "validation": c.get("validation")} for c in cases]}, indent=1))


if __name__ == "__main__":
    main()
