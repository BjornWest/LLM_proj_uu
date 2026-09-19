"""Sequential owned-account vote rehearsals; original snapshot target reset per case."""
import argparse,json,os,subprocess,sys,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4];HERE=Path(__file__).parent;sys.path.insert(0,str(ROOT))
from data.curation.expansion.webarena_votes.common import *

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False);old=inspect()
 command('docker','rm','-f',NAME);command('docker','run','-d','--pull','never','--name',NAME,'--label','intent.owner=curation-biography','--label','intent.reset-scope=isolated-disposable','-p','127.0.0.1:19099:80','-p','127.0.0.1:19098:8877','-e','WA_ENV_CTRL_EXTERNAL_SITE_URL='+ORIGIN,'--memory','2g','--cpus','2',IMAGE)
 for _ in range(60):
  try:sql('SELECT 1');command('docker','exec',NAME,'env-ctrl','init','--base-url',ORIGIN);break
  except subprocess.CalledProcessError:time.sleep(1)
 else:raise RuntimeError('Owned server not ready')
 contracts=json.loads((HERE/'contracts.json').read_text());baselines={str(t['source_task_id']):db_state(t['grader_input']['target_id'])for t in contracts['tasks']};assert all(not d['vote']for d in baselines.values())
 warm=[]
 for path in ['/','/forums']+['/f/'+t['scripted_navigation']['forum_label']+'/new'for t in contracts['tasks']]:
  r=urllib.request.urlopen(urllib.request.Request(ORIGIN+path,headers={'X-Postmill-Auto-Login':USER+':test1234'}),timeout=60);assert r.status==200;warm.append({'url':r.url,'status':r.status})
 (a.output/'setup.json').write_text(json.dumps({'image':IMAGE,'previous_owned_container':old,'new_owned_container':inspect(),'baselines':baselines,'warm_gets':warm,'reset_scope':'Fresh original owned container, then exact initial target net_score and absent account vote restored before each sequential case. No other site/container touched.'},indent=2))
 keys=[(tid,var)for tid in range(404,409)for var in ['positive','wrong']]+[(407,var)for var in ['undo','neutral','missing-evidence']];records=[]
 env=dict(os.environ,CURATION_FROZEN_RUNTIME=str(ROOT/'.local/curation-expansion/frozen-runtime-v1'))
 for tid,var in keys:
  original=baselines[str(tid)]['target'][0];target=original['id'];score=original['net_score']
  sql(f"BEGIN;DELETE FROM submission_votes WHERE submission_id={target} AND user_id=(SELECT id FROM users WHERE username='{USER}');UPDATE submissions SET net_score={score} WHERE id={target};COMMIT;")
  current=db_state(target);assert current['vote']==[] and current['target']==baselines[str(tid)]['target']
  out=a.output/f'{tid}-{var}'
  with (a.output/f'{tid}-{var}.log').open('x')as log:
   try:rc=subprocess.run([sys.executable,str(HERE/'run.py'),'--task',str(tid),'--variant',var,'--output',str(out)],stdout=log,stderr=subprocess.STDOUT,env=env,timeout=240).returncode
   except subprocess.TimeoutExpired:rc=124
  record={'task_id':tid,'variant':var,'returncode':rc,'report':str(out/'report.json')}
  if (out/'report.json').exists():record['result']=json.loads((out/'report.json').read_text())
  records.append(record);(a.output/'report.json').write_text(json.dumps({'schema':'webarena-vote-suite-v1','cases':records,'complete':len(records)==len(keys),'diagnostics_passed':all(r['returncode']==0 for r in records),'model_calls':0,'training_eligible':False},indent=2));print(tid,var,rc,flush=True)
  if rc:raise SystemExit(rc)
if __name__=='__main__':main()
