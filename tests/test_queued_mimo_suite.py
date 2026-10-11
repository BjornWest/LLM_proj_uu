"""Focused launch-gate controls; no browser, service or provider construction."""
import copy,json,runpy,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
M=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/queued_mimo_suite.py'))
class LaunchGate(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  self.s={'cases':[{'id':str(i)} for i in range(8)],'start_order':[str(i) for i in range(8)],'max_concurrent_episodes':3,'prewarm_count':1,'model':'xiaomi/mimo-v2.6-pro','output':'isolated','caller_commit':'exact'}
  self.s['driver']={'path':'fixed','sha256':'fixed'}
  self.rows=[]
  for c in self.s['cases']:
   p=self.root/(c['id']+'.json');p.write_text(json.dumps({'result':{'viewer_projection':{'task_completed':True}}}));self.rows.append({'case':c['id'],'result':M['pin'](p)})
  p=self.root/'ready.json';p.write_text(json.dumps({'status':'passed','driver':self.s['driver'],'cases':self.rows}));self.s['ready']=M['pin'](p)
  p=self.root/'review.json';p.write_text(json.dumps({'status':'approved','configuration_sha256':M['config_hash'](self.s)}));self.s['review']=M['pin'](p)
 def invoke(self,s):
  with patch.dict(M['check_release'].__globals__,source_guard=lambda s:None):M['check_release'](s)
 def test_valid_exact_eight(self):self.invoke(self.s)
 def test_cap_above_three_and_other_provider_rejected(self):
  for k,v in [('max_concurrent_episodes',4),('prewarm_count',2),('model','other/model')]:
   with self.subTest(k=k):
    s=copy.deepcopy(self.s);s[k]=v
    with self.assertRaises(ValueError):self.invoke(s)
 def test_changed_context_config_rejected(self):
  s=copy.deepcopy(self.s);s['max_input_tokens']=999999
  with self.assertRaises(ValueError):self.invoke(s)
 def test_private_runtime_socket_addition_preserves_authorized_configuration(self):
  s=copy.deepcopy(self.s);s.update(sockets={'0':'private.sock'},tokenizer_socket='private.tokens');self.invoke(s)
 def test_missing_or_false_accepted_verdict_rejected(self):
  p=self.root/'0.json';p.write_text(json.dumps({'result':{'viewer_projection':{'task_completed':False}}}))
  self.rows[0]['result']=M['pin'](p);ready=self.root/'ready.json';ready.write_text(json.dumps({'status':'passed','driver':self.s['driver'],'cases':self.rows}));self.s['ready']=M['pin'](ready)
  with self.assertRaises(ValueError):self.invoke(self.s)
class TimingChecks(unittest.TestCase):
 def test_zero_provider_stop_retains_unknown_first_dispatch(self):
  t={'environment_creation_monotonic':2,'environment_ready_monotonic':4,'activated_monotonic':8,'reset_calls':1}
  row=M['timing_record']('B01',t,1,True)
  self.assertIsNone(row['activation_to_first_policy_dispatch_s'])
  self.assertIsNone(row['process_to_first_policy_dispatch_s'])
  self.assertFalse(row['policy_dispatch_observed'])
  self.assertEqual(row['parked_ready_s'],4)
 def test_warm_and_cold_timings_use_observed_boundaries(self):
  t={'environment_creation_monotonic':2,'environment_ready_monotonic':4,'activated_monotonic':8,'first_policy_dispatch_monotonic':8.5,'reset_calls':1}
  row=M['timing_record']('B01',t,1,True)
  self.assertEqual(row['activation_to_first_policy_dispatch_s'],.5)
  self.assertEqual(row['process_to_ready_s'],3)
if __name__=='__main__':unittest.main()
