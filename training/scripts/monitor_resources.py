#!/usr/bin/env python3
"""Optional Linux resource sidecar; samples only, no model or GPU compute.

Write one atomic latest-sample mailbox per role. RuntimeMetrics imports it when
emitting its next snapshot. Not a profiler: samples between imports coalesce.
"""
import argparse
from pathlib import Path
import signal
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from browser_training.monitoring_files import atomic_json, exclusive_writer
from browser_training.monitoring_io import load_snapshot
from browser_training.publication import publication_run_id
from browser_training.resource_monitor import ResourceSampler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--monitoring-dir', required=True, type=Path)
    parser.add_argument('--role', choices=['browser', 'trainer', 'rollout'], required=True)
    parser.add_argument('--pid', type=int, help='Root process; descendants are included')
    parser.add_argument('--gpu', help='Explicit physical nvidia-smi index/UUID, not CUDA ordinal; no MIG')
    parser.add_argument('--interval-s', type=float, default=10)
    parser.add_argument('--samples', type=int, default=0, help='0: until SIGINT/SIGTERM')
    args = parser.parse_args()
    if args.interval_s <= 0 or args.samples < 0:
        parser.error('Positive interval and nonnegative samples required')
    value = load_snapshot(args.monitoring_dir / 'snapshot.json')
    sampler = ResourceSampler(role=args.role, root_pid=args.pid, device=args.gpu)
    stopped = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopped.set())
    path = args.monitoring_dir / 'resources' / f'{args.role}.json'
    with exclusive_writer(path.with_suffix('.lock')):
        count = 0
        while not stopped.is_set():
            event = sampler.sample()
            atomic_json(path, dict(run_id=value['run_id'], synthetic=value['synthetic'], event=event,
                                  publication_run_id=publication_run_id(value)))
            count += 1
            if args.samples and count >= args.samples:
                break
            stopped.wait(args.interval_s)


if __name__ == '__main__':
    main()
