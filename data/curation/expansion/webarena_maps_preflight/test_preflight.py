import copy,json,subprocess,sys,tempfile,unittest
from pathlib import Path
from data.curation.expansion.webarena_maps_preflight.evidence import *
class PreflightTests(unittest.TestCase):
 def route(self,mode='car',status=200):return {'request':{'method':'GET','url':ORIGIN+'/osrm/routed-'+mode+'/route/v1/driving/-79.94,40.44;-79.95,40.45'},'response':{'status':status,'content':{'text':json.dumps({'code':'Ok','waypoints':[{},{}],'routes':[{'distance':1600,'duration':300,'legs':[{'steps':[{'geometry':'abc'}]}]}]})}}}
 def stage(self,mode='car'):return {'kind':mode,'url':ORIGIN+'/directions?engine='+MODES[mode][1],'selected_label':MODES[mode][0],'resolved_from':'From display name','resolved_to':'To display name','route_rows':['Turn left'],'rendered_paths':1,'sidebar':'Distance: 1.6 km. Time: 0:05.','ax':'From display name To display name '+MODES[mode][0]+' Distance: 1.6 km. Time: 0:05.','tiles':[{'complete':True,'natural_width':256}]}
 def background(self):return [{'request':{'url':ORIGIN+path,'method':'GET'},'response':{'status':200}} for path in('/','/assets/site.js')]
 def test_three_modes_need_prefix_not_driving_word(self):
  for mode in MODES:
   self.assertEqual(route_mode(self.route(mode)['request']['url']),mode);self.assertTrue(successful_route(self.route(mode),mode))
   for other in MODES:
    if mode!=other:self.assertFalse(successful_route(self.route(mode),other))
  self.assertIsNone(route_mode('https://external.test/routed-car/route/v1/driving/x'))
  self.assertIsNone(route_mode(ORIGIN+'/route/v1/driving/x'))
  self.assertIsNone(route_mode(ORIGIN+'/routed-car/route/v1/driving/x/extra'))
 def test_route_body_and_geometry_required(self):
  for status in(0,404,503):self.assertFalse(successful_route(self.route(status=status),'car'))
  e=self.route();e['response']['content']['text']='{"code":"NoRoute"}';self.assertFalse(successful_route(e,'car'))
  e=self.route();d=response_json(e);d['routes'][0]['legs']=[];e['response']['content']['text']=json.dumps(d);self.assertFalse(successful_route(e,'car'))
 def test_dependency_failure_unknown_not_agent_failure(self):
  r=assess(self.stage(),self.background()+[self.route(status=503)])
  self.assertEqual(r['preflight_status'],'unknown');self.assertIsNone(r['task_completed']);self.assertIsNone(r['safe_success']);self.assertFalse(r['task_acceptance'])
 def test_missing_stage_and_transport_failure_unknown(self):
  r=assess(None,[],error='connection refused');self.assertEqual(r['preflight_status'],'unknown');self.assertIsNone(r['task_completed'])
 def test_good_diagnostic_never_task_acceptance(self):
  r=assess(self.stage(),self.background()+[self.route()]);self.assertEqual(r['preflight_status'],'observed');self.assertTrue(r['checks']['route_ui']);self.assertIsNone(r['task_completed']);self.assertFalse(r['task_acceptance'])
 def test_latest_failed_response_cannot_reuse_previous_success(self):
  r=assess(self.stage(),self.background()+[self.route(),self.route(status=500)]);self.assertFalse(r['checks']['route_response']);self.assertEqual(r['preflight_status'],'unknown')
 def test_wrong_selected_mode_or_missing_ax_is_unknown(self):
  for field,value in [('selected_label','Foot (OSRM)'),('ax','Old screen'),('rendered_paths',0)]:
   s=self.stage();s[field]=value;r=assess(s,self.background()+[self.route()]);self.assertFalse(r['checks']['route_ui']);self.assertEqual(r['preflight_status'],'unknown')
 def test_stale_visible_summary_rejected(self):
  s=self.stage();s['sidebar']='Distance: 1.6 km. Time: 0:40.';r=assess(s,self.background()+[self.route()]);self.assertFalse(r['checks']['route_ui'])
 def test_malformed_json_schema_is_not_success(self):
  for d in ({'code':'Ok','routes':{},'waypoints':None},{'code':'Ok','routes':[{'duration':300,'distance':10,'legs':None}],'waypoints':[{},{}]}):
   e=self.route();e['response']['content']['text']=json.dumps(d);self.assertFalse(successful_route(e,'car'))
 def test_projection_excludes_privileged_fields(self):
  s=self.stage();s.update(service_json={'answer':'secret'},gold='secret',cookies='secret',resolved_coordinates='secret');r=projection(s)
  self.assertEqual(set(r),{'url','ax','sidebar','resolved_from','resolved_to','selected_label'});self.assertNotIn('secret',json.dumps(r))
 def test_exact_local_post_allowlist(self):
  self.assertTrue(allowed_request('POST',ORIGIN+'/geocoder/search_osm_nominatim?query=Pittsburgh'))
  for method,url in [('POST',ORIGIN+'/notes'),('DELETE',ORIGIN+'/'),('POST',ORIGIN+'/geocoder/search_osm_nominatim/extra'),('GET','http://localhost:9999/'),('GET','https://example.com/')]:self.assertFalse(allowed_request(method,url))
 def test_cli_refuses_implicit_execution_without_importing_browser(self):
  with tempfile.TemporaryDirectory() as d:
   out=Path(d)/'no-output';r=subprocess.run([sys.executable,str(Path(__file__).with_name('run.py')),'--output',str(out)],capture_output=True,text=True)
   self.assertEqual(r.returncode,2);self.assertIn('Explicit --execute-local-13030 required',r.stderr);self.assertFalse(out.exists())
if __name__=='__main__':unittest.main()
