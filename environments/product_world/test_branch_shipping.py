from copy import deepcopy
import pytest
from .scenario import generate_scenario,sample_task
from .locations import quote,validate_locations
from .branch_shipping import delivery_sources
from .merchant_profiles import PROFILES
from .generator import digest


def fixture(enabled=1,stockout=0):
    return generate_scenario({'seed':0,'family':'footwear','destination_city':'malmo','hidden':'none'},
        {'seed':42,'models_per_store':1,'store_config':{'stockout_probability':stockout}},
        {'branch_shipping':{'enabled_probability':enabled,'dispatch_days_max':0},
         'config':{'home_city_probability':1,'home_country_probability':0,'branch_carry_probability':1,'branch_stockout_probability':0},
         'profile_weights':{k:int(k=='local_shop') for k in PROFILES}})


def test_branch_dispatch_reduces_time_and_is_quantity_specific():
    s=fixture();w=s['bundle'];loc=s['locations'];o=w['public']['offers'][0]
    sources=delivery_sources(w,loc,o['offer_id']);branch=next(q for q in sources if q['source_kind']=='branch')
    q=quote(w,loc,o['offer_id']);assert q['eligible'] and q['ready_days']==1
    assert q['source_kind']=='branch' and q['stock_source'].startswith(o['retailer_id']+'-branch-')
    assert q['ready_days']<sources[0]['ready_days']
    large=delivery_sources(w,loc,o['offer_id'],branch['source_stock_quantity']+1)
    assert next(x for x in large if x['stock_source']==branch['stock_source'])['eligible'] is False
    assert validate_locations(w,loc)['valid']


def test_local_only_stock_remains_collectable_without_online_stock_or_shipping():
    s=fixture(enabled=0,stockout=1);w=s['bundle'];loc=s['locations'];o=w['public']['offers'][0]
    b=loc['public']['merchants'][0]['branches'][0]
    online=quote(w,loc,o['offer_id']);pickup=quote(w,loc,o['offer_id'],method='pickup',branch_id=b['branch_id'])
    assert not online['eligible'] and online['total_minor'] is None
    assert pickup['eligible'] and not pickup['requires_stock_transfer'] and pickup['ready_days']==0
    assert pickup['stock_source']==b['branch_id']


def test_branch_shipping_can_supply_an_empty_online_warehouse():
    s=fixture(stockout=1);o=s['bundle']['public']['offers'][0]
    q=quote(s['bundle'],s['locations'],o['offer_id'])
    assert q['eligible'] and q['source_kind']=='branch' and o['stock_quantity']==0
    assert q['total_minor']==o['price_minor']+q['shipping_minor']


def test_stock_is_not_combined_across_origins():
    s=fixture();w=s['bundle'];loc=s['locations'];o=w['public']['offers'][0]
    quantities=[q['source_stock_quantity'] for q in delivery_sources(w,loc,o['offer_id'])]
    q=quote(w,loc,o['offer_id'],quantity=max(quantities)+1)
    assert not q['eligible']


def test_legacy_world_no_branch_shipping_and_new_fields_require_version_marker():
    s=generate_scenario({'family':'footwear','destination_city':'malmo'},{'seed':42,'models_per_store':1},{})
    assert 'branch_shipping' not in s['locations']['public']
    q=quote(s['bundle'],s['locations'],s['bundle']['public']['offers'][0]['offer_id'])
    assert q['stock_source'].endswith('-warehouse') and 'delivery_sources' not in q
    bad=fixture();bad['locations']['public']['merchants'][0]['branches'][0]['shipping_enabled']='yes'
    with pytest.raises(ValueError,match='capability'):validate_locations(bad['bundle'],bad['locations'])


def test_nearest_pickup_tasks_require_local_stock_not_eventual_transfer():
    for seed in (0,7,23):
        t=sample_task(seed=seed,family='footwear',query='nearest_pickup',destination_city='malmo',world_preferences='none')
        assert any(p['field']=='requires_stock_transfer' and p['value'] is False for p in t['resolved_task']['world_requirements'])
