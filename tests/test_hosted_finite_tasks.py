"""Finite task authorization and complete-request limits without providers."""
from copy import deepcopy
from pathlib import Path
import runpy,tempfile,json,unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
subjects=runpy.run_path(str(ROOT/'tests/test_openrouter_qwen_suite.py'))
hosted,caller=subjects['hosted'],subjects['caller']

class FiniteTaskTests(unittest.TestCase):
 def spec(self):
  s=subjects['HostedSourceAdmissionTests']().spec()
  s.update(hosted_limit_profile='finite-task-limits-v1',max_steps=40,max_input_tokens=96000)
  s['cases'][0].update(max_steps=30,max_input_tokens=64000)
  return s
 def test_finite_limits_require_explicit_profile_and_per_case_bounds(self):
  s=self.spec();hosted.validate_limits(s)
  missing=deepcopy(s);del missing['hosted_limit_profile']
  with self.assertRaises(ValueError):hosted.validate_limits(missing)
  for key,value in [('max_steps',None),('max_steps',True),('max_input_tokens',150001),('episode_timeout',10),('hosted_limit_profile','typo')]:
   with self.subTest(key=key,value=value),self.assertRaises(ValueError):hosted.validate_limits({**s,key:value})
  for key,value in [('max_steps',None),('max_steps',41),('max_steps',True),('max_input_tokens',96001),('max_input_tokens',True)]:
   c={**s['cases'][0],key:value}
   with self.subTest(case=key,value=value),self.assertRaises(ValueError):hosted.validate_limits({**s,'cases':[c]})
 def test_policy_and_formatter_hard_limit_is_case_specific(self):
  helper=subjects['HostedAdmissionTests']()
  for limit in (64000,96000):
   for count in (limit,limit+1):
    b,seen,_,_=helper.backend(count);b.input_limit=limit
    try:
     if count==limit:b.complete([]);self.assertEqual(len(seen),1)
     else:
      with self.assertRaisesRegex(ValueError,str(limit)):b.complete([])
      self.assertEqual(seen,[])
    finally:b.close()
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'extraction/schema.json';path.parent.mkdir();path.write_text('{"type":"object"}')
   b,seen,_,_=helper.backend(63960,phase='formatter',directory=Path(tmp)/'transport');b.input_limit=64000
   try:
    with self.assertRaisesRegex(ValueError,'64000'):b.complete([])
    self.assertEqual(seen,[])
   finally:b.close()
 def test_once_only_authorization_binds_prose_recipe_and_limits(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);prepared=p/'prepared';(prepared/'recipe').mkdir(parents=True)
   for f in [prepared/'recipe/manifest.json',prepared/'prepared-instance.json']:f.write_text('{}')
   s=self.spec();c=s['cases'][0];c.update(family='catalog_statistics',public_request='Count',recipe_manifest=caller.pin(prepared/'recipe/manifest.json'),prepared_receipt=caller.pin(prepared/'prepared-instance.json'))
   s.update(start_order=[c['id']],max_concurrent_episodes=1,prewarm_count=0,canary_task_ids=['B02'],hosted_readiness={'path':str(p/'readiness'),'sha256':'not-used'})
   request={'cases':[{'id':'B02','family':c['family'],'public_request':'Count','prepared':str(prepared),'manifest_sha256':c['recipe_manifest']['sha256'],'prepared_receipt_sha256':c['prepared_receipt']['sha256'],'maximum_complete_input_tokens':64000,'max_steps':30,'max_output_tokens':16384}], 'policy_and_formatter_model':hosted.MODEL,'concurrency':1,'request_timeout_seconds':180}
   (p/'request.json').write_text(json.dumps(request))
   auth={'schema':'hosted-finite-task-authorization-v1','request':caller.pin(p/'request.json'),'case_ids':[c['id']],'dispatch_authorized':True,'automatic_retries':False,'policy_model':hosted.MODEL,'formatter_model':hosted.MODEL,'max_active_combined':1,'prewarm_count':0}
   s['authorization']=caller.pin(p/'request.json')
   real_checked=caller.checked
   def checked(row):
    if row==s['hosted_readiness']:raise RuntimeError('readiness-gate-reached')
    return real_checked(row)
   with patch.object(caller,'hosted_runtime',return_value=vars(hosted)),patch.object(caller,'hosted_authorization',return_value=auth),patch.object(caller,'hosted_prior_specs',return_value={}),patch.object(caller,'checked',side_effect=checked):
    with self.assertRaisesRegex(RuntimeError,'readiness-gate-reached'):caller.check_hosted_release(s)
    for key,value in [('max_steps',31),('max_input_tokens',64001),('public_request','other'),('family','feature_offer')]:
     bad=deepcopy(s);bad['cases'][0][key]=value
     with self.subTest(key=key),self.assertRaises(ValueError):caller.check_hosted_release(bad)
    with patch.object(caller,'hosted_prior_specs',return_value={'previous':{}}):
     with self.assertRaisesRegex(ValueError,'automatic repeat'):caller.check_hosted_release(s)
    auth['automatic_retries']=True
    with self.assertRaisesRegex(ValueError,'once-only'):caller.check_hosted_release(s)

 def test_independent_native_acceptance_preserves_producer_and_rejects_cross_case(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);trace=p/'runs/trace';trace.mkdir(parents=True);prepared=p/'prepared';prepared.mkdir()
   c={'id':'qwen-new','argument':str(prepared),'root':'/frozen-native','public_request':'Count','recipe_manifest':{'path':'recipe','sha256':'hash'},'prepared_receipt':{'path':'receipt','sha256':'hash'}}
   def write(name,value):
    path=p/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value));return caller.pin(path)
   row={'case':c['id'],'recipe_manifest':c['recipe_manifest'],'prepared_receipt':c['prepared_receipt'],'native_source_root':c['root'],
    'control':write('control.json',{'status':'passed','expected_verdict':True,'external_provider_requests':0,'instance':{'prepared':str(prepared)},'trace':str(trace)}),
    'result':write('result.json',{'status':'graded_and_projected','trace':str(trace),'native_grade':{'structured_claims_correct':True}}),
    'canonical':write('runs/trace/evaluation.json',{'task_completed':True,'technical_error':None}),
    'metadata':write('runs/trace/metadata.json',{'tags':['scripted']}),
    'public_task':write('runs/trace/policy-task.json',{'user_message':'Count'}),
    'HTTP':write('HTTP.json',{'derived_evaluation':{'binding_status':'verified','structured_claims_correct':True}}),
    'producer':write('producer.json',{'actual_source':'independent-native-runner'})}
   caller.verify_finite_ready_case({},c,row)
   for key,value in [('case','other'),('native_source_root','/different'),('recipe_manifest',{'path':'other','sha256':'different'})]:
    with self.subTest(key=key),self.assertRaises(ValueError):caller.verify_finite_ready_case({},c,{**row,key:value})
   for key,name,value in [('canonical','false.json',{'task_completed':False,'technical_error':None}),('public_task','task.json',{'user_message':'other'}),('HTTP','wrong-HTTP.json',{'derived_evaluation':{'binding_status':'verified','structured_claims_correct':False}})]:
    with self.subTest(key=key),self.assertRaises(ValueError):caller.verify_finite_ready_case({},c,{**row,key:write(name,value)})

if __name__=='__main__':unittest.main()
