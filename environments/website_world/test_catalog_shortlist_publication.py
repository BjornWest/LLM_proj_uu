from copy import deepcopy
from hashlib import sha256
import json
import pytest
from environments.website_world import catalog_shortlist_publication as publication
from environments.website_world.test_catalog_shortlist_task import fixture


def request():
    return {'schema': 'website-world-generation-v2', 'seed': 80,
        'world': {'concept_ids': ['footwear.walking_shoes']},
        'task': {'kind': 'shortlist_matching_models', 'concept_id': 'footwear.walking_shoes',
            'limit': 2, 'predicates': [{'field': 'sku.size_eu', 'operator': 'eq', 'value': 42}]}}


@pytest.mark.parametrize('bad', ['limit', 'predicates', 'start_scope'])
def test_invalid_request_rejects_before_sampling(monkeypatch, bad):
    r = request()
    if bad == 'limit': r['task']['limit'] = True
    if bad == 'predicates': r['task']['predicates'] = []
    if bad == 'start_scope':
        r['task']['comparison_site_id'] = 'comparison-00'
        r['episode'] = {'start': {'kind': 'comparison_home', 'comparison_site_id': 'comparison-01'}}
    def forbidden(*a, **kw): raise AssertionError('No draw allowed')
    monkeypatch.setattr(publication.native.feature_generation, 'generate', forbidden)
    with pytest.raises(ValueError): publication.generate(r)


def test_comparison_home_is_predeclared_and_not_a_world_sampling_start():
    r = request(); r['task']['comparison_site_id'] = 'comparison-00'
    r['episode'] = {'start': {'kind': 'comparison_home', 'comparison_site_id': 'comparison-00'}}
    before = deepcopy(r); config = publication.compile_request(r)
    assert r == before
    assert config['requested_start'] == r['episode']['start']
    assert config['feature_request']['episode']['start'] == {'kind': 'directory'}
    assert config['selection']['comparison_site_id'] == 'comparison-00'


@pytest.mark.parametrize('empty', [False, True])
def test_full_population_cutoff_ties_and_natural_empty_retained(monkeypatch, empty):
    w, _, _, _, _ = fixture(); before = deepcopy(w); calls = []
    def supplied(proxy, *, world_factory):
        calls.append(proxy)
        return {'world': w, 'surrounding': None, 'episode': {}, 'resolved_configuration': {},
            'audit': {'request_sha256': 'feature'}}
    monkeypatch.setattr(publication.native.feature_generation, 'generate', supplied)
    r = request()
    if empty: r['task']['max_price_minor'] = 1
    result = publication.generate(r); ref = result['catalog_shortlist_reference']; task = result['catalog_shortlist_task']
    assert len(calls) == 1 and result['world'] == before
    assert result['shortlist_binding'] == {'status': 'bound', 'world_repaired': False}
    assert result['episode']['manual_task'] == {'user_message': task['user_message'], 'memories': []}
    assert result['shortlist_field_inventory']['concept_id'] == task['concept_id']
    if empty:
        assert ref['status'] == 'no_match' and ref['selected_models'] == []
    else:
        assert ref['population_count'] == 4 and len(ref['selected_models']) == 3
        assert task['limit'] == 2 and ref['cutoff_price_minor'] == 80000
        assert len(ref['selected_models'][0]['winners']) == 4


@pytest.mark.parametrize('status', ['match', 'no_match'])
def test_freeze_exact_reference_rows_and_inventory(tmp_path, monkeypatch, status):
    reference = {'status': status, 'selected_models': [] if status == 'no_match' else [
        {'product_id': 'p', 'price_minor': 10, 'winners': [{'offer_id': 'a/p'}]},
        {'product_id': 'q', 'price_minor': 10, 'winners': [{'offer_id': 'b/q'}]}]}
    result = {'catalog_shortlist_task': {'kind': publication.native.native.KIND},
        'catalog_shortlist_reference': reference, 'shortlist_field_inventory': {'source_hashes': {}},
        'shortlist_binding': {'status': 'bound', 'world_repaired': False}}
    monkeypatch.setattr(publication, 'generate', lambda *a, **kw: result)
    def freeze(request, output, **kw):
        result = generate(request); output.mkdir(); files = {}
        for name, key in [('feature-offer-task.private.json', 'feature_offer_task'),
                ('feature-offer-reference.private.json', 'feature_offer_reference'),
                ('feature-field-inventory.private.json', 'feature_field_inventory')]:
            (output/name).write_text(json.dumps(result[key])); files[name] = sha256((output/name).read_bytes()).hexdigest()
        return {'files': files}
    monkeypatch.setattr(publication.feature, 'prepare', freeze)
    output = tmp_path/'new'; manifest = publication.prepare(request(), output)
    assert json.loads((output/'catalog-shortlist-reference.private.json').read_text()) == reference
    assert json.loads((output/'shortlist-field-inventory.private.json').read_text()) == result['shortlist_field_inventory']
    assert manifest['shortlist_binding_status'] == 'bound'
    assert not list(output.glob('feature-*'))
    for name, h in manifest['files'].items(): assert sha256((output/name).read_bytes()).hexdigest() == h
