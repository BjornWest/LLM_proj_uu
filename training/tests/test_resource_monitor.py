import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from browser_training.monitoring_files import atomic_json, exclusive_writer
from browser_training.monitoring_io import agent_summary
from browser_training.outcomes import snapshot, validate
from browser_training.resource_monitor import ResourceSampler, gpu_sample, ingest_sample
from browser_training.runtime_metrics import RuntimeMetrics


def stat(root, pid, ppid, ticks, start, pss=1024):
    directory = root / str(pid)
    directory.mkdir(exist_ok=True)
    fields = ['0'] * 22
    fields[0], fields[1], fields[11], fields[12], fields[19] = 'S', str(ppid), str(ticks), '0', str(start)
    (directory / 'stat').write_text(f'{pid} (odd ) process name) ' + ' '.join(fields))
    if pss is not None:
        (directory / 'smaps_rollup').write_text(f'Pss: {pss} kB\n')


def test_process_tree_cpu_identity_and_pss(tmp_path):
    stat(tmp_path, 10, 1, 100, 5)
    stat(tmp_path, 20, 10, 30, 6, pss=2048)
    sampler = ResourceSampler(role='browser', root_pid=10, proc=tmp_path)
    first = sampler.sample(now=100, monotonic=1)['payload']
    assert first['unavailable']['browser/cpu_cores'] == 'needs_two_samples'
    assert first['values']['browser/ram_gib'] == 3 / 1024
    stat(tmp_path, 10, 1, 150, 5)
    stat(tmp_path, 20, 10, 999999, 7)  # Same PID now a different process: never subtract counters.
    second = sampler.sample(now=101, monotonic=2)['payload']
    assert second['values']['browser/cpu_cores'] == 50 / os.sysconf('SC_CLK_TCK')
    stat(tmp_path, 10, 1, 999999, 8)
    missing = sampler.sample(now=102, monotonic=3)['payload']
    assert not missing['values']
    assert set(missing['unavailable'].values()) == {'root_exited_or_reused'}


def test_partial_pss_is_not_a_false_low_memory_reading(tmp_path):
    stat(tmp_path, 10, 1, 100, 5)
    stat(tmp_path, 20, 10, 30, 6, pss=None)
    p = ResourceSampler(role='browser', root_pid=10, proc=tmp_path).sample()['payload']
    assert 'browser/ram_gib' not in p['values']
    assert p['unavailable']['browser/ram_gib'] == 'partial_or_denied_pss'


def test_gpu_query_explicit_scope_and_unsupported_readings():
    def query(args, **kwargs):
        assert args[2] == 'GPU-abcd' and kwargs['timeout'] == 5
        return SimpleNamespace(stdout='GPU-abcd, [N/A], 2048\n')
    values, unavailable, identity = gpu_sample('GPU-abcd', query)
    assert values == {'vram_gib': 2}
    assert unavailable == {'gpu_utilization_pct': 'unsupported_or_invalid_reading'}
    assert identity == 'GPU-abcd'
    def absent(*a, **kw):
        raise FileNotFoundError('SECRET-should-never-be-recorded')
    assert gpu_sample('0', absent)[0] == {}
    assert set(gpu_sample('0', absent)[1].values()) == {'device_query_failed'}
    with pytest.raises(ValueError, match='MIG'):
        ResourceSampler(role='trainer', device='MIG-test')


def test_missing_sample_clears_old_reading_and_delayed_delivery_cannot_resurrect(tmp_path, monkeypatch):
    from browser_training import resource_monitor
    monitor = RuntimeMetrics(tmp_path / 'monitor', run_id='sample', synthetic=True)
    sampler = ResourceSampler(role='trainer', device='0')
    monkeypatch.setattr(resource_monitor, 'gpu_sample', lambda _: ({'vram_gib': 10}, {}, 'GPU-test'))
    first = sampler.sample(now=100)
    monkeypatch.setattr(resource_monitor, 'gpu_sample', lambda _: ({}, {'vram_gib': 'device_query_failed'}, None))
    second = sampler.sample(now=101)
    def envelope(event):
        return dict(run_id='sample', synthetic=True, event=event)
    ingest_sample(monitor.ledger, envelope(second), role='trainer')
    ingest_sample(monitor.ledger, envelope(first), role='trainer')
    ingest_sample(monitor.ledger, envelope(second), role='trainer')
    value = snapshot(monitor.ledger, now=102)
    assert value['watermark'] == 2
    assert value['telemetry']['trainer/vram_gib'] is None
    assert agent_summary(value, now=102)['telemetry_unavailable']['trainer/vram_gib']['reason'] == 'device_query_failed'
    first['payload']['unavailable'] = {'trainer/vram_gib': 'overlap'}
    with pytest.raises(ValueError, match='overlap'):
        validate(first)


def test_runtime_import_is_idempotent_and_rejects_wrong_run_without_stopping(tmp_path):
    monitor = RuntimeMetrics(tmp_path / 'monitor', run_id='sample', synthetic=True)
    event = ResourceSampler(role='browser', root_pid=os.getpid()).sample()
    envelope = dict(run_id='wrong', synthetic=True, event=event)
    path = monitor.directory / 'resources/browser.json'
    atomic_json(path, envelope)
    assert monitor.emit_snapshot()['watermark'] == 0
    envelope['run_id'] = 'sample'
    atomic_json(path, envelope)
    assert monitor.emit_snapshot()['watermark'] == 1
    assert monitor.emit_snapshot()['watermark'] == 1
    with exclusive_writer(tmp_path / 'lock'):
        with pytest.raises(RuntimeError, match='writer'):
            with exclusive_writer(tmp_path / 'lock'):
                pass
    with exclusive_writer(tmp_path / 'lock'):
        pass
