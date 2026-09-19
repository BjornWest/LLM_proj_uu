"""Saved original-comment diagnostic review; intentionally accepts no tasks."""
import argparse,ast,gzip,hashlib,json
from collections import Counter
from pathlib import Path
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[3]
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def review():
 indexpath=ROOT/'data/curation/expansion/webarena_comments/validation-index.json';index=read(indexpath);counts=Counter();cases=[]
 source={t['task_id']:t for t in read(ROOT/'.local/webarena-verified/dataset.json')}
 for item in index['cases']:
  reportpath=ROOT/item['report'];assert sha(reportpath)==item['report_sha256'];report=read(reportpath);directory=reportpath.parent;trace=Path(report['trace'])
  assert report['accepted'] is False and report['model_calls']==0 and report['source_unchanged']
  assert read(directory/'source-before.json')==read(directory/'source-after.json')==report['source_sha256']
  for name,digest in report['source_sha256'].items():assert sha(ROOT/name)==digest;counts['source_hashes']+=1
  assert set(report['artifact_sha256'])=={str(p.relative_to(directory))for p in directory.rglob('*')if p.is_file()}-{'report.json'}
  for name,digest in report['artifact_sha256'].items():assert sha(directory/name)==digest;counts['artifact_hashes']+=1
  contract=read(trace/'contract.json');assert contract['policy_input']['goal']==source[610]['intent'];expected=contract['grader_input']
  with gzip.open(trace/'baseline.json.gz','rt')as stream:baseline=json.load(stream)
  saved=read(trace/'comment-final-state.json');e=saved['evidence'];posts=e['posts'];comments=e['comments'];pages={r['id']:r for r in e['reads']}
  assert len(pages)==len(e['reads']) and set(pages)=={p['id']for p in posts}|{c['submission_id']for c in comments}
  assert all(p['id']not in baseline['submissions']for p in posts)
  assert all(c['id']not in baseline['comments']for c in comments)
  htmls=[]
  for pid,r in pages.items():
   htmlpath=trace/r['html'];assert sha(htmlpath)==r['html_sha256'];html=htmlpath.read_text();htmls.append(html);soup=BeautifulSoup(html,'html.parser')
   article=soup.select_one('article.submission');form=article.select_one('[data-vote-route-value="submission_vote"]')
   assert int(form['data-vote-id-value'])==pid==r['confirmed_post_id'] and r['status']==200
   fields={k:article.select_one(sel).get_text('\n',strip=True)for k,sel in [('title','.submission__title'),('author','.submission__submitter'),('forum','.submission__forum')]};assert fields==r['fields']
   parsed=[]
   for c in soup.select('article.comment'):
    parsed.append({'id':int(c['id'].split('_')[1]),'author':c.select_one('.comment__header a[href^="/user/"]').get_text(strip=True),'body':c.select_one('.comment__body').get_text('\n',strip=True)})
   assert parsed==r['comments']
  matched=[]
  for p in posts:
   fields=pages[p['id']]['fields'];assert (fields['title'],fields['author'],fields['forum'])==(p['title'],p['username'],p['forum_name'])
   if p['title']==expected['title']and p['username']==expected['author']and p['forum_id']==expected['forum_id']and p['visibility']=='visible'and p['moderated']is False:matched.append(p['id'])
  linked=[]
  for c in comments:
   matches=[x for x in pages[c['submission_id']]['comments']if x['id']==c['id']];assert len(matches)==1
   assert matches[0]['body']==c['body']and matches[0]['author']==c['username']
   if c['submission_id']in matched and c['parent_id']is None and c['username']==expected['author']and c['body']==expected['comment']and c['visibility']=='visible'and c['moderated']is False:linked.append(c['id'])
  structural=bool(matched and linked);whole=None if structural else False
  unauthorized=len(posts)>1 or len(comments)>1 or any(c['submission_id']not in matched for c in comments)or any(e['removed_baseline_ids'].values())
  auth=False if unauthorized else None
  result=saved['result'];assert result==report['derived_result'];assert result['structural_completion']is structural and result['task_completed']is whole and result['review_semantics']is None and result['authorization_satisfied']is auth
  evaluation=read(trace/'evaluation.json');assert evaluation==report['summary']['evaluation'];assert evaluation['task_completed']is whole and evaluation['authorization_satisfied']is auth
  errors=[]
  for line in (trace/'steps.jsonl').read_text().splitlines():
   step=json.loads(line);assert step['model_response']['offline_fixture']and step['messages']==step['model_request']['messages'];counts['scripted_requests']+=1
   text=(trace/step['observation']['text']).read_text();assert any(text in str(m.get('content',''))for m in step['messages'])
   assert all(h not in json.dumps(step['messages'])for h in htmls)
   if step.get('action_error'):errors.append({'step':step['step'],'error':step['action_error']})
   action=ast.parse(step['action'],mode='eval').body
   if action.func.id!='send_msg_to_user':
    kwargs={k.arg:ast.literal_eval(k.value)for k in action.keywords};bid=kwargs.get('bid',ast.literal_eval(action.args[0])if action.args else None);assert f'[{bid}]'in text;counts['AX_targets']+=1
  assert len(errors)==report['summary']['action_error_count']==item['scripted_action_error_count']
  events=[json.loads(line)['event']for line in (trace/'events.jsonl').read_text().splitlines()];assert events.index('evaluation_completed')<events.index('environment_close_started')
  native=read(directory/'native-grade.json');assert native==report['native_grade']
  cases.append({'variant':item['variant'],'report':item['report'],'report_sha256':sha(reportpath),'matched_new_post_ids':matched,'linked_new_comment_ids':linked,'new_comment_parents':[c['submission_id']for c in comments],'structural_completion':structural,'task_completed':whole,'authorization_satisfied':auth,'native_score':native['score'],'action_errors':errors})
 assert len(cases)==3
 return {'schema':'forum-comments-independent-diagnostic-review-v1','index_sha256':sha(indexpath),'reviewer_sha256':sha(Path(__file__)),'cases':cases,'checks':dict(counts),'accepted_ids':[],'held_ids':list(range(610,615)),'review_semantics':None,'model_calls':0,'new_browser_runs':0,'candidate_checker_imported':False,'training_eligible':False,'conclusion':'Wrong-parent native false positive reproduced in clean browser case. Structural positive does not establish unspecified user review semantics; positive and missing-comment warnings remain explicit.'}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 with a.output.open('x')as f:r=review();json.dump(r,f,indent=2);f.write('\n')
 print(json.dumps({k:v for k,v in r.items()if k!='cases'},indent=2))
