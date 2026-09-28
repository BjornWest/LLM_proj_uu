#!/usr/bin/env python3
"""Execute an explicitly supplied evaluation worker, or compare saved reports.

This command can invoke model-serving workers; budget/authorize those separately.
The mock worker used in CPU tests performs no inference and downloads nothing.
"""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from browser_training.evaluation_runner import run
from browser_training.monitoring_files import atomic_json

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--request', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--monitoring-dir', type=Path, help='Atomically deliver to the running service inbox')
    p.add_argument('--concurrency', type=int, default=2)
    p.add_argument('--timeout-s', type=float, default=120)
    p.add_argument('--worker', nargs=argparse.REMAINDER, required=True, help='Command argv; specify last')
    a=p.parse_args()
    job=json.loads(a.request.read_text())
    delivery=run(job, a.output, a.worker, concurrency=a.concurrency, timeout_s=a.timeout_s)
    if a.monitoring_dir:
        from browser_training.monitoring_io import load_snapshot
        from browser_training.publication import publication_run_id
        from browser_training.outcomes import require
        current=load_snapshot(a.monitoring_dir/'snapshot.json')
        require(publication_run_id(current) == job['publication_run_id'], 'Wrong target monitoring execution')
        atomic_json(a.monitoring_dir/'evaluation-inbox'/f"{job['evaluation_id']}.json", delivery)
    print(json.dumps({'evaluation_id':job['evaluation_id'], 'cases':len(delivery['episodes']),
                      'delivery':str(a.output/'delivery.json')}))
