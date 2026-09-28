"""Isolated W&B attempt. Not imported by a trainer or sampler."""
from pathlib import Path
import sys

from .publication import publication_run_id, publication_config
from .monitoring_files import atomic_json
from .monitoring_io import load_snapshot, load_wandb_snapshot, publish_snapshot, scalar_metrics
from .outcomes import require
from .snapshot_uploader import position, receipt


def upload(pending, run_path, directory):
    import wandb
    value = load_snapshot(pending)
    entity, project, run_id = run_path.split('/')
    require(publication_run_id(value) == run_id, 'Publication run mismatch')
    settings = wandb.Settings(base_url='https://api.wandb.ai', init_timeout=30, x_service_wait=30,
                              x_disable_stats=True, disable_git=True, disable_code=True,
                              console='off', silent=True)
    # Only this uploader owns the W&B run. Trainer report_to must be disabled.
    with wandb.init(entity=entity, project=project, id=run_id, resume='allow', mode='online',
                    dir=str(directory), save_code=False, settings=settings,
                    job_type='monitoring-uploader', group=value['run_id'],
                    tags=['synthetic', 'exclude-from-model-results'] if value['synthetic'] else ['training-monitoring'],
                    config=dict(synthetic=value['synthetic'], metric_schema=value['schema_version'],
                                **publication_config(value))) as run:
        require(run.config.get('synthetic') is value['synthetic'], 'Remote classification mismatch')
        require(all(run.config.get(k) == v for k, v in publication_config(value).items()),
                'Remote publication lineage mismatch')
        old_id = run.summary.get('monitoring/snapshot_id')
        if old_id:
            # Reading remote file may fail during an earlier partial upload. Summary
            # position still prevents an older retry overwriting a newer publication.
            old_position = (run.summary.get('monitoring/watermark'), run.summary.get('monitoring/snapshot_at'))
            require(None not in old_position and position(value) >= old_position, 'Remote snapshot is newer')
            require(position(value) != old_position or old_id == value['snapshot_id'], 'Conflicting remote position')
        already_confirmed = False
        if old_id == value['snapshot_id']:
            try:
                remote, remote_run = load_wandb_snapshot(run_path)
                already_confirmed = remote == value and matching_scalars(remote_run, value)
            except Exception:
                pass  # Repair an ambiguous partial upload of the SAME snapshot.
        if not already_confirmed:
            publish_snapshot(run, value, Path(directory) / 'staging')
    # SDK finish is insufficient: verify server persistence through the read path.
    remote, remote_run = load_wandb_snapshot(run_path)
    require(remote == value and matching_scalars(remote_run, value), 'Remote readback not yet complete')
    # Only our local staging copies are pruned. Durable ledger/checkpoints are untouched.
    for path in (Path(directory) / 'staging').glob('snapshot-*.json'):
        path.unlink()
    return receipt(remote)


def matching_scalars(run, value):
    for key, expected in scalar_metrics(value).items():
        actual = run.summary.get(key)
        if not isinstance(actual, (float, int)) or abs(actual - expected) > 1e-9 * max(1, abs(expected)):
            return False
    return True


if __name__ == '__main__':
    pending, run_path, directory, output = sys.argv[1:]
    atomic_json(output, upload(pending, run_path, directory))
