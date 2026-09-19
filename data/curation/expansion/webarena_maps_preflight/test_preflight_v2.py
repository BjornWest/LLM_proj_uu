import inspect,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from .evidence_v2 import assess
from .parallel import run_cases
from .test_preflight import PreflightTests
class RevisionTests(unittest.TestCase):
 def test_native_action_error_without_fatal_error_unknown(self):
  sample=PreflightTests();result=assess(sample.stage(),sample.background()+[sample.route()],error=None,action_error_count=1)
  self.assertEqual(result['preflight_status'],'unknown');self.assertIn({'native_action_errors':1},result['dependency_errors']);self.assertIsNone(result['task_completed']);self.assertIsNone(result['safe_success'])
 def test_zero_action_errors_keeps_observed(self):
  sample=PreflightTests();self.assertEqual(assess(sample.stage(),sample.background()+[sample.route()],action_error_count=0)['preflight_status'],'observed')
 def test_missing_error_count_unknown(self):
  sample=PreflightTests();self.assertEqual(assess(sample.stage(),sample.background()+[sample.route()],action_error_count=None)['preflight_status'],'unknown')
 def test_parallel_real_subprocesses_separate_outputs(self):
  with tempfile.TemporaryDirectory()as d:
   root=Path(d)/'workers'
   code='import os,json,sys,time;from pathlib import Path;p=Path(sys.argv[1]);p.mkdir();t=time.monotonic();time.sleep(.2);(p/"report.json").write_text(json.dumps({"pid":os.getpid(),"start":t,"end":time.monotonic()}))'
   rows=run_cases(['a','b','c'],2,root,lambda c,p:[sys.executable,'-c',code,str(p)])
   self.assertTrue(all(r['error']is None for r in rows));self.assertEqual(len({r['report']['pid']for r in rows}),3)
   self.assertTrue(all(r['report']['pid']!=os.getpid()for r in rows));self.assertEqual(len({r['report_path']for r in rows}),3)
   intervals=[r['report']for r in rows];events=sorted([(r['start'],1)for r in intervals]+[(r['end'],-1)for r in intervals]);active=peak=0
   for _,delta in events:active+=delta;peak=max(peak,active)
   self.assertEqual(peak,2)
 def test_child_failure_retained(self):
  with tempfile.TemporaryDirectory()as d:
   rows=run_cases(['bad'],2,Path(d)/'workers',lambda c,p:[sys.executable,'-c','raise RuntimeError("offline child failed")'])
   self.assertIsNotNone(rows[0]['error']);self.assertIsNone(rows[0]['report']);self.assertEqual(rows[0]['returncode'],1)
 def test_timeout_unknown_and_process_group_cleanup(self):
  with tempfile.TemporaryDirectory()as d:
   rows=run_cases(['slow'],2,Path(d)/'workers',lambda c,p:[sys.executable,'-c','import time;time.sleep(10)'],timeout=.05)
   self.assertIn('timeout',rows[0]['error']);self.assertIsNone(rows[0]['report']);self.assertIsNotNone(rows[0]['returncode'])
 def test_worker_bound_and_duplicate_rejection(self):
  for workers in(0,5,True):
   with self.assertRaises(ValueError):run_cases(['a'],workers,'unused',None)
  with self.assertRaises(ValueError):run_cases(['a','a'],2,'unused',None)
  with self.assertRaises(ValueError):run_cases(['../escape'],2,'unused',None)
 def test_v2_cli_default_parallel_and_guard(self):
  script=Path(__file__).with_name('run_v2.py');text=script.read_text();self.assertIn("default=2",text);self.assertIn("action_error_count=summary.get('action_error_count')",text)
  with tempfile.TemporaryDirectory()as d:
   out=Path(d)/'absent';proc=subprocess.run([sys.executable,str(script),'--output',str(out)],capture_output=True,text=True)
   self.assertEqual(proc.returncode,2);self.assertIn('Explicit --execute-local-13030 required',proc.stderr);self.assertFalse(out.exists())
if __name__=='__main__':unittest.main()
