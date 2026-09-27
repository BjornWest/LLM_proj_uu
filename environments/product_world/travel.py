"""Export public places and cached mode-specific trips for a synthetic travel site."""
import copy
from .generator import digest
from .geography import route, data_provenance, CUSTOMER_MODES
from .locations import validate_locations

VERSION='travel-planner-export-v1'
MODES=CUSTOMER_MODES


def export_travel_planner(world, locations):
    validate_locations(world,locations)
    public=locations['public'];user=public['user_location']
    places=[{'place_id':user['location_id'],'kind':'saved_place','name':'Home',
             'label':f"Home, {user['city']}, {user['country']}", 'city':user['city'],'country':user['country'],
             'retailer_id':None,'aliases':['home','my home','user home'], 'location':copy.deepcopy(user)}]
    stores={s['retailer_id']:s for s in world['public']['retailers']}
    for m in public['merchants']:
        store=stores[m['retailer_id']]
        for branch in m['branches']:
            point=branch['location'];label=f"{store['name']} — {branch['name']}, {point['country']}"
            places.append({'place_id':branch['branch_id'],'kind':'branch','name':store['name']+' — '+branch['name'],
                'label':label,'city':point['city'],'country':point['country'],'retailer_id':m['retailer_id'],
                'aliases':[store['name'],branch['name'],store['specialization'],*store['families']],
                'location':copy.deepcopy(point)})
    # City corridors are cached once per directed pair/mode. Per-place records
    # contain only the result, not repeated full paths or warehouse information.
    trips=[]
    for origin in places:
        for destination in places:
            for mode in MODES:
                r=route(origin['location'],destination['location'],mode)
                trips.append({'origin_id':origin['place_id'],'destination_id':destination['place_id'],'mode':mode,
                    'status':r['status'],'distance_km':r['distance_km'],'duration_minutes':r['duration_minutes'],
                    'crossing_kinds':r.get('crossing_kinds',[]),'reason':r.get('reason'), 'approximate':True})
    payload={'places':places,'modes':list(MODES),'trips':trips}
    return {'schema_version':VERSION,'public':payload,'public_sha256':digest(payload),
        'private_provenance':{'source_world_sha256':world['world_sha256'],
            'source_locations_sha256':locations['locations_sha256'],**data_provenance(),
            'scope':'Saved home and every physical branch; all directed pairs. No arbitrary real-address geocoding.',
            'routing_objective':'Estimated fastest authored driving corridor; synthetic local walking/cycling estimates. No claim of globally shortest street route.'}}
