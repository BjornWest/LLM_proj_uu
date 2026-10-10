from copy import deepcopy
from hashlib import sha256
import json

import pytest

from environments.website_world import catalog_comparison_publication as publication
from environments.website_world.test_catalog_comparison_task import fixture


def request():
    return {'schema': 'website-world-generation-v2', 'seed': 84,
        'world': {'concept_ids': ['footwear.walking_shoes']},
        'task': {'kind': 'compare_product_facts', 'concept_id': 'footwear.walking_shoes',
            'fields': ['product.facts.cushioning', 'product.facts.reference_mass_g'], 'model_limit': 2}}


@pytest.mark.parametrize('bad', ['sku', 'duplicate', 'model_limit', 'price'])
def test_invalid_model_fact_selection_rejects_before_sampling(monkeypatch, bad):
    r = request()
    if bad == 'sku': r['task']['fields'] = ['sku.size_eu']
    if bad == 'duplicate': r['task']['fields'] *= 2
    if bad == 'model_limit': r['task']['model_limit'] = 1
    if bad == 'price': r['task']['fields'] = ['product.reference_price_sek']
    def forbidden(*a, **kw): raise AssertionError('No draw allowed')
    monkeypatch.setattr(publication.native.unified_generation, 'generate', forbidden)
    with pytest.raises(ValueError): publication.generate(r)


def test_request_and_public_field_order_are_immutable():
    r = request(); original = deepcopy(r); config = publication.compile_request(r)
    assert r == original and config['selection']['fields'] == r['task']['fields']
    assert config['proxy_request']['task'] == {'user_message': 'Browse generated retailers. Do not place an order.', 'memories': []}


@pytest.mark.parametrize('count', [0, 1, 4])
def test_named_model_population_basis_and_no_models_preserved(monkeypatch, count):
    world, _, _, _, _ = fixture()
    keep = {p['public']['product_id'] for p in world['products'][:count]}
    for retailer in world['retailers']:
        retailer['offers'] = [o for o in retailer['offers'] if o['product_id'] in keep]
    original = deepcopy(world); calls = []
    def supplied(proxy, *, world_factory):
        calls.append(proxy)
        return {'world': world, 'surrounding': None, 'episode': {},
            'resolved_configuration': {}, 'audit': {'request_sha256': 'proxy'}}
    monkeypatch.setattr(publication.native.unified_generation, 'generate', supplied)
    r = request(); r['task']['model_limit'] = 4; before = deepcopy(r)
    result = publication.generate(r); task, ref = result['catalog_comparison_task'], result['catalog_comparison_reference']
    assert len(calls) == 1 and world == original and r == before
    assert len(task['models']) == count and len(ref['models']) == count
    assert ref['status'] == ('comparison' if count else 'no_models')
    assert ref['evidence_coverage'] == 'not_inferred_from_native_truth'
    assert result['comparison_binding'] == {'status': 'bound', 'world_repaired': False}
    assert result['episode']['manual_task'] == {'user_message': task['user_message'], 'memories': []}
    assert task['measurement_scopes']['product.facts.reference_mass_g']['basis'] == 'one item, EU 40 reference configuration'
    assert result['comparison_field_inventory']['concept_id'] == task['concept_id']
    assert 'Models do not have to be in stock' in task['user_message']


def test_unknown_na_values_not_repaired_or_conflated(monkeypatch):
    world, _, _, _, _ = fixture(model_limit=4)
    world['products'][0]['catalog_status']['product.facts.cushioning'] = 'unknown'
    world['products'][1]['catalog_status']['product.facts.cushioning'] = 'not_applicable'
    original = deepcopy(world)
    def supplied(*a, **kw):
        return {'world': world, 'surrounding': None, 'episode': {},
            'resolved_configuration': {}, 'audit': {'request_sha256': 'proxy'}}
    monkeypatch.setattr(publication.native.unified_generation, 'generate', supplied)
    r = request(); r['task']['model_limit'] = 4; result = publication.generate(r)
    facts = {m['product_id']: m['facts']['product.facts.cushioning'] for m in result['catalog_comparison_reference']['models']}
    assert world == original and facts['p']['status'] == 'unknown' and facts['q']['status'] == 'not_applicable'
    assert facts['p']['value'] is None and facts['q']['value'] is None


@pytest.mark.parametrize('status', ['comparison', 'no_models'])
def test_freeze_exact_native_model_fact_cells_and_inventory(tmp_path, monkeypatch, status):
    task = {'kind': publication.native.native.KIND, 'fields': ['product.facts.reference_mass_g'],
        'measurement_scopes': {'product.facts.reference_mass_g': {'basis': 'declared reference configuration'}}}
    ref = {'status': status, 'models': [] if status == 'no_models' else [{'product_id': 'p', 'facts': {
        'product.facts.reference_mass_g': {'status': 'known', 'value': 250, 'unit': 'g', 'basis': 'declared reference configuration'}}}]}
    result = {'catalog_comparison_task': task, 'catalog_comparison_reference': ref,
        'comparison_field_inventory': {'source_hashes': {}}, 'comparison_binding': {'status': 'bound', 'world_repaired': False}}
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
    assert json.loads((output/'catalog-comparison-task.private.json').read_text()) == task
    assert json.loads((output/'catalog-comparison-reference.private.json').read_text()) == ref
    assert json.loads((output/'comparison-field-inventory.private.json').read_text()) == result['comparison_field_inventory']
    assert manifest['comparison_binding_status'] == 'bound' and not list(output.glob('feature-*'))
    for name, h in manifest['files'].items(): assert sha256((output/name).read_bytes()).hexdigest() == h
