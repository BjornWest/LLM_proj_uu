"""Producer identities must survive both persisted world formats."""
from copy import deepcopy
import json

import pytest

from . import basket_quote, model, package_export, pin_v2
from environments.website_world import checkout_domain


@pytest.fixture
def make_world(monkeypatch, tmp_path):
    # Isolate the producer's finalization from expensive manufacture. The real
    # product factory still creates the axes, and the real producer hashes them.
    concept = 'tablets.everyday_media_tablets'
    ledger = tmp_path / 'ledger.json'
    ledger.write_text(json.dumps({concept: {}}))
    monkeypatch.setattr(package_export, 'LEDGER', ledger)
    monkeypatch.setattr(package_export, 'source_gate', lambda cid: {})
    monkeypatch.setattr(model, 'carrier_reviews', lambda *args: {})
    monkeypatch.setattr(model, 'pin_sources', lambda world: {
        'experiments/accepted_catalog_commerce/model.py':
            package_export.digest_file(model.__file__)})

    def make(values):
        def sample(seed, cid, brand, pid, **kwargs):
            return {'public': {'product_id': pid, 'concept_id': cid,
                    'brand_id': 'test-brand', 'name': 'Test tablet',
                    'family_id': 'tablets', 'facts': {},
                    'skus': [{'sku_id': f'{pid}/{i}', 'product_id': pid,
                              'storage_gb': value} for i, value in enumerate(values)]},
                    'private': {'profiles': {'positioning': 'mainstream'}}, 'reviews': [],
                    'variant_fields': {'storage_gb': {
                        'retail_presentation': {'allowed': ['selector']}}},
                    'commerce': {'shipping_class': 'regular',
                        'classification_basis': 'closed_ordinary_parcel_concept_slice_v1'}}

        def population(seed, *, product_factory, **kwargs):
            product_factory({'product_id': 'test-product', 'concept_id': concept}, {}, [])
            return {'controls': {}, 'retailers': [], 'diagnostics': {}}

        monkeypatch.setattr(package_export, 'sample', sample)
        monkeypatch.setattr(model.population, 'sample', population)
        return model.generate(1, concept_ids=[concept], tasks=[])

    return make


@pytest.mark.parametrize('values', [(256, 512, 1000), (1, 2, 10), (1, 2, 3), ('basic', 'plus')])
def test_identity_and_bindings_survive_json_roundtrip(make_world, values):
    world = make_world(values)
    saved = json.loads(json.dumps(world))
    assert world == saved
    assert model.native.digest(world) == model.native.digest(saved)
    body = {key: value for key, value in saved.items() if key != 'world_id'}
    assert saved['world_id'] == model.native.digest(body)
    roles = world['products'][0]['axes']['storage_gb']['roles']
    assert all(type(key) is str for key in roles)
    # Representation changes must not turn actual SKU values into strings.
    assert [sku['storage_gb'] for sku in world['products'][0]['public']['skus']] == list(values)
    plan = basket_quote.make_plan(world)
    basket_quote.validate_plan(saved, json.loads(json.dumps(plan)))
    domain = checkout_domain.make(world)
    checkout_domain.validate(saved, json.loads(json.dumps(domain)))
    # Preserve historical bindings when numeric/string key orders already agree.
    historical = deepcopy(body)
    historical['products'][0]['axes']['storage_gb']['roles'] = {
        value: 'base' if value == sorted(values)[0] else 'extension' for value in values}
    if values in ((1, 2, 3), ('basic', 'plus')):
        assert model.native.digest(historical) == saved['world_id']
    else:
        assert model.native.digest(historical) != saved['world_id']


@pytest.mark.parametrize('version', ['v1', 'v2'])
def test_freeze_load_retains_basket_and_checkout_bindings(make_world, tmp_path, version):
    world = make_world((256, 512, 1000))
    domain = checkout_domain.make(world)
    output = tmp_path / version
    if version == 'v1':
        model.freeze(world, output)
        loaded, manifest = model.load(output)
    else:
        store = tmp_path / 'sources'
        pin_v2.freeze(world, output, source_store=store)
        loaded, manifest = pin_v2.load(output, source_store=store)
    assert loaded == world
    assert manifest['world_id'] == world['world_id']
    plan = json.loads((output / 'basket-plan.private.json').read_text())
    basket_quote.validate_plan(loaded, plan)
    checkout_domain.validate(loaded, json.loads(json.dumps(domain)))


@pytest.mark.parametrize('mode', ['off', 'full'])
def test_real_manufacture_roundtrip_keeps_shipping_bindings(mode):
    from .execution import Execution
    world = Execution(validation=mode).generate(1,
        concept_ids=['footwear.walking_shoes', 'footwear.casual_trainers',
                     'tablets.everyday_media_tablets'],
        controls={'world_size': .4}, review_count=0)
    assert world['retailers'] and world['products']
    saved = json.loads(json.dumps(world))
    assert [p['axes'] for p in world['products']] == [p['axes'] for p in saved['products']]
    assert model.native.digest(world) == model.native.digest(saved)
    assert world['world_id'] == model.native.digest({
        key: value for key, value in saved.items() if key != 'world_id'})
    plan = basket_quote.make_plan(world)
    domain = checkout_domain.make(world)
    basket_quote.validate_plan(saved, json.loads(json.dumps(plan)))
    checkout_domain.validate(saved, json.loads(json.dumps(domain)))
