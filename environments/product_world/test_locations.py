import copy
from concurrent.futures import ThreadPoolExecutor
import pytest
from .geography import cities, location, route, user_location, haversine
from .generator import digest
from .locations import quote, validate_locations
from .merchant_profiles import PROFILES
from .scenario import generate_scenario


def scenario(city='uppsala', seed=42, config=None, profile=None, stockout=0):
    weights={p:int(p==profile) for p in PROFILES} if profile else None
    return generate_scenario({'seed':2,'family':'footwear','destination_city':city},
        {'seed':seed,'models_per_store':3,'store_config':{'stockout_probability':stockout}},
        {'config':config,'profile_weights':weights})


def first_offer(s):return s['bundle']['public']['offers'][0]['offer_id']


def test_deterministic_offline_and_task_destination_stays_fixed(monkeypatch):
    import socket
    monkeypatch.setattr(socket,'create_connection',lambda *a,**kw:pytest.fail('Network access during world construction'))
    a=scenario('paris');b=scenario('paris',seed=23)
    assert a==scenario('paris')
    assert a['task']==b['task']
    assert a['task']['request']['context']['destination']=='FR'
    assert 'Paris' in a['task']['public']['environment_context']['shopping_scope']
    assert a['locations']['public']['user_location']==b['locations']['public']['user_location']
    validate_locations(a['bundle'],a['locations'])


def test_crossings_and_disconnected_ground_routes_are_not_straight_lines():
    def trip(a,b,mode='driving'):return route(location(1,'a',a),location(1,'b',b),mode)
    assert 'ferry' in trip('london','paris')['crossing_kinds']
    assert 'bridge_tunnel' in trip('malmo','copenhagen')['crossing_kinds']
    assert 'ferry' in trip('belfast','london')['crossing_kinds']
    assert trip('belfast','dublin')['crossing_kinds']==[]
    assert trip('reykjavik','paris')['status']=='not_modelled'
    assert 'air_cargo' in trip('reykjavik','paris','freight')['crossing_kinds']
    assert trip('london','paris','walking')['status']=='not_modelled'
    assert trip('uppsala','uppsala','walking')['duration_minutes']>0
    a=location(1,'a','uppsala')
    assert route(a,a)['distance_km']==0


def test_transfer_is_not_immediate_pickup():
    s=scenario(config={'branch_stockout_probability':1,'transfer_probability':1},profile='local_shop')
    b=s['locations']['public']['merchants'][0]['branches'][0]
    q=quote(s['bundle'],s['locations'],first_offer(s),method='pickup',branch_id=b['branch_id'])
    assert q['eligible'] and q['requires_stock_transfer'] and q['ready_days']>=2
    assert q['branch_stock_quantity']==0 and q['stock_source'].endswith('-warehouse')
    assert q['travel']['walking']['origin_id']=='user-home'
    assert q['travel']['cycling']['origin_id']=='user-home'


def test_cycling_local_speed_and_no_invented_bridge_access():
    a=location(1,'a','malmo');b=location(1,'b','malmo')
    walk,cycle,car=[route(a,b,mode) for mode in ('walking','cycling','driving')]
    assert walk['distance_km']==cycle['distance_km']==car['distance_km']
    assert car['duration_minutes']<=cycle['duration_minutes']<walk['duration_minutes']
    assert route(a,a,'cycling')['duration_minutes']==0
    unknown=route(a,location(1,'c','copenhagen'),'cycling')
    assert unknown['status']=='not_modelled' and unknown['duration_minutes'] is None
    assert unknown['reason']=='intercity_cycling_not_modelled'


def test_country_constrained_sampling_and_city_mismatch_rejection():
    from .scenario import sample_task
    for country in sorted({c['country'] for c in cities().values()}):
        task=sample_task(seed=2,family='footwear',destination_country=country)
        assert task['request']['context']['destination']==country
        assert task==sample_task(seed=2,family='footwear',destination_country=country)
    with pytest.raises(ValueError,match='outside selected country'):
        sample_task(destination_city='paris',destination_country='SE')
    with pytest.raises(ValueError,match='Unknown destination country'):
        sample_task(destination_country='XX')


def test_neighbour_bias_and_explicit_cross_border_worlds():
    from .geography import neighbour_countries
    biased=scenario('malmo',config={'home_city_probability':0,'home_country_probability':0,'foreign_neighbour_probability':1})
    assert all(m['headquarters']['country'] in neighbour_countries('SE') for m in biased['locations']['public']['merchants'])
    for home,foreign in [('malmo','copenhagen'),('lille','brussels'),('amsterdam','antwerp')]:
        s=generate_scenario({'family':'footwear','destination_city':home},{'seed':42,'models_per_store':1},
            {'merchant_home_cities':{'store-001':foreign,'store-002':home},
             'profile_weights':{p:int(p=='local_shop') for p in PROFILES}})
        merchants=s['locations']['public']['merchants']
        assert merchants[0]['headquarters']['city_id']==foreign
        assert merchants[1]['headquarters']['city_id']==home
        assert merchants[0]['branches'][0]['location']['country']!=cities()[home]['country']
        assert route(s['locations']['public']['user_location'],merchants[0]['branches'][0]['location'])['status']=='estimated'
        validate_locations(s['bundle'],s['locations'])
    with pytest.raises(ValueError,match='known retailer IDs'):
        generate_scenario({'destination_city':'malmo'},location_options={'merchant_home_cities':{'missing-store':'copenhagen'}})


def test_area_names_are_distinct_and_do_not_force_multiple_branches():
    from .locations import plan_locations
    user=user_location(1,'uppsala')
    profiles={'shop':{'profile_id':'local_shop','branch_count':1,'international_probability':0},
              'chain':{'profile_id':'major_retailer','branch_count':10,'international_probability':1}}
    plan=plan_locations(1,user,profiles,merchant_home_cities={'shop':'uppsala','chain':'luxembourg'})
    by_id={m['retailer_id']:m for m in plan['merchants']}
    assert len(by_id['shop']['branches'])==1
    assert by_id['shop']['branches'][0]['location']['area_kind']=='named_area_approximate_anchor'
    names=[b['name'] for b in by_id['chain']['branches']]
    assert len(set(names))==10 and all('branch ' not in n for n in names)
    for merchant in plan['merchants']:
        for b in merchant['branches']:
            assert b['location']['area_name'] in b['name']


def test_branch_stock_can_survive_online_stockout_and_no_stock_is_invented():
    s=scenario(config={'branch_stockout_probability':0,'branch_carry_probability':1},profile='local_shop',stockout=1)
    b=s['locations']['public']['merchants'][0]['branches'][0]
    assert quote(s['bundle'],s['locations'],first_offer(s))['reason_codes']==['warehouse_insufficient_stock']
    pickup=quote(s['bundle'],s['locations'],first_offer(s),method='pickup',branch_id=b['branch_id'])
    assert pickup['eligible'] and not pickup['requires_stock_transfer'] and pickup['ready_days']==0
    assert not quote(s['bundle'],s['locations'],first_offer(s),method='pickup',branch_id=b['branch_id'],quantity=10000)['eligible']
    empty=scenario(config={'branch_stockout_probability':1,'display_probability':0,'transfer_probability':1},profile='local_shop',stockout=1)
    b=empty['locations']['public']['merchants'][0]['branches'][0]
    assert not quote(empty['bundle'],empty['locations'],first_offer(empty),method='pickup',branch_id=b['branch_id'])['eligible']
    assert not quote(empty['bundle'],empty['locations'],first_offer(empty),method='inspect',branch_id=b['branch_id'])['eligible']


def test_inspection_display_is_not_sellable_stock():
    s=scenario(config={'branch_stockout_probability':1,'branch_carry_probability':1,'display_probability':1,'transfer_probability':0},profile='local_shop',stockout=1)
    b=s['locations']['public']['merchants'][0]['branches'][0]
    assert quote(s['bundle'],s['locations'],first_offer(s),method='inspect',branch_id=b['branch_id'])['eligible']
    assert not quote(s['bundle'],s['locations'],first_offer(s),method='pickup',branch_id=b['branch_id'])['eligible']


def test_delivery_country_policy_and_geographic_cost():
    s=scenario('paris',config={'home_city_probability':0,'home_country_probability':0},profile='local_shop')
    merchant=s['locations']['public']['merchants'][0]
    merchant['fulfilment_policy']['delivery_countries']=[merchant['headquarters']['country']]
    q=quote(s['bundle'],s['locations'],first_offer(s))
    assert 'destination_not_served' in q['reason_codes']
    merchant['fulfilment_policy']['delivery_countries'].append('FR')
    q=quote(s['bundle'],s['locations'],first_offer(s))
    assert q['eligible'] and q['ready_days']>0 and q['shipping_minor']>4900
    offer=s['bundle']['public']['offers'][0]
    assert q['total_minor']==offer['price_minor']+q['shipping_minor']


def test_profile_correlations_and_sold_out_major_retailers():
    local=scenario(profile='local_shop');large=scenario(profile='major_retailer')
    for s in (local,large):validate_locations(s['bundle'],s['locations'])
    assert all(len(m['branches'])<=2 for m in local['locations']['public']['merchants'])
    for m in local['locations']['public']['merchants']:
        assert all(haversine(cities()[m['headquarters']['city_id']],cities()[b['location']['city_id']])<=60 for b in m['branches'])
    assert all(len(m['branches'])>=6 for m in large['locations']['public']['merchants'])
    assert min(r['models'] for r in large['summary']['stores'])>max(r['models'] for r in local['summary']['stores'])
    assert max(o['stock_quantity'] for o in large['bundle']['public']['offers'])>max(o['stock_quantity'] for o in local['bundle']['public']['offers'])
    sold=scenario(profile='major_retailer',stockout=1)
    assert all(o['stock_quantity']==0 for o in sold['bundle']['public']['offers'])
    online=scenario(profile='online_specialist')
    assert all(m['branches']==[] for m in online['locations']['public']['merchants'])


def test_all_countries_and_independent_branch_stock_audit():
    representatives={c['country']:c['city_id'] for c in cities().values()}
    assert len(representatives)==17
    def check(city):
        s=scenario(city);assert validate_locations(s['bundle'],s['locations'])['valid']
        assert s['task']['request']['context']['destination']==cities()[city]['country']
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(check,representatives.values()))
    a=scenario(config={'branch_stockout_probability':0});b=scenario(config={'branch_stockout_probability':1})
    assert a['task']==b['task'] and a['bundle']==b['bundle']
    assert a['locations']['public']['routes']==b['locations']['public']['routes']


def test_stale_missing_or_corrupt_locations_rejected():
    s=scenario();world=s['bundle'];loc=s['locations']
    for kind in ('route','stock','country','fee'):
        bad=copy.deepcopy(loc)
        if kind=='route':bad['public']['routes'].pop(next(iter(bad['public']['routes'])))
        if kind=='stock':bad['public']['branch_inventory'][0]['stock_quantity']=-1
        if kind=='country':bad['public']['user_location']['country']='DE'
        if kind=='fee':bad['public']['merchants'][0]['fulfilment_policy']['base_shipping_minor']=-1
        bad['locations_sha256']=digest(bad['public'])
        with pytest.raises(ValueError):validate_locations(world,bad)
    with pytest.raises(ValueError,match='another world'):quote(scenario(seed=44)['bundle'],loc,first_offer(s))
    with pytest.raises(ValueError,match='Branch must belong'):quote(world,loc,first_offer(s),method='pickup',branch_id='not-a-branch')


@pytest.mark.parametrize('options',[
    {'config':{'home_city_probability':1,'home_country_probability':1}},
    {'profile_weights':{'major_retailer':-1}}, {'config':{'branch_carry_probability':2}},
    {'correlated_profiles':'yes'}, {'config':{'unknown':1}},
])
def test_bad_config_rejected(options):
    with pytest.raises(ValueError):generate_scenario({'destination_city':'uppsala'},location_options=options)
