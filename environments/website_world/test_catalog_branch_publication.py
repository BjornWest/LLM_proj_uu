from copy import deepcopy
from hashlib import sha256
import json

import pytest
from . import catalog_branch_publication as publication
from .test_catalog_branch_task import fixture


def request():
    return {'schema': 'website-world-generation-v2', 'seed': 91,
        'world': {'concept_ids': ['footwear.walking_shoes']},
        'task': {'kind': 'cheapest_matching_local_branch_stock',
            'concept_id': 'footwear.walking_shoes',
            'predicates': [{'field': 'sku.size_eu', 'operator': 'eq', 'value': 42}],
            'city': 'Uppsala', 'country': 'SE'}}


@pytest.mark.parametrize('bad', ['city', 'country', 'start_scope'])
def test_invalid_locality_or_scope_rejects_before_sampling(monkeypatch, bad):
    r = request()
    if bad == 'city': r['task']['city'] = ''
    if bad == 'country': r['task']['country'] = 'se'
    if bad == 'start_scope':
        r['task']['comparison_site_id'] = 'comparison-00'
        r['episode'] = {'start': {'kind': 'comparison_home', 'comparison_site_id': 'comparison-01'}}
    def forbidden(*a, **kw): raise AssertionError('No draw allowed')
    monkeypatch.setattr(publication.native.feature_generation, 'generate', forbidden)
    with pytest.raises(ValueError): publication.generate(r)


def test_comparison_home_scope_preserves_original_request():
    r = request(); r['task']['comparison_site_id'] = 'comparison-00'
    r['episode'] = {'start': {'kind': 'comparison_home', 'comparison_site_id': 'comparison-00'}}
    before = deepcopy(r); config = publication.compile_request(r)
    assert r == before and config['requested_start'] == r['episode']['start']
    assert config['feature_request']['episode']['start'] == {'kind': 'directory'}


@pytest.mark.parametrize('empty', [False, True])
def test_native_physical_stock_all_ties_and_no_match_survive(monkeypatch, empty):
    world, _, _, _, _ = fixture(); original = deepcopy(world); calls = []
    def supplied(proxy, *, world_factory):
        calls.append(proxy)
        return {'world': world, 'surrounding': None, 'episode': {},
            'resolved_configuration': {}, 'audit': {'request_sha256': 'proxy'}}
    monkeypatch.setattr(publication.native.feature_generation, 'generate', supplied)
    r = request()
    if empty: r['task']['city'] = 'Nowhere'
    before = deepcopy(r); result = publication.generate(r)
    task, ref = result['catalog_branch_task'], result['catalog_branch_reference']
    assert len(calls) == 1 and world == original and r == before
    assert result['branch_binding'] == {'status': 'bound', 'world_repaired': False}
    assert result['episode']['manual_task'] == {'user_message': task['user_message'], 'memories': []}
    assert len(ref['branch_inventory']['a']) == 3
    if empty:
        assert ref['status'] == 'no_match' and ref['branch_winners'] == []
    else:
        assert ref['minimum_price_minor'] == 74000 and len(ref['branch_winners']) == 2
        assert {r['branch_id'] for r in ref['branch_winners']} == {'d/central'}
        assert ref['feature_reference']['minimum_price_minor'] == 63000


@pytest.mark.parametrize('status', ['match', 'no_match'])
def test_freeze_retains_native_branch_inventory_and_reference(tmp_path, monkeypatch, status):
    task = {'kind': publication.native.native.KIND, 'city': 'Uppsala', 'country': 'SE'}
    ref = {'status': status, 'branch_inventory': {'a': [{'branch_id': 'a/disabled', 'pickup_enabled': False}]},
        'branch_winners': [] if status == 'no_match' else [{'offer_id': 'a', 'branch_id': 'a/central'}]}
    result = {'catalog_branch_task': task, 'catalog_branch_reference': ref,
        'branch_field_inventory': {'source_hashes': {}}, 'branch_binding': {'status': 'bound', 'world_repaired': False}}
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
    assert json.loads((output/'catalog-branch-task.private.json').read_text()) == task
    assert json.loads((output/'catalog-branch-reference.private.json').read_text()) == ref
    assert json.loads((output/'branch-field-inventory.private.json').read_text()) == result['branch_field_inventory']
    assert not list(output.glob('feature-*'))
    for name, h in manifest['files'].items(): assert sha256((output/name).read_bytes()).hexdigest() == h
