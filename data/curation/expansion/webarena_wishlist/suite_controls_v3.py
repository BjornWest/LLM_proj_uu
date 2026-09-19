"""Bounded sequential cases; controlled membership cleanup on the owned clone only."""
import argparse,json,os,signal,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4];HERE=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from data.curation.expansion.webarena_wishlist.common import *
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--tasks',default='465,466,467,468,469,516,517,518,519,520');p.add_argument('--variants',default='positive,wrong-product');p.add_argument('--continue-on-failure',action='store_true');a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
initial=json.loads((ROOT/'.local/curation-expansion/wishlist-setup-v1/baseline.json').read_text());container=inspect();results=[];cases=[(int(t),v)for t in a.tasks.split(',')for v in a.variants.split(',')]
for task,variant in cases:
 clear_to_empty(initial);output=a.output/f'{task}-{variant}'
 with (a.output/f'{task}-{variant}.log').open('x')as log:
  proc=subprocess.Popen([sys.executable,str(HERE/'run_controls_v3.py'),'--task',str(task),'--variant',variant,'--output',str(output)],stdout=log,stderr=subprocess.STDOUT,start_new_session=True,env=dict(os.environ,CURATION_FROZEN_RUNTIME=str(ROOT/'.local/curation-expansion/frozen-runtime-v1')))
  try:rc=proc.wait(timeout=240)
  except subprocess.TimeoutExpired:
   os.killpg(proc.pid,signal.SIGTERM)
   try:proc.wait(timeout=10)
   except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
   rc=124
 results.append({'task_id':task,'variant':variant,'returncode':rc,'report':str(output/'report.json')})
 result={'schema':'webarena-wishlist-controls-suite-v3','complete':len(results)==len(cases),'passed':all(r['returncode']==0 for r in results),'cases':results,'container':container,'sequential_reason':'Shared dedicated account. Remove only wishlist items/options between controlled scripts after their final evidence; prove empty original membership restored. No full database reset or arbitrary-model reset readiness claim.','model_calls':0,'training_eligible':False}
 (a.output/'report.json').write_text(json.dumps(result,indent=2)+'\n');print(task,variant,rc,flush=True)
 if rc and not a.continue_on_failure:raise SystemExit(rc)
