"""Synthetic callback controls; actual browser/recipe acceptance is separate."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from . import simulated_order_address_capture as address
from .simulated_order_capture import OrderCapture


def fixture_capture(tmp_path):
    # Synthetic only: do not label this as actual constructor/capture acceptance.
    trace = SimpleNamespace(directory=tmp_path, episode_id='synthetic-episode')
    binding = {'runtime_id': 'synthetic-runtime', 'episode_binding': {
        'episode_id': trace.episode_id}}
    records = [{'order_id': 'first', 'address': {'unit': '24'}},
               {'order_id': 'retry', 'address': {'unit': ''}}]
    capsule = {'episode_id': trace.episode_id, 'main_trace_sha256': 'a'*64,
        'before': {'order_snapshot': {'orders': [], 'events': []}},
        'after': {'order_snapshot': {'orders': records, 'events': [1, 2]}},
        'effect_journal': None}
    capture = object.__new__(address.AddressOrderCapture)
    capture.binding = binding
    capture.task = {'task_id': 'synthetic-task', 'retailer_id': 'synthetic-shop'}
    capture.trace = trace
    capture.artifacts = {'before': {}, 'after': {}}
    capture.storage_artifacts = {}
    private = tmp_path/'manual-review-private'
    private.mkdir()
    for phase in ('before', 'after'):
        row = {'phase': phase, 'binding': deepcopy(binding), 'episode_id': trace.episode_id,
            'storage_state': {'origins': []}}
        path = private/(phase+'.json')
        path.write_text(json.dumps(row))
        capture.storage_artifacts[phase] = {'path': str(path),
                                           'sha256': sha256(path.read_bytes()).hexdigest()}
    return capture, capsule


def test_seal_retains_all_submitted_addresses_and_unknown_effects(tmp_path, monkeypatch):
    capture, capsule = fixture_capture(tmp_path)
    original = deepcopy(capsule)
    monkeypatch.setattr(OrderCapture, 'seal', lambda *args: (deepcopy(capsule), True))
    evidence, completed = capture.seal(tmp_path, {})
    assert completed is True
    assert evidence['ledger'] == original
    assert [row['address']['unit'] for row in evidence['ledger']['after']['order_snapshot']['orders']] == ['24', '']
    assert evidence['complete_effect_envelope'] is None
    assert evidence['full_effects'] == 'unknown'
    assert evidence['order_outcome_scored'] is False
    assert 'grade' not in evidence
    assert capsule == original
    assert (tmp_path/'manual-review-private/order-address-evidence.private.json').is_file()


@pytest.mark.parametrize('mutation', ['missing', 'hash', 'outside', 'phase', 'binding', 'episode'])
def test_rejects_missing_or_unbound_address_artifacts(tmp_path, monkeypatch, mutation):
    capture, capsule = fixture_capture(tmp_path)
    calls = []
    monkeypatch.setattr(OrderCapture, 'seal', lambda *args: calls.append(args))
    artifact = capture.storage_artifacts['after']
    path = Path(artifact['path'])
    row = json.loads(path.read_bytes())
    if mutation == 'missing':
        del capture.storage_artifacts['after']
    elif mutation == 'hash':
        path.write_text('{}')
    elif mutation == 'outside':
        artifact['path'] = str(tmp_path.parent/'outside.json')
    else:
        field = 'episode_id' if mutation == 'episode' else mutation
        row[field] = {'runtime_id': 'other'} if mutation == 'binding' else 'other'
        path.write_text(json.dumps(row))
        artifact['sha256'] = sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        capture.seal(tmp_path, {})
    assert not calls


def test_duplicate_evidence_file_never_overwrites_previous(tmp_path, monkeypatch):
    capture, capsule = fixture_capture(tmp_path)
    path = tmp_path/'manual-review-private/order-address-evidence.private.json'
    path.write_text('retained original')
    monkeypatch.setattr(OrderCapture, 'seal', lambda *args: (capsule, True))
    with pytest.raises(FileExistsError):
        capture.seal(tmp_path, {})
    assert path.read_text() == 'retained original'
