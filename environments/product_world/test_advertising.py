from copy import deepcopy
import pytest
from .advertising import generate_advertising,validate_advertising
from .stores import generate_store_world
from .generator import digest

SITES=[{'site_id':'comparison-footwear','kind':'aggregator','families':['footwear']},
       {'site_id':'comparison-all','kind':'aggregator','families':['footwear','laptops']},
       {'site_id':'reviews-footwear','kind':'product_review','families':['footwear']}]

@pytest.fixture
def world():
    return generate_store_world(42,models_per_store=3,footwear_depth={})


def test_frozen_sidecar_deterministic_and_does_not_mutate_world_or_site_order(world):
    before=deepcopy(world)
    first=generate_advertising(world,SITES,seed=42,focus_families=['footwear'])
    assert validate_advertising(world,first)['ads']>=4
    assert first==generate_advertising(world,list(reversed(SITES)),seed=42,focus_families=['footwear'])
    assert world==before


def test_context_controls_choose_related_or_unrelated_without_requiring_match(world):
    sites=SITES[:1]
    related=generate_advertising(world,sites,config={'contextual_probability':1,'ads_per_site':3})
    unrelated=generate_advertising(world,sites,config={'contextual_probability':0,'ads_per_site':3})
    assert all(a['family']=='footwear' for a in related['sites'][0]['ads'])
    assert all(a['family']!='footwear' for a in unrelated['sites'][0]['ads'])
    # General comparator broad focus can affect ad families, not offers or ranking.
    focused=generate_advertising(world,SITES[1:2],focus_families=['footwear'],config={'contextual_probability':1})
    assert all(a['family']=='footwear' for a in focused['sites'][0]['ads'])


def test_zero_and_full_site_participation(world):
    off=generate_advertising(world,SITES,config={'aggregator_site_probability':0,'review_site_probability':0})
    assert all(not s['ads'] for s in off['sites'])
    on=generate_advertising(world,SITES,config={'review_site_probability':1,'ads_per_site':3})
    assert all(len(s['ads'])==3 for s in on['sites'])
    assert all(not s['ads'] for s in generate_advertising(world,SITES,config={'ads_per_site':0})['sites'])


def test_selection_is_independent_of_stock_and_price(world):
    changed=deepcopy(world)
    for offer in changed['public']['offers']:
        offer['price_minor']+=10000;offer['stock_quantity']=0
    changed['world_sha256']=digest(changed['public'])
    a=generate_advertising(world,SITES);b=generate_advertising(changed,SITES)
    for left,right in zip(a['sites'],b['sites']):
        assert len(left['ads'])==len(right['ads'])
        for x,y in zip(left['ads'],right['ads']):
            assert y['price_minor']==x['price_minor']+10000
            assert {k:v for k,v in x.items() if k!='price_minor'}=={k:v for k,v in y.items() if k!='price_minor'}


@pytest.mark.parametrize('field,value',[
 ('label','Recommended'),('price_minor',1),('body','Guaranteed cheapest and in stock'),
 ('retailer_id','missing'),('product_id','missing'),('model_id','missing'),('currency','EUR')])
def test_false_claims_and_bad_targets_rejected(world,field,value):
    a=generate_advertising(world,SITES);a['sites'][0]['ads'][0][field]=value
    with pytest.raises(ValueError):validate_advertising(world,a)


def test_unknown_fields_wrong_world_duplicate_ads_and_private_inputs_rejected(world):
    a=generate_advertising(world,SITES)
    bad=deepcopy(a);bad['source_world_sha256']='other'
    with pytest.raises(ValueError):validate_advertising(world,bad)
    bad=deepcopy(a);bad['sites'][0]['ads'].append(deepcopy(bad['sites'][0]['ads'][0]))
    with pytest.raises(ValueError):validate_advertising(world,bad)
    bad=deepcopy(a);bad['sites'][0]['ads'][0]['task_relevant']=True
    with pytest.raises(ValueError):validate_advertising(world,bad)
    with pytest.raises(TypeError):generate_advertising(world,SITES,hidden_requirements=[])
    with pytest.raises(ValueError):generate_advertising(world,SITES,config={'contextual_probability':True})
    with pytest.raises(ValueError):generate_advertising(world,SITES,config={'ads_per_site':True})
