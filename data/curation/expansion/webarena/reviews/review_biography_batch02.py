"""Independent saved-evidence audit. No browser calls or candidate-adapter import."""
import argparse,ast,base64,copy,hashlib,json,re
from collections import Counter
from pathlib import Path
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[5]
HISTORICAL=ROOT/'.local/curation-expansion/webarena-biography-batch02-v1/report.json'
DEFAULT_SUITE=ROOT/'.local/curation-expansion/webarena-biography-batch02-recovery-v1/report.json'
CONTRACT=ROOT/'data/curation/expansion/webarena_biography_batch02/contracts.json'
SOURCE=ROOT/'.local/webarena-verified/dataset.json'
ORIGIN='http://localhost:19089';USERNAME='MarvelsGrantMan136'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def rendered(entry):
 if entry is None:return None
 if entry['request']!={'method':'GET','url':ORIGIN+'/user/'+USERNAME}:return None
 if entry['response']['status']!=200:return None
 body=entry['response']['content']
 if 'html'not in body.get('mimeType','').lower()or 'text'not in body:return None
 text=body['text']
 if body.get('encoding')=='base64':text=base64.b64decode(text,validate=True).decode()
 nodes=BeautifulSoup(text,'html.parser').select('div.user-bio__biography')
 return ' '.join(nodes[0].get_text().split())if len(nodes)==1 else None

def review(SUITE=DEFAULT_SUITE):
 suite=read(SUITE);assert suite['complete']and suite['passed']and len(suite['rows'])==10
 contract=read(CONTRACT);source={t['task_id']:t for t in read(SOURCE)}
 assert sha(SOURCE)==contract['source_sha256'];contracts={t['source_task_id']:t for t in contract['tasks']}
 assert set(contracts)=={400,401,402,403}
 for n,t in contracts.items():
  assert t['template_id']==source[n]['intent_template_id']==6
  assert t['policy_input']['goal']==source[n]['intent']
  assert t['grader_input']['original_evaluators']==source[n]['eval']
  assert t['grader_input']['expected_biography']==re.search(r'"([^"]+)"',source[n]['intent'])[1]
  assert t['training_eligible']is False
 pins=read(ROOT/'.local/curation-expansion/frozen-runtime-v1/manifest.json')['source_sha256']
 setup_path=SUITE.parent/'setup.json'
 if not setup_path.exists():setup_path=HISTORICAL.parent/'setup.json'
 setup=read(setup_path);assert setup['model_calls']==0
 recovery_setup=setup
 parent_setup_path=ROOT/setup['parent_setup'];assert sha(parent_setup_path)==setup['parent_setup_sha256']
 setup=read(parent_setup_path);assert setup['container_id']==recovery_setup['container_id']
 wrapper=ROOT/'.local/curation-expansion/infrastructure/run-biography-recovery-v1.py';assert sha(wrapper)==recovery_setup['wrapper_sha256']
 history=read(HISTORICAL);assert len(history['rows'])==1 and not history['passed']
 previous=history['rows'][0]['result'];assert previous['summary']['action_error_count']==1 and not previous['passed']
 historical_warning={'suite':str(HISTORICAL.relative_to(ROOT)),'sha256':sha(HISTORICAL),'action_error_count':1,'clean_acceptance':False,'observed_completion':previous['summary']['evaluation']['task_completed']}
 counts=Counter();rows=[];artifacts={str(p.relative_to(ROOT)):sha(p)for p in [SUITE,CONTRACT,setup_path,parent_setup_path,wrapper,HISTORICAL]}
 historical_case_path=ROOT/history['rows'][0]['report'];assert read(historical_case_path)==previous
 artifacts[str(historical_case_path.relative_to(ROOT))]=sha(historical_case_path)
 for rel,pin in previous['artifact_sha256'].items():
  f=historical_case_path.parent/rel;assert sha(f)==pin;counts['historical_artifact_hashes']+=1;artifacts[str(f.relative_to(ROOT))]=pin
 for row in suite['rows']:
  case=row['result'];case_path=Path(row['report']);case_path=case_path if case_path.is_absolute()else ROOT/case_path
  assert read(case_path)==case and case['passed']and case['source_unchanged']
  artifacts[str(case_path.relative_to(ROOT))]=sha(case_path)
  directory=case_path.parent;trace=Path(case['trace']);trace=trace if trace.is_absolute()else ROOT/trace
  n=row['task_id'];variant=row['variant'];target=re.search(r'"([^"]+)"',source[n]['intent'])[1]
  assert read(trace/'contract.json')==contracts[n]
  assert case['summary']['error']is None and case['summary']['action_error_count']==0
  assert case['container']['Id']==setup['container_id']and case['container']['Image']==setup['image_id']and not case['container']['Mounts']
  assert read(trace/'metadata.json')['runtime']['source_sha256']=={Path(k).name:v for k,v in pins.items()}
  actual={str(p.relative_to(directory))for p in directory.rglob('*')if p.is_file()}-{'report.json'}
  assert actual==set(case['artifact_sha256'])
  for rel,pin in case['artifact_sha256'].items():
   p=directory/rel;assert sha(p)==pin;counts['artifact_hashes']+=1;artifacts[str(p.relative_to(ROOT))]=pin
  assert read(directory/'source-before.json')==case['source_sha256']
  for rel,pin in case['source_sha256'].items():assert sha(ROOT/rel)==pin;counts['current_source_hashes']+=1
  final=trace/'privileged-final-profile-read.json';entry=read(final)if final.exists()else None;value=rendered(entry)
  completed=None if value is None else value==' '.join(target.split())
  expected={'positive':True,'wrong':False,'correct-then-wrong':False,'missing-final-read':None}[variant]
  assert completed is expected
  saved=read(trace/'derived-final-evaluation.json');assert saved['final_read']==entry
  assert saved['result']['task_completed']is expected
  assert case['full_har_plus_independent_read_replay']['task_completed']is expected
  evaluation=read(trace/'evaluation.json');assert evaluation==case['summary']['evaluation']
  assert evaluation['task_completed']is expected and evaluation['authorization_satisfied']is None
  assert evaluation['safe_success']is(False if expected is False else None)
  assert case['authorization_satisfied']is None and case['training_eligible']is False and case['model_calls']==0
  requests=[];targets=[]
  for line in(trace/'steps.jsonl').read_text().splitlines():
   step=json.loads(line);assert step['model_response']['offline_fixture']and step['messages']==step['model_request']['messages']
   assert not step.get('action_error');counts['mock_requests']+=1
   selected=trace/step['observation']['text'];assert selected.name.startswith('decision-observation-')
   text=selected.read_text();messages=step['model_request']['messages'];current=messages[-1]['content'].rsplit('CURRENT BROWSER OBSERVATION\n',1)[1]
   assert text in current
   assert sha(selected)==step['observation_text_sha256']
   node=ast.parse(step['action'],mode='eval').body
   if node.func.id!='send_msg_to_user':
    values={k.arg:ast.literal_eval(k.value)for k in node.keywords};bid=values.get('bid',ast.literal_eval(node.args[0])if node.args else None)
    assert bid is not None and f'[{bid}]'in text and f'[{bid}]'in current
    targets.append({'step':step['step'],'bid':bid,'action':step['action'],'selected_observation':selected.name,'sha256':sha(selected)});counts['delivered_AX_targets']+=1
   serialized=json.dumps(messages)
   for private in ['project_derived_final_server_profile','derived-final-evaluation.json','original_evaluators','expected_biography','privileged-final-profile-read.json']:assert private not in serialized
   if entry:assert entry['response']['content']['text']not in serialized
  events=[json.loads(x)['event']for x in(trace/'events.jsonl').read_text().splitlines()]
  assert events.index('evaluation_completed')<events.index('environment_close_started')
  # Recompute history from actual browser HAR body, independently of the candidate checker.
  har=read(directory/'network.har');posts=[]
  from urllib.parse import parse_qs
  for e in har['log']['entries']:
   req=e['request']
   if req['method']=='POST'and req['url']==ORIGIN+'/user/'+USERNAME+'/edit_biography':
    data=req.get('postData',{});params={x['name']:x['value']for x in data.get('params',[])}
    if not params:params={k:v[-1]for k,v in parse_qs(data.get('text','')).items()}
    posts.append({'value':params.get('user_biography[biography]'),'status':e['response']['status']})
  assert len(posts)==(2 if variant=='correct-then-wrong'else 1)
  assert all(p['status']==302 for p in posts)
  if variant=='correct-then-wrong':assert posts[0]['value']==target and posts[1]['value']!=target and case['native_grade']['score']==1
  if variant=='missing-final-read':assert entry is None and not final.exists()and posts[0]['value']==target and case['native_grade']['score']==1
  rows.append({'task_id':n,'variant':variant,'trace':str(trace.relative_to(ROOT)),'recomputed_completion':completed,'observed_biography':value,'native_score':case['native_grade']['score'],'actual_posts':posts,'AX_targets':targets,'source_unchanged':True,'authorization_satisfied':None,'safe_success':evaluation['safe_success']})
 return {'schema':'independent-webarena-biography-batch02-review-v1','source_task_ids':[400,401,402,403],'distinct_source_templates':1,'passed':True,'setup_reference':str(setup_path.relative_to(ROOT)),'parent_setup_reference':str(parent_setup_path.relative_to(ROOT)),'recovery_wrapper':str(wrapper.relative_to(ROOT)),'historical_warning_preserved':historical_warning,'accepted_scope':'Scripted development task completion with project-derived final server-profile verifier; no model capability or broad safety acceptance.','cases':rows,'checks':dict(counts),'artifact_sha256':artifacts,'reviewer_sha256':sha(Path(__file__)),'model_calls':0,'new_browser_runs':0,'training_eligible':False,'limitations':['Same account and isolated full site; sequential known-biography restoration supports these controlled scripts, not arbitrary model reset.','Server-rendered read is not a complete account or transaction ledger.','Privileged scripted target value comes from a private contract matching the explicitly quoted user goal; not teacher/model reasoning evidence.','Only one shared-template overwrite and one missing-read browser case; other targets get positive/wrong pairs.','In-flight mutation completion races and transport-failed final reads are not covered by these10cases.']}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--suite',type=Path,default=DEFAULT_SUITE);args=p.parse_args();result=review(args.suite.resolve())
 with args.output.open('x')as f:json.dump(result,f,indent=2);f.write('\n')
 print(json.dumps({'passed':result['passed'],'checks':result['checks']}))
