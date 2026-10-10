"""Consumer binds exact SKU statements and never revives omitted optional data."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from environments.product_world import tablet_publication
from environments.website_world.catalog_adapter import PublicAdapter, fact_rows, public_products
from environments.website_world.surrounding_pages import products_with_optional_facts


@pytest.fixture(scope='module')
def world():
    return json.loads(Path('.local/website-delivery-options-20261006-v1/world-7-final/pin/world.private.json').read_text())


def tablet_variants(catalog):
    return [(p, v) for p in catalog['products'] if p['familyId']=='tablets' for v in p['variants']]


def test_exact_selected_sku_packets_replace_raw_rows_and_keep_commerce(world):
    adapter=PublicAdapter(world,selected_content=True)
    original=PublicAdapter(world)
    count=0
    for retailer in world['retailers']:
        rid=retailer['retailer_id'];catalog=adapter.catalog(rid,{})
        baseline={v['key']:v for p,v in tablet_variants(original.catalog(rid,{}))}
        for product,variant in tablet_variants(catalog):
            count+=1
            packet=adapter.selected_packets[(rid,product['canonicalProductId'],variant['skuId'])]
            expected=[s for g in packet['display_groups'] for s in g['slots']]
            actual=[f for g in variant['details'] if g['role']=='descriptive' for f in g['facts']]
            assert [(s['id'],s['text'],s['assertions']) for s in expected]==[(f['slotId'],f['value'],f['assertions']) for f in actual]
            assert packet['sku_id']==variant['skuId']
            assert product['introduction']=='' and product['descriptions']==[]
            assert all(a['status']=='known' for f in actual for a in f['assertions'])
            assert all(h['slotId'] in {s['id'] for s in expected} for h in variant['highlights'])
            for key in ('selection','priceMinor','price','currency','sourceStock','state','supplierOrder','pickup','offerId'):
                assert variant[key]==baseline[variant['key']][key],key
    tablet_ids={p['public']['product_id'] for p in world['products'] if p['public']['concept_id']=='tablets.everyday_media_tablets'}
    assert count==sum(o['product_id'] in tablet_ids for r in world['retailers'] for o in r['offers'])>0


def test_packets_cached_once_per_retailer_product_sku(world,monkeypatch):
    original=tablet_publication.export_tablet_content;calls=[]
    def export(item,**kwargs):
        calls.append((kwargs['retailer_id'],item['public']['product_id'],kwargs['sku_id']))
        return original(item,**kwargs)
    monkeypatch.setattr(tablet_publication,'export_tablet_content',export)
    adapter=PublicAdapter(world,selected_content=True)
    rid='marketplace-03';a=adapter.catalog(rid,{});b=adapter.catalog(rid,{})
    assert a==b
    assert len(calls)==len(set(calls))==len(tablet_variants(a))>0
    assert all(key in adapter.selected_packets for key in calls)


def test_empty_packet_removes_optional_content_without_legacy_fallback(world,monkeypatch):
    original=tablet_publication.export_tablet_content
    monkeypatch.setattr(tablet_publication,'export_tablet_content',
        lambda item,**kwargs:original(item,**kwargs,selected_groups=[]))
    adapter=PublicAdapter(world,selected_content=True)
    for p,v in tablet_variants(adapter.catalog('marketplace-03',{})):
        assert p['introduction']=='' and p['descriptions']==[]
        assert v['highlights']==[]
        assert all(g['role']!='descriptive' for g in v['details'])
        assert any(g['role']=='reference_price' for g in v['details'])
        assert v['selection'] and v['offerId'] and v['priceMinor']>0


def test_unknown_and_private_fields_omitted_known_negatives_preserved():
    rows=fact_rows({'charger':False,'cable_units':0,'missing':-1,'irrelevant':0,'model_price_factor':1.2},
                   {'missing':'unknown','irrelevant':'not_applicable'},prefix='product.facts.')
    assert [(r['field'],r['value']) for r in rows]==[('product.facts.charger','No'),('product.facts.cable_units',0)]
    products={'a':{'facts':{'charger':False,'unknown':-1,'model_price_factor':2},'fact_status':{'unknown':'unknown'}}}
    before=deepcopy(products);clean=products_with_optional_facts(products)
    assert products==before
    assert clean['a']['facts']=={'charger':False} and clean['a']['fact_status']=={}


def test_review_and_comparison_export_excludes_unknowns_and_private_pricing(world):
    products=public_products(world)
    for p in products.values():
        assert not {'model_price_factor','configuration_price_factor','connection_price_factor'}.intersection(p['facts'])
        assert all(v not in ('unknown','not_applicable') for v in p['fact_status'].values())
        assert 'Not provided' not in p['facts'].values()
