from copy import deepcopy
from hashlib import sha256
import json
import pytest
from environments.website_world import catalog_review_publication as publication
from environments.website_world.test_catalog_review_generation import request
from environments.website_world.test_catalog_review_task import fixture


def test_invalid_topic_rejects_before_sampling(monkeypatch):
    r = request(); r['task']['topic']['aspect'] = 'not_declared'
    def forbidden(*a, **kw): raise AssertionError('No draw allowed')
    monkeypatch.setattr(publication.native.unified_generation, 'generate', forbidden)
    with pytest.raises(ValueError): publication.generate(r)


@pytest.mark.parametrize('missing', [None, 'subject', 'publication'])
def test_inventory_and_native_binding_preserve_the_world(missing, monkeypatch):
    world, _, _, _, sidecar, inventory = fixture(); before = deepcopy(world); calls = []
    r = request()
    if missing == 'subject': r['task']['product_index'] = 100
    if missing == 'publication': sidecar['sites'] = []
    def generated(proxy, *, world_factory):
        calls.append(proxy)
        return {'world': world, 'surrounding': sidecar, 'resolved_configuration': {},
                'audit': {'request_sha256': 'proxy'}, 'episode': {}}
    monkeypatch.setattr(publication.native.unified_generation, 'generate', generated)
    result = publication.generate(r)
    assert len(calls) == 1 and world == before
    assert result['review_task_binding']['world_repaired'] is False
    assert (result['review_task_binding']['status'] == 'bound') == (missing is None)
    export = result['review_topic_inventory']
    assert export['topics'] == inventory.topics
    assert export['field_inventory']['fields'] == inventory.fields.fields
    assert export['source_hashes'] == inventory.source_hashes
    if missing == 'subject': assert result['catalog_review_task'] is None
    else:
        task = result['catalog_review_task']
        assert result['episode']['manual_task'] == {'user_message': task['user_message'], 'memories': task['memories']}


@pytest.mark.parametrize('supported', [True, False])
def test_freeze_replaces_only_fresh_writer_placeholders(tmp_path, monkeypatch, supported):
    task = {'kind': publication.native.native.KIND} if supported else None
    reference = {'status': 'summary'} if supported else None
    binding = {'status': 'bound' if supported else 'unsupported_no_manufactured_subject', 'world_repaired': False}
    records = {'catalog_review_task': task, 'catalog_review_reference': reference,
        'review_task_binding': binding, 'review_topic_inventory': {'topics': []}}
    monkeypatch.setattr(publication, 'generate', lambda *a, **kw: records)
    def freeze(request, output, **kw):
        result = generate(request)  # privately supplied by _bind in prepare
        output.mkdir()
        files = {}
        for name, key in [('feature-offer-task.private.json', 'feature_offer_task'),
                          ('feature-offer-reference.private.json', 'feature_offer_reference'),
                          ('feature-field-inventory.private.json', 'feature_field_inventory')]:
            (output/name).write_text(json.dumps(result[key]))
            files[name] = sha256((output/name).read_bytes()).hexdigest()
        return {'files': files}
    monkeypatch.setattr(publication.feature, 'prepare', freeze)
    output = tmp_path/'fresh'
    manifest = publication.prepare(request(), output)
    assert json.loads((output/'catalog-review-task.private.json').read_text()) == task
    assert json.loads((output/'catalog-review-reference.private.json').read_text()) == reference
    assert manifest['automatic_grader_supported'] is supported
    for name, expected in manifest['files'].items():
        assert sha256((output/name).read_bytes()).hexdigest() == expected
    assert not list(output.glob('feature-*'))
