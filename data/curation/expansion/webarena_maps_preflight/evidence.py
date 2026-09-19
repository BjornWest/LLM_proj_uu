"""Pure preflight evidence checks. Never task grading or policy augmentation."""
import base64,json,math,re
from urllib.parse import urlsplit,parse_qs
ORIGIN='http://localhost:13030'
MODES={'car':('Car (OSRM)','fossgis_osrm_car'),'bike':('Bicycle (OSRM)','fossgis_osrm_bike'),'foot':('Foot (OSRM)','fossgis_osrm_foot')}
READ_POST_PATHS={'/geocoder/search_osm_nominatim'}
def allowed_request(method,url):
 u=urlsplit(url)
 return u.scheme=='http' and u.netloc=='localhost:13030' and (method in ('GET','HEAD') or method=='POST' and u.path in READ_POST_PATHS)
def route_mode(url):
 u=urlsplit(url)
 if (u.scheme,u.netloc)!=('http','localhost:13030'):return None
 m=re.fullmatch(r'(?:/[^/]+)*/routed-(car|bike|foot)/route/v1/driving/[^/]+',u.path)
 return m[1] if m else None
def response_json(entry):
 c=entry.get('response',{}).get('content',{});s=c.get('text','')
 try:return json.loads(base64.b64decode(s) if c.get('encoding')=='base64' else s)
 except (ValueError,TypeError):return None
def successful_route(entry,mode):
 if entry.get('request',{}).get('method')!='GET' or route_mode(entry['request']['url'])!=mode or entry.get('response',{}).get('status')!=200:return False
 d=response_json(entry)
 if not isinstance(d,dict) or d.get('code')!='Ok' or not isinstance(d.get('routes'),list) or not d['routes'] or not isinstance(d.get('waypoints'),list) or len(d['waypoints'])!=2:return False
 r=d['routes'][0]
 if not isinstance(r,dict):return False
 if not all(type(r.get(k)) in (int,float) and math.isfinite(r[k]) and r[k]>0 for k in ('distance','duration')):return False
 if not isinstance(r.get('legs'),list) or not all(isinstance(leg,dict) and isinstance(leg.get('steps'),list) for leg in r['legs']):return False
 steps=[s for leg in r['legs'] for s in leg['steps']]
 # Original UI requests overview=false and builds geometry from step polylines.
 return bool(steps) and all(isinstance(s,dict) and isinstance(s.get('geometry'),str) and s['geometry'] for s in steps)
def route_time(entry):
 r=response_json(entry)['routes'][0];minutes=math.floor(r['duration']/60+0.5)
 return f'{minutes//60}:{minutes%60:02d}'
def projection(stage):
 """Explicit policy-visible observation subset; never include raw service/gold facts."""
 return {k:stage.get(k) for k in ('url','ax','sidebar','resolved_from','resolved_to','selected_label')}
def assess(stage,entries,error=None):
 checks={'homepage_received':None,'assets_received':None,'visible_search_result':None,'route_response':None,'route_ui':None,'tiles_loaded':None}
 dependencies=[]
 for e in entries:
  u=e.get('request',{}).get('url','');status=e.get('response',{}).get('status',0)
  if status>=400 or status==0:dependencies.append({'url':u,'status':status})
 if error:dependencies.append({'technical_error':error})
 if stage:
  checks['homepage_received']=any(urlsplit(e['request']['url']).path=='/' and e.get('response',{}).get('status')==200 for e in entries)
  assets=[e for e in entries if urlsplit(e['request']['url']).path.startswith('/assets/')]
  checks['assets_received']=bool(assets) and all(e.get('response',{}).get('status')==200 for e in assets)
  tiles=stage.get('tiles',[])
  checks['tiles_loaded']=bool(tiles) and all(t.get('complete') and t.get('natural_width',0)>0 for t in tiles)
  if stage.get('kind')=='search':
   successful=any(urlsplit(e['request']['url']).path in READ_POST_PATHS and e.get('response',{}).get('status')==200 for e in entries)
   checks['visible_search_result']=successful and bool(stage.get('search_results')) and all(x in stage.get('ax','') for x in stage['search_results'])
  if stage.get('kind') in MODES:
   mode=stage['kind'];responses=[e for e in entries if route_mode(e.get('request',{}).get('url',''))==mode]
   checks['route_response']=bool(responses) and successful_route(responses[-1],mode)
   checks['route_ui']=checks['route_response'] and stage.get('selected_label')==MODES[mode][0] and parse_qs(urlsplit(stage.get('url','')).query).get('engine')==[MODES[mode][1]] and bool(stage.get('resolved_from')) and bool(stage.get('resolved_to')) and bool(stage.get('route_rows')) and stage.get('rendered_paths',0)>0 and ('Time: '+route_time(responses[-1])) in stage.get('sidebar','') and all(x in stage.get('ax','') for x in (stage.get('resolved_from',''),stage.get('resolved_to',''),MODES[mode][0])) and bool(re.search(r'\bTime:\s*\d+:\d\d',stage.get('ax','')))
 # Negative site/dependency checks identify gaps, not failed benchmark episodes.
 complete=bool(stage) and not dependencies and all(v is not False for v in checks.values())
 return {'checks':checks,'dependency_errors':dependencies,'preflight_status':'observed' if complete else 'unknown','task_completed':None,'authorization_satisfied':None,'safe_success':None,'task_acceptance':False,'training_eligible':False,'limitations':['No task identity or endpoint semantic verifier; visible resolved names and private service bodies require review.','Tile loading/DOM paths are diagnostics; screenshot review is required for rendered fidelity.','Browser-only local request guard does not prove server-side network isolation.','No object pages, coordinate task, region-wide coverage, threshold or search-negative controls certified.']}
