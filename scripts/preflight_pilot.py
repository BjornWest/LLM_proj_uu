"""Audit curated task identity and missing capabilities without executing tasks."""

import argparse
from pathlib import Path

from intent_browser.pilot import load_pilot, preflight
from intent_browser.trace import write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("data/curation/pilot_manifest.json"))
    parser.add_argument("--inventory", type=Path, default=Path("data/curation/inventory.jsonl"))
    parser.add_argument("--output", type=Path, default=Path(".local/preflight/pilot-preflight.json"))
    args = parser.parse_args()
    tasks, fingerprint = load_pilot(args.manifest)
    report = preflight(tasks, fingerprint, args.inventory)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, report)
    print(f"Read {report['candidate_count']} candidates; {report['ready_count']} execution-ready.")
    print(f"First-four plan: {len(report['first_four_episode_plan'])} unexecuted paired episodes.")
    print(f"Privileged audit report: {args.output}")


if __name__ == "__main__":
    main()
