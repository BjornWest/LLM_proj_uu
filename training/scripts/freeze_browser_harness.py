#!/usr/bin/env python3
"""Copy and qualify the complete P11/core-tools-v3 closure without model calls.

Run with training/.venv/bin/python; browser subprocesses use the root .venv.
Each scripted case owns its server/browser. No shared services are reset.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_project_browser_metrics import digest, freeze, save, verify_freeze


def worker(output, variant):
    sys.path[:0] = [str(ROOT), str(ROOT / "training")]
    from scripts.run_harness_suite import run_case
    manifest = json.loads((output / "frozen-sources.json").read_text())
    verify_freeze(ROOT, manifest["files"])
    settings = json.loads((output / "profile.json").read_text())
    # Inspect before BrowserGym starts its process-global Playwright sync loop.
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        executable = Path(playwright.chromium.executable_path)
    chromium = dict(path=str(executable), sha256=digest(executable.read_bytes()))
    row = run_case(output, settings, settings["cases"][0], "P11-clean-" + variant,
                   None, variant=variant)
    imported = {}
    for name, module in tuple(sys.modules.items()):
        if name.split(".")[0] in {"intent_browser", "browser_training", "scripts"} and getattr(module, "__file__", None):
            path = Path(module.__file__).resolve()
            if not path.is_relative_to(ROOT):
                raise RuntimeError(f"Import escaped snapshot: {name}")
            imported[name] = str(path.relative_to(ROOT))
    verify_freeze(ROOT, manifest["files"])
    row.update(imports=imported, packages={d.metadata["Name"]: d.version
        for d in importlib.metadata.distributions() if d.metadata["Name"]},
        chromium=chromium)
    save(output / f"{variant}.json", row)
    if not row["passed"]:
        raise RuntimeError(f"{variant} acceptance failed: {row['trace']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / ".local/tricky-full-v1")
    parser.add_argument("--output", type=Path, default=ROOT / "training/outputs/browser-harness")
    parser.add_argument("--browser-python", type=Path, default=ROOT / ".venv/bin/python")
    parser.add_argument("--worker", choices=("positive", "negative"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker(args.output.resolve(), args.worker)
        return
    output = args.output.resolve() / ("p11-" + uuid.uuid4().hex[:12])
    output.mkdir(parents=True, exist_ok=False)
    destination = output / "frozen"
    names = ["scripts/run_harness_suite.py", "scripts/harness_suite_tasks.py",
             "scripts/native_probe_budget.py", "scripts/inspect_chaos.mjs",
             "scripts/verify_chaos.py", "scripts/verify_tricky_full.py",
             "scripts/verify_tricky_privacy.py", "scripts/verify_tricky_membership.py",
             "scripts/verify_authorized_warranty.py", "config/chaos_verifier.json",
             "config/authorized_warranty_contract.json", "pyproject.toml",
             "training/scripts/freeze_browser_harness.py"]
    extras = {name: ROOT / name for name in names}
    extras.update({f"site/{name}": args.build.resolve() / name
                   for name in ("appointments.json", "membership-catalog.json")})
    identity = freeze(ROOT, args.build.resolve(), destination, extra_sources=extras)
    save(output / "profile.json", dict(cases=[dict(id="P11-clean", family="tricky", task="P11", condition="clean")],
        config=dict(tricky_build=str(destination / "site"), compact_feedback=True,
                    reasoning_replay="preserve", max_steps=8, observation_chars=48000),
        frozen_source_sha256=identity, harness_profile="core-tools-v3", training_eligible=False))
    save(output / "checkout.json", dict(commit=subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        note="Copied working sources include uncommitted edits; hashes identify runtime."))
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    # No remote model/W&B credentials are needed by scripted browser workers.
    for key in tuple(env):
        if key.endswith(("_API_KEY", "_API_SECRET", "_TOKEN")):
            env.pop(key)
    libs = [str(p) for p in (ROOT / ".local/system-libs/usr/lib/x86_64-linux-gnu",
            ROOT / "training/.cache/browser-libs/root/usr/lib/x86_64-linux-gnu") if p.is_dir()]
    env["LD_LIBRARY_PATH"] = ":".join(libs + ([env["LD_LIBRARY_PATH"]] if env.get("LD_LIBRARY_PATH") else []))
    print(f"Snapshot: {output}", flush=True)

    def run(variant):
        with (output / f"{variant}.log").open("w") as log:
            subprocess.run([str(args.browser_python.absolute()), "-I",
                str(destination / "training/scripts/freeze_browser_harness.py"),
                "--worker", variant, "--output", str(output)], cwd=destination,
                env=env, stdout=log, stderr=subprocess.STDOUT, timeout=180, check=True)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(run, ("positive", "negative")))
    rows = [json.loads((output / f"{v}.json").read_text()) for v in ("positive", "negative")]
    verify_freeze(destination, json.loads((output / "frozen-sources.json").read_text())["files"])
    report = dict(status="PASS", source_sha256=identity, harness="core-tools-v3",
                  task="P11-clean", model_calls=0, training_performed=False, training_eligible=False,
                  scope="Fresh scripted browser acceptance; not model-driven GRPO qualification",
                  cases=[{k: row[k] for k in ("variant", "trace", "passed", "evaluation", "steps")} for row in rows],
                  runtime_note="Python environment and cached Chromium reused, versions/hash recorded per case; not a copied runtime image.")
    save(output / "report.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
