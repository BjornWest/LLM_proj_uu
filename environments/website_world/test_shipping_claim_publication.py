from copy import deepcopy
from hashlib import sha256
import json

import pytest
from environments.website_world import shipping_claim_publication as publication
from environments.website_world.test_catalog_shipping_claim_task import fixture, world


def request():
    return {'schema': 'website-world-generation-v2', 'seed': 87,
        'world': {'concept_ids': ['footwear.walking_shoes']},
        'task': {'kind': 'audit_free_shipping_claim', 'quantity': 2}}


@pytest.mark.parametrize('fault', ['quantity', 'type', 'selector', 'comparison_start'])
def test_invalid_declarations_reject_before_any_draw(monkeypatch, fault):
    r = request()
    if fault == 'quantity': r['task']['quantity'] = True
    if fault == 'type': r['task']['delivery_types'] = ['shop_collection']
    if fault == 'selector': r['task']['offer_index'] = -1
    if fault == 'comparison_start': r['episode'] = {'start': {'kind': 'comparison_home'}}
    def forbidden(*a, **kw): raise AssertionError('World draw forbidden')
    monkeypatch.setattr(publication.native.unified_generation, 'generate', forbidden)
    with pytest.raises(ValueError): publication.generate(r)


@pytest.mark.parametrize('missing', [False, True])
def test_population_and_full_native_menu_are_preserved(monkeypatch, world, missing):
    w, _, _, q, domain, _ = fixture(world)
    original = deepcopy(w); calls = []; factory = object()
    def supplied(proxy, *, world_factory):
        assert world_factory is factory
        calls.append(deepcopy(proxy))
        return {'world': w, 'episode': {}, 'resolved_configuration': {},
            'basket_plan': {}, 'checkout_domain': domain, 'audit': {'request_sha256': 'proxy'}}
    monkeypatch.setattr(publication.native.unified_generation, 'generate', supplied)
    monkeypatch.setattr(publication.native, 'prepare', lambda *a, **kw: q)
    r = request()
    if missing: r['task']['retailer_index'] = 10000
    before = deepcopy(r); result = publication.generate(r, world_factory=factory)
    assert w == original and r == before and len(calls) == 1
    assert result['shipping_claim_inventory']['quantity_basis'] == 'retail_sale_units'
    assert result['resolved_configuration']['shipping_claim_selection']['quantity'] == 2
    if missing:
        assert result['shipping_claim_task'] is None and result['shipping_claim_reference'] is None
        assert result['shipping_claim_binding']['status'] == 'unsupported_no_selected_offer'
    else:
        ref = result['shipping_claim_reference']
        assert ref['option_count'] == len(ref['scoped_options'])
        assert len(ref['all_quote_options']) >= ref['option_count']
        assert result['episode']['manual_task']['user_message'] == result['shipping_claim_task']['user_message']
    assert result['shipping_claim_binding']['world_repaired'] is False


@pytest.mark.parametrize('missing', [False, True])
def test_freeze_retains_authoritative_nulls_and_native_values(tmp_path, monkeypatch, missing):
    result = {'shipping_claim_task': None if missing else {'kind': publication.native.native.KIND},
        'shipping_claim_reference': None if missing else {'assessment': 'none_free', 'all_quote_options': [1, 2]},
        'shipping_claim_inventory': {'source_hashes': {}},
        'shipping_claim_binding': {'status': 'unsupported_no_selected_offer' if missing else
            'requires_public_quote_and_policy_adoption', 'world_repaired': False}}
    monkeypatch.setattr(publication, 'generate', lambda *a, **kw: result)
    def freeze(request, output, **kw):
        sampled = generate(request); output.mkdir(); files = {}
        for name, key in [('feature-offer-task.private.json', 'feature_offer_task'),
                ('feature-offer-reference.private.json', 'feature_offer_reference'),
                ('feature-field-inventory.private.json', 'feature_field_inventory')]:
            (output/name).write_text(json.dumps(sampled[key])); files[name] = sha256((output/name).read_bytes()).hexdigest()
        return {'files': files}
    monkeypatch.setattr(publication.feature, 'prepare', freeze)
    output = tmp_path/'new';manifest = publication.prepare(request(), output)
    assert json.loads((output/'shipping-claim-task.private.json').read_text()) == result['shipping_claim_task']
    assert json.loads((output/'shipping-claim-reference.private.json').read_text()) == result['shipping_claim_reference']
    assert manifest['automatic_grader_supported'] is (not missing)
    assert not list(output.glob('feature-*'))
    for name, h in manifest['files'].items(): assert sha256((output/name).read_bytes()).hexdigest() == h
