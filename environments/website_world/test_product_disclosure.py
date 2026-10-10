"""Fresh recipes explicitly bind the released count-first producer protocol."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from environments.website_world import product_disclosure as controls, unified_generation
from environments.website_world.catalog_adapter import PublicAdapter


def test_defaults_and_count_pairs_use_the_released_protocol():
    settings=controls.options({'enabled':True})
    assert settings['protocol']=='semantic-group-count-first-v1' and settings['highlight_bias']==.25
    assert settings['count_weights']=={}
    request={'enabled':True,'count_weights':{'tops.t_shirts':[[4,2],[0,1],[8,1]]}}
    before=deepcopy(request);parsed=controls.options(request)
    assert request==before and parsed['count_weights']['tops.t_shirts']==[[0,1],[4,2],[8,1]]
    assert controls.producer_arguments(parsed,'tops.t_shirts')['count_weights']=={0:1,4:2,8:1}


@pytest.mark.parametrize('value',[None,{}, {'enabled':1}, {'enabled':False,'highlight_bias':0},
    {'enabled':True,'count_weights':{'unknown':[[0,1]]}},
    {'enabled':True,'count_weights':{'tops.t_shirts':[[12,1]]}},
    {'enabled':True,'count_weights':{'tablets.everyday_media_tablets':[[16,1]]}},
    {'enabled':True,'count_weights':{'tops.t_shirts':[[True,1]]}},
    {'enabled':True,'highlight_bias':True},{'enabled':True,'highlight_bias':float('nan')},
    {'enabled':True,'highlight_bias':2}])
def test_invalid_recipe_controls_reject(value):
    with pytest.raises(ValueError):controls.options(value)


def test_recipe_enables_selected_content_explicitly_and_preserves_legacy():
    request={'schema':unified_generation.VERSION,'seed':7,'realism':{'product_disclosure':{'enabled':True}}}
    before=deepcopy(request);parsed=unified_generation.compile_request(request)
    assert parsed['selected_content'] and parsed['product_disclosure']['protocol']=='semantic-group-count-first-v1'
    assert request==before
    assert unified_generation.compile_request({'schema':unified_generation.VERSION,'seed':7})['product_disclosure'] is None
    assert unified_generation.compile_request({'schema':unified_generation.VERSION,'seed':7,'realism':{'selected_content':True}})['product_disclosure'] is None
    request['realism']['selected_content']=False
    with pytest.raises(ValueError,match='requires selected content'):unified_generation.compile_request(request)


def world():
    return json.loads(Path('.local/website-delivery-options-20261006-v1/world-7-final/pin/world.private.json').read_text())


@pytest.mark.parametrize('requested',[0,15])
def test_empty_and_full_tablet_topics_preserve_native_controls_without_refill(requested):
    settings=controls.options({'enabled':True,'count_weights':{'tablets.everyday_media_tablets':[[requested,1]]}})
    adapter=PublicAdapter(world(),selected_content=True,disclosure_settings=settings)
    catalog=adapter.catalog('marketplace-03',{})
    for product in catalog['products']:
        if product['familyId']!='tablets':continue
        for v in product['variants']:
            packet=adapter.content_packet(adapter.products[product['canonicalProductId']],'marketplace-03',v['skuId'])
            selection=packet['disclosure_selection'];assert selection['requested_count']==requested
            assert selection['published_count']<=requested
            assert v['selection'] and v['priceMinor']>0
            assert product['introduction']=='' and product['descriptions']==[]
            descriptive=[f for g in v['details'] if g['role']=='descriptive' for f in g['facts']]
            assert len(descriptive)==selection['published_count']
            if not requested:assert not descriptive and v['highlights']==[]
    assert all(key[-1]==adapter.disclosure_digest for key in adapter.selected_packets)


def test_count_first_topic_plan_is_stable_across_tablet_skus():
    adapter=PublicAdapter(world(),selected_content=True,disclosure_settings=controls.options({'enabled':True}))
    catalog=adapter.catalog('marketplace-03',{})
    product=next(p for p in catalog['products'] if len(p['variants'])>1 and p['familyId']=='tablets')
    selections=[adapter.content_packet(adapter.products[product['canonicalProductId']],'marketplace-03',v['skuId'])['disclosure_selection'] for v in product['variants']]
    assert all(s['selected_groups']==selections[0]['selected_groups'] and s['requested_count']==selections[0]['requested_count'] for s in selections)
    assert adapter.catalog('marketplace-03',{})==catalog


@pytest.mark.parametrize('requested',[0,11])
def test_tshirt_details_care_and_highlights_share_selected_slots(requested):
    adapter=PublicAdapter(world(),selected_content=True,disclosure_settings=controls.options(
        {'enabled':True,'count_weights':{'tops.t_shirts':[[requested,1]]}}))
    catalog=adapter.catalog('apparel-05',{})
    shirts=[product for product in catalog['products'] if
        adapter.products[product['canonicalProductId']]['public']['concept_id']=='tops.t_shirts']
    assert shirts
    for product in shirts:
        packet=adapter.content_packet(adapter.products[product['canonicalProductId']],'apparel-05')
        slots={s['id']:s for g in packet['display_groups'] for s in g['slots']}
        care={s['id'] for g in packet['display_groups'] if g['key']=='care' for s in g['slots']}
        actual_care={s['id'] for paragraph in product['descriptions'] for s in paragraph['slots']}
        assert care==actual_care
        for variant in product['variants']:
            detail={f['slotId'] for g in variant['details'] if g['role']=='descriptive' for f in g['facts']}
            assert detail|care==set(slots) and not detail&care
            assert all(h['slotId'] in slots for h in variant['highlights'])
        if not requested:assert not slots and not product['descriptions']
