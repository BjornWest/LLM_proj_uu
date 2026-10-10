"""Target choice must stay independent of retailer economics and site coverage."""
from copy import deepcopy
from hashlib import sha256
import json
import sys
from types import SimpleNamespace

import pytest

from environments.website_world import comparison_stock_generation as recipe
from environments.website_world.test_comparison_sku_task import fixture


def manufactured_world():
    world, sidecar = fixture()
    world['products'][0]['public']['concept_id'] = 'footwear.walking_shoes'
    sidecar['source_world_sha256'] = sha256(json.dumps(
        world, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return world, sidecar


def test_target_draw_ignores_prices_stock_order_and_reviews():
    world, _ = manufactured_world()
    target = {'concept_id': 'footwear.walking_shoes', 'selectors': {'size_eu': 42}}
    expected = recipe.bind_target(world, target, seed=71)
    other = deepcopy(world)
    other['retailers'] = []
    other['products'][0]['public']['skus'].reverse()
    other['products'][0]['reviews'] = [{'text': 'Unrelated review'}]
    assert recipe.bind_target(other, target, seed=71) == expected


def test_variant_subset_is_late_bound_to_one_manufactured_sku():
    world, _ = manufactured_world()
    result = recipe.bind_target(world, {'concept_id': 'footwear.walking_shoes',
                               'selectors': {'colour': 'blue'}}, seed=71)
    assert result['sku_id'] == 'p-blue-42'
    # Blue exists in manufacture even though no merchant has an offer for it.
    assert all(o['sku_id'] != result['sku_id'] for r in world['retailers'] for o in r['offers'])


def test_missing_target_is_explicit_without_stock_repair():
    world, _ = manufactured_world()
    result = recipe.bind_target(world, {'sku_id': 'missing'}, seed=71)
    assert result['status'] == 'empty'
    assert 'sku_id' not in result


def test_duplicate_manufactured_identity_is_ambiguous():
    world, _ = manufactured_world()
    world['products'][0]['public']['skus'].append(
        deepcopy(world['products'][0]['public']['skus'][0]))
    assert recipe.bind_target(world, {'sku_id': 'p-black-42'}, seed=71)['status'] == 'ambiguous'


@pytest.mark.parametrize('target', [{'sku_id': ''}, {'concept_id': 'x', 'price': 5},
    {'concept_id': 'x', 'selectors': {'x': float('nan')}}, {'concept_id': 'x', 'selectors': []}])
def test_invalid_target_notation_rejected(target):
    with pytest.raises(ValueError):
        recipe.target_options(target)


@pytest.mark.parametrize('published', [True, False])
def test_fresh_binding_preserves_unsold_target_and_does_not_redraw(monkeypatch, published):
    world, sidecar = manufactured_world()
    if not published:
        sidecar['sites'][0]['product_ids'] = []
    request = {'schema': recipe.REQUEST_SCHEMA, 'seed': 71,
               'task': {'kind': recipe.KIND, 'target': {'sku_id': 'p-blue-42'}}}
    config = {'proxy_request': {'schema': 'proxy'}, 'target': {'sku_id': 'p-blue-42'},
              'start': {'kind': 'comparison_home', 'comparison_site_id': 'comparison-00'}}
    calls = []
    def fake_generate(proxy, *, world_factory=None):
        calls.append(proxy)
        return {'world': world, 'surrounding': sidecar,
                'resolved_configuration': {'episode': {'start': {'kind': 'directory'}}},
                'audit': {'request_sha256': 'proxy'},
                'episode': {'start': {'kind': 'directory'},
                            'manual_task': {'user_message': 'proxy'}}}
    monkeypatch.setitem(sys.modules, 'environments.website_world.unified_generation',
                        SimpleNamespace(generate=fake_generate,
                                        shared=SimpleNamespace(digest=lambda r: 'request')))
    monkeypatch.setattr(recipe, 'compile_request', lambda r: config)
    result = recipe.generate(request)
    assert result['resolved_configuration']['task'] == request['task']
    assert result['resolved_configuration']['episode']['start']['kind'] == 'comparison_home'
    assert len(calls) == 1
    assert result['comparison_stock_binding']['sku_id'] == 'p-blue-42'
    if published:
        assert result['comparison_stock_task']['selectors'] == {'colour': 'blue', 'size_eu': 42}
        assert result['comparison_stock_reference']['winners'][0]['availability'] == 'variant_not_sold'
        assert result['episode']['start']['kind'] == 'comparison_home'
    else:
        assert result['comparison_stock_binding']['status'] == 'unpublished'
        assert 'manual_task' not in result['episode']
        assert 'comparison_stock_task' not in result
