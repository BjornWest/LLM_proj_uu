"""Native pin shapes must preserve the complete saved-publication closure."""
from hashlib import sha256
import json
from types import SimpleNamespace

import pytest

from . import saved_answer_publication as publication


@pytest.fixture
def saved_publication(tmp_path, monkeypatch):
    root, saved, output = (tmp_path/name for name in ('root', 'saved', 'output'))
    root.mkdir(); saved.mkdir()
    payloads = {'collector.py': b'# collector source', 'producer.py': b'# producer source',
                'fields.json': b'{"fields": []}', 'ordinary.py': b'# ordinary task source',
                'scripts/trace_grades.py': b'# reader'}
    for name, payload in payloads.items():
        target = root/name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(payload)
    hashes = {name: sha256(payload).hexdigest() for name, payload in payloads.items()}
    collector = {'collector.py': hashes['collector.py']}
    producer = {'producer.py': hashes['producer.py']}
    calls = []
    def freeze(world, destination):
        calls.append(world)
        destination.mkdir(parents=True)
        return {'files': {}, 'source_sha256': dict(producer)}
    monkeypatch.setattr(publication, 'ROOT', root)
    monkeypatch.setattr(publication, '_bind', lambda *args, **kwargs: lambda: dict(collector))
    monkeypatch.setattr(publication, 'Execution', lambda **kwargs: SimpleNamespace(freeze=freeze))
    def prepare(pins):
        task = {'task_id': 'offer-1', 'kind': 'fixture', 'memories': [], **pins}
        records = {'task.json': json.dumps(task).encode(), 'execution.private.json': b'{}',
                   'pin/world.private.json': b'{"world_id":"saved-world"}',
                   'episode.json': b'{"original":true}'}
        for name, data in records.items():
            target = saved/name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
        raw = json.dumps({'files': {name: sha256(data).hexdigest() for name,data in records.items()}}).encode()
        (saved/'manifest.json').write_bytes(raw)
        expected = sha256(raw).hexdigest()
        snapshot = publication.read_recipe(saved, expected_manifest_sha256=expected)
        setup = {'schema': publication.VERSION, 'task_id': 'offer-1', 'memories': [], 'user_message': 'Find it.'}
        manifest = publication.prepare_saved(snapshot, output, expected_manifest_sha256=expected,
                                             setup=setup, task_filename='task.json', adapter_file=__file__)
        return manifest, records
    return SimpleNamespace(root=root, saved=saved, output=output, hashes=hashes,
                           collector=collector, producer=producer, calls=calls, prepare=prepare)


@pytest.mark.parametrize('shape', ['stock', 'ordinary', 'features', 'both'])
def test_native_pin_shapes_keep_complete_source_archive(saved_publication, shape):
    f = saved_publication
    pins = {}
    if shape in ('ordinary', 'both'):
        pins['source_sha256'] = {'ordinary.py': f.hashes['ordinary.py']}
    if shape in ('features', 'both'):
        pins['field_source_sha256'] = {'fields.json': f.hashes['fields.json']}
    manifest, records = f.prepare(pins)
    expected = {**f.collector, **f.producer, 'scripts/trace_grades.py': f.hashes['scripts/trace_grades.py']}
    for mapping in pins.values():
        expected.update(mapping)
    assert manifest['source_sha256'] == expected
    for name, h in expected.items():
        assert sha256((f.output/'pin/source-snapshot'/name).read_bytes()).hexdigest() == h
    for name,data in records.items():
        if name != 'execution.private.json':
            assert (f.output/name).read_bytes() == data
        assert (f.saved/name).read_bytes() == data
    assert json.loads((f.output/'execution.private.json').read_bytes()) == {
        'source_sha256': expected, 'answer_grading': {'mode': 'external_required', 'native_kind': 'fixture'},
        'runtime_options': {'lazy_publication': True}}
    assert len(f.calls) == 1 and manifest['world_draws'] == manifest['model_runs'] == 0
    if shape == 'stock':
        assert 'source_sha256' not in json.loads(records['task.json'])
        assert 'field_source_sha256' not in json.loads(records['task.json'])


@pytest.mark.parametrize('field', ['source_sha256', 'field_source_sha256'])
def test_present_wrong_native_pin_rejects_before_freeze(saved_publication, field):
    f = saved_publication
    with pytest.raises(ValueError, match='Saved native input dependency changed'):
        f.prepare({field: {'fields.json': '0'*64}})
    assert not f.output.exists() and not f.calls


@pytest.mark.parametrize('field', ['source_sha256', 'field_source_sha256'])
@pytest.mark.parametrize('value', [None, [], 'missing', 0])
def test_present_malformed_pin_map_is_not_absence(saved_publication, field, value):
    f = saved_publication
    with pytest.raises(ValueError, match='Saved native input dependency map changed'):
        f.prepare({field: value})
    assert not f.output.exists() and not f.calls


@pytest.mark.parametrize('bad_field', ['source_sha256', 'field_source_sha256'])
def test_one_valid_map_does_not_hide_an_invalid_second_map(saved_publication, bad_field):
    f = saved_publication
    pins = {'source_sha256': {'ordinary.py': f.hashes['ordinary.py']},
            'field_source_sha256': {'fields.json': f.hashes['fields.json']}}
    pins[bad_field]['fields.json'] = '0'*64
    with pytest.raises(ValueError, match='Saved native input dependency changed'):
        f.prepare(pins)
    assert not f.output.exists() and not f.calls


def test_task_pin_collector_conflict_still_rejects(saved_publication):
    f = saved_publication
    f.collector['fields.json'] = '0'*64
    with pytest.raises(ValueError, match='Saved native input dependency changed'):
        f.prepare({'field_source_sha256': {'fields.json': f.hashes['fields.json']}})
    assert not f.output.exists() and not f.calls


def test_stock_still_checks_collected_source_bytes(saved_publication):
    f = saved_publication
    f.collector['collector.py'] = '0'*64
    with pytest.raises(ValueError, match='Saved-answer source changed'):
        f.prepare({})
    assert len(f.calls) == 1


def test_stock_still_checks_producer_collector_conflict(saved_publication):
    f = saved_publication
    f.producer['collector.py'] = '0'*64
    with pytest.raises(ValueError, match='Producer/saved-answer source conflict'):
        f.prepare({})
    assert len(f.calls) == 1

@pytest.mark.parametrize('shape', ['feature_task', 'declarations', 'requirements', 'scenarios'])
def test_nested_native_dependencies_remain_in_frozen_union(saved_publication, shape):
    f = saved_publication
    row = {'field_source_sha256': {'fields.json': f.hashes['fields.json']}}
    if shape == 'feature_task': pins = {shape: row}
    elif shape == 'declarations': pins = {shape: {'requirement-1': row}}
    else: pins = {shape: [row]}
    manifest, _ = f.prepare(pins)
    assert manifest['source_sha256']['fields.json'] == f.hashes['fields.json']
    assert (f.output/'pin/source-snapshot/fields.json').read_bytes() == (f.root/'fields.json').read_bytes()


def test_wrong_nested_policy_rejects_before_freeze(saved_publication):
    f = saved_publication
    with pytest.raises(ValueError, match='dependency changed'):
        f.prepare({'feature_task': {'field_source_sha256': {'fields.json':'0'*64}}})
    assert not f.output.exists() and not f.calls


def test_nested_reference_maps_preserve_conflict_checks(saved_publication):
    f = saved_publication
    assert publication.declared_sources({'requirements': [{'source_sha256': {'fields.json':f.hashes['fields.json']}}]}) == {'fields.json':f.hashes['fields.json']}
    with pytest.raises(ValueError, match='Conflicting'):
        publication.declared_sources({'field_source_sha256':{'fields.json':f.hashes['fields.json']}},
                                    {'sources': [{'source_sha256':{'fields.json':'0'*64}}]})
    with pytest.raises(ValueError, match='escaped'):
        publication.declared_sources({'nested': {'source_sha256':{'../outside.json':'0'*64}}})
