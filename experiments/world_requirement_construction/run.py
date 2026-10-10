"""Saved-only construction/native acceptance from an exact Git dependency root."""
import argparse
from copy import deepcopy
from hashlib import sha256
import importlib
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

from model import CannotConstruct, VERSION, byte_digest, check, construct, price_domain


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


def verify_sources(root):
    pins = {}
    for module in tuple(sys.modules.values()):
        name = getattr(module, "__file__", None)
        if not name:
            continue
        path = Path(name).resolve()
        if (getattr(module, "__name__", "").split(".")[0] in
                {"environments", "experiments", "intent_browser", "training", "scripts"}
                and not path.is_relative_to(root)):
            raise ValueError("Project dependency escaped the accepted root: " + str(path))
        if path.is_relative_to(root) and path.suffix == ".py":
            relative = path.relative_to(root).as_posix()
            expected = subprocess.check_output(["git", "-C", str(root), "show", "HEAD:" + relative])
            if path.read_bytes() != expected:
                raise ValueError("Native dependency differs from its committed blob: " + relative)
            pins[relative] = byte_digest(expected)
    return pins


def reject(call, expected=(ValueError,)):
    try:
        call()
    except expected:
        return True
    raise AssertionError("Negative control was accepted")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-root", type=Path, required=True)
    parser.add_argument("--native-commit", required=True)
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--requirement", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    root = args.native_root.resolve()
    api = load_native(root, args.native_commit)
    source_pins = verify_sources(root)
    manifest_raw = (args.recipe / "manifest.json").read_bytes()
    manifest = json.loads(manifest_raw)
    names = ("pin/world.private.json", "basket-plan.private.json", "checkout-domain.private.json")
    originals = {name: (args.recipe / name).read_bytes() for name in names}
    for name, raw in originals.items():
        if byte_digest(raw) != manifest["files"][name]:
            raise ValueError("Accepted input differs from its recipe manifest: " + name)
    parent, plan, domain = (json.loads(originals[name]) for name in names)
    api.commerce.validate(parent)
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
    assert new_plan["retailer_policies"] == plan["retailer_policies"]
    assert new_domain["quantity_limits"] == domain["quantity_limits"]
    controls = {"old_basket_binding_rejects": reject(lambda: api.basket.validate_plan(world, plan)),
                "old_checkout_binding_rejects": reject(lambda: api.checkout.validate(world, domain)),
                "old_task_binding_rejects": reject(lambda: api.basic.reference(world, api.basic.make(parent, {"kind": "cheapest_available", "concept_id": requirement["concept_id"]})))}
    by_id = {o["offer_id"]: o for r in world["retailers"] for o in r["offers"]}
    first = requirement["offer_ids"][0]
    bad = deepcopy(world)
    next(o for r in bad["retailers"] for o in r["offers"] if o["offer_id"] == first)["price_minor"] += 1
    controls["unequal_target_prices_reject"] = reject(lambda: check(bad, requirement, api), (CannotConstruct,))
    bad_stock = deepcopy(world)
    offer = next(o for r in bad_stock["retailers"] for o in r["offers"] if o["offer_id"] == first)
    offer["stock_by_source"] = {s: 0 for s in offer["stock_by_source"]}
    offer["supplier_order"] = {"enabled": True, "wait_days": 1, "disclosure": "product_page"}
    controls["supplier_only_target_rejects"] = reject(lambda: check(bad_stock, requirement, api), (CannotConstruct,))
    impossible = deepcopy(parent)
    targets = set(requirement["offer_ids"])
    competitor = next(o for r in impossible["retailers"] for o in r["offers"]
                      if o["offer_id"] in {c["offer_id"] for c in api.basic.reference(parent, api.basic.make(parent, {"kind": "cheapest_available", "concept_id": requirement["concept_id"]}))["candidates"]} and o["offer_id"] not in targets)
    competitor["price_minor"] = 1
    controls["no_price_support_declines_without_edit"] = reject(
        lambda: construct(impossible, requirement, api, parent_bytes_sha256="control"), (CannotConstruct,))
    bad_target = {**requirement, "offer_ids": [first, "absent-offer"]}
    controls["unknown_target_rejects"] = reject(lambda: construct(parent, bad_target, api, parent_bytes_sha256="control"), (CannotConstruct,))
    # A separate direct full-population scan, independent of the existing oracle.
    products = {p["public"]["product_id"]: p["public"] for p in world["products"]}
    eligible = [o for r in world["retailers"] for o in r["offers"]
                if products[o["product_id"]]["concept_id"] == requirement["concept_id"]
                and (any(o["stock_by_source"].values()) or o["supplier_order"]["enabled"])]
    minimum = min(o["price_minor"] for o in eligible)
    assert {o["offer_id"] for o in eligible if o["price_minor"] == minimum} == targets
    controls["direct_scan_matches_native_reference"] = True
    controls["target_prices_in_native_support"] = all(
        by_id[oid]["price_minor"] in price_domain(by_id[oid], world["config"]["retailer_price"], api.native.rounded_price) for oid in targets)
    assert all(controls.values())
    # No source or original artifact drift is accepted during construction.
    assert source_pins.items() <= verify_sources(root).items()
    assert all((args.recipe / n).read_bytes() == raw for n, raw in originals.items())
    assert (args.recipe / "manifest.json").read_bytes() == manifest_raw
    assert args.requirement.read_bytes() == requirement_raw
    assert subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip() == args.native_commit
    assert not subprocess.check_output(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"])
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
               "native_source_sha256": verify_sources(root),
               "parent_recipe": str(args.recipe.resolve()), "parent_manifest_sha256": byte_digest(manifest_raw),
               "original_artifacts": {n: byte_digest(raw) for n, raw in originals.items()},
               "requirement_sha256": byte_digest(requirement_raw),
               "controls": controls, "summary": parent["summary"],
               "winner_count": len(reference["winners"]), "minimum_price_minor": minimum,
               "changed_price_leaves": len(provenance["changes"]),
               "background_exact_inverse": True, "parent_bindings_remain_valid": True,
               "files": {n: byte_digest((output / n).read_bytes()) for n in artifacts},
               "invalidated_not_rebuilt": ["surrounding", "presentation", "URL bindings", "execution recipes", "old tasks and references"],
               "browser_runtime_ready": False, "world_draws": 0, "provider_calls": 0,
               "elapsed_seconds": time.monotonic() - started}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({k: receipt[k] for k in ("status", "minimum_price_minor", "winner_count", "changed_price_leaves", "elapsed_seconds")}))


if __name__ == "__main__":
    main()
