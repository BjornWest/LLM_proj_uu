from copy import deepcopy

import pytest

from .generator import digest
from .stores import generate_store_world,validate_store_world


def world(probability):
    return generate_store_world(42,store_config={'footwear_size_surcharge_probability':probability,
        'variant_carry_probability':1},config={'variant_omission_probability':0})


def test_ordinary_sizes_colours_and_widths_share_retailer_model_price():
    value=world(0);p=value['public'];offers={(o['retailer_id'],o['product_id']):o for o in p['offers']}
    rows={(r['retailer_id'],r['model_id']):r for r in p['comparison_listings']}
    for assortment in p['assortments']:
        row=rows.get((assortment['retailer_id'],assortment['model_id']))
        if row:
            assert row['entry_product_id'] in assortment['product_ids']
            assert {offers[assortment['retailer_id'],sku]['price_minor'] for sku in assortment['product_ids']}=={row['advertised_price_minor']}
    assert rows


def test_surcharges_change_actual_quotes_without_changing_comparison_or_inventory():
    base,extra=world(0),world(1)
    for field in ('products','product_groups','retailers','assortments','comparison_listings','web_index'):
        assert base['public'][field]==extra['public'][field]
    products={p['product_id']:p for p in extra['public']['products']}
    changed=[]
    for a,b in zip(base['public']['offers'],extra['public']['offers']):
        assert {k:v for k,v in a.items() if k!='price_minor'}=={k:v for k,v in b.items() if k!='price_minor'}
        assert b['price_minor']>=a['price_minor']
        if b['price_minor']!=a['price_minor']:
            assert products[b['product_id']]['category']=='footwear'
            changed.append(b)
    assert changed


def test_comparison_validation_rejects_wrong_model_duplicate_and_unlisted_navigation():
    original=world(0)
    for kind in ('model','duplicate','sku','price','missing'):
        bad=deepcopy(original);rows=bad['public']['comparison_listings']
        if kind=='model':rows[0]['model_id']='missing'
        if kind=='duplicate':rows.append(deepcopy(rows[0]))
        if kind=='sku':rows[0]['entry_product_id']='missing'
        if kind=='price':rows[0]['advertised_price_minor']=0
        if kind=='missing':rows.pop()
        bad['world_sha256']=digest(bad['public'])
        with pytest.raises(ValueError,match='comparison|advertised'):validate_store_world(bad)


def test_legacy_world_without_comparison_projection_remains_valid():
    old=world(0);old['public'].pop('comparison_listings')
    old['world_sha256']=digest(old['public'])
    validate_store_world(old)
