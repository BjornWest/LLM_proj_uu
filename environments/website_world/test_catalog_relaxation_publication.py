from copy import deepcopy
from hashlib import sha256
import json
import pytest
from environments.website_world import catalog_relaxation_publication as publication
from environments.website_world.test_catalog_relaxation_task import fixture


def request():
    return {'schema': 'website-world-generation-v2', 'seed': 81,
        'world': {'concept_ids': ['footwear.walking_shoes']},
        'task': {'kind': 'cheapest_matching_with_permitted_relaxations', 'concept_id': 'footwear.walking_shoes',
            'predicates': [{'field': 'sku.size_eu', 'operator': 'eq', 'value': 42},
                {'field':'product.facts.reference_mass_g','operator':'le','value':200,'unit':'g'}],
            'relaxations':[{'label':'Allow up to 350 g','replacements':[
                {'field':'product.facts.reference_mass_g','operator':'le','value':350,'unit':'g'}]}]}}


@pytest.mark.parametrize('bad', ['alternatives', 'predicates', 'start_scope'])
def test_invalid_request_rejects_before_sampling(monkeypatch, bad):
    r = request()
    if bad == 'alternatives': r['task']['relaxations'] = []
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
def test_full_population_ordered_criteria_and_natural_empty_retained(monkeypatch, empty):
    w, _, _, _, _ = fixture(); before = deepcopy(w); calls = []
    def supplied(proxy, *, world_factory):
        calls.append(proxy)
        return {'world': w, 'surrounding': None, 'episode': {}, 'resolved_configuration': {},
            'audit': {'request_sha256': 'feature'}}
    monkeypatch.setattr(publication.native.feature_generation, 'generate', supplied)
    r = request()
    if empty: r['task']['max_price_minor'] = 1
    result = publication.generate(r); ref = result['catalog_relaxation_reference']; task = result['catalog_relaxation_task']
    assert len(calls) == 1 and result['world'] == before
    assert result['relaxation_binding'] == {'status': 'bound', 'world_repaired': False}
    assert result['episode']['manual_task'] == {'user_message': task['user_message'], 'memories': []}
    assert result['relaxation_field_inventory']['concept_id'] == task['concept_id']
    if empty:
        assert ref['status'] == 'no_match' and ref['selected_index'] is None
    else:
        assert ref['selected_index'] == 1 and ref['selected_label'] == 'Allow up to 350 g'
        assert ref['minimum_price_minor'] == 74000
        assert len(ref['scenario_references'][1]['winners']) == 4


@pytest.mark.parametrize('status', ['match', 'no_match'])
def test_freeze_exact_criteria_references_and_inventory(tmp_path, monkeypatch, status):
    reference = {'status':status,'selected_label':None if status=='no_match' else 'Allow up to 350 g',
        'scenario_references':[{'status':'no_match'},{'status':status,'winners':[{'offer_id':'a/p'},{'offer_id':'b/p'}]}]}
    result = {'catalog_relaxation_task': {'kind': publication.native.native.KIND},
        'catalog_relaxation_reference': reference, 'relaxation_field_inventory': {'source_hashes': {}},
        'relaxation_binding': {'status': 'bound', 'world_repaired': False}}
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
    assert json.loads((output/'catalog-relaxation-reference.private.json').read_text()) == reference
    assert json.loads((output/'relaxation-field-inventory.private.json').read_text()) == result['relaxation_field_inventory']
    assert manifest['relaxation_binding_status'] == 'bound'
    assert not list(output.glob('feature-*'))
    for name, h in manifest['files'].items(): assert sha256((output/name).read_bytes()).hexdigest() == h
