"""Physical networks and static geographic fulfilment, separate from runtime carts."""
import copy
import math
from .config import _number
from .generator import rng, digest
from .geography import cities, location, route, data_provenance, haversine, neighbour_countries, CUSTOMER_MODES
from .areas import city_areas

VERSION='product-locations-v1'


def location_defaults():
    return {'home_city_probability':.4,'home_country_probability':.45,'foreign_neighbour_probability':.85,
            'branch_carry_probability':.6,'branch_stockout_probability':.25,
            'display_probability':.35,'transfer_probability':.85}


def resolve_location_config(patch=None):
    cfg=location_defaults()
    if patch is not None:
        if not isinstance(patch,dict) or set(patch)-set(cfg):raise ValueError('Unknown location configuration field')
        for k,v in patch.items():_number(v,k,probability=True);cfg[k]=v
    if cfg['home_city_probability']+cfg['home_country_probability']>1:
        raise ValueError('Home-city and home-country probabilities must sum to at most one')
    return cfg


def _city_in_country(seed, namespace, country):
    return rng(seed,namespace).choice(sorted(c['city_id'] for c in cities().values() if c['country']==country))


def plan_locations(seed, user, profiles, config=None, merchant_home_cities=None, branch_shipping=None):
    """Generate merchant homes, warehouse/branch locations and policies before SKUs."""
    if type(seed) is not int:raise ValueError('Location seed must be an integer')
    cfg=resolve_location_config(config);merchants=[]
    if branch_shipping is not None:
        from .branch_shipping import resolve_options
        branch_shipping=resolve_options(branch_shipping)
    overrides={} if merchant_home_cities is None else merchant_home_cities
    if not isinstance(overrides,dict) or set(overrides)-set(profiles) or any(not isinstance(city,str) or city not in cities() for city in overrides.values()):
        raise ValueError('Merchant home overrides require known retailer IDs and city IDs')
    for id,profile in sorted(profiles.items()):
        draw=rng(seed,id+'/home-region').random()
        if id in overrides:home=overrides[id]
        elif draw<cfg['home_city_probability']:home=user['city_id']
        elif draw<cfg['home_city_probability']+cfg['home_country_probability']:
            home=_city_in_country(seed,id+'/home-city',user['country'])
        else:
            neighbours=neighbour_countries(user['country'])
            nearby=bool(neighbours) and rng(seed,id+'/foreign-neighbour').random()<cfg['foreign_neighbour_probability']
            countries=neighbours if nearby else sorted({c['country'] for c in cities().values()}-{user['country']})
            country=rng(seed,id+'/home-country').choice(countries)
            home=min((c for c in cities().values() if c['country']==country),key=lambda c:(haversine(user,c),c['city_id']))['city_id'] if nearby else _city_in_country(seed,id+'/home-city',country)
        headquarters=location(seed,id+'-headquarters',home);country=headquarters['country']
        scale=profile.get('profile_id','regional_chain')
        radius={'local_shop':60,'regional_chain':250,'major_retailer':float('inf'),'online_specialist':float('inf')}[scale]
        city_pool=sorted(c['city_id'] for c in cities().values() if c['country']==country and haversine(c,cities()[home])<=radius)
        warehouse_city=home if rng(seed,id+'/warehouse-home').random()<.6 else rng(seed,id+'/warehouse-city').choice(city_pool)
        warehouse=location(seed,id+'-warehouse',warehouse_city)
        branches=[]
        used_cities=set()
        used_areas=set()
        for i in range(profile['branch_count']):
            remaining=sorted(set(city_pool)-used_cities) or city_pool
            city_id=home if i==0 else rng(seed,f'{id}/branch-city/{i}').choice(remaining)
            used_cities.add(city_id)
            bid=f'{id}-branch-{i+1:02d}'
            areas=[a for a in city_areas(cities()[city_id]) if a['area_id'] not in used_areas]
            named=[a for a in areas if a['kind']=='named_area_approximate_anchor']
            area=rng(seed,bid+'/area').choice(named or areas);used_areas.add(area['area_id'])
            branches.append({'branch_id':bid,'name':cities()[city_id]['name']+' — '+area['name'],
                             'location':location(seed,bid,city_id,area),'pickup_enabled':True,
                             'inspection_families':['footwear','laptops']})
            if branch_shipping is not None:
                from .branch_shipping import branch_fields
                branches[-1].update(branch_fields(seed,bid,branch_shipping))
        international=rng(seed,id+'/international').random()<profile['international_probability']
        delivery_countries=sorted({c['country'] for c in cities().values()}) if international else [country]
        merchants.append({'retailer_id':id,'headquarters':headquarters,'warehouse':warehouse,'branches':branches,
            'fulfilment_policy':{'delivery_countries':delivery_countries,
                'warehouse_transfer_enabled':rng(seed,id+'/transfer').random()<cfg['transfer_probability'],
                'base_shipping_minor':4900,'per_500km_minor':2500,'cross_border_minor':8000,
                'crossing_minor':7000,'air_cargo_minor':25000,'transfer_fee_minor':0,
                'currency':'SEK','time_basis':'calendar_days_after_order',
                'opening_hours':'not_modelled','pricing_basis':'authored_all_in_scenario_charges_not_real_carrier_rates'}})
    result={'schema_version':VERSION,'seed':seed,'config':cfg,'merchant_home_cities':copy.deepcopy(overrides),'user_location':copy.deepcopy(user),'merchants':merchants}
    if branch_shipping is not None:result['branch_shipping']=branch_shipping
    return result


def route_id(origin,destination,mode):return mode+'|'+origin['location_id']+'|'+destination['location_id']


def build_locations(world, plan):
    """Materialize independent branch stock and precompute every supported quote route."""
    seed=plan['seed'];cfg=plan['config'];pub=world['public'];user=plan['user_location']
    products={p['product_id']:p for p in pub['products']};routes={};inventory=[]
    def add(a,b,mode):routes[route_id(a,b,mode)]=route(a,b,mode)
    for merchant in plan['merchants']:
        id=merchant['retailer_id'];warehouse=merchant['warehouse']
        add(warehouse,user,'freight')
        for branch in merchant['branches']:
            point=branch['location']
            for mode in CUSTOMER_MODES:add(user,point,mode)
            add(warehouse,point,'freight')
            if branch.get('shipping_enabled'):add(point,user,'freight')
            for offer in pub['offers']:
                if offer['retailer_id']!=id:continue
                sku=offer['product_id'];ns=branch['branch_id']+'/'+sku
                if rng(seed,ns+'/carried').random()>=cfg['branch_carry_probability']:continue
                stock=0 if rng(seed,ns+'/stockout').random()<cfg['branch_stockout_probability'] else rng(seed,ns+'/quantity').randint(1,8)
                display=products[sku]['category'] in branch['inspection_families'] and rng(seed,ns+'/display').random()<cfg['display_probability']
                inventory.append({'retailer_id':id,'branch_id':branch['branch_id'],'product_id':sku,
                                  'stock_quantity':stock,'inspection_unit_available':display})
    public={'user_location':user,'merchants':copy.deepcopy(plan['merchants']),
            'branch_inventory':inventory,'routes':routes}
    if 'branch_shipping' in plan:public['branch_shipping']=copy.deepcopy(plan['branch_shipping'])
    result={'schema_version':VERSION,'public':public,'private_provenance':{
        'seed':seed,'config':cfg,'merchant_home_cities':plan.get('merchant_home_cities',{}),'source_world_sha256':world['world_sha256'],**data_provenance(),
        'stock_semantics':'Offer stock is the online warehouse pool; branch stock is an independent pool. Inspection units are not saleable stock.',
        'quote_scope':'Static single-SKU quotes; no reservation, cart mutation, opening-hour schedules or branch-to-branch transfers.'},
        'locations_sha256':digest(public)}
    validate_locations(world,result)
    return result


def _transit(route):
    # One handling day plus whole distance bands; crossings add latency. The same
    # route and formula serve delivery and warehouse-to-branch transfer.
    crossings=sum(leg['kind']!='road' for leg in route['legs'])
    return 1+math.ceil(route['distance_km']/650)+crossings+(2 if 'air_cargo' in route['crossing_kinds'] else 0)


def quote(world, locations, offer_id, *, method='delivery', branch_id=None, quantity=1):
    if locations['private_provenance']['source_world_sha256']!=world['world_sha256']:
        raise ValueError('Locations belong to another world')
    if type(quantity) is not int or quantity<1:raise ValueError('quantity must be a positive integer')
    if method not in ('delivery','pickup','inspect'):raise ValueError('Unknown geographic quote method')
    offer=next((o for o in world['public']['offers'] if o['offer_id']==offer_id),None)
    if offer is None:raise ValueError('Unknown offer')
    public=locations['public'];merchant=next(m for m in public['merchants'] if m['retailer_id']==offer['retailer_id'])
    policy=merchant['fulfilment_policy'];warehouse=merchant['warehouse'];user=public['user_location']
    result={'offer_id':offer_id,'product_id':offer['product_id'],'retailer_id':offer['retailer_id'],
            'method':method,'quantity':quantity,'currency':'SEK','eligible':False,'reason_codes':[],
            'requires_stock_transfer':False,'ready_days':None,'shipping_minor':None,'total_minor':None,
            'travel':None,'route_id':None,'stock_source':None}
    if method=='delivery':
        if 'branch_shipping' in public:
            from .branch_shipping import quote_delivery
            return quote_delivery(world,locations,offer_id,quantity)
        route_key=route_id(warehouse,user,'freight');r=public['routes'][route_key]
        reasons=[]
        if user['country'] not in policy['delivery_countries']:reasons.append('destination_not_served')
        if r['status']!='estimated':reasons.append('freight_route_not_modelled')
        if offer['stock_quantity']<quantity:reasons.append('warehouse_insufficient_stock')
        result.update(reason_codes=reasons,route_id=route_key,stock_source=warehouse['location_id'])
        if not reasons:
            foreign=warehouse['country']!=user['country'];cross=r['crossing_kinds']
            crossing_count=sum(l['kind'] not in ('road','air_cargo') for l in r['legs'])
            fee=policy['base_shipping_minor']+math.ceil(r['distance_km']/500)*policy['per_500km_minor']+foreign*policy['cross_border_minor']+crossing_count*policy['crossing_minor']+('air_cargo' in cross)*policy['air_cargo_minor']
            result.update(eligible=True,ready_days=offer['dispatch_days']+_transit(r)+int(foreign),shipping_minor=fee,total_minor=offer['price_minor']*quantity+fee)
        return result
    branch=next((b for b in merchant['branches'] if b['branch_id']==branch_id),None)
    if branch is None:raise ValueError('Branch must belong to the offer retailer')
    result['branch_id']=branch_id
    result['travel']={mode:public['routes'][route_id(user,branch['location'],mode)] for mode in CUSTOMER_MODES}
    item=next((i for i in public['branch_inventory'] if i['branch_id']==branch_id and i['product_id']==offer['product_id']),None)
    stock=item['stock_quantity'] if item else 0
    result['branch_stock_quantity']=stock
    if method=='inspect':
        product=next(p for p in world['public']['products'] if p['product_id']==offer['product_id'])
        if product['category'] not in branch['inspection_families']:result['reason_codes']=['inspection_not_offered_for_family']
        elif not item or not (item['inspection_unit_available'] or stock>0):result['reason_codes']=['no_unit_to_inspect']
        else:result.update(eligible=True,ready_days=0,stock_source=branch_id)
        return result
    if not branch['pickup_enabled']:result['reason_codes']=['pickup_not_offered'];return result
    if stock>=quantity:
        result.update(eligible=True,ready_days=0,shipping_minor=0,total_minor=offer['price_minor']*quantity,stock_source=branch_id)
        return result
    if not policy['warehouse_transfer_enabled']:result['reason_codes']=['branch_insufficient_stock','warehouse_transfer_disabled'];return result
    if offer['stock_quantity']<quantity:result['reason_codes']=['branch_insufficient_stock','warehouse_insufficient_stock'];return result
    key=route_id(warehouse,branch['location'],'freight');r=public['routes'][key]
    if r['status']!='estimated':result['reason_codes']=['transfer_route_not_modelled'];return result
    result.update(eligible=True,requires_stock_transfer=True,stock_source=warehouse['location_id'],route_id=key,
                  ready_days=offer['dispatch_days']+_transit(r),shipping_minor=policy['transfer_fee_minor'],
                  total_minor=offer['price_minor']*quantity+policy['transfer_fee_minor'])
    return result


def validate_locations(world, bundle):
    if bundle.get('schema_version')!=VERSION:raise ValueError('Unknown locations schema')
    p=bundle['public'];stores={s['retailer_id']:s for s in world['public']['retailers']}
    if 'branch_shipping' in p:
        from .branch_shipping import resolve_options
        if resolve_options(p['branch_shipping'])!=p['branch_shipping']:raise ValueError('Incomplete branch shipping options')
    merchants={m['retailer_id']:m for m in p['merchants']}
    if len(merchants)!=len(p['merchants']) or set(stores)!=set(merchants):raise ValueError('Merchant/location mismatch')
    branches={};points={p['user_location']['location_id']:p['user_location']}
    for id,m in merchants.items():
        if stores[id]['location']!={'city':m['headquarters']['city'],'country':m['headquarters']['country']} or stores[id]['warehouse_location']!={'city':m['warehouse']['city'],'country':m['warehouse']['country']}:raise ValueError('Store geography metadata drift')
        for point in [m['headquarters'],m['warehouse'],*[b['location'] for b in m['branches']]]:
            if point['location_id'] in points:raise ValueError('Duplicate location ID')
            city=cities().get(point['city_id'])
            if not city or point['country']!=city['country'] or point['city']!=city['name']:raise ValueError('City/country mismatch')
            points[point['location_id']]=point
        for b in m['branches']:
            if 'branch_shipping' in p:
                if type(b.get('shipping_enabled')) is not bool or type(b.get('shipping_dispatch_days')) is not int or not 0<=b['shipping_dispatch_days']<=7:
                    raise ValueError('Invalid branch shipping capability')
            elif 'shipping_enabled' in b or 'shipping_dispatch_days' in b:
                raise ValueError('Branch shipping requires explicit location contract')
            if b['branch_id'] in branches:raise ValueError('Duplicate branch ID')
            if b['branch_id']!=b['location']['location_id']:raise ValueError('Branch/location ID mismatch')
            point=b['location']
            area=next((a for a in city_areas(cities()[point['city_id']]) if a['area_id']==point.get('area_id')),None)
            if area is None or point.get('area_name')!=area['name'] or point.get('area_kind')!=area['kind'] or b['name']!=point['city']+' — '+area['name']:
                raise ValueError('Invalid branch area label')
            if abs(point['local_east_km']-area['east_km'])>.121 or abs(point['local_north_km']-area['north_km'])>.121:
                raise ValueError('Branch coordinates disagree with area anchor')
            branches[b['branch_id']]=id
        if len({b['name'] for b in m['branches']})!=len(m['branches']):raise ValueError('Duplicate branch name within retailer')
        policy=m['fulfilment_policy']
        countries=policy['delivery_countries']
        if not isinstance(countries,list) or not countries or set(countries)-{c['country'] for c in cities().values()}:raise ValueError('Unknown delivery country')
        for key in ('base_shipping_minor','per_500km_minor','cross_border_minor','crossing_minor','air_cargo_minor','transfer_fee_minor'):
            if type(policy[key]) is not int or policy[key]<0:raise ValueError('Invalid shipping charge')
        if type(policy['warehouse_transfer_enabled']) is not bool:raise ValueError('Invalid transfer policy')
    for point in points.values():
        city=cities().get(point['city_id'])
        if city is None or point['country']!=city['country'] or point['city']!=city['name']:raise ValueError('City/country mismatch')
        for key,limit in (('latitude',90),('longitude',180),('local_east_km',4),('local_north_km',4)):
            value=point[key]
            if type(value) not in (float,int) or not math.isfinite(value) or abs(value)>limit:raise ValueError('Invalid location coordinates')
    listed={(o['retailer_id'],o['product_id']) for o in world['public']['offers']};seen=set()
    for i in p['branch_inventory']:
        key=(i['branch_id'],i['product_id'])
        if key in seen or branches.get(i['branch_id'])!=i['retailer_id'] or (i['retailer_id'],i['product_id']) not in listed:raise ValueError('Invalid branch inventory binding')
        seen.add(key)
        if type(i['stock_quantity']) is not int or i['stock_quantity']<0 or type(i['inspection_unit_available']) is not bool:raise ValueError('Invalid branch stock')
    expected=set()
    for m in merchants.values():
        expected.add(route_id(m['warehouse'],p['user_location'],'freight'))
        for b in m['branches']:
            expected.update(route_id(p['user_location'],b['location'],mode) for mode in CUSTOMER_MODES)
            expected.add(route_id(m['warehouse'],b['location'],'freight'))
            if b.get('shipping_enabled'):expected.add(route_id(b['location'],p['user_location'],'freight'))
    if set(p['routes'])!=expected:raise ValueError('Missing/extra precomputed route')
    for key,r in p['routes'].items():
        if r!=route(points[r['origin_id']],points[r['destination_id']],r['mode']):raise ValueError('Route differs from offline network')
    if bundle['locations_sha256']!=digest(p):raise ValueError('Location digest mismatch')
    if bundle['private_provenance']['source_world_sha256']!=world['world_sha256']:raise ValueError('Locations belong to another world')
    return {'valid':True,'branches':len(branches),'routes':len(p['routes'])}
