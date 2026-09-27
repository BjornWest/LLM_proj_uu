"""Location-specific dispatch. Origins never share or sum stock for a shipment."""
from copy import deepcopy
import math
from .config import _number
from .generator import rng


def resolve_options(options):
    defaults={'enabled_probability':.45,'dispatch_days_max':1}
    if not isinstance(options,dict) or set(options)-set(defaults):raise ValueError('Unknown branch shipping option')
    result={**defaults,**options}
    _number(result['enabled_probability'],'enabled_probability',probability=True)
    if type(result['dispatch_days_max']) is not int or not 0<=result['dispatch_days_max']<=7:
        raise ValueError('Branch dispatch_days_max must be 0..7')
    return result


def branch_fields(seed,branch_id,options):
    cfg=resolve_options(options)
    return {'shipping_enabled':rng(seed,branch_id+'/shipping-enabled').random()<cfg['enabled_probability'],
            'shipping_dispatch_days':rng(seed,branch_id+'/shipping-handling').randint(0,cfg['dispatch_days_max'])}


def delivery_sources(world,locations,offer_id,quantity=1):
    """Public source quotes, including unavailable sources and their reason codes."""
    from .locations import route_id,_transit
    if type(quantity) is not int or quantity<1:raise ValueError('quantity must be a positive integer')
    if locations['private_provenance']['source_world_sha256']!=world['world_sha256']:
        raise ValueError('Locations belong to another world')
    offer=next((o for o in world['public']['offers'] if o['offer_id']==offer_id),None)
    if offer is None:raise ValueError('Unknown offer')
    public=locations['public'];user=public['user_location']
    merchant=next(m for m in public['merchants'] if m['retailer_id']==offer['retailer_id'])
    policy=merchant['fulfilment_policy']
    inventory={i['branch_id']:i for i in public['branch_inventory'] if i['product_id']==offer['product_id'] and i['retailer_id']==offer['retailer_id']}
    origins=[(merchant['warehouse'],'warehouse',True,offer['stock_quantity'],offer['dispatch_days'])]
    origins += [(b['location'],'branch',b.get('shipping_enabled',False),inventory.get(b['branch_id'],{}).get('stock_quantity',0),b.get('shipping_dispatch_days',0)) for b in merchant['branches']]
    result=[]
    for origin,kind,enabled,stock,dispatch in origins:
        key=route_id(origin,user,'freight');route=public['routes'].get(key)
        reasons=[]
        if not enabled:reasons.append('branch_shipping_not_supported')
        if stock<quantity:reasons.append(kind+'_insufficient_stock')
        if user['country'] not in policy['delivery_countries']:reasons.append('destination_not_served')
        if enabled and (route is None or route['status']!='estimated'):reasons.append('freight_route_not_modelled')
        q={'offer_id':offer_id,'product_id':offer['product_id'],'retailer_id':offer['retailer_id'],
            'method':'delivery','quantity':quantity,'currency':'SEK','eligible':not reasons,'reason_codes':reasons,
            'requires_stock_transfer':False,'ready_days':None,'shipping_minor':None,'total_minor':None,
            'travel':None,'route_id':key if route else None,'stock_source':origin['location_id'],
            'source_kind':kind,'source_stock_quantity':stock,'shipping_supported':enabled}
        if not reasons:
            foreign=origin['country']!=user['country'];cross=route['crossing_kinds']
            crossings=sum(l['kind'] not in ('road','air_cargo') for l in route['legs'])
            fee=(policy['base_shipping_minor']+math.ceil(route['distance_km']/500)*policy['per_500km_minor']
                +foreign*policy['cross_border_minor']+crossings*policy['crossing_minor']+('air_cargo' in cross)*policy['air_cargo_minor'])
            transit=1 if kind=='branch' and origin['city_id']==user['city_id'] else _transit(route)
            q.update(ready_days=dispatch+transit+int(foreign),shipping_minor=fee,total_minor=offer['price_minor']*quantity+fee)
        result.append(q)
    return result


def quote_delivery(world,locations,offer_id,quantity=1):
    sources=delivery_sources(world,locations,offer_id,quantity)
    eligible=[q for q in sources if q['eligible']]
    if eligible:
        result=deepcopy(min(eligible,key=lambda q:(q['ready_days'],q['total_minor'],q['stock_source'])))
    else:
        result=deepcopy(sources[0]);result['stock_source']=None
        result['reason_codes']=['no_shipping_origin_available']
    result['dispatch_policy']='fastest_source_then_lowest_total'
    result['delivery_sources']=sources
    return result
