from copy import deepcopy
from hashlib import sha256
import json

import pytest

from environments.website_world import catalog_priority_publication as publication
from environments.website_world.test_catalog_priority_task import fixture


def request():
    return {'schema': 'website-world-generation-v2', 'seed': 83,
        'world': {'concept_ids': ['footwear.walking_shoes']},
        'task': {'kind': 'recommend_matching_by_priorities',
            'concept_id': 'footwear.walking_shoes',
            'predicates': [{'field': 'sku.size_eu', 'operator': 'eq', 'value': 42}],
            'priorities': [{'field': 'product.facts.reference_mass_g', 'direction': 'min', 'unit': 'g'}]}}


@pytest.mark.parametrize('bad', ['unit', 'direction', 'start_scope'])
def test_invalid_priority_or_scope_rejects_before_sampling(monkeypatch, bad):
    r = request()
    if bad == 'unit': r['task']['priorities'][0]['unit'] = 'kg'
    if bad == 'direction': r['task']['priorities'][0]['direction'] = 'average'
    if bad == 'start_scope':
        r['task']['comparison_site_id'] = 'comparison-00'
        r['episode'] = {'start': {'kind': 'comparison_home', 'comparison_site_id': 'comparison-01'}}
    def forbidden(*a, **kw): raise AssertionError('No draw allowed')
    monkeypatch.setattr(publication.native.feature_generation, 'generate', forbidden)
    with pytest.raises(ValueError): publication.generate(r)


def test_comparison_home_scope_and_request_immutability():
    r = request(); r['task']['comparison_site_id'] = 'comparison-00'
    r['episode'] = {'start': {'kind': 'comparison_home', 'comparison_site_id': 'comparison-00'}}
    original = deepcopy(r); config = publication.compile_request(r)
    assert r == original and config['requested_start'] == r['episode']['start']
    assert config['feature_request']['episode']['start'] == {'kind': 'directory'}
    assert config['selection']['comparison_site_id'] == 'comparison-00'


@pytest.mark.parametrize('empty', [False, True])
def test_native_priorities_price_ties_basis_and_empty_preserved(monkeypatch, empty):
    world, _, _, _, _ = fixture(); original = deepcopy(world); calls = []
    def supplied(proxy, *, world_factory):
        calls.append(proxy)
        return {'world': world, 'surrounding': None, 'episode': {},
            'resolved_configuration': {}, 'audit': {'request_sha256': 'proxy'}}
    monkeypatch.setattr(publication.native.feature_generation, 'generate', supplied)
    r = request()
    if empty: r['task']['max_price_minor'] = 1
    before = deepcopy(r); result = publication.generate(r)
    task, ref = result['catalog_priority_task'], result['catalog_priority_reference']
    assert len(calls) == 1 and world == original and r == before
    assert result['priority_binding'] == {'status': 'bound', 'world_repaired': False}
    assert result['episode']['manual_task'] == {'user_message': task['user_message'], 'memories': []}
    assert task['priority_measurement_scopes']['product.facts.reference_mass_g']['basis'] == 'one item, EU 40 reference configuration'
    assert task['predicates'][0]['value'] == 42
    assert result['priority_field_inventory']['concept_id'] == task['concept_id']
    if empty:
        assert ref['status'] == 'no_match' and ref['winners'] == []
    else:
        assert ref['best_priority_values'] == [250] and ref['tie_price_minor'] == 80000
        assert len(ref['winners']) == 12 and {v['product_id'] for v in ref['winners']} == {'q', 'r'}
        assert ref['feature_reference']['minimum_price_minor'] == 74000


@pytest.mark.parametrize('status', ['match', 'no_match'])
def test_freeze_keeps_exact_native_priorities_scopes_and_inventory(tmp_path, monkeypatch, status):
    task = {'kind': publication.native.native.KIND, 'priorities': [{'field': 'product.facts.reference_mass_g', 'direction': 'min', 'unit': 'g'}],
        'priority_measurement_scopes': {'product.facts.reference_mass_g': {'basis': 'declared reference configuration'}}}
    ref = {'status': status, 'winners': [] if status == 'no_match' else [{'offer_id': 'a'}, {'offer_id': 'b'}],
        'best_priority_values': None if status == 'no_match' else [250], 'tie_price_minor': None if status == 'no_match' else 80000}
    result = {'catalog_priority_task': task, 'catalog_priority_reference': ref,
        'priority_field_inventory': {'source_hashes': {}}, 'priority_binding': {'status': 'bound', 'world_repaired': False}}
    monkeypatch.setattr(publication, 'generate', lambda *a, **kw: result)
    def freeze(request, output, **kw):
        sampled = generate(request); output.mkdir(); files = {}
        for name, key in [('feature-offer-task.private.json', 'feature_offer_task'),
                ('feature-offer-reference.private.json', 'feature_offer_reference'),
                ('feature-field-inventory.private.json', 'feature_field_inventory')]:
            (output/name).write_text(json.dumps(sampled[key])); files[name] = sha256((output/name).read_bytes()).hexdigest()
        return {'files': files}
    monkeypatch.setattr(publication.feature, 'prepare', freeze)
    output = tmp_path/'new'; manifest = publication.prepare(request(), output)
    assert json.loads((output/'catalog-priority-task.private.json').read_text()) == task
    assert json.loads((output/'catalog-priority-reference.private.json').read_text()) == ref
    assert json.loads((output/'priority-field-inventory.private.json').read_text()) == result['priority_field_inventory']
    assert manifest['priority_binding_status'] == 'bound' and not list(output.glob('feature-*'))
    for name, h in manifest['files'].items(): assert sha256((output/name).read_bytes()).hexdigest() == h
