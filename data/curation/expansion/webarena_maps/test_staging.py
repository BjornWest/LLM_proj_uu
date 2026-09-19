"""Offline boundary tests only; synthetic receipts are not browser evidence."""
import copy,hashlib,json,tempfile,unittest
from pathlib import Path
from .staging import contracts,contract,policy_projection,preflight_status,NotReady,MapsStagingTask
from .driver import source_plan,visible_time_to_hms,one_hour_from_rounded_minutes,effective_mode
ROOT=Path(__file__).resolve().parents[4]
class Boundaries(unittest.TestCase):
 def test_original_goals_and_private_source_preserved(self):
  source={r['task_id']:r for r in json.loads((ROOT/'.local/webarena-verified/dataset.json').read_text())}
  ts=contracts()['tasks'];self.assertEqual(len(ts),10);self.assertEqual(len({t['source_template_id']for t in ts}),10)
  for t in ts:
   self.assertEqual(policy_projection(t),{'goal':source[t['source_task_id']]['intent']})
   self.assertEqual(t['grader_input']['original_source_row'],source[t['source_task_id']])
 def test_policy_projection_does_not_leak(self):
  t=contract(70);t['grader_input']['secret_test_marker']='PRIVATE';self.assertNotIn('PRIVATE',json.dumps(policy_projection(t)))
 def test_goal_rewrite_rejected(self):
  t=contract(70);t['policy_input']['goal']='Changed'
  with self.assertRaises(ValueError):policy_projection(t)
 def test_no_receipt_not_ready(self):
  self.assertFalse(preflight_status(contract(70),{},ROOT)['site_preflight_sufficient'])
  with self.assertRaises(NotReady):MapsStagingTask(70,{},ROOT).prepare(None)
 def test_claimed_ready_without_artifacts_rejected(self):
  c=contract(70);r={'schema':'webarena-maps-site-preflight-v1','image':contracts()['image'],'dataset_sha256':contracts()['source_sha256'],'origin':'http://localhost:10000','source_inspection_only':False,'browser_preflight_executed':True,'checks':{g:{'passed':True}for g in c['required_preflight_gates']}}
  self.assertFalse(preflight_status(c,r,ROOT)['site_preflight_sufficient'])
 def test_hash_bound_synthetic_receipt_only_validates_gate(self):
  with tempfile.TemporaryDirectory()as d:
   p=Path(d)/'synthetic-unit-evidence.txt';p.write_text('Not a browser observation; validator test only.')
   c=contract(70);r={'schema':'webarena-maps-site-preflight-v1','image':contracts()['image'],'dataset_sha256':contracts()['source_sha256'],'origin':'http://localhost:10000','source_inspection_only':False,'browser_preflight_executed':True,'checks':{g:{'passed':True,'evidence':[{'path':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}]}for g in c['required_preflight_gates']}}
   result=preflight_status(c,r,d);self.assertTrue(result['site_preflight_sufficient']);self.assertFalse(result['task_accepted'])
   p.write_text('changed');self.assertFalse(preflight_status(c,r,d)['site_preflight_sufficient'])
 def test_source_plan_never_emits_answer(self):
  for t in contracts()['tasks']:
   plan=source_plan(t['source_task_id']);self.assertFalse(plan['browser_executed']);self.assertNotIn('send_msg_to_user',json.dumps(plan));self.assertNotIn('retrieved_data',json.dumps(plan))
 def test_visible_precision(self):
  self.assertEqual(visible_time_to_hms('0:07'),'00:07:00');self.assertEqual(visible_time_to_hms('5:47'),'05:47:00')
  self.assertIsNone(one_hour_from_rounded_minutes('1:00'));self.assertTrue(one_hour_from_rounded_minutes('0:59'));self.assertFalse(one_hour_from_rounded_minutes('1:01'))
 def test_driving_path_does_not_imply_car(self):
  self.assertEqual(effective_mode('http://localhost:10000/routed-foot/route/v1/driving/1,2;3,4'),'walking')
  self.assertEqual(effective_mode('http://localhost:10000/routed-bike/route/v1/driving/1,2;3,4'),'cycling')
  self.assertIsNone(effective_mode('http://localhost:10000/route/v1/driving/1,2;3,4'))
if __name__=='__main__':unittest.main()
