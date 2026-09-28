#!/usr/bin/env python3
"""Separate, restartable W&B uploader. Never called from a trainer callback.

No browser/GPU/model access. One writer per monitoring run. The source snapshot
may advance during an outage; intermediate snapshots coalesce, raw ledger stays local.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from browser_training.publication import publication_run_id
from browser_training.monitoring_files import exclusive_writer
from browser_training.monitoring_io import credentials_from_project_env, load_snapshot
from browser_training.snapshot_uploader import SnapshotUploader, subprocess_transport


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', required=True, type=Path)
    parser.add_argument('--state-dir', required=True, type=Path)
    parser.add_argument('--entity')
    parser.add_argument('--project', default='browser-training')
    parser.add_argument('--interval-s', type=float, default=60)
    parser.add_argument('--attempt-timeout-s', type=float, default=120)
    parser.add_argument('--max-attempts', type=int, default=0, help='0: until stopped; failures retain pending state')
    args = parser.parse_args()
    if args.interval_s <= 0 or args.attempt_timeout_s <= 0 or args.max_attempts < 0:
        parser.error('Intervals/timeouts must be positive and attempts nonnegative')
    credentials_from_project_env(ROOT.parent)
    entity = args.entity or os.environ.get('WANDB_ENTITY')
    if not entity or not os.environ.get('WANDB_API_KEY'):
        parser.error('Set WANDB_ENTITY and WANDB_API_KEY in environment or ignored project .env')
    value = load_snapshot(args.snapshot)
    run_path = f"{entity}/{args.project}/{publication_run_id(value)}"
    stopped = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopped.set())
    with exclusive_writer(args.state_dir / 'uploader.lock'):
        uploader = SnapshotUploader(args.state_dir, run_path=run_path)
        attempts = 0
        while not stopped.is_set():
            def transport(*values):
                nonlocal attempts
                attempts += 1
                return subprocess_transport(*values, timeout_s=args.attempt_timeout_s)
            result = uploader.tick(args.snapshot, transport)
            print(json.dumps(dict(status=result, attempts=attempts, run_path=run_path)), flush=True)
            if args.max_attempts and (attempts >= args.max_attempts or result == 'caught_up'):
                break
            delay = max(args.interval_s, uploader.state['next_attempt_at'] - time.time())
            stopped.wait(delay)
    if uploader.state['status'] in {'retry_pending', 'sending'}:
        sys.exit(1)


if __name__ == '__main__':
    main()
