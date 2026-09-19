"""Bounded native core-tools-v3 authored rehearsal using MockTransport only."""
import argparse,faulthandler,hashlib,json,os,signal,sys
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[5];HERE=Path(__file__).parent
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
from data.curation.expansion.runtime_snapshot import activate,fingerprints
FROZEN=activate()
def hashes():
 files=[ROOT/'data/curation/expansion/runtime_snapshot.py',HERE.parent/'authored/solver.py']+(list((FROZEN/'intent_browser').glob('*.py'))+[FROZEN/'manifest.json'] if FROZEN else list((ROOT/'intent_browser').glob('*.py')))+[ROOT/'scripts/harness_suite_tasks.py',ROOT/'scripts/native_probe_budget.py',ROOT/'data/curation/expansion/webarena/run_bounded.py']+[HERE/n for n in ['native_v2.py','solver.py','grader_v2.py','contracts.json','verify_native_v2.py']]
 fixture=ROOT/'.local/tricky-full-v1';files += [fixture/'build.json',fixture/'catalog.json']+list((fixture/'dist').rglob('*'))
 return {str(p.relative_to(ROOT)):sha(p) for p in files if p.is_file()}
IMPORT_SOURCE=hashes()
from intent_browser.actions import make_action_set
from intent_browser.harness import native_tools_profile
from intent_browser.runner import run_episode
from scripts.harness_suite_tasks import scripted_backend
from data.curation.expansion.webarena.run_bounded import execute_case
from data.curation.expansion.tricky.authored02.native_v2 import AuthoredTask,Driver
if hashes()!=IMPORT_SOURCE:raise RuntimeError('Source changed while importing runtime')

def case(task_id,negative,output):
 before=hashes();assert before==IMPORT_SOURCE;output.mkdir(parents=True,exist_ok=False);(output/'source-before.json').write_text(json.dumps(before,indent=2));task=AuthoredTask(task_id);holder={};backend=scripted_backend(Driver(task,negative,holder));profile=native_tools_profile(parallel_tool_calls=None,compact_feedback=True,reasoning_replay='preserve');assert profile.name=='core-tools-v3'
 def factory(video):holder['env']=task.make_env(video,make_action_set().to_python_code);return holder['env']
 try:
  trace,result=run_episode(factory,backend,{'task':'tricky-project-authored-native','task_id':task_id,'case':'negative' if negative else 'positive','model':None,'model_calls':0,'transport':'httpx.MockTransport','training_eligible':False},output=output/'traces',max_steps=28,episode_task=task,harness_profile=profile,before_observation=lambda:None,terminal_response_instruction=task.data['policy_response_protocol'],observation_text_limit=48000)
  unchanged=before==hashes();ev=result['evaluation'];passed=unchanged and result['error'] is None and result['action_error_count']==0 and ev['task_completed'] is (not negative)
  report={'task_id':task_id,'template_id':task.contract['template_id'],'site':task.contract['site'],'case':'negative' if negative else 'positive','passed':passed,'source_unchanged':unchanged,'source_sha256':before,'trace':str(trace),'summary':result,'profile':'core-tools-v3','model_calls':0,'training_eligible':False,'files_sha256':{str(p.relative_to(trace)):sha(p) for p in trace.rglob('*') if p.is_file()}}
  (output/'report.json').write_text(json.dumps(report,indent=2));print(task_id,negative,passed,result['error'],flush=True);return passed
 finally:task.close();backend.client.close()

def main():
 faulthandler.register(signal.SIGUSR1,all_threads=True);p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--task',action='append');p.add_argument('--negative',action='store_true');p.add_argument('--child',action='store_true');p.add_argument('--not-after',required=False);a=p.parse_args();os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','')
 if a.child:raise SystemExit(0 if case(a.task[0],a.negative,a.output) else 1)
 a.output.mkdir(parents=True,exist_ok=False);tasks=a.task or [t['id'] for t in json.loads((HERE/'contracts.json').read_text())['tasks']];rows=[];executions=[];before=hashes();reason=None;report={'passed':False,'rows':rows,'executions':executions,'source_sha256':before,'planned_cases':len(tasks)*2}
 for task in tasks:
  for negative in [False,True]:
   if a.not_after and datetime.now(timezone.utc)>=datetime.fromisoformat(a.not_after):reason='explicit_run_deadline';break
   if hashes()!=before:reason='source_closure_changed';break
   label=task+('-negative' if negative else '-positive');out=a.output/label;command=[sys.executable,str(Path(__file__)),'--child','--task',task,'--output',str(out)]+(['--negative'] if negative else []);execution=execute_case(command,a.output/(label+'.log'),90);executions.append(execution)
   if (out/'report.json').exists():
    row=json.loads((out/'report.json').read_text());row['parent_closure_matches']=row['source_sha256']==before;row['passed']=row['passed'] and row['parent_closure_matches'];rows.append(row)
   report={'schema_version':1,'profile':'core-tools-v3','transport':'httpx.MockTransport','model_calls':0,'training_eligible':False,'independent_review':False,'passed':len(rows)==len(executions) and all(r['passed'] for r in rows),'planned_cases':len(tasks)*2,'completed_cases':len(rows),'stop_reason':reason,'source_sha256':before,'rows':rows,'executions':executions}
   (a.output/'report.json').write_text(json.dumps(report,indent=2));print(label,execution['returncode'],flush=True)
   if execution['timed_out'] or execution['returncode']!=0 or (rows and not rows[-1]['passed']):reason='case_failed_review_required';break
  if reason:break
 report.update(stop_reason=reason,complete=len(rows)==len(tasks)*2);(a.output/'report.json').write_text(json.dumps(report,indent=2))
 if reason or not report['passed']:raise SystemExit(1)
if __name__=='__main__':main()
