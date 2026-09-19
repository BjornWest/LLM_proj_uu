"""Bounded independent saved-evidence review. No candidate imports or live access."""
from pathlib import Path
import hashlib,json,re
from urllib.parse import urlsplit,unquote,parse_qs
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[5]
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
load=lambda p:json.loads(Path(p).read_text())
source=next(t for t in load(ROOT/'.local/webarena-verified/dataset.json') if t['task_id']==516)
records=[];hashes=0;requests=0;sourcepins=0
for cohort,expected in [('wishlist-probe-v1',False),('wishlist-session-probe-v2',True)]:
 base=ROOT/'.local/curation-expansion'/cohort/'516-positive';report=load(base/'report.json');trace=ROOT/report['trace']
 for name,pin in report['artifact_sha256'].items():assert sha(base/name)==pin,name;hashes+=1
 for name,pin in report['source_sha256'].items():assert sha(ROOT/name)==pin,name;sourcepins+=1
 c=load(trace/'contract.json');initial=load(trace/'initial-state.json');meta=load(trace/'metadata.json');steps=[json.loads(x)for x in (trace/'steps.jsonl').read_text().splitlines()]
 assert c['policy_input']['goal']==source['intent']==meta['goal']==initial['resolved_goal']
 original_url=source['start_urls'][0].replace('__SHOPPING__','http://localhost:17770');assert initial['task_state']['url']==original_url
 assert meta['max_steps']==24 and meta['observation_text_limit']==48000 and meta['harness_profile']['name']=='core-tools-v3'
 targets=load(trace/'scripted-targets.json');assert len(targets)==1 and len(steps)==2
 for row in steps:
  req=row['model_request'];assert req['messages']==row['messages'];requests+=1
  users=[x['content']for x in req['messages'] if x['role']=='user'];assert users[0].split('\n\nCURRENT BROWSER OBSERVATION\n')[0]=='USER GOAL: '+source['intent']
  if row['step']==0:
   obs=(trace/row['observation']['text']).read_text();assert any(obs in u for u in users)
  assert row['action_error'] in (None,'')
 target=targets[0];first=steps[0];assert target['current_ax']==(trace/first['observation']['text']).read_text();assert f"[{target['bid']}]" in target['current_ax'];assert re.search(r'\['+target['bid']+r"\] link 'Add to Wish List'",target['current_ax']);assert target['bid'] in first['action']
 assert all('privileged-session-setup' not in json.dumps(x['model_request']) for x in steps)
 evidence=load(trace/'wishlist-final-state.json')['evidence'];baseline=load(trace/'baseline.json');assert baseline['items']==[];db=evidence['database'];assert db['owner']==baseline['owner'] and db['wishlist']==baseline['wishlist'] and db['owner']['email']=='emma.lopez@gmail.com'
 rendered=BeautifulSoup((trace/'privileged-wishlist.html').read_text(),'html.parser');items=[]
 for el in rendered.select('.products-grid.wishlist li.product-item'):
  items.append({'id':int(el['id'].removeprefix('item_')),'name':el.select_one('.product-item-name').get_text(' ',strip=True),'qty':el.select_one('input.qty')['value']})
 assert {x['id']for x in items}=={x['wishlist_item_id']for x in db['items']}
 matching=[x for x in db['items'] if x['product_id']==104497 and float(x['qty'])>0];assert bool(matching)is expected
 for x in matching:assert any(y['id']==x['wishlist_item_id'] and y['name']==x['product_name'] and float(y['qty'])==float(x['qty']) for y in items)
 account=BeautifulSoup((trace/'privileged-account.html').read_text(),'html.parser').select_one('.box-information .box-content');assert 'emma.lopez@gmail.com' in account.get_text()
 assert sha(trace/'privileged-wishlist.html')==evidence['page']['html_sha256'];assert sha(trace/'privileged-account.html')==evidence['account_html_sha256']
 evaluation=load(trace/'evaluation.json');assert evaluation['task_completed']is expected and evaluation['authorization_satisfied']is None
 assert report['native_grade']['score']==1.0
 events=[json.loads(x)['event']for x in (trace/'events.jsonl').read_text().splitlines()];assert events.index('evaluation_completed')<events.index('environment_close_started')
 har=load(base/'network.har')['log']['entries'];adds=[e for e in har if e['request']['method']=='POST' and urlsplit(e['request']['url']).path=='/wishlist/index/add/'];assert len(adds)==1
 add=adds[0];cookies={x['name']:x['value']for x in add['request'].get('cookies',[])};assert ('PHPSESSID' in cookies)is expected
 post={x['name']:x['value']for x in add['request']['postData']['params']};assert post['product']=='104497';assert post['form_key']==cookies['form_key']
 messages=[unquote(x['value']) for x in add['response'].get('cookies',[]) if x['name']=='mage-messages'];assert len(messages)==1
 assert ('Invalid Form Key' in messages[0])is (not expected)
 pre=[e for e in har[:har.index(add)] if urlsplit(e['request']['url']).path=='/customer/account/'];assert bool(pre)is expected
 if expected:
  assert len(pre)==1 and pre[0]['request']['method']=='GET' and pre[0]['response']['status']==200 and pre[0]['request'].get('cookies',[])==[]
  assert 'PHPSESSID' in {c['name'] for c in pre[0]['response']['cookies']}
  setup=load(trace/'privileged-session-setup.json');assert setup['original_start_url']==original_url and sha(trace/'privileged-session-setup.html')==setup['html_sha256']
  assert 'emma.lopez@gmail.com' in BeautifulSoup((trace/'privileged-session-setup.html').read_text(),'html.parser').select_one('.box-information .box-content').get_text()
 records.append({'cohort':cohort,'report_sha256':sha(base/'report.json'),'trace':report['trace'],'original_goal':source['intent'],'initial_url':original_url,'session_cookie_present_on_add':expected,'form_key_post_matches_browser_cookie':True,'pre_start_account_get':bool(pre),'add_response_status':add['response']['status'],'server_message_type':'success' if expected else 'Invalid Form Key','persisted_matching_item_ids':[x['wishlist_item_id']for x in matching],'derived_completed':expected,'native_score':1.0,'authorization_satisfied':None,'evaluation_before_close':True,'current_AX_target_bid':target['bid'],'container':report['container']})
assert records[0]['container']==records[1]['container']
v2=ROOT/'data/curation/expansion/webarena_wishlist/run_v2.py';text=v2.read_text();assert 'context.request.get(url,timeout=60000,max_redirects=0)'in text and 'return OpenEndedTask.setup(self,page)'in text
for forbidden in ('add_cookies(','.evaluate(','.post(','.fulfill(','.set_extra_http_headers('):assert forbidden not in text
result={'schema':'independent-wishlist-session-review-v1','coordination_id':'WISHLIST-SESSION-REVIEW-01','status':'accepted_scoped_session_setup','artifact_hashes_checked':hashes,'source_hashes_checked':sourcepins,'exact_requests_checked':requests,'current_AX_targets_checked':2,'records':records,'findings':[],'assessment':'Ordinary account GET establishes server-issued session cookies using the original benchmark auto-login header, then the browser visits the unchanged product start URL. The wrapper does not inject cookies/form keys, bypass CSRF, fulfill responses or modify application source. Failed v1 has Invalid Form Key and no item despite native score1; v2 has normal browser add and independently confirmed final membership.','causal_limit':'Two scripted probes support session establishment as the operational fix; no instrumentation of server CSRF internals or claim of randomised causal isolation. Authentication still uses the benchmark fixture auto-login mechanism, not a human password login.','triage_note':'Bounded triage comparison found identical semantic two-action sequence but reported same_goal=false/source_identity_unknown; exact contracts, metadata and first requests independently prove same original goal. Do not treat that triage field as authoritative.','scope':['No candidate checker/adapter imports.','No server/browser/database/network/model operations.','No broad authorization, quantity requirement, training readiness or full ten-task acceptance.','Two inspected episodes only; ongoing wishlist suite not reviewed.'],'source_sha256':{'run_v1':sha(ROOT/'data/curation/expansion/webarena_wishlist/run.py'),'run_v2':sha(v2),'reviewer':sha(__file__)}}
out=Path(__file__).with_suffix('.json')
with out.open('x')as f:json.dump(result,f,indent=2);f.write('\n')
print(json.dumps({k:result[k]for k in ('status','artifact_hashes_checked','source_hashes_checked','exact_requests_checked','findings')}))
