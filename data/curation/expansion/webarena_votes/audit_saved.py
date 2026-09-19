"""Post-hoc producer audit; no candidate checker import, no browser/model calls."""
from pathlib import Path
import json,hashlib
from html.parser import HTMLParser
ROOT=Path(__file__).resolve().parents[4];HERE=Path(__file__).parent
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
class Forms(HTMLParser):
 def __init__(self):super().__init__();self.rows=[]
 def handle_starttag(self,tag,attrs):
  d=dict(attrs)
  if tag=='form' and d.get('data-vote-route-value')=='submission_vote':self.rows.append({'id':int(d['data-vote-id-value']),'choice':int(d['data-vote-choice-value'])})
def main():
 contracts=json.loads((HERE/'contracts.json').read_text());original={t['task_id']:t for t in json.loads((ROOT/'.local/webarena-verified/dataset.json').read_text())}
 for t in contracts['tasks']:
  o=original[t['source_task_id']];assert t['policy_input']['goal']==o['intent'] and t['grader_input']['original_evaluators']==o['eval'] and t['template_id']==o['intent_template_id']
 selected=[]
 for tid in range(404,409):
  base=ROOT/'.local/curation-expansion'/('webarena-votes-v1'if tid<407 else 'webarena-votes-v1-remaining')
  selected.extend(base/f'{tid}-{v}/report.json'for v in ['positive','wrong'])
 selected.extend(ROOT/f'.local/curation-expansion/webarena-votes-v2-controls/407-{v}/report.json'for v in ['undo','neutral','missing-evidence'])
 rows=[];hashes=targets=decisions=0
 for rp in selected:
  r=json.loads(rp.read_text());assert r['diagnostic_passed'];out=rp.parent;trace=Path(r['trace']);c=next(t for t in contracts['tasks']if t['source_task_id']==r['task_id']);target=c['grader_input']['target_id']
  for name,h in r['artifact_sha256'].items():assert sha(out/name)==h,name;hashes+=1
  before=json.loads((out/'source-before.json').read_text());assert before==json.loads((out/'source-after.json').read_text())
  for name,h in before.items():assert sha(ROOT/name)==h,name
  saved=json.loads((trace/'vote-final-state.json').read_text());e=saved['evidence'];result=saved['result']
  if e is None:assert r['variant']=='missing-evidence' and result['task_completed']is None and result['source_target_upvoted']is None
  else:
   assert sha(trace/'privileged-final-forum.html')==e['html_sha256'];p=Forms();p.feed((trace/'privileged-final-forum.html').read_text());assert p.rows[0]['id']==target
   db=e['db'];assert db['ui_newest'][0]['id']==target;vote=db['vote'];assert len(vote)<=1;choice=0 if not vote else 1 if vote[0]['upvote']else-1
   if vote:assert vote[0]['username']=='MarvelsGrantMan136'
   assert p.rows[0]['choice']==choice=={'positive':1,'wrong':-1,'undo':0,'neutral':0}[r['variant']]
   agrees=db['target'][0]['timestamp']==db['timestamp_newest'][0]['timestamp'];assert agrees is(r['task_id']==407)
   assert result['task_completed']is((choice==1)if agrees else None);assert result['source_target_upvoted']is(choice==1)
  assert r['summary']['evaluation']['task_completed']is result['task_completed'];assert r['summary']['evaluation']['authorization_satisfied']is None
  assert r['summary']['action_error_count']==0 and r['summary']['error']is None
  events=[json.loads(l)['event']for l in(trace/'events.jsonl').read_text().splitlines()];assert events.index('evaluation_completed')<events.index('environment_close_started')
  steps=[json.loads(l)for l in(trace/'steps.jsonl').read_text().splitlines()];ts=json.loads((trace/'scripted-targets.json').read_text());assert len(ts)==len(steps)-1
  for step,t in zip(steps,ts):
   ax=step['messages'][-1]['content'].rsplit('CURRENT BROWSER OBSERVATION\n',1)[-1];assert ax==t['current_ax'] and f"[{t['bid']}]"in ax;args=json.loads(step['assistant_tool_message']['tool_calls'][0]['function']['arguments']);assert args['bid']==t['bid'];targets+=1
   assert not any(k in json.dumps(step['messages'])for k in ['timestamp_newest','grader_input','source_target_upvoted','original_evaluators'])
  d=json.loads((trace/'driver-evidence.json').read_text());assert int(next(x for x in d if x['label']=='browser_derived_newest')['data']['id'])==target
  if r['variant']=='undo':assert r['native_grade']['score']==0 and result['task_completed']is False and 'Retract upvote'in ts[-1]['current_ax']
  decisions+=len(steps)
  rows.append({'task_id':r['task_id'],'variant':r['variant'],'report':str(rp.relative_to(ROOT)),'report_sha256':sha(rp),'trace':str(trace.relative_to(ROOT))if trace.is_absolute()else str(trace),'native_score':r['native_grade']['score'],'task_completed':result['task_completed'],'source_target_upvoted':result['source_target_upvoted'],'action_errors':0,'steps':len(steps),'selected_driver':'run_v2.py'if 'v2-controls'in str(rp)else'run.py','source_manifest':str((out/'source-before.json').relative_to(ROOT)),'source_manifest_sha256':sha(out/'source-before.json')})
 warnings=[]
 for name in ['webarena-votes-v1/407-positive','webarena-votes-v1-remaining/407-undo']:
  p=ROOT/'.local/curation-expansion'/name/'report.json';r=json.loads(p.read_text());assert not r['diagnostic_passed'];warnings.append({'path':str(p.relative_to(ROOT)),'sha256':sha(p),'error':r['summary']['error'],'action_error_count':r['summary']['action_error_count'],'diagnostic_passed':False})
 v1=(HERE/'run.py').read_text();v2=(HERE/'run_v2.py').read_text();assert v2==v1.replace('New isolated native vote diagnostics','Version2 scripted undo-label correction; isolated native vote diagnostics').replace("if self.variant=='undo':yield self.act(first.get_by_role('button',name='Upvote',exact=True))","if self.variant=='undo':yield self.act(first.get_by_role('button',name='Retract upvote',exact=True))")
 assert(HERE/'suite_v2.py').read_text()==(HERE/'suite.py').read_text().replace("str(HERE/'run.py')","str(HERE/'run_v2.py')").replace("'webarena-vote-suite-v1'","'webarena-vote-suite-v2'")
 report={'schema':'webarena-votes-derived-validation-v1','status':'task407_ready_for_independent_review_four_original_tasks_held','requested_original_instances':5,'original_acceptance_candidates':[407],'held_original_instances':[404,405,406,408],'template_count':1,'selected_native_cases':13,'artifact_hashes_verified':hashes,'current_AX_targets_verified':targets,'mocked_native_requests':decisions,'evaluation_before_close':True,'candidate_checker_imported_for_replay':False,'rows':rows,'historical_failed_cases':warnings,'source_artifacts':{str(p.relative_to(ROOT)):sha(p)for p in [HERE/'contracts.json',HERE/'new-sort-source.json',HERE/'timestamp-source-evidence.json',HERE/'publication-visibility-evidence.json',HERE/'run.py',HERE/'run_v2.py',HERE/'suite.py',HERE/'suite_v2.py',HERE/'grader.py',HERE/'common.py']},'current_command':'Use suite_v2.py for new cohorts; whole-suite wrapper not rerun. Selected evidence is per-case v1 positive/wrong and corrected v2 controls, with exact separate source manifests.','offline_unit_tests':7,'model_calls':0,'training_eligible':False,'authorization_satisfied':None,'independent_review':False,'limitations':['Four original goals remain ambiguous; no goal rewriting or acceptance promotion.','Vote-state diagnostics do not count held tasks as original-task successes.','One navigation timeout and one obsolete-label driver failure are retained; no harness-timeout fix claimed.','Native evaluator correctly rejects undo in observed evidence, so no historical-vote false-positive claim.','Final vote checked through privileged authenticated GET and readonly DB; broad authorization remains unknown.']}
 with(HERE/'validation-index.json').open('x')as f:json.dump(report,f,indent=2);f.write('\n')
 print({k:report[k]for k in ['selected_native_cases','artifact_hashes_verified','current_AX_targets_verified','mocked_native_requests','original_acceptance_candidates']})
if __name__=='__main__':main()
