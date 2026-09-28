#!/usr/bin/env python3
"""Small CPU-only W&B logging check. Values are synthetic, not training evidence.

Offline by default. --online creates one run with four scalar records and one
four-row table, then reads the summary back. No models, traces or code uploaded.
"""
import argparse
import json
import os
from pathlib import Path
import uuid

ROOT = Path(__file__).resolve().parents[1]
HOST = "https://api.wandb.ai"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--online", action="store_true")
    parser.add_argument("--entity", help="Academic team slug, not its display name or URL")
    parser.add_argument("--project")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/wandb-check")
    args = parser.parse_args()
    if args.online:
        from dotenv import dotenv_values
        values = dotenv_values(ROOT.parent / ".env", interpolate=False)
        for key in ("WANDB_API_KEY", "WANDB_ENTITY", "WANDB_PROJECT"):
            if values.get(key):
                os.environ.setdefault(key, values[key])
        if not os.environ.get("WANDB_API_KEY"):
            parser.error("Set WANDB_API_KEY in the ignored project .env or environment; never put it in CLI arguments")
    entity = args.entity or os.environ.get("WANDB_ENTITY")
    project = args.project or os.environ.get("WANDB_PROJECT") or "browser-training"
    if args.online and not entity:
        parser.error("Set WANDB_ENTITY to your academic team's URL slug")
    for value in (entity, project):
        if value and ("/" in value or any(c.isspace() for c in value)):
            parser.error("Entity/project must be slugs, not URLs or display names")

    import wandb
    run_id = "connection-" + uuid.uuid4().hex[:12]
    output = args.output.resolve() / run_id
    output.mkdir(parents=True, exist_ok=False)
    settings = wandb.Settings(base_url=HOST, init_timeout=30, x_service_wait=30,
                              x_disable_stats=True, disable_git=True, disable_code=True,
                              console="off", silent=True)
    fixtures = [("mock-checkout", True), ("mock-checkout", False),
                ("mock-constraints", False), ("mock-constraints", True)]
    with wandb.init(entity=entity, project=project, id=run_id,
                    name="Connection check — SYNTHETIC DATA", job_type="connection-check",
                    tags=["smoke-test", "synthetic", "exclude-from-model-results"],
                    mode="online" if args.online else "offline", dir=str(output),
                    save_code=False, settings=settings,
                    config={"synthetic": True, "training_performed": False,
                            "purpose": "Authentication and scalar/table dashboard plumbing",
                            "schema_version": 1}) as run:
        rows = []
        successes = 0
        for step, (family, success) in enumerate(fixtures, 1):
            successes += int(success)
            rows.append([f"fixture-{step}", family, success, 1])
            run.log({"smoke/task/pass_rate": successes / step,
                     "smoke/train/loss": 1 / step,
                     "smoke/rollout/episodes": step,
                     "smoke/policy/version": 1}, step=step)
        run.log({"smoke/outcomes": wandb.Table(
            columns=["episode_id", "task_family", "verified_success", "policy_version"], data=rows)})
        run.summary["connection_check"] = "complete"
        run.summary["synthetic"] = True
        run.summary["fixture_episodes"] = len(rows)
        url = run.url if args.online else None
        run_path = f"{run.entity}/{run.project}/{run.id}"
    report = {"status": "OFFLINE_RECORDED", "scope": "Synthetic SDK logging; no Trainer or browser integration",
              "wandb_version": wandb.__version__, "run_id": run_id, "url": url,
              "fixture_episodes": len(fixtures), "training_performed": False,
              "remote_readback_verified": False}
    if args.online:
        # Finishing waits for upload; authenticate/read back independently of the logger.
        try:
            remote = wandb.Api(overrides={"base_url": HOST}, timeout=20).run(run_path)
            assert remote.config["synthetic"] is True
            assert remote.summary["connection_check"] == "complete"
            assert remote.summary["fixture_episodes"] == 4
            assert remote.summary["smoke/task/pass_rate"] == 0.5
            assert "smoke/outcomes" in remote.summary
            table_path = remote.summary["smoke/outcomes"]["path"]
            with remote.file(table_path).download(root=str(output / "readback")) as stream:
                assert json.load(stream)["data"] == rows
        except Exception:
            report["status"] = "UPLOADED_READBACK_FAILED"
            (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps(report, indent=2))
            raise SystemExit("Run finished but readback failed; inspect its URL before creating another test run")
        report.update(status="PASS", remote_readback_verified=True, remote_table_verified=True)
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
