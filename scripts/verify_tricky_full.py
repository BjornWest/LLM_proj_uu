"""Scripted restored-site lifecycle checks. No model requests, no label promotion."""
import argparse,json,hashlib
from pathlib import Path
from intent_browser.actions import make_action_set
from intent_browser.runner import run_episode
from intent_browser.tricky import TrickyTask
from intent_browser.tricky_privacy import PrivacyTask
from intent_browser.tricky_membership import MembershipTask
from intent_browser.tricky_authorized import AuthorizedWarrantyTask
from scripts.verify_tricky import FixtureDriver
from scripts.verify_tricky_privacy import PrivacyDriver
from scripts.verify_tricky_membership import MembershipDriver
from scripts.verify_authorized_warranty import WarrantyDriver
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--build',type=Path,default=ROOT/'.local/tricky-full-v1');a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
 cases=[(TrickyTask,FixtureDriver,c,i,True,au) for c,i,au in [('clean',False,True),('allowed',True,True),('warranty',True,False)]]
 cases += [(AuthorizedWarrantyTask,WarrantyDriver,'keep',True,True,True),(AuthorizedWarrantyTask,WarrantyDriver,'remove',True,False,True)]
 cases += [(MembershipTask,MembershipDriver,c,i,tc,au) for c,i,tc,au in [('allowed',False,True,True),('allowed',True,True,True),('duo',True,False,False),('duplicate-individual',True,False,False)]]
 cases += [(PrivacyTask,PrivacyDriver,c,i,tc,au) for c,i,tc,au in [('clean',False,True,True),('allowed',True,True,True),('untouched-save',True,True,False),('both-cancelled',True,True,False)]]
 rows=[]
 for cls,drv,case,inj,complete,auth in cases:
  task=cls(build_dir=a.build,**({} if cls is AuthorizedWarrantyTask else {'condition':'one_selected_injection' if inj else 'no_added_injection'}));env={}
  def factory(video):env['env']=task.make_env(video,action_mapping=make_action_set().to_python_code,headless=True);return env['env']
  try:
   folder,result=run_episode(factory,drv(task,case,env),{'task':'complete-site-scripted-validation','driver':'privileged-scripted','model':None,'case':case},output=ROOT/'runs',max_steps=20,episode_task=task)
   v=result['evaluation'];errors=[s for s in (json.loads(x) for x in (folder/'steps.jsonl').read_text().splitlines()) if s.get('action_error')]
   passed=v['technical_error'] is None and (v['task_completed'],v['authorization_satisfied'])==(complete,auth) and not errors
   row={'task':cls.__name__,'case':case,'condition':task.condition,'trace':str(folder.relative_to(ROOT)),'evaluation':v,'passed':passed,'files':{str(f.relative_to(folder)):hashlib.sha256(f.read_bytes()).hexdigest() for f in folder.rglob('*') if f.is_file()}}
   rows.append(row);(a.output/'report.json').write_text(json.dumps({'rows':rows,'passed':all(r['passed'] for r in rows),'model_calls':0},indent=2));print(cls.__name__,case,passed,flush=True)
  finally:task.close()
 if not all(r['passed'] for r in rows):raise SystemExit(1)
if __name__=='__main__':main()
