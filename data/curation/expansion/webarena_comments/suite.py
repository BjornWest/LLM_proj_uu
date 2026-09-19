"""Three bounded sequential cases on dedicated state; no cleanup of evidence rows."""
import argparse,json,os,signal,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4];HERE=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from data.curation.expansion.webarena_comments.common import inspect
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
container=inspect();results=[]
for variant in ['positive','wrong-parent','missing-comment']:
 output=a.output/variant
 with (a.output/(variant+'.log')).open('x')as log:
  proc=subprocess.Popen([sys.executable,str(HERE/'run.py'),'--variant',variant,'--output',str(output)],stdout=log,stderr=subprocess.STDOUT,start_new_session=True,env=dict(os.environ,CURATION_FROZEN_RUNTIME=str(ROOT/'.local/curation-expansion/frozen-runtime-v1')))
  try:rc=proc.wait(timeout=240)
  except subprocess.TimeoutExpired:
   os.killpg(proc.pid,signal.SIGTERM)
   try:proc.wait(timeout=10)
   except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
   rc=124
 row={'variant':variant,'returncode':rc,'report':str(output/'report.json')};results.append(row)
 result={'schema':'webarena-comments-structural-suite-v1','complete':len(results)==3,'passed':all(r['returncode']==0 for r in results),'cases':results,'container':container,'sequential_reason':'Same dedicated DB; each case captures all currently existing IDs and checks only new rows. Prior cases remain on the full site, with immutable evidence. No cross-case IID claim.','accepted_tasks':[],'review_semantics':None,'model_calls':0,'training_eligible':False}
 (a.output/'report.json').write_text(json.dumps(result,indent=2)+'\n');print(variant,rc,flush=True)
 if rc:raise SystemExit(rc)
