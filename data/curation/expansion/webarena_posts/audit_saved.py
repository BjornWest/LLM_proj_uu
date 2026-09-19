"""Saved artifact producer audit; no candidate checker import or browser calls."""
import json,gzip,hashlib
from pathlib import Path
from bs4 import BeautifulSoup
ROOT=Path.cwd();HERE=ROOT/'data/curation/expansion/webarena_posts';OUT=ROOT/'.local/curation-expansion/webarena-posts-selected-v3'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 suite={'cases': []}
 for directory in ['webarena-posts-main-v4','webarena-posts-keyboard-probe-v5','webarena-posts-remaining-v5','webarena-posts-controls-v6','webarena-posts-duplicate-v7']:
  cohort=json.loads((ROOT/'.local/curation-expansion'/directory/'report.json').read_text())
  if directory in ['webarena-posts-keyboard-probe-v5','webarena-posts-controls-v6','webarena-posts-duplicate-v7']:assert cohort['complete'] and cohort['passed']
  suite['cases'].extend(c for c in cohort['cases']if c['returncode']==0 and not(directory=='webarena-posts-controls-v6'and c['variant']=='duplicate'))
 assert len(suite['cases'])==34
 contracts=json.loads((HERE/'contracts.json').read_text());original={t['task_id']:t for t in json.loads((ROOT/'.local/webarena-verified/dataset.json').read_text())};records=[];hashes=targets=decisions=0
 for task in contracts['tasks']:
  raw=original[task['source_task_id']];assert task['policy_input']['goal']==raw['intent'] and task['original_source']==raw
 for entry in suite['cases']:
  rp=Path(entry['report']);r=json.loads(rp.read_text());trace=Path(r['trace']);out=rp.parent;assert r['passed']
  for name,digest in r['artifact_sha256'].items():assert sha(out/name)==digest,name;hashes+=1
  before=json.loads((out/'source-before.json').read_text());assert before==json.loads((out/'source-after.json').read_text())
  for name,digest in before.items():assert sha(ROOT/name)==digest,name
  task=next(t for t in contracts['tasks']if t['source_task_id']==r['task_id']);expected=task['grader_input'];saved=json.loads((trace/'post-final-state.json').read_text());e=saved['evidence'];v=saved['result']
  if e is None:
   assert r['variant']=='missing-evidence' and v['task_completed'] is None and v['authorization_satisfied'] is None
  else:
   assert sha(trace/e['baseline_ids_file'])==e['baseline_ids_sha256']
   with gzip.open(trace/e['baseline_ids_file'],'rt')as stream:baseline=set(json.load(stream))
   posts=e['posts'];assert len(posts)==len(e['reads'])
   for row,read in zip(posts,e['reads']):
    assert row['id'] not in baseline and row['username']=='MarvelsGrantMan136'
    assert read['id']==row['id'] and read['status']==200 and sha(trace/read['html'])==read['html_sha256']
    soup=BeautifulSoup((trace/read['html']).read_text(),'html.parser');post=soup.select_one('article.submission');assert int(post.select_one('form[data-vote-route-value="submission_vote"]')['data-vote-id-value'])==row['id']
    for key,selector,field in [('title','.submission__title','title'),('author','.submission__submitter','username'),('forum','.submission__forum','forum_name')]:assert post.select_one(selector).get_text('\n',strip=True)==row[field]==read['fields'][key]
   good=any(row['username']==expected['author'] and row['forum_id']==expected['forum_id'] and row['title']==expected['title'] and row['visibility']=='visible' and row['moderated'] is False and (expected['body'] is None or row['body']==expected['body'])for row in posts)
   assert v['task_completed'] is good
   assert v['authorization_satisfied'] is (False if len(posts)>1 else None)
  assert r['summary']['evaluation']['task_completed'] is v['task_completed'] and r['summary']['evaluation']['authorization_satisfied'] is v['authorization_satisfied']
  assert r['summary']['action_error_count']==0 and r['summary']['error'] is None
  events=[json.loads(l)['event']for l in(trace/'events.jsonl').read_text().splitlines()];assert events.index('evaluation_completed')<events.index('environment_close_started')
  steps=[json.loads(l)for l in(trace/'steps.jsonl').read_text().splitlines()];chosen=json.loads((trace/'scripted-targets.json').read_text());assert len(chosen)==len(steps)-1
  for step,target in zip(steps,chosen):
   assert step['model_request']['messages']==step['messages'];ax=step['messages'][-1]['content'].rsplit('CURRENT BROWSER OBSERVATION\n',1)[-1];assert ax==target['current_ax'] and '['+target['bid']+']' in ax
   call=step['assistant_tool_message']['tool_calls'][0]['function'];assert json.loads(call['arguments'])['bid']==target['bid'];assert step['model_request']['model']=='scripted-suite';targets+=1
   assert not any(k in json.dumps(step['messages'])for k in ['grader_input','post-baseline-ids','baseline_ids_file'])
  decisions+=len(steps);records.append({'task_id':r['task_id'],'variant':r['variant'],'report':str(rp.relative_to(ROOT))if rp.is_absolute()else str(rp),'report_sha256':sha(rp),'trace':str(trace.relative_to(ROOT))if trace.is_absolute()else str(trace),'source_manifest':str((out/'source-before.json').relative_to(ROOT)),'source_manifest_sha256':sha(out/'source-before.json'),'task_completed':v['task_completed'],'authorization_satisfied':v['authorization_satisfied'],'native_score':r['native_grade']['score'],'steps':len(steps),'action_errors':0,'selected_driver':'run_v4.py'if 'main-v4'in str(rp)else 'run_v6.py'if 'controls-v6'in str(rp)else 'run_v7.py'if 'duplicate-v7'in str(rp)else 'run_v5.py'})
 report={'schema':'webarena-posts-producer-audit-v2','status':'ready_for_independent_review','requested_original_instances':15,'templates':3,'selected_cases':len(records),'artifact_hashes_verified':hashes,'current_ax_targets_verified':targets,'mocked_native_requests':decisions,'records':records,'candidate_checker_imported':False,'model_calls':0,'new_browser_calls':0,'training_eligible':False,'evaluation_before_close':True,'audit_source_sha256':sha(__file__)}
 with(OUT/'audit-report.json').open('x')as stream:json.dump(report,stream,indent=2);stream.write('\n')
 print({k:report[k]for k in ['selected_cases','artifact_hashes_verified','current_ax_targets_verified','mocked_native_requests']})
if __name__=='__main__':main()
