"""Profile mode persists one producer tendency and preserves earlier recipes."""
from copy import deepcopy
import json
from pathlib import Path
import pytest

from environments.product_world import retailer_disclosure as producer
from environments.website_world import product_disclosure as controls,unified_generation,presentation
from environments.website_world.catalog_adapter import PublicAdapter

def world():
    return json.loads(Path('.local/website-delivery-options-20261006-v1/world-7-final/pin/world.private.json').read_text())

def settings():return controls.options({'enabled':True,'mode':'retailer_profile'})

def test_explicit_mode_keeps_uniform_custom_settings_identical():
    assert controls.validate_settings(settings())==settings()
    assert controls.options({'enabled':True})=={'schema':controls.VERSION,'protocol':'semantic-group-count-first-v1','highlight_bias':.25,'count_weights':{}}
    custom={'enabled':True,'count_weights':{'tops.t_shirts':[[0,1],[7,2]]}}
    assert controls.options(custom)==controls.options({**custom,'mode':'count_first'})
    for bad in [{'enabled':True,'mode':'unknown'},{'enabled':True,'mode':'retailer_profile','count_weights':{}},
                {'enabled':True,'mode':'retailer_profile','highlight_bias':True}]:
        with pytest.raises(ValueError):controls.options(bad)

def test_profile_mode_is_persisted_before_pages_and_rejects_stale_profiles():
    w=world();before=deepcopy(w)
    request={'schema':unified_generation.VERSION,'seed':7,'realism':{'product_disclosure':{'enabled':True,'mode':'retailer_profile'}}}
    result=unified_generation.generate(request,world_factory=lambda *a,**kw:deepcopy(w))
    profiles=controls.retailer_profiles(w,settings())
    assert result['presentation']['retailer_disclosure_profiles']==profiles
    assert presentation.validate_request(w,result['presentation'])==result['presentation']
    assert w==before
    changed=deepcopy(result['presentation']);changed['retailer_disclosure_profiles'][next(iter(profiles))]['count_fraction']=0
    with pytest.raises(ValueError,match='Stale'):presentation.validate_request(w,changed)
    changed=deepcopy(result['presentation']);changed.pop('retailer_disclosure_profiles')
    with pytest.raises(ValueError,match='missing'):presentation.validate_request(w,changed)

def test_exact_packets_shared_profile_variant_topics_cache_and_public_privacy():
    w=world();adapter=PublicAdapter(w,selected_content=True,disclosure_settings=settings())
    profiles=controls.retailer_profiles(w,settings());assert adapter.disclosure_profiles==profiles
    counts={}
    for retailer in w['retailers']:
        rid=retailer['retailer_id'];catalog=adapter.catalog(rid,{})
        # Private profile tables and count provenance do not become browser payload.
        assert 'retailer_disclosure' not in json.dumps(catalog)
        assert 'count_fraction' not in json.dumps(catalog)
        for product in catalog['products']:
            item=adapter.products[product['canonicalProductId']];cid=item['public']['concept_id']
            if cid not in controls.CAPACITIES:continue
            selections=[]
            for variant in product['variants']:
                packet=adapter.content_packet(item,rid,variant['skuId'] if cid.startswith('tablets.') else None)
                expected=(producer.export_profiled_tablet_content(item,sku_id=variant['skuId'],seed=w['seed'],retailer=retailer)
                    if cid.startswith('tablets.') else producer.export_profiled_tshirt_content(item,seed=w['seed'],retailer=retailer))
                assert packet==expected and packet['retailer_disclosure']==profiles[rid]
                selection=packet['disclosure_selection'];selections.append(selection['selected_groups'])
                counts[(rid,product['canonicalProductId'])]=selection['requested_count']
                slots={s['id'] for g in packet['display_groups'] for s in g['slots']}
                actual={f['slotId'] for g in variant['details'] if g['role']=='descriptive' for f in g['facts']}
                actual.update(s['id'] for d in product['descriptions'] for s in d.get('slots',[]))
                assert actual==slots
            assert all(s==selections[0] for s in selections)
        assert adapter.catalog(rid,{})==catalog
    assert counts and len(set(counts.values()))>1
    for key in adapter.selected_packets:
        assert key[-2]==adapter.disclosure_digest and key[-1]==adapter.disclosure_profile_digests[key[0]]

def test_profile_cache_and_validation_include_all_profile_inputs():
    w=world();adapter=PublicAdapter(w,selected_content=True,disclosure_settings=settings())
    rid=w['retailers'][0]['retailer_id'];changed=deepcopy(w);changed['retailers'][0]['price_preference']='premium' if w['retailers'][0]['price_preference']!='premium' else 'budget'
    # Isolate profile validation from the source-world validator: changed records
    # are not a claim that an existing frozen world's identity can be rewritten.
    profiles=controls.retailer_profiles(changed,settings())
    assert profiles[rid]!=adapter.disclosure_profiles[rid]
    with pytest.raises(ValueError,match='Stale'):controls.validate_profiles(changed,settings(),adapter.disclosure_profiles)
