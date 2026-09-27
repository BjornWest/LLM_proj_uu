"""Bundled city anchors and offline approximate routes; no network access."""
from functools import lru_cache
import heapq
import json
import math
from pathlib import Path
from .generator import rng, digest

VERSION = 'offline-geography-v1'
CUSTOMER_MODES = ('walking', 'cycling', 'driving')


@lru_cache(maxsize=1)
def network():
    return json.loads(Path(__file__).with_name('data').joinpath('europe_locations.json').read_text())


def cities():
    return {c['city_id']: c for c in network()['cities']}


def haversine(a, b):
    lat1, lat2 = map(math.radians, (a['latitude'], b['latitude']))
    dlat = lat2-lat1
    dlon = math.radians(b['longitude']-a['longitude'])
    h = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1, max(0, h))))


def location(seed, id, city_id, area=None):
    if city_id not in cities(): raise ValueError('Unknown bundled city: '+str(city_id))
    city = cities()[city_id]
    radius = rng(seed, 'location/'+id+'/radius').uniform(.25, 4)
    angle = rng(seed, 'location/'+id+'/angle').uniform(0, math.tau)
    # Synthetic local coordinates, explicitly not a real address/geocoded venue.
    east, north = radius*math.cos(angle), radius*math.sin(angle)
    if area is not None:
        east = area['east_km'] + rng(seed, 'location/'+id+'/area-east').uniform(-.12,.12)
        north = area['north_km'] + rng(seed, 'location/'+id+'/area-north').uniform(-.12,.12)
    return {'location_id': id, 'city_id': city_id, 'city': city['name'], 'country': city['country'],
            'latitude': round(city['latitude'] + north/111.195, 6),
            'longitude': round(city['longitude'] + east/(111.195*math.cos(math.radians(city['latitude']))), 6),
            'local_east_km': round(east, 3), 'local_north_km': round(north, 3),
            'precision': 'synthetic_city_neighbourhood', 'timezone': city['timezone'],
            **({'area_id':area['area_id'],'area_name':area['name'],'area_kind':area['kind']} if area else {})}


def user_location(seed=0, city_id='uppsala', country=None):
    if type(seed) is not int: raise ValueError('Location seed must be an integer')
    if country is not None and (not isinstance(country,str) or country not in {c['country'] for c in cities().values()}):
        raise ValueError('Unknown destination country')
    if city_id == 'random':
        # Uniform countries, then uniform supported cities; not population weighted.
        country = country or rng(seed, 'user-country').choice(sorted({c['country'] for c in cities().values()}))
        city_id = rng(seed, 'user-city').choice(sorted(c['city_id'] for c in cities().values() if c['country']==country))
    if country is not None and cities().get(city_id,{}).get('country') != country:
        raise ValueError('Destination city is outside selected country')
    return location(seed, 'user-home', city_id)


def neighbour_countries(country):
    """Countries directly connected by a bundled ground/sea corridor, not air cargo."""
    result=set();known=cities()
    for edge in network()['edges']:
        if edge['kind']=='air_cargo':continue
        a,b=known[edge['from']]['country'],known[edge['to']]['country']
        if a!=b and country in (a,b):result.add(b if a==country else a)
    return sorted(result)


@lru_cache(maxsize=8192)
def city_path(origin, destination, freight=False):
    """Shortest authored travel-time path, with crossings retained as evidence."""
    if origin not in cities() or destination not in cities(): raise ValueError('Unknown route city')
    graph = {id: [] for id in cities()}
    for edge in network()['edges']:
        kind = edge['kind']
        if kind == 'air_cargo' and not freight: continue
        a,b=edge['from'],edge['to']
        factor = {'road':1.22, 'bridge':1.25, 'bridge_tunnel':1.4, 'ferry':1.25, 'air_cargo':1.05}[kind]
        km=haversine(cities()[a],cities()[b])*factor
        speed={'road':75,'bridge':65,'bridge_tunnel':65,'ferry':28,'air_cargo':650}[kind]
        handling={'road':0,'bridge':10,'bridge_tunnel':15,'ferry':90,'air_cargo':240}[kind]
        minutes=km/speed*60+handling
        graph[a].append((b,minutes,km,kind));graph[b].append((a,minutes,km,kind))
    queue=[(0,origin,0,[],[origin])]; seen=set()
    while queue:
        minutes,node,km,legs,path=heapq.heappop(queue)
        if node in seen:continue
        seen.add(node)
        if node==destination:return {'minutes':minutes,'km':km,'legs':legs,'city_path':path}
        for other,time,distance,kind in graph[node]:
            if other not in seen:
                leg={'from_city':node,'to_city':other,'kind':kind,'distance_km':round(distance,1)}
                heapq.heappush(queue,(minutes+time,other,km+distance,legs+[leg],path+[other]))
    return None


def route(origin, destination, mode='driving'):
    if mode not in (*CUSTOMER_MODES,'freight'): raise ValueError('Unknown travel mode')
    for point in (origin,destination):
        if point['city_id'] not in cities(): raise ValueError('Unknown route endpoint')
        if any(type(point[k]) not in (int,float) or not math.isfinite(point[k]) for k in ('latitude','longitude','local_east_km','local_north_km')):
            raise ValueError('Invalid coordinates')
    same=origin['city_id']==destination['city_id']
    base={'origin_id':origin['location_id'],'destination_id':destination['location_id'],'mode':mode,
          'estimate_method':'authored_city_corridors_and_synthetic_local_offsets', 'approximate':True}
    if mode in ('walking','cycling') and not same:
        return {**base,'status':'not_modelled','reason':f'intercity_{mode}_not_modelled','distance_km':None,'duration_minutes':None,'legs':[],'city_path':[]}
    path=city_path(origin['city_id'],destination['city_id'],mode=='freight')
    if path is None:
        return {**base,'status':'not_modelled','reason':'no_modelled_ground_route','distance_km':None,'duration_minutes':None,'legs':[],'city_path':[]}
    if same:
        local=math.hypot(origin['local_east_km']-destination['local_east_km'],origin['local_north_km']-destination['local_north_km'])*1.3
    else:
        local=sum(math.hypot(p['local_east_km'],p['local_north_km']) for p in (origin,destination))*1.3
    distance=path['km']+local
    minutes=path['minutes']+local/{'walking':4.8,'cycling':15,'driving':25,'freight':25}[mode]*60
    return {**base,'status':'estimated','distance_km':round(distance,1),
            'duration_minutes':math.ceil(minutes),'legs':path['legs'],'city_path':path['city_path'],
            'crossing_kinds':sorted({l['kind'] for l in path['legs'] if l['kind']!='road'})}


def data_provenance():
    from .areas import city_areas
    return {'geography_version':VERSION,'network_sha256':digest(network()),'city_source':network()['source'],
            'area_vocabulary_sha256':digest({id:city_areas(city) for id,city in cities().items()}),
            'local_speed_kmh':{'walking':4.8,'cycling':15,'driving':25},
            'limitations':network()['network_note']+' Local offsets and area anchors are approximate, without street/land-boundary checks; walking/cycling are same-city only; no timetables or live traffic.'}
