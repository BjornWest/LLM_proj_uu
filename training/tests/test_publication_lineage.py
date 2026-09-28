import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import time

import pytest

from browser_training.monitoring_io import (agent_summary, load_wandb_snapshot, publish_snapshot, scalar_metrics)
from browser_training.outcomes import snapshot
from browser_training.publication import publication_run_id, publication_config, validate_publication
from browser_training.resource_monitor import ResourceSampler, ingest_sample
from browser_training.runtime_metrics import RuntimeMetrics
from browser_training.snapshot_uploader import SnapshotUploader, receipt
from test_monitoring_io import FakeRun
from test_runtime_metrics import make, begin, checkpoint, GOOD


def branch(tmp_path):
    parent = make(tmp_path)
    begin(parent, 'a')
    parent.finish('a', GOOD)
    parent.log(dict(step=2, wall_time=100, loss=0.2), policy_version=3)
    folder = checkpoint(tmp_path, parent)
    at_checkpoint = snapshot(parent.ledger, now=json.loads((folder/'monitoring/state.json').read_text())['snapshot_at'])
    # A newer parent result must survive even though the child restores earlier.
    begin(parent, 'b')
    parent.finish('b', GOOD)
    before = parent.emit_snapshot()
    child = make(tmp_path, 'resumed', resume=folder)
    return parent, child, folder, at_checkpoint, before


def test_restore_gets_linked_publication_without_changing_parent_or_sampler_run(tmp_path):
    parent, child, folder, saved, before = branch(tmp_path)
    result = child.emit_snapshot()
    lineage = result['publication']
    assert result['run_id'] == before['run_id'] == 'stable'
    assert publication_run_id(result) != publication_run_id(before)
    assert lineage['parent_run_id'] == 'stable'
    assert lineage['checkpoint_snapshot_id'] == saved['snapshot_id']
    assert lineage['inherited_watermark'] == saved['watermark'] < before['watermark']
    assert lineage['checkpoint_policy_version'] == 3
    assert not child.ledger.event('finish-b')
    assert snapshot(parent.ledger, now=before['snapshot_at']) == before
    assert json.loads((folder / 'monitoring/state.json').read_text())['snapshot_id'] == saved['snapshot_id']
    assert child.ledger.metadata['run_id'] == parent.ledger.metadata['run_id']
    assert agent_summary(result)['publication_run_id'] == lineage['run_id']


def test_inherited_diagnostics_do_not_claim_live_trainer_or_gpu_health(tmp_path):
    _, child, _, _, _ = branch(tmp_path)
    result = child.emit_snapshot()
    assert result['telemetry']['rl/loss']['inherited'] is True
    assert result['producer_last_seen']['trainer'] is None
    assert scalar_metrics(result)['telemetry_available/rl/loss'] == 0
    assert 'telemetry/rl/loss' not in scalar_metrics(result)
    child.log(dict(step=3, loss=0.1, wall_time=time.time()), policy_version=4)
    result = child.emit_snapshot()
    assert result['telemetry']['rl/loss']['inherited'] is False
    assert result['producer_last_seen']['trainer'] is not None
    assert scalar_metrics(result)['telemetry/rl/loss'] == 0.1


def test_second_restore_links_to_immediate_parent_and_siblings_are_distinct(tmp_path):
    _, child, folder, _, _ = branch(tmp_path)
    sibling = make(tmp_path, 'sibling', resume=folder)
    assert publication_run_id(sibling.ledger.metadata) != publication_run_id(child.ledger.metadata)
    next_folder = tmp_path / 'checkpoint-3'
    next_folder.mkdir()
    (next_folder/'rollout_state.json').write_text(json.dumps(dict(prompt_index=1, model_version=4)))
    child.checkpoint(next_folder)
    grandchild = make(tmp_path, 'grandchild', resume=next_folder)
    value = grandchild.emit_snapshot()
    assert value['publication']['parent_run_id'] == publication_run_id(child.ledger.metadata)
    assert value['run_id'] == 'stable'


def test_uploader_rejects_repointing_old_pending_queue_at_new_execution(tmp_path):
    parent, child, _, _, _ = branch(tmp_path)
    upload = SnapshotUploader(tmp_path / 'upload', run_path='team/project/stable')
    def offline(*args):
        raise TimeoutError('offline')
    assert upload.tick(parent.directory/'snapshot.json', offline, now=1) == 'retry_pending'
    pending = upload.pending_path.read_bytes()
    with pytest.raises(ValueError, match='publication run'):
        upload.tick(child.directory/'snapshot.json', lambda *args: pytest.fail('must not send'), now=20)
    assert upload.pending_path.read_bytes() == pending
    child_upload = SnapshotUploader(tmp_path/'child-upload',
                                    run_path=f'team/project/{publication_run_id(child.ledger.metadata)}')
    assert child_upload.tick(child.directory/'snapshot.json',
        lambda path, *_: receipt(json.loads(path.read_text()))) == 'confirmed'


def test_branch_publication_readback_checks_lineage(tmp_path, monkeypatch):
    _, child, _, _, _ = branch(tmp_path)
    value = child.emit_snapshot()
    run = FakeRun(value)
    run.id = publication_run_id(value)
    run.config.update(publication_config(value))
    monkeypatch.setitem(sys.modules, 'wandb', SimpleNamespace(Table=lambda **kwargs: kwargs))
    publish_snapshot(run, value, tmp_path/'upload')
    api = SimpleNamespace(flush=lambda: None, run=lambda _: run)
    remote, _ = load_wandb_snapshot(f'team/project/{run.id}', api=api)
    assert remote == value
    run.config['publication_lineage'] = None
    with pytest.raises(ValueError, match='lineage'):
        load_wandb_snapshot(f'team/project/{run.id}', api=api)


def test_old_resource_producer_cannot_appear_in_resumed_execution(tmp_path):
    _, child, _, _, _ = branch(tmp_path)
    event = ResourceSampler(role='trainer', root_pid=os.getpid()).sample()
    envelope = dict(run_id='stable', synthetic=True, event=event)
    with pytest.raises(ValueError, match='publication run'):
        ingest_sample(child.ledger, envelope, role='trainer')
    envelope['publication_run_id'] = publication_run_id(child.ledger.metadata)
    ingest_sample(child.ledger, envelope, role='trainer')
    value = child.emit_snapshot()
    assert value['telemetry']['trainer/ram_gib']['inherited'] is False


def test_lineage_metadata_corruption_is_rejected(tmp_path):
    _, child, _, _, _ = branch(tmp_path)
    lineage = child.ledger.metadata['publication']
    with pytest.raises(ValueError, match='new publication'):
        validate_publication({**lineage, 'run_id': lineage['parent_run_id']}, 'stable')
    with pytest.raises(ValueError, match='checksum'):
        validate_publication({**lineage, 'checkpoint_snapshot_id': 'invalid'}, 'stable')
