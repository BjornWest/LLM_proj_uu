#!/usr/bin/env python3
"""Read metrics as JSON, without a GPU, browser or dashboard dependency."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from browser_training.monitoring_io import (agent_summary, catalog, credentials_from_project_env,
                                          load_snapshot, load_wandb_snapshot)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--snapshot", type=Path)
    source.add_argument("--wandb", metavar="ENTITY/PROJECT/RUN_ID")
    source.add_argument("--catalog", action="store_true")
    parser.add_argument("--full", action="store_true", help="Include full per-template snapshot")
    parser.add_argument("--history-key", help="One exact W&B metric key; return unsampled history")
    parser.add_argument("--min-step", type=int, default=0, help="Inclusive W&B log step, not optimizer step")
    parser.add_argument("--max-step", type=int, help="Exclusive W&B log step")
    parser.add_argument("--stale-after-s", type=float, default=120)
    parser.add_argument("--split", help="Only this recorded data split")
    parser.add_argument("--window", choices=["all", "recent"], default="recent")
    parser.add_argument("--compare-evaluations", nargs=2, metavar=("LEFT_ID", "RIGHT_ID"),
                        help="Paired comparison of two complete reports from the identical fixed suite")
    parser.add_argument("--families", action="store_true", help="Include family breakdowns")
    args = parser.parse_args()
    if args.history_key and not args.wandb:
        parser.error("--history-key requires --wandb")
    if args.catalog:
        result = catalog()
    else:
        if args.wandb:
            credentials_from_project_env(ROOT.parent)
            value, run = load_wandb_snapshot(args.wandb)
        else:
            value = load_snapshot(args.snapshot)
        result = value if args.full else agent_summary(value, stale_after_s=args.stale_after_s,
                                                       split=args.split, window=args.window, families=args.families)
        if args.wandb:
            result = {**result, "wandb_url": run.url, "wandb_state": run.state}
        if args.compare_evaluations:
            from browser_training.evaluation import compare
            reports = {r["evaluation_id"]: r for r in value.get("evaluations", [])}
            if not all(identity in reports for identity in args.compare_evaluations):
                parser.error("Evaluation ID not present in this snapshot")
            result["evaluation_comparison"] = compare(*(reports[identity] for identity in args.compare_evaluations))
        if args.history_key:
            result["history"] = list(run.scan_history(keys=[args.history_key], min_step=args.min_step,
                                                     max_step=args.max_step, use_cache=False))
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
