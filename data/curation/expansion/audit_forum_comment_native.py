"""Synthetic audit of original post-then-comment grading; no browser execution."""
import argparse, copy, hashlib, json
from pathlib import Path
from urllib.parse import urlencode
from webarena_verified.api import WebArenaVerified
from webarena_verified.types.config import WebArenaVerifiedConfig
ROOT=Path(__file__).resolve().parents[3]
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
 source=ROOT/'.local/webarena-verified/dataset.json';tasks={t['task_id']:t for t in json.loads(source.read_text())};origin='http://localhost:19089'
 api=WebArenaVerified(config=WebArenaVerifiedConfig(environments={'__REDDIT__':{'urls':[origin]}}))
 def entry(url,fields,referer,location):
  body=urlencode(fields)
  return {'startedDateTime':'2026-09-19T17:10:00.000Z','time':1,
   'request':{'method':'POST','url':origin+url,'httpVersion':'HTTP/1.1','cookies':[],
    'headers':[{'name':'Accept','value':'text/html'},{'name':'Referer','value':origin+referer},{'name':'Content-Type','value':'application/x-www-form-urlencoded'}],
    'queryString':[],'postData':{'mimeType':'application/x-www-form-urlencoded','text':body,'params':[{'name':k,'value':v}for k,v in fields.items()]},'headersSize':-1,'bodySize':len(body)},
   'response':{'status':302,'statusText':'Found','httpVersion':'HTTP/1.1','cookies':[],
    'headers':[{'name':'Location','value':origin+location}],'redirectURL':origin+location,'headersSize':-1,'bodySize':0,'content':{'size':0,'mimeType':'text/html','text':''}},
   'cache':{},'timings':{'send':0,'wait':1,'receive':0}}
 rows=[]
 for tid in range(610,615):
  task=tasks[tid];values=task['instantiation_dict'];slug={'610':'to-kill-a-mockingbird-by-harper-lee','611':'harry-potter','612':'big-little-lies','613':'love-story','614':'gone-with-the-wind'}[str(tid)]
  for linked in (True,False):
   post_id=123;comment_id=123 if linked else 456
   entries=[entry('/submit/books',{'submission[title]':values['book'],'submission[forum]':'10037'},'/submit/books',f'/f/books/{post_id}/{slug}'),
    entry(f'/f/books/{comment_id}/-/comment',{f'reply_to_submission_{comment_id}[comment]':values['content']},f'/f/books/{comment_id}/{slug}',f'/f/books/{comment_id}/{slug}')]
   har={'log':{'version':'1.2','creator':{'name':'explicit-synthetic-audit','version':'1'},'pages':[],'entries':entries}}
   h=a.output/f'{tid}-{linked}.har';h.write_text(json.dumps(har))
   grade=api.evaluate_task(task_id=tid,agent_response={'task_type':'mutate','status':'SUCCESS','retrieved_data':None},network_trace=h).model_dump(mode='json')
   rows.append({'task_id':tid,'comment_targets_created_post':linked,'synthetic_post_id':post_id,'synthetic_comment_post_id':comment_id,'har':str(h),'har_sha256':sha(h),'native_grade':grade})
 result={'schema':'webarena-post-comment-native-synthetic-v1','source_sha256':sha(source),'reviewer_sha256':sha(Path(__file__)),
  'scope':'Synthetic request records only; not actual site persistence, browser or model evidence.','cases':rows,'browser_runs':0,'model_calls':0,'accepted_tasks':[], 'training_eligible':False}
 (a.output/'report.json').write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps([{'task':r['task_id'],'linked':r['comment_targets_created_post'],'score':r['native_grade']['score']}for r in rows]))
if __name__=='__main__':main()
