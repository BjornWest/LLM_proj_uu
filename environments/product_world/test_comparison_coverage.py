from copy import deepcopy

import pytest

from environments.connected_shopping.comparison import build
from .comparison_coverage import (generate_coverage,validate_coverage,identities,
    coverage_summary,candidate_visibility)
from .config import FAMILY_IDS
from .generator import digest
from .stores import generate_store_world
from .scenario import generate_scenario
from .outcomes import evaluate


SITES=[{'site_id':'general-a','families':list(FAMILY_IDS)},
       {'site_id':'general-b','families':list(FAMILY_IDS)},
       {'site_id':'shoes','families':['footwear']}]
FULL={'retailer_only_probability':0,'shared_core_probability':1,
      'retailer_feed_probability':1,'listing_probability':1}


@pytest.fixture(scope='module')
def world():
    return generate_store_world(42,models_per_store=3)


def test_deterministic_membership_is_independent_of_order_and_additional_sites(world):
    a=generate_coverage(world,SITES,seed=42)
    assert a==generate_coverage(world,list(reversed(SITES)),seed=42)
    extra=generate_coverage(world,SITES+[{'site_id':'new','families':['laptops']}],seed=42)
    assert a['sites']==[s for s in extra['sites'] if s['site_id']!='new']
    assert a['sites']!=generate_coverage(world,SITES,seed=43)['sites']


def test_comparison_identity_matches_renderer_and_lists_only_actual_pairs(world):
    families,pairs,comparison_for=identities(world)
    assert set(families)=={e['id'] for e in build(world)}
    coverage=generate_coverage(world,SITES,config=FULL)
    for s in coverage['sites']:
        expected={cid for cid,f in families.items() if f in s['families']}
        assert set(s['comparison_ids'])==expected
        assert {(r['comparison_id'],r['retailer_id']) for r in s['listings']}=={p for p in pairs if p[0] in expected}
    for p in world['public']['products']:
        if p['category']=='footwear':assert comparison_for[p['product_id']]!=p['product_id']
        else:assert comparison_for[p['product_id']]==p['product_id']


def test_price_and_stock_do_not_affect_membership(world):
    changed=deepcopy(world)
    for o in changed['public']['offers']:
        o['price_minor']+=70000
        o['stock_quantity']=0
    changed['world_sha256']=digest(changed['public'])
    a=generate_coverage(world,SITES,seed=42);b=generate_coverage(changed,SITES,seed=42)
    assert a['source_world_sha256']!=b['source_world_sha256']
    assert a['sites']==b['sites']


def test_empty_coverage_and_tracked_products_without_listings_are_valid(world):
    empty=generate_coverage(world,SITES,config={'retailer_only_probability':1})
    assert all(not s['comparison_ids'] and not s['listings'] for s in empty['sites'])
    summary=coverage_summary(world,empty)
    assert len(summary['retailer_only_comparison_ids'])==summary['offered_comparison_products']
    tracked=generate_coverage(world,SITES,config={**FULL,'listing_probability':0})
    assert all(not s['listings'] for s in tracked['sites'])
    assert tracked['sites'][0]['comparison_ids']
    assert coverage_summary(world,tracked)['sites'][0]['tracked_without_listings']


@pytest.mark.parametrize('failure',['world','unknown','family','duplicate_product','duplicate_site',
    'duplicate_pair','false_pair','untracked_pair','extra_field'])
def test_invalid_membership_is_rejected(world,failure):
    bad=generate_coverage(world,SITES,config=FULL);site=bad['sites'][0]
    if failure=='world':bad['source_world_sha256']='wrong'
    if failure=='unknown':site['comparison_ids'].append('missing')
    if failure=='family':site['families']=['footwear']
    if failure=='duplicate_product':site['comparison_ids'].append(site['comparison_ids'][0])
    if failure=='duplicate_site':bad['sites'].append(deepcopy(site))
    if failure=='duplicate_pair':site['listings'].append(deepcopy(site['listings'][0]))
    if failure=='false_pair':
        families,pairs,_=identities(world)
        false=next((cid,r['retailer_id']) for cid in families for r in world['public']['retailers'] if (cid,r['retailer_id']) not in pairs)
        site['listings'].append(dict(zip(('comparison_id','retailer_id'),false)))
    if failure=='untracked_pair':site['comparison_ids'].remove(site['listings'][0]['comparison_id'])
    if failure=='extra_field':site['winner']=True
    with pytest.raises(ValueError):validate_coverage(world,bad)


@pytest.mark.parametrize('config',[{'unknown':1},{'listing_probability':True},
    {'shared_core_probability':-1},{'site_extra_probability':float('nan')}])
def test_invalid_probabilities_are_rejected(world,config):
    with pytest.raises(ValueError):generate_coverage(world,SITES,config=config)


def test_retailer_only_candidates_remain_in_authoritative_outcome():
    scenario=generate_scenario({'seed':0,'family':'footwear','requirements':1,'hidden':'none',
        'destination_city':'malmo','world_preferences':'none'}, {'seed':42,'models_per_store':3}, {})
    before=deepcopy(scenario);reference=evaluate(scenario)
    coverage=generate_coverage(scenario['bundle'],SITES,config={'retailer_only_probability':1})
    visible=candidate_visibility(scenario['bundle'],coverage,reference['candidates'])
    assert visible
    assert all(not line['sites_tracking_product'] and not line['sites_tracking_listing'] for c in visible for line in c['lines'])
    assert scenario==before
    assert evaluate(scenario)==reference
    assert {c['candidate_id'] for c in visible}=={c['candidate_id'] for c in reference['candidates']}
