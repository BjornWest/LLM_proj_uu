#!/usr/bin/env python3
"""Import existing AuditCallback metrics into a local ledger; no W&B upload."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from browser_training.metric_catalog import TELEMETRY
from browser_training.outcomes import Ledger, snapshot, write_snapshot
from browser_training.trainer_metrics import trainer_event


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--kind", choices=["sft", "rl"], required=True)
    p.add_argument("--metrics-jsonl", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--context", required=True, help="Model/tokenizer and source measurement scope")
    p.add_argument("--synthetic", action="store_true")
    args = p.parse_args()
    raw = args.metrics_jsonl.read_bytes()
    source_id = hashlib.sha256(raw).hexdigest()
    ledger = Ledger(args.output / "events.sqlite", run_id=args.run_id, synthetic=args.synthetic,
                    expected_producers=["trainer"])
    keys = set()
    source_rows = raw.decode().splitlines()
    for number, line in enumerate(source_rows):
        event = trainer_event(json.loads(line), kind=args.kind, source_id=source_id, row_number=number,
                              context=args.context)
        if event is not None:
            ledger.append(event)
            keys.update(event["payload"]["values"])
    value = snapshot(ledger)
    write_snapshot(value, args.output / "snapshot.json")
    report = dict(source_sha256=source_id, source_rows=len(source_rows), normalized_records=len(ledger.records()),
                  measured_keys=sorted(keys), unmeasured_telemetry=sorted(set(TELEMETRY)-keys),
                  policy_version_known=False, checkpoint_identity_known=False, online_upload=False,
                  snapshot=str(args.output / "snapshot.json"))
    (args.output / "import-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
