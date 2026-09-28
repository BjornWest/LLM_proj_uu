#!/usr/bin/env python3
"""Bounded CPU resource/sidecar qualification; optional tiny W&B readback.

No model, GPU compute, browser tasks or cloud allocation. All results synthetic;
CPU/PSS and optional device readings themselves come from the actual local machine.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from browser_training.monitoring_files import atomic_json, exclusive_writer
from browser_training.monitoring_io import credentials_from_project_env, load_wandb_snapshot, scalar_metrics
from browser_training.outcomes import write_snapshot
from browser_training.resource_monitor import ResourceSampler
from browser_training.runtime_metrics import RuntimeMetrics
from browser_training.snapshot_uploader import SnapshotUploader, subprocess_transport


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'outputs/resource-upload')
    parser.add_argument('--online', action='store_true')
    parser.add_argument('--gpu', help='Optional read-only physical nvidia-smi ID/UUID')
    args = parser.parse_args()
    run_id = 'resources-' + uuid.uuid4().hex[:12]
    directory = args.output.resolve() / run_id
    monitor = RuntimeMetrics(directory / 'monitor', run_id=run_id, synthetic=True,
                             expected_producers=['browser', 'trainer'] if args.gpu else ['browser'])
    # Small separate CPU workload, kept alive so PID scope is stable across samples.
    child = subprocess.Popen([sys.executable, '-c',
        'import time\nend=time.monotonic()+10\nx=0\nwhile time.monotonic()<end: x=(x+1)%100003'])
    try:
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/monitor_resources.py'),
                                 '--monitoring-dir', str(monitor.directory), '--role', 'browser',
                                 '--pid', str(child.pid), '--samples', '3', '--interval-s', '0.2'],
                                timeout=15, check=True, capture_output=True, text=True)
        if args.gpu:
            sampler = ResourceSampler(role='trainer', device=args.gpu)
            atomic_json(monitor.directory / 'resources/trainer.json',
                        dict(run_id=run_id, synthetic=True, event=sampler.sample()))
        value = monitor.emit_snapshot()
        assert value['telemetry']['browser/cpu_cores']['value'] > 0
        assert value['telemetry']['browser/ram_gib']['value'] > 0
        assert monitor.emit_snapshot()['watermark'] == value['watermark']
    finally:
        child.terminate()
        child.wait(timeout=5)
    # Resource mailboxes intentionally coalesce to latest; duplicate import is harmless.
    value = monitor.emit_snapshot()
    report = dict(status='LOCAL_PASS', synthetic=True, training_performed=False, gpu_compute_performed=False,
                  dashboard_created=False, run_id=run_id, snapshot_id=value['snapshot_id'],
                  watermark=value['watermark'], scalar_count=len(scalar_metrics(value)),
                  cpu_cores=value['telemetry']['browser/cpu_cores']['value'],
                  pss_gib=value['telemetry']['browser/ram_gib']['value'],
                  remote_readback_verified=False)
    if args.gpu:
        report['gpu'] = {k: v for k, v in value['telemetry'].items() if k in {'trainer/vram_gib', 'trainer/gpu_utilization_pct'}}
        report['unavailable'] = value.get('telemetry_unavailable', {})
    atomic_json(directory / 'report.json', report)
    if args.online:
        credentials_from_project_env(ROOT.parent)
        if not os.environ.get('WANDB_API_KEY') or not os.environ.get('WANDB_ENTITY'):
            parser.error('Missing W&B environment; local checks passed')
        run_path = f"{os.environ['WANDB_ENTITY']}/{os.environ.get('WANDB_PROJECT', 'browser-training')}/{run_id}"
        state_dir = directory / 'uploader'
        with exclusive_writer(state_dir / 'uploader.lock'):
            uploader = SnapshotUploader(state_dir, run_path=run_path)
            def offline(*args):
                raise ConnectionError('intentional transport fault, before any network call')
            assert uploader.tick(monitor.directory / 'snapshot.json', offline, now=0) == 'retry_pending'
            uploader = SnapshotUploader(state_dir, run_path=run_path)
            # At most TWO bounded attempts, including recovery if first remote read is delayed.
            for attempt in range(2):
                status = uploader.tick(monitor.directory / 'snapshot.json', subprocess_transport,
                                       now=max(time.time(), uploader.state['next_attempt_at']))
                if status == 'confirmed':
                    break
            assert status == 'confirmed', 'Upload pending; preserved status.json and snapshot for restart'
            remote, run = load_wandb_snapshot(run_path)
            assert remote == value
            for key, expected in scalar_metrics(value).items():
                assert abs(run.summary[key] - expected) <= 1e-9 * max(1, abs(expected)), key
            # Simulate loss of the local acknowledgement AFTER remote persistence.
            # A real resumed SDK attempt must discover it, without appending history again.
            before = list(run.scan_history(keys=['monitoring/snapshot_id'], use_cache=False))
            uploader.state.update(confirmed=None, status='sending')
            uploader.save()
            write_snapshot(value, uploader.pending_path)
            uploader = SnapshotUploader(state_dir, run_path=run_path)
            assert uploader.tick(monitor.directory / 'snapshot.json', subprocess_transport) == 'confirmed'
            _, reread = load_wandb_snapshot(run_path)
            after = list(reread.scan_history(keys=['monitoring/snapshot_id'], use_cache=False))
            assert before == after, 'Ambiguous retry duplicated W&B history'
            # Recovery/restart after confirmation performs no additional network operation.
            uploader = SnapshotUploader(state_dir, run_path=run_path)
            def should_not_upload(*args):
                raise AssertionError('confirmed snapshot resent')
            assert uploader.tick(monitor.directory / 'snapshot.json', should_not_upload) == 'caught_up'
        report.update(status='PASS', remote_readback_verified=True, url=run.url,
                      uploader_restart_verified=True, ambiguous_remote_retry_verified=True,
                      bounded_remote_attempts=attempt+2)
    atomic_json(directory / 'report.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
