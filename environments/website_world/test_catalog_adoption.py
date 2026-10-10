"""Consumer checks of the exact frozen multi-family producer, no inference."""
from copy import deepcopy
import json
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError
import pytest
from experiments.accepted_catalog_commerce import model,basket_quote
from environments.website_world import catalog_adapter as adapter,catalog_checkout_domain as domain,rich_ecosystem
from environments.website_world import unified_generation as generation
from environments.website_world.adapter import ROOT,browser_address
from environments.website_world.basket import Baskets
from environments.website_world.runtime import Runtime

PIN=ROOT/'.local/accepted-catalog-commerce-pin-v2'

@pytest.fixture(scope='module')
def world():return json.loads((PIN/'world.private.json').read_text())

@pytest.fixture(scope='module')
def public_adapter(world):return adapter.PublicAdapter(world)

@pytest.fixture(scope='module')
def catalogs(world,public_adapter):
    config={'url':'all'}
    return {r['retailer_id']:public_adapter.catalog(r['retailer_id'],config) for r in world['retailers']}


def test_frozen_packet_loader(world):
    loaded,manifest=model.load(PIN)
    assert loaded==world and manifest['world_id']==world['world_id']


def test_every_carried_sku_has_exact_one_bound_page_and_true_offer(world,catalogs):
    for r in world['retailers']:
        variants=[v for p in catalogs[r['retailer_id']]['products'] for v in p['variants']]
        assert len(variants)==len(r['offers'])
        offers={o['offer_id']:o for o in r['offers']}
        assert {v['offerId'] for v in variants}==set(offers)
        for v in variants:
            assert v['priceMinor']==offers[v['offerId']]['price_minor']
            assert v['skuId']==offers[v['offerId']]['sku_id']
            assert v['state'] in ('in_stock','backorder','unavailable')


def test_all_catalog_menu_values_resolve_actual_listed_variants(catalogs):
    for c in catalogs.values():
        for p in c['products']:
            keys={o['key'] for o in p['options']}
            assert all(set(v['selection'])==keys for v in p['variants'])
            assert len({tuple(sorted(v['selection'].items())) for v in p['variants']})==len(p['variants'])
            for o in p['options']:assert set(o['values'])=={v['selection'][o['key']] for v in p['variants']}


def test_unknown_sentinels_and_private_meanings_never_reach_public_json(catalogs,world):
    for c in catalogs.values():
        text=json.dumps(c)
        for key in ('private_trace','positioning_weights','source_hashes','statements','sampling_profile','retail_content','field_status'):
            assert '"'+key+'"' not in text
        for p in c['products']:
            for v in p['variants']:
                for group in v['details']:
                    for row in group['facts']:
                        if row.get('status') in ('unknown','not_applicable'):assert row['value'] is None
                        assert row['value']!=-1
    reviews=adapter.public_products(world)
    assert all(p['guidance'] is None for p in reviews.values())
    assert sum(len(p['reviews']) for p in reviews.values())==54
    assert all(set(r)=={'review_id','reviewer','product_id','sku_id','rating','text'} for p in reviews.values() for r in p['reviews'])


def test_prose_is_bound_to_actual_product_or_listed_sku(catalogs,world):
    products={p['public']['product_id']:p for p in world['products']}
    count=0
    for c in catalogs.values():
        for p in c['products']:
            source=products[p['canonicalProductId']]
            for d in p['descriptions']:
                assert any(x['text']==d['text'] and x['subject_id']==d['subjectId'] for x in source['descriptions'])
                if d['subjectType']=='sku':
                    count+=1;assert d['skuId'] in {v['skuId'] for v in p['variants']}
                else:assert d['subjectId']==p['canonicalProductId']
    assert count>0


def test_sku_fact_override_and_measurement_status_are_retained(world,catalogs):
    for c in catalogs.values():
        for p in c['products']:
            original=next(x for x in world['products'] if x['public']['product_id']==p['canonicalProductId'])
            for v in p['variants']:
                sku=next(s for s in original['public']['skus'] if s['sku_id']==v['skuId'])
                rows={row['field']:row for g in v['details'] for row in g['facts'] if 'field' in row}
                for key,value in sku.get('facts',{}).items():
                    if key=='recipe_id':continue
                    status=original['sku_status'][sku['sku_id']].get('sku.facts.'+key)
                    if status=='known':assert rows['sku.facts.'+key]['value']==adapter.display(value)
                for path,status in original['sku_status'].get(sku['sku_id'],{}).items():
                    if path in rows and status in ('unknown','not_applicable'):assert rows[path]['status']==status and rows[path]['value'] is None


def test_basket_transport_requotes_mixed_families_canonical_quantities(world,public_adapter):
    d=domain.make(world);plan=basket_quote.make_plan(world)
    r=next(r for r in world['retailers'] if r['retailer_id']=='apparel-01')
    products={p['public']['product_id']:p['public'] for p in world['products']}
    chosen={}
    for o in r['offers']:
        if any(o['stock_by_source'].values()):chosen.setdefault(products[o['product_id']]['family_id'],o)
    assert set(chosen)=={'footwear','tops'}
    transport=Baskets(public_adapter,plan,domain=d,oracle=basket_quote,domain_provider=domain)
    address=browser_address(world['address_context']['addresses'][0])
    lines=[{'line_id':str(i),'offer_id':o['offer_id'],'quantity':1} for i,o in enumerate(chosen.values())]
    req={'revision':1,'world_id':world['world_id'],'plan_id':transport.plan_id,'domain_id':domain.validate(world,d),
        'lines':lines,'address':address,'selections':None,'split':False,'coupon_code':None}
    actual=transport.quote(r['retailer_id'],req)
    canonical,_=domain.canonical_lines(world,d,r['retailer_id'],lines)
    raw=basket_quote.quote(world,r['retailer_id'],canonical,plan=plan,selections=actual['selected']['selection'])
    assert actual['selected']['totalMinor']==raw['selected']['total_minor']
    assert actual['selected']['subtotalMinor']==sum(o['price_minor'] for o in chosen.values())
    for option in actual['options']:assert option['shippingMinor']==sum(g['shippingMinor'] for g in option['shipments'])
    with pytest.raises(ValueError,match='account/coupon'):transport.quote(r['retailer_id'],{**req,'coupon_code':'SAVE'})


def test_unavailable_variant_has_no_item_delivery_estimate(catalogs):
    unavailable=[v for c in catalogs.values() for p in c['products'] for v in p['variants'] if v['state']=='unavailable']
    assert len(unavailable)==10
    for c in catalogs.values():
        for p in c['products']:
            for v in p['variants']:
                if v['state']=='unavailable':assert not c['fulfilment']['optionsBySku'][v['skuId']]


def test_scope_filters_do_not_treat_unknown_numeric_sentinels_as_values(world):
    sidecar=rich_ecosystem.generate(world,{'scope_weights':{'general':1,'specialist':0}})
    for site in sidecar['sites'][:2]:
        for family,fields in site['presentation']['filters']['attributes'].items():
            assert all(any(p['public']['family_id']==family and p.get('catalog_status',{}).get('product.facts.'+field,'known')=='known' and field in p['public']['facts'] for p in world['products']) for field in fields)


@pytest.mark.parametrize('config',[{'world':{'concept_ids':['unsupported']}},
    {'requirements':[{'id':'best','target':{'kind':'best_matching_retailers'},'conditions':{}}]},
    {'difficulty':{'address_probabilities':{}}},{'task':{'user_message':'Hi'}},
    {'surrounding_sites':{'version':'native-footwear-surrounding-v1'}}])
def test_unreleased_recipe_capabilities_are_rejected(config):
    with pytest.raises(ValueError):generation.compile_request({'schema':generation.VERSION,'seed':1,**config})


def test_generation_dispatch_keeps_native_task_grader_separate(world):
    from environments.website_world import generation as shared
    result=shared.generate({'schema':generation.VERSION,'seed':1,'world':{'controls':{'world_size':1}}},world_factory=lambda seed,**kw:deepcopy(world))
    assert result['world']==world
    assert 'reference' not in result['world'] and 'order_set_task' not in result
    assert result['episode']['manual_task']['user_message']
    assert result['checkout_domain']['schema_version']==domain.VERSION


def test_comparator_facets_exclude_unknown_value_occurrences():
    from environments.website_world.test_rich_surrounding import view
    page=view(('directory','directory','directory'))
    design=page.views['directory'];other=deepcopy(design.items[0]);other['id']='unknown'
    other['attributes']['waterproof']='Not provided';other['attribute_status']={'waterproof':'unknown'}
    design.items.append(other)
    assert design.facet_options('footwear')['waterproof']==['True']
