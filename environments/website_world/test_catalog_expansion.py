"""Exact generic packets, SKU scope, omission and expanded recipe validation."""
from copy import deepcopy
from pathlib import Path
import json
import pytest

from experiments.accepted_catalog_commerce import package_export, basket_quote, prepared_quote, model
from experiments.accepted_catalog_commerce.execution import Execution
from experiments.accepted_catalog_commerce.test_catalog_expansion import BRAND
from environments.product_world import catalog_publication as producer
from environments.website_world import catalog_adapter, product_disclosure, unified_generation

ROOT = Path('.local/product-catalog-expansion-20261006')


@pytest.fixture(scope='module')
def world():
    return json.loads((ROOT/'world-first-v1.json').read_text())


@pytest.fixture(scope='module')
def items():
    execution=Execution()
    return {cid:execution.sample(7,cid,BRAND,'website-probe/'+cid,review_count=0)
            for cid in producer.CONCEPTS}


def adapter(world,settings=None,selected=True):
    plan=basket_quote.make_plan(world)
    return catalog_adapter.PublicAdapter(world,plan,selected_content=selected,
        disclosure_settings=settings,prepared=prepared_quote.prepare(world,plan=plan),lazy=True)


def slots(packet):
    return [s for g in packet['display_groups'] for s in g['slots']]


def assert_projection(packet, rows, care):
    expected_details=[s for g in packet['display_groups'] if g['key']!='care' for s in g['slots']]
    expected_care=[s for g in packet['display_groups'] if g['key']=='care' for s in g['slots']]
    assert [(r['slotId'],r['value'],r['assertions']) for r in rows]==[
        (s['id'],s['text'],s['assertions']) for s in expected_details]
    assert [s for d in care for s in d['slots']]==expected_care
    assert all(d['text']==' '.join(s['text'] for s in d['slots']) for d in care)
    assert len(rows)+sum(len(d['slots']) for d in care)==len(slots(packet))


@pytest.mark.parametrize('cid',producer.CONCEPTS)
def test_every_released_inventory_compiles_and_preserves_exact_selected_records(cid,items):
    item=items[cid];inv=producer.inventory(cid)
    assert product_disclosure.CAPACITIES[cid]==inv['capacity']
    labels={'tops':'Tops','tablets':'Tablets',**producer.FAMILY_LABELS}
    assert catalog_adapter.FAMILY_LABELS[item['public']['family_id']]==labels[item['public']['family_id']]
    # Omitted concentration tasks resolve to this explicit target, rather than
    # incorrectly retaining a walking-shoe task outside its one-concept slice.
    request={'schema':unified_generation.VERSION,'seed':7,
        'world':{'concept_ids':[cid]},'task':{'kind':'cheapest_available','concept_id':cid},
        'realism':{'product_disclosure':{'enabled':True,'count_weights':{cid:[[inv['capacity'],1]]}}}}
    compiled=unified_generation.compile_request(request)
    assert compiled['world']['concept_ids']==[cid] and compiled['world']['tasks']==[cid]
    for sku in item['public']['skus'][:2]:
        packet=producer.export_catalog_content(item,sku_id=sku['sku_id'],seed=7,
            retailer_id='probe',selected_groups=list(inv['groups']))
        rows=[r for g in catalog_adapter.selected_details(packet) for r in g['facts']]
        care=catalog_adapter.selected_care(packet,sku_id=sku['sku_id'])
        assert_projection(packet,rows,care)
        assert all(d['skuId']==d['subjectId']==sku['sku_id'] and d['subjectType']=='sku' for d in care)
        for slot in slots(packet):
            for assertion in slot['assertions']:
                assert assertion['subject']['id'] in (item['public']['product_id'],sku['sku_id'])
                if assertion['semantic_id'] is None:
                    assert assertion['mapping_status']=='native_scalar_field_without_authored_meaning'
                    assert assertion['authority']=='source_catalog_field'
        assert all(h['slotId'] in {s['id'] for s in slots(packet)} for h in catalog_adapter.selected_highlights(packet))


def test_defaults_and_unreleased_or_excessive_slices_still_reject():
    default=unified_generation.compile_request({'schema':unified_generation.VERSION,'seed':7})
    assert default['world']['concept_ids']==list(package_export.CONCEPTS) and len(package_export.CONCEPTS)==5
    for ids in (['unadopted.example'],['phones.smartphones','phones.smartphones']):
        with pytest.raises(ValueError,match='supported unique'):
            unified_generation.compile_request({'schema':unified_generation.VERSION,'seed':7,
                'world':{'concept_ids':ids,'tasks':[]}})
    for cid in producer.CONCEPTS:
        with pytest.raises(ValueError):
            product_disclosure.options({'enabled':True,'count_weights':{cid:[[producer.inventory(cid)['capacity']+1,1]]}})


def test_fresh_expanded_pin_loads_without_rewriting_historical_pins(world,tmp_path):
    original=deepcopy(world)
    manifest=model.freeze(world,tmp_path/'pin')
    loaded,actual=model.load(tmp_path/'pin')
    assert loaded==original==world and actual==manifest


@pytest.mark.parametrize('mode',['default','full','empty','retailer_profile'])
def test_mixed_family_catalog_exact_packet_native_controls_and_no_raw_fallback(world,mode):
    settings=(None if mode=='default' else product_disclosure.options(
        {'enabled':True,'mode':'retailer_profile'} if mode=='retailer_profile' else
        {'enabled':True,'count_weights':{cid:[[0 if mode=='empty' else producer.inventory(cid)['capacity'],1]]
          for cid in producer.CONCEPTS}}))
    public=adapter(world,settings);baseline=adapter(world,selected=False)
    known_families=set(); count=0
    for retailer in world['retailers']:
        rid=retailer['retailer_id'];catalog=public.catalog(rid,{})
        native={v['offerId']:v for p in baseline.catalog(rid,{})['products'] for v in p['variants']}
        for product in catalog['products']:
            known_families.add(product['familyId'])
            item=public.products[product['canonicalProductId']];cid=item['public']['concept_id']
            if cid not in producer.CONCEPTS:continue
            assert product['introduction']==''
            choices=[]
            for variant in product['variants']:
                count+=1;packet=public.content_packet(item,rid,variant['skuId'])
                assert packet['sku_id']==variant['skuId']
                expected=producer.export_catalog_content(item,sku_id=variant['skuId'],seed=world['seed'],
                    **({'retailer':retailer,'highlight_bias':settings['highlight_bias']} if mode=='retailer_profile' else
                       {'retailer_id':rid,**(product_disclosure.producer_arguments(settings,cid) if settings else {})}))
                assert packet==expected
                choices.append(packet['disclosure_selection']['selected_groups'])
                rows=[r for g in variant['details'] if g['role']=='descriptive' for r in g['facts']]
                care=[d for d in product['descriptions'] if d.get('skuId')==variant['skuId']]
                assert care==catalog_adapter.selected_care(packet,sku_id=variant['skuId'])
                assert_projection(packet,rows,care)
                for key in ('selection','priceMinor','currency','state','sourceStock','supplierOrder','pickup','offerId'):
                    assert variant[key]==native[variant['offerId']][key]
                if mode=='empty':assert not rows and not care and not variant['highlights']
            assert all(c==choices[0] for c in choices)
        assert catalog==public.catalog(rid,{})
        assert 'retailer_disclosure' not in json.dumps(catalog)
    assert len(known_families)==9 and count>0
    assert all('mapping_status' in row for row in public.fields if row.get('semantic_id') is None and 'slot_id' in row)


@pytest.mark.parametrize('name',['full','partial','empty'])
def test_frozen_packet_examples_survive_projection_exactly(world,name):
    expected=json.loads((ROOT/('packet-'+name+'-v1.json')).read_text())
    public=adapter(world)
    item=public.products[expected['product_id']]
    groups=expected['disclosure_selection']['selected_groups']
    # The producer fixture uses explicit topics, avoiding a new sampling draw.
    actual=producer.export_catalog_content(item,sku_id=expected['sku_id'],seed=world['seed'],
        retailer_id=expected['retailer_id'],selected_groups=groups)
    assert actual==expected
    rows=[r for g in catalog_adapter.selected_details(actual) for r in g['facts']]
    assert_projection(actual,rows,catalog_adapter.selected_care(actual,sku_id=actual['sku_id']))
    if name=='empty':assert not rows and not catalog_adapter.selected_highlights(actual)


@pytest.mark.parametrize('name',['full','partial','empty'])
@pytest.mark.parametrize('batch',['direct-v2','shared-v3'])
def test_next_batch_care_packets_preserve_every_selected_assertion(name,batch):
    prefix,version=batch.split('-')
    packet=json.loads((ROOT/(prefix+'-packet-'+name+'-'+version+'.json')).read_text())
    rows=[r for g in catalog_adapter.selected_details(packet) for r in g['facts']]
    care=catalog_adapter.selected_care(packet,sku_id=packet['sku_id'])
    assert_projection(packet,rows,care)
    if name=='full':assert care
    if name=='empty':assert not rows and not care
    with pytest.raises(ValueError,match='differs from selected SKU'):
        catalog_adapter.selected_care(packet,sku_id='different-sku')


@pytest.mark.parametrize('mode',['full','empty','retailer_profile'])
@pytest.mark.parametrize('source',['direct-next-world-v1.json','shared-world-v2.json'])
def test_next_saved_world_care_binding_and_native_sku_preservation(mode,source):
    world=json.loads((ROOT/source).read_text())
    settings=product_disclosure.options({'enabled':True,'mode':'retailer_profile'}
        if mode=='retailer_profile' else {'enabled':True,'count_weights':{
            cid:[[0 if mode=='empty' else producer.inventory(cid)['capacity'],1]]
            for cid in producer.CONCEPTS}})
    public=adapter(world,settings);baseline=adapter(world,selected=False)
    care_count=0;joined=0
    for retailer in world['retailers']:
        rid=retailer['retailer_id'];catalog=public.catalog(rid,{})
        native={v['offerId']:v for p in baseline.catalog(rid,{})['products'] for v in p['variants']}
        for product in catalog['products']:
            item=public.products[product['canonicalProductId']]
            for variant in product['variants']:
                joined+=1
                for key in ('selection','priceMinor','currency','state','sourceStock','supplierOrder','pickup','offerId'):
                    assert variant[key]==native[variant['offerId']][key]
                if item['public']['concept_id'] not in producer.CONCEPTS:continue
                packet=public.content_packet(item,rid,variant['skuId'])
                rows=[r for g in variant['details'] if g['role']=='descriptive' for r in g['facts']]
                care=[d for d in product['descriptions'] if d.get('skuId')==variant['skuId']]
                assert_projection(packet,rows,care)
                for description in care:
                    care_count+=len(description['slots'])
                    for slot in description['slots']:
                        for assertion in slot['assertions']:
                            bindings=[b for b in public.fields if b.get('slot_id')==slot['id']
                                and b['retailer_id']==rid and b['page_id']==product['id']
                                and b['sku_id']==variant['skuId'] and b['field']==assertion['field']]
                            assert len(bindings)==1
                            binding=bindings[0]
                            assert binding['subject']==assertion['subject']
                            assert binding['subject_id']==assertion['subject']['id']
                            assert binding['subject_type']==assertion['subject']['kind']
                            assert binding['semantic_id']==assertion['semantic_id']
                            assert binding['authority']==assertion['authority']
                            assert binding.get('mapping_status')==assertion.get('mapping_status')
                if mode=='empty':assert not rows and not care and not variant['highlights']
    assert joined==world['summary']['offers']=={'direct-next-world-v1.json':105,'shared-world-v2.json':118}[source]
    if mode=='full':assert care_count>0
    if mode=='empty':assert care_count==0


def test_generic_cache_uses_exact_sku_and_all_disclosure_inputs(world,monkeypatch):
    original=producer.export_catalog_content;calls=[]
    def export(item,**kwargs):
        calls.append((kwargs.get('retailer_id',kwargs.get('retailer',{}).get('retailer_id')),item['public']['product_id'],kwargs['sku_id']))
        return original(item,**kwargs)
    monkeypatch.setattr(producer,'export_catalog_content',export)
    public=adapter(world,product_disclosure.options({'enabled':True,'mode':'retailer_profile'}))
    for retailer in world['retailers']:
        public.catalog(retailer['retailer_id'],{});public.catalog(retailer['retailer_id'],{})
    assert calls and len(calls)==len(set(calls))
    for key,packet in public.selected_packets.items():
        if packet['concept_id'] not in producer.CONCEPTS:continue
        assert key[:3]==(packet['retailer_id'],packet['product_id'],packet['sku_id'])
        assert key[-2:]==(public.disclosure_digest,public.disclosure_profile_digests[key[0]])


def test_sku_dependent_generic_packet_recomputes_without_changing_topics(world):
    public=adapter(world)
    item=Execution().sample(0,'keyboards.split_ergonomic_keyboards',BRAND,
        'split-variant-fixture',review_count=0)
    rid=world['retailers'][0]['retailer_id']
    packets=[public.content_packet(item,rid,s['sku_id']) for s in item['public']['skus'][:2]]
    assert len(packets)==2 and packets[0]['sku_id']!=packets[1]['sku_id']
    assert packets[0]['disclosure_selection']['selected_groups']==packets[1]['disclosure_selection']['selected_groups']
    for packet in packets:
        for slot in slots(packet):
            for record in slot['assertions']:
                if record['subject']['kind']=='sku':assert record['subject']['id']==packet['sku_id']
