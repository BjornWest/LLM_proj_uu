#!/usr/bin/env python3
"""CPU checkpoint-metadata and optional W&B continuation test. No model/optimizer.

The native rollout_state is a fixture; this validates publication history, not
restoration of model weights, optimizer state, or a real GRPO training run.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from browser_training.monitoring_files import atomic_json, exclusive_writer
from browser_training.monitoring_io import credentials_from_project_env, load_wandb_snapshot, scalar_metrics
from browser_training.publication import publication_run_id
from browser_training.runtime_metrics import RuntimeMetrics
from browser_training.snapshot_uploader import SnapshotUploader, subprocess_transport


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'outputs/publication-resume')
    parser.add_argument('--online', action='store_true')
    args = parser.parse_args()
    run_id = 'resume-check-' + uuid.uuid4().hex[:12]
    directory = args.output.resolve()/run_id
    parent = RuntimeMetrics(directory/'parent', run_id=run_id, synthetic=True, expected_producers=['trainer'])
    parent.log(dict(step=8, wall_time=time.time(), loss=0.2), policy_version=3)
    checkpoint = directory/'checkpoint-8'
    checkpoint.mkdir()
    atomic_json(checkpoint/'rollout_state.json', dict(prompt_index=2, model_version=3))
    state = parent.checkpoint(checkpoint)
    parent.log(dict(step=12, wall_time=time.time(), loss=0.8), policy_version=5)
    parent_value = parent.emit_snapshot()
    child = RuntimeMetrics(directory/'child', run_id=run_id, synthetic=True, expected_producers=['trainer'],
                           resume=checkpoint)
    inherited = child.emit_snapshot()
    assert inherited['watermark'] < parent_value['watermark']
    assert inherited['publication']['checkpoint_state_sha256'] == state['state_sha256']
    assert scalar_metrics(inherited)['telemetry_available/rl/loss'] == 0
    assert inherited['producer_last_seen']['trainer'] is None
    report = dict(status='LOCAL_PASS', run_id=run_id, publication_run_id=publication_run_id(inherited),
                  synthetic=True, model_loaded=False, training_performed=False, gpu_used=False,
                  checkpoint_kind='monitoring sidecar plus synthetic native rollout_state; no model checkpoint',
                  inherited_watermark=inherited['watermark'], parent_later_watermark=parent_value['watermark'],
                  lineage=inherited['publication'], inherited_health_masked=True,
                  remote_readback_verified=False, source_sha256={name: hashlib.sha256((ROOT/'browser_training'/name).read_bytes()).hexdigest()
                      for name in ('publication.py', 'runtime_metrics.py', 'outcomes.py', 'monitoring_io.py', 'snapshot_uploader.py', 'upload_worker.py')})
    atomic_json(directory/'report.json', report)
    if args.online:
        credentials_from_project_env(ROOT.parent)
        if not os.environ.get('WANDB_API_KEY') or not os.environ.get('WANDB_ENTITY'):
            parser.error('W&B credentials required; local checks passed')
        destination = f"{os.environ['WANDB_ENTITY']}/{os.environ.get('WANDB_PROJECT', 'browser-training')}"
        def publish(monitor, value, label):
            path = f'{destination}/{publication_run_id(value)}'
            state_dir = directory/f'upload-{label}'
            with exclusive_writer(state_dir/'uploader.lock'):
                uploader = SnapshotUploader(state_dir, run_path=path)
                # One bounded external process; no retry loop/new run creation.
                status = uploader.tick(monitor.directory/'snapshot.json', subprocess_transport)
                assert status == 'confirmed', f'{label} pending; inspect local status.json'
            remote, run = load_wandb_snapshot(path)
            assert remote == value
            for key, expected in scalar_metrics(value).items():
                assert abs(run.summary[key]-expected) <= 1e-9*max(1, abs(expected)), key
            assert run.group == run_id
            return run
        parent_remote = publish(parent, parent_value, 'parent')
        child_remote = publish(child, inherited, 'child')
        assert child_remote.config['publication_lineage']['parent_run_id'] == parent_remote.id
        child.log(dict(step=9, wall_time=time.time(), loss=0.15), policy_version=4)
        continued = child.emit_snapshot()
        assert scalar_metrics(continued)['telemetry_available/rl/loss'] == 1
        child_remote = publish(child, continued, 'child')
        still_parent, parent_remote = load_wandb_snapshot(f'{destination}/{run_id}')
        assert still_parent == parent_value, 'Parent evidence changed during child publication'
        parent_history = list(parent_remote.scan_history(keys=['monitoring/snapshot_id'], use_cache=False))
        child_history = list(child_remote.scan_history(keys=['monitoring/snapshot_id'], use_cache=False))
        assert [row['monitoring/snapshot_id'] for row in parent_history] == [parent_value['snapshot_id']]
        assert [row['monitoring/snapshot_id'] for row in child_history] == [inherited['snapshot_id'], continued['snapshot_id']]
        report.update(status='PASS', remote_readback_verified=True, parent_history_unchanged=True,
                      child_history_points=len(child_history), parent_url=parent_remote.url,
                      child_url=child_remote.url, child_scalar_count=len(scalar_metrics(continued)),
                      inherited_scalar_count=len(scalar_metrics(inherited)))
    atomic_json(directory/'report.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
