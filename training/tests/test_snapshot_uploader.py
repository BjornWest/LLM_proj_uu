import json

import pytest

from browser_training.monitoring_files import atomic_json
from browser_training.outcomes import snapshot, write_snapshot
from browser_training.snapshot_uploader import SnapshotUploader, receipt, subprocess_transport
from test_outcome_metrics import episode, ledger


def setup(ledger, tmp_path):
    ledger.append(episode())
    value = snapshot(ledger, now=200)
    source = tmp_path / 'snapshot.json'
    write_snapshot(value, source)
    uploader = SnapshotUploader(tmp_path / 'upload', run_path='team/project/test')
    return value, source, uploader


def test_retry_restart_coalesces_and_does_not_ack_before_exact_receipt(ledger, tmp_path):
    value, source, uploader = setup(ledger, tmp_path)
    def fail(*args):
        raise ConnectionError('secret-token-in-message')
    assert uploader.tick(source, fail, now=1) == 'retry_pending'
    assert 'secret' not in uploader.state_path.read_text()
    restarted = SnapshotUploader(uploader.directory, run_path=uploader.run_path)
    assert restarted.tick(source, fail, now=2) == 'backoff'
    ledger.append(episode(1))
    newer = snapshot(ledger, now=201)
    write_snapshot(newer, source)
    pending_ids = []
    def remote(path, *_):
        pending = json.loads(path.read_text())
        pending_ids.append(pending['snapshot_id'])
        return receipt(pending)
    assert restarted.tick(source, remote, now=7) == 'confirmed'
    assert pending_ids == [value['snapshot_id']]
    assert restarted.tick(source, remote, now=8) == 'confirmed'
    assert pending_ids[-1] == newer['snapshot_id']
    assert restarted.tick(source, remote, now=9) == 'caught_up'
    assert not restarted.pending_path.exists()


def test_ambiguous_success_and_crash_after_confirmation_are_recoverable(ledger, tmp_path):
    value, source, uploader = setup(ledger, tmp_path)
    remote = {}
    def ambiguous(path, *_):
        remote.update(receipt(json.loads(path.read_text())))
        raise TimeoutError('server persisted but response lost')
    assert uploader.tick(source, ambiguous, now=1) == 'retry_pending'
    assert uploader.tick(source, lambda *args: remote, now=6) == 'confirmed'
    # Simulate process crash after status commit, before pending unlink.
    write_snapshot(value, uploader.pending_path)
    restarted = SnapshotUploader(uploader.directory, run_path=uploader.run_path)
    assert restarted.tick(source, lambda *args: pytest.fail('should not resend'), now=10) == 'confirmed'
    assert not restarted.pending_path.exists()


def test_wrong_receipt_rollback_and_destination_are_rejected(ledger, tmp_path):
    value, source, uploader = setup(ledger, tmp_path)
    assert uploader.tick(source, lambda *args: {}, now=1) == 'retry_pending'
    assert uploader.state['confirmed'] is None
    assert uploader.tick(source, lambda *args: receipt(value), now=6) == 'confirmed'
    write_snapshot(snapshot(ledger, now=199), source)
    with pytest.raises(ValueError, match='rolled back'):
        uploader.tick(source, lambda *a: None, now=7)
    with pytest.raises(ValueError, match='destination'):
        SnapshotUploader(uploader.directory, run_path='other/project/test')


def test_timeout_terminates_worker_process_group(tmp_path, monkeypatch):
    import subprocess
    from browser_training import snapshot_uploader
    class Hung:
        pid = 123456
        calls = 0
        def wait(self, timeout=None):
            self.calls += 1
            if timeout is not None:
                raise subprocess.TimeoutExpired('fixture', timeout)
            return -9
    child = Hung()
    killed = []
    monkeypatch.setattr(snapshot_uploader.subprocess, 'Popen', lambda *a, **kw: child)
    monkeypatch.setattr(snapshot_uploader.os, 'killpg', lambda *args: killed.append(args))
    with pytest.raises(TimeoutError):
        subprocess_transport(tmp_path / 'pending', 'team/project/test', tmp_path, timeout_s=0.01)
    assert killed == [(child.pid, 9)] and child.calls == 2
