from copy import deepcopy
import pytest
from .catalog_branch_runtime import enrich_catalog, branch_shop_source
from .test_catalog_branch_task import fixture


def public_fixture():
    world, _, _, _, _ = fixture()
    retailer = world['retailers'][0]
    retailer['source_locations'][0]['location'] = {'city': 'Uppsala', 'country': 'SE'}
    sources = {s['source_id']: s for s in retailer['source_locations']}
    catalog = {'branches': {b['branch_id']: {'name': b['name'],
        'address': b['location']['city']+', '+b['location']['country'],
        'hours': 'Opening hours are not published'} for b in retailer['geography']['branches']},
        'products': [{'variants': [{'offerId': o['offer_id'], 'skuId': o['sku_id'],
            'sourceStock': [{'sourceId': sid, 'quantity': q, 'kind': sources[sid]['kind'],
                'shippingEnabled': sources[sid]['shipping_enabled'], 'name': sources[sid]['location']['city']}
                for sid, q in o['stock_by_source'].items()]} for o in retailer['offers']]}]}
    return catalog, retailer


def test_additive_full_inventory_and_stock_inverse():
    public, retailer = public_fixture(); before = deepcopy(public); native = deepcopy(retailer)
    rendered = enrich_catalog(public, retailer)
    assert public == before and retailer == native
    assert rendered['branches'][retailer['retailer_id']+'/disabled']['pickupEnabled'] is False
    for variant in rendered['products'][0]['variants']:
        for row in variant['sourceStock']:
            if row['kind'] != 'branch': continue
            assert row['branchName'] in ('Central', 'Remote', 'Disabled')
            for key in ('branchName', 'city', 'country', 'pickupEnabled'): row.pop(key)
    for b in rendered['branches'].values():
        for key in ('city', 'country', 'pickupEnabled'): b.pop(key)
    assert rendered == before


@pytest.mark.parametrize('bad', ['inventory', 'stock', 'source_kind', 'duplicate_offer', 'sku'])
def test_projection_cannot_repair_invalid_public_bindings(bad):
    public, retailer = public_fixture()
    row = public['products'][0]['variants'][0]
    if bad == 'inventory': public['branches'].pop(next(iter(public['branches'])))
    if bad == 'stock': row['sourceStock'][0]['quantity'] += 1
    if bad == 'source_kind': row['sourceStock'][0]['kind'] = 'branch'
    if bad == 'duplicate_offer': public['products'][0]['variants'].append(deepcopy(row))
    if bad == 'sku': row['skuId'] = 'foreign'
    with pytest.raises(ValueError): enrich_catalog(public, retailer)


def test_renderer_hook_missing_rejects(monkeypatch):
    from . import catalog_branch_runtime as runtime
    monkeypatch.setattr(runtime, 'basket_shop_source', lambda s, **kw: s)
    with pytest.raises(ValueError, match='hook changed'): branch_shop_source('foreign renderer')
