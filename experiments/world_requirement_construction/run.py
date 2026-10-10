"""Saved-only construction/native acceptance from an exact Git dependency root."""
import argparse
from copy import deepcopy
import importlib
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

if __package__:
    from .model import (CannotConstruct, META_FIELDS, VERSION, apply_draw, byte_digest,
                        check, construct, price_rule_violations)
else:
    from model import (CannotConstruct, META_FIELDS, VERSION, apply_draw, byte_digest,
                       check, construct, price_rule_violations)

HERE = Path(__file__).resolve().parent
RELATIVE = "experiments/world_requirement_construction/"


def ensure(condition, message):
    if not condition:
        raise AssertionError(message)


def load_native(root, commit):
    root = root.resolve()
    actual = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if actual != commit:
        raise ValueError("Native dependency HEAD differs from the approved base")
    if subprocess.check_output(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"]):
        raise ValueError("Tracked native dependency tree is not clean")
    # No mutable repository fallback: this script's directory and the exact root
    # are the only project search paths. Stdlib/site-packages are still available.
    project = Path(__file__).resolve().parents[2]
    sys.path = [str(root)] + [p for p in sys.path
                             if Path(p or ".").resolve() != project]
    names = {"basic": "environments.website_world.basic_offer_task",
             "commerce": "experiments.accepted_catalog_commerce.model",
             "native": "experiments.footwear_world_pilot.model",
             "basket": "experiments.accepted_catalog_commerce.basket_quote",
             "checkout": "environments.website_world.catalog_checkout_domain"}
    modules = {k: importlib.import_module(v) for k, v in names.items()}
    for module in modules.values():
        if not Path(module.__file__).resolve().is_relative_to(root):
            raise ValueError("Imported native module escaped the accepted dependency root")
    return SimpleNamespace(**modules)


def pin_constructor(declared):
    """Resolve the declared commit in the constructor's own repository."""
    try:
        commit = subprocess.check_output(
            ["git", "-C", str(HERE), "rev-parse", "--verify", "--quiet", declared + "^{commit}"],
            text=True, stderr=subprocess.DEVNULL).strip()
    except subprocess.CalledProcessError:
        raise ValueError("Constructor commit cannot be resolved: " + declared) from None
    pins, paths = {}, {}
    for name in ("__init__.py", "model.py", "run.py"):
        expected = subprocess.check_output(["git", "-C", str(HERE), "show", commit + ":" + RELATIVE + name])
        if (HERE / name).read_bytes() != expected:
            raise ValueError("Constructor source differs from its declared commit: " + name)
        pins[name] = paths[str(HERE / name)] = byte_digest(expected)
    return commit, pins, paths


def verify_sources(root, constructor_paths):
    pins = {}
    for module in tuple(sys.modules.values()):
        name = getattr(module, "__file__", None)
        if not name:
            continue
        path = Path(name).resolve()
        if (getattr(module, "__name__", "").split(".")[0] in
                {"environments", "experiments", "intent_browser", "training", "scripts"}
                and not path.is_relative_to(root)):
            if constructor_paths.get(str(path)) != byte_digest(path.read_bytes()):
                raise ValueError("Project dependency escaped the accepted root: " + str(path))
        if path.is_relative_to(root) and path.suffix == ".py":
            relative = path.relative_to(root).as_posix()
            expected = subprocess.check_output(["git", "-C", str(root), "show", "HEAD:" + relative])
            if path.read_bytes() != expected:
                raise ValueError("Native dependency differs from its committed blob: " + relative)
            pins[relative] = byte_digest(expected)
    return pins


def declines(call, reason):
    """A control passes only when the operator declines for the named reason."""
    try:
        call()
    except CannotConstruct as error:
        return error.reason == reason
    return False


def rejects(call):
    try:
        call()
    except ValueError:
        return True
    return False


def direct_scan(world, requirement):
    """Full-population winner scan, independent of the native oracle."""
    products = {p["public"]["product_id"]: p["public"] for p in world["products"]}
    eligible = [(r["retailer_id"], o) for r in world["retailers"] for o in r["offers"]
                if products[o["product_id"]]["concept_id"] == requirement["concept_id"]
                and (any(o["stock_by_source"].values()) or o["supplier_order"]["enabled"])]
    minimum = min(o["price_minor"] for _, o in eligible)
    return minimum, {(rid, o["product_id"]) for rid, o in eligible if o["price_minor"] == minimum}


def negative_controls(parent, world, requirement, api, plan, domain):
    """Deliberately broken inputs; none of this is needed to construct."""
    selection = {"kind": "cheapest_available", "concept_id": requirement["concept_id"]}
    controls = {
        "old_basket_binding_rejects": rejects(lambda: api.basket.validate_plan(world, plan)),
        "old_checkout_binding_rejects": rejects(lambda: api.checkout.validate(world, domain)),
        "old_task_binding_rejects": rejects(
            lambda: api.basic.reference(world, api.basic.make(parent, selection)))}
    config = world["config"]["retailer_price"]
    first, product_id = requirement["retailer_ids"][0], requirement["product_id"]
    scratch = deepcopy(world)
    group = [o for r in scratch["retailers"] if r["retailer_id"] == first
             for o in r["offers"] if o["product_id"] == product_id]
    saved = deepcopy(group)
    # The retired variant-level edit: one SKU cheaper than its siblings.
    group[0]["price_minor"] -= 100
    controls["single_variant_price_edit_breaks_price_rule"] = declines(
        lambda: check(scratch, requirement, api), "price_rule")
    for offer, original in zip(group, saved):
        offer.update(deepcopy(original))
    if len(requirement["retailer_ids"]) > 1:
        # A consistent draw that moves one designated retailer off the shared price.
        current = group[0]["price_minor"]
        for offset in (config["offset_max"], config["offset_min"]):
            apply_draw(group, (False, offset), config, api.native.rounded_price)
            if group[0]["price_minor"] != current:
                break
        controls["repriced_designated_retailer_loses_tie"] = declines(
            lambda: check(scratch, requirement, api), "winners")
    others = [r["retailer_id"] for r in world["retailers"]
              if r["retailer_id"] not in requirement["retailer_ids"]]
    if others:
        wider = {**requirement, "retailer_ids": requirement["retailer_ids"] + others[:1]}
        controls["extra_designated_retailer_rejects"] = declines(
            lambda: check(world, wider, api), "winners")
    absent = {**requirement, "retailer_ids": requirement["retailer_ids"] + ["absent-retailer"]}
    controls["unknown_retailer_declines"] = declines(
        lambda: construct(parent, absent, api, parent_bytes_sha256="control"), "unavailable")
    controls["authored_chain_declines"] = declines(
        lambda: construct(world, requirement, api, parent_bytes_sha256="control"), "not_sampled")
    # The same prices presented as an untouched sampled world.
    satisfied = {**world, **{field: parent[field] for field in META_FIELDS}}
    controls["already_satisfied_parent_declines"] = declines(
        lambda: construct(satisfied, requirement, api, parent_bytes_sha256="control"), "already_holds")
    return controls


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-root", type=Path, required=True)
    parser.add_argument("--native-commit", required=True)
    parser.add_argument("--constructor-commit", required=True)
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--expected-parent-manifest-sha256", required=True)
    parser.add_argument("--requirement", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--controls", action="store_true",
                        help="also run the negative controls; not needed to construct")
    args = parser.parse_args()
    started = time.monotonic()
    root = args.native_root.resolve()
    api = load_native(root, args.native_commit)
    constructor_commit, constructor_pins, constructor_paths = pin_constructor(args.constructor_commit)
    source_pins = verify_sources(root, constructor_paths)
    manifest_raw = (args.recipe / "manifest.json").read_bytes()
    if byte_digest(manifest_raw) != args.expected_parent_manifest_sha256:
        raise ValueError("Parent manifest differs from its externally declared pin")
    manifest = json.loads(manifest_raw)
    names = ("pin/world.private.json", "basket-plan.private.json", "checkout-domain.private.json")
    originals = {name: (args.recipe / name).read_bytes() for name in names}
    for name, raw in originals.items():
        if byte_digest(raw) != manifest["files"][name]:
            raise ValueError("Accepted input differs from its recipe manifest: " + name)
    parent, plan, domain = (json.loads(originals[name]) for name in names)
    api.basket.validate_plan(parent, plan)
    api.checkout.validate(parent, domain)
    requirement_raw = args.requirement.read_bytes()
    requirement = json.loads(requirement_raw)
    world, task, reference, provenance = construct(
        parent, requirement, api, parent_bytes_sha256=byte_digest(originals[names[0]]))
    # Policies/options are retained, while all world hash envelopes are rebuilt.
    policies = {r["retailer_id"]: {k: v for k, v in r.items() if k != "retailer_id"}
                for r in plan["retailer_policies"]}
    new_plan = api.basket.make_plan(world, retailer_policies=policies)
    new_domain = api.checkout.make(world, domain["options"])
    api.basket.validate_plan(world, new_plan)
    api.checkout.validate(world, new_domain)
    ensure(new_plan["retailer_policies"] == plan["retailer_policies"], "Basket policies changed")
    ensure(new_domain["quantity_limits"] == domain["quantity_limits"], "Checkout quantity limits changed")
    designated = {(rid, requirement["product_id"]) for rid in requirement["retailer_ids"]}
    minimum, scanned = direct_scan(world, requirement)
    checks = {"direct_scan_matches_native_reference":
                  scanned == designated and minimum == reference["minimum_price_minor"],
              "price_rule_holds": not price_rule_violations(world, api.native.rounded_price),
              "parent_unchanged_in_memory": parent == json.loads(originals[names[0]])}
    controls = negative_controls(parent, world, requirement, api, plan, domain) if args.controls else {}
    ensure(all(checks.values()) and all(controls.values()),
           "Failed: " + ", ".join(k for k, v in {**checks, **controls}.items() if not v))
    # No source or original artifact drift is accepted during construction.
    final_pins = verify_sources(root, constructor_paths)
    ensure(source_pins.items() <= final_pins.items(), "Consumed native sources changed")
    ensure(all((args.recipe / n).read_bytes() == raw for n, raw in originals.items()), "Original input artifact changed")
    ensure((args.recipe / "manifest.json").read_bytes() == manifest_raw, "Parent manifest changed")
    ensure(args.requirement.read_bytes() == requirement_raw, "Requirement changed")
    ensure(subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip() == args.native_commit, "Native HEAD changed")
    ensure(not subprocess.check_output(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"]), "Native tracked tree changed")
    ensure(all(byte_digest((HERE / n).read_bytes()) == pin for n, pin in constructor_pins.items()), "Constructor source changed")
    api.basket.validate_plan(parent, plan)
    api.checkout.validate(parent, domain)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    artifacts = {"world.private.json": world, "task.private.json": task,
                 "reference.private.json": reference, "basket-plan.private.json": new_plan,
                 "checkout-domain.private.json": new_domain, "edit-provenance.json": provenance}
    for name, value in artifacts.items():
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    receipt = {"schema": VERSION, "status": "passed_construction_native_only",
               "native_commit": args.native_commit, "native_root": str(root),
               "constructor_commit": constructor_commit, "constructor_source_sha256": constructor_pins,
               "native_source_sha256": final_pins,
               "parent_recipe": str(args.recipe.resolve()), "parent_manifest_sha256": byte_digest(manifest_raw),
               "original_artifacts": {n: byte_digest(raw) for n, raw in originals.items()},
               "requirement_sha256": byte_digest(requirement_raw),
               "checks": checks, "negative_controls": controls, "summary": parent["summary"],
               "winner_count": len(reference["winners"]), "minimum_price_minor": minimum,
               "repriced_retailer_products": len(provenance["changes"]),
               "changed_price_leaves": sum(row["before"] != row["after"]
                                           for change in provenance["changes"] for row in change["offers"]),
               "probability_claim": None,
               "files": {n: byte_digest((output / n).read_bytes()) for n in artifacts},
               "invalidated_not_rebuilt": ["surrounding", "presentation", "URL bindings", "execution recipes", "old tasks and references"],
               "browser_runtime_ready": False, "world_draws": 0, "provider_calls": 0,
               "elapsed_seconds": time.monotonic() - started}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({k: receipt[k] for k in ("status", "minimum_price_minor", "winner_count", "repriced_retailer_products", "changed_price_leaves", "elapsed_seconds")}))


if __name__ == "__main__":
    main()
