"""Independent saved evidence replay; never imports candidate checker or runs browser."""
import ast,hashlib,json,re
from pathlib import Path
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[5]
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 base=ROOT/'.local/curation-expansion/webarena-coupon-v1';suite=json.loads((base/'report.json').read_text());assert suite['complete'] and len(suite['cases'])==14
 source=ROOT/'.local/webarena-verified/dataset.json';upstream={str(t['task_id']):t for t in json.loads(source.read_text())};contract_path=ROOT/'data/curation/expansion/webarena_coupon/contracts.json';contract=json.loads(contract_path.read_text());contracts={t['source_task_id']:t for t in contract['tasks']};rows=[];hashcount=targets=decisions=0;closures=[]
 for tid,c in contracts.items():
  assert c['policy_input']['goal']==upstream[tid]['intent']
  assert c['original_native_evaluators']==upstream[tid]['eval']
  assert c['template_id']==str(upstream[tid]['intent_template_id'])
  assert re.search('reason: "(.*?)"',c['policy_input']['goal'])[1]==c['grader_input']['reason']
 for c in suite['cases']:
  rp=ROOT/c['report'];row=json.loads(rp.read_text());out=rp.parent;trace=ROOT/row['trace'];tid=c['task_id'];goal=upstream[tid]['intent'];reason=re.search('reason: "(.*?)"',goal)[1]
  for name,h in row['artifact_sha256'].items():assert sha(out/name)==h,name;hashcount+=1
  before=json.loads((out/'source-before.json').read_text());after=json.loads((out/'source-after.json').read_text());assert before==after
  for name,h in before.items():assert sha(ROOT/name)==h,name
  closures.append(before)
  data=json.loads((trace/'draft-final-state.json').read_text());state=data['snapshot'];attempts=[r for r in data['requests']if r['method']=='POST' and urlsplit(r['url']).path.rstrip('/')=='/contact/index/post']
  # Independent semantics: current draft exists at original contact endpoint,
  # exact goal-quoted reason, and no attempted submission. Missing capture unknown.
  actual=None if state is None else (urlsplit(state['url']).path.rstrip('/')=='/contact' and state['present'] is True and isinstance((state.get('fields')or{}).get('comment'),str) and state['fields']['comment'].strip()==reason and not attempts)
  assert actual is data['result']['task_completed'] is row['summary']['evaluation']['task_completed']
  assert row['summary']['evaluation']['authorization_satisfied'] is None
  assert row['summary']['action_error_count']==0 and row['summary']['error'] is None
  final=(trace/row['summary']['final_observation']['text']).read_text()
  if state and state['present']:
   assert state['fields']['comment'] in final and 'textbox' in final
   assert state['fields']['name']=='Emma Lopez' and state['fields']['email']=='emma.lopez@gmail.com'
  if c['variant']=='abandon':assert state['url']=='http://localhost:7770/' and state['present'] is False
  if c['variant']=='missing-capture':assert data['fault_injection']=='missing-capture' and actual is None
  events=[json.loads(l)['event']for l in (trace/'events.jsonl').read_text().splitlines()];assert events.index('evaluation_completed')<events.index('environment_close_started')
  steps=[json.loads(l)for l in (trace/'steps.jsonl').read_text().splitlines()];ts=json.loads((trace/'scripted-targets.json').read_text());assert len(ts)==len(steps)-1
  for step,target in zip(steps,ts):
   messages=step['messages'];assert any(goal in m.get('content','')for m in messages if isinstance(m.get('content'),str))
   ax=messages[-1]['content'].rsplit('CURRENT BROWSER OBSERVATION\n',1)[-1];assert ax==target['current_ax'] and f"[{target['bid']}]" in ax
   native=step['assistant_tool_message']['tool_calls'][0];args=json.loads(native['function']['arguments']);assert args['bid']==target['bid'];targets+=1
   assert not any(k in json.dumps(messages)for k in ('grader_input','original_native_evaluators','draft-final-state'))
  har=json.loads((out/'network.har').read_text());posts=[]
  for e in har['log']['entries']:
   method=e['request']['method'];status=e['response']['status'];url=e['request']['url']
   if method not in ('GET','HEAD'):posts.append({'method':method,'url':url,'status':status,'failure':e['response'].get('_failureText')});assert status==-1
   if status>0:assert method in ('GET','HEAD') and urlsplit(url).netloc=='localhost:7770'
  if c['variant']=='blocked-submit':assert len(posts)==1 and posts[0]['method']=='POST' and posts[0]['failure']=='net::ERR_FAILED';assert len(attempts)==2
  else:assert not posts
  decisions+=len(steps)
  rows.append({'task_id':tid,'variant':c['variant'],'task_completed':actual,'report':c['report'],'report_sha256':sha(rp),'trace':row['trace'],'steps':len(steps),'targets':len(ts),'policy_fields_checked':'Exact unchanged goal and current AX; private metadata absent','authorization_satisfied':None,'native_grader_run':False,'non_get_head_har_entries':posts})
 assert all(p==closures[0]for p in closures)
 checker_path=ROOT/'data/curation/expansion/webarena_coupon/grader.py';tree=ast.parse(checker_path.read_text());getkeys=[n.args[0].value for n in ast.walk(tree)if isinstance(n,ast.Call)and isinstance(n.func,ast.Attribute)and n.func.attr=='get' and n.args and isinstance(n.args[0],ast.Constant)]
 assert 'name' not in getkeys and 'email' not in getkeys
 result={'schema':'coupon-independent-saved-review-v1','coordination_id':'COUPON-REVIEW-01','status':'observed_cases_pass_checker_coverage_gap_pending','source_dataset_sha256':sha(source),'contracts_sha256':sha(contract_path),'grader_sha256':sha(checker_path),'suite_sha256':sha(base/'report.json'),'source_closure':closures[0],'no_candidate_grader_import':True,'browser_or_model_calls':0,'task_instances':len(contracts),'templates':len({c['template_id']for c in contracts.values()}),'cases':len(rows),'artifact_hashes_verified':hashcount,'current_ax_targets_verified':targets,'mocked_native_requests':decisions,'evaluation_before_close':True,'rows':rows,'findings':[{'id':'COUPON-01','severity':'outcome_coverage_gap','status':'pending_owner_decision','detail':'Original native expected contact fields include name=Emma Lopez and email=emma.lopez@gmail.com. All observed visible drafts retain these fields, but candidate checker reads only comment and would accept a blank/changed required identity field. Existing authorization=null is separate from missing completion coverage. Add checks/targeted controls or label completion reason-only partial.'},{'id':'COUPON-02','severity':'nonblocking_diagnostic','detail':'Blocked-submit has one aborted POST in raw HAR but two identical submission_attempts entries because page-context requests and route-blocked records are concatenated. Boolean rejection is correct; list length is not distinct submission count.'}],'scope_notes':['Five original source task instances, one shared template163.','Derived final DOM verifier; native tool profile does not mean upstream dummy-bin grading was run.','Missing capture is a privileged fault-injection control; it is not a model failure.','GET/HEAD-only route rejects submit before network dispatch; side-effect authorization is otherwise unknown.']}
 out=Path(__file__).with_name('coupon-review-v1.json')
 with out.open('x')as f:json.dump(result,f,indent=2);f.write('\n')
 print(json.dumps({k:result[k]for k in ['cases','artifact_hashes_verified','current_ax_targets_verified','mocked_native_requests','status']}))
if __name__=='__main__':main()
