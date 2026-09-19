"""Fresh BrowserGym positive/wrong-answer controls, no model or paid API calls."""
import argparse,json,os
from pathlib import Path
from intent_browser.actions import make_action_set
from intent_browser.backend import Completion
from intent_browser.runner import run_episode
from intent_browser.trace import write_json
from data.curation.expansion.tricky.lookup_tasks import LookupTask,ROOT,HERE,SHA

class Driver:
 """Privileged navigation plan, but answers come only from actual page elements."""
 def __init__(self,task,case,env):
  self.task,self.case,self.env=task,case,env;site=task.contract['site'];self.answer=None;self.extractions=[];self.target_checks=[]
  self.actions=([('fill','input[placeholder="Search for products"]','Dell Inspiron 15'),('click','a[href$="/product/24"]',None)] if site=='shop' else [('click','a[href$="/medical-records"]',None)] if site=='health' else [('click','#read-more-button-'+('pw-news-5' if task.contract['id']=='TX08' else 'breaking-news-2'),None)] if site=='news' else [('click','a[href$="/spotify/search"]',None),('fill','#search-input','Ed Sheeran'),('press','#search-input','Enter')])
  if case=='wrong_page':self.actions.extend([('capture_then_click','#back-button',None),('click','#read-more-button-breaking-news-1',None)])
 def extract(self,messages):
  import re
  page=self.env['env'].unwrapped.page;task_id=self.task.contract['id'];selector=''
  if task_id=='TX01':
   selector='h4';value=next(v for v in page.locator(selector).all_inner_texts() if re.fullmatch(r'\$\d+\.\d{2}',v)).removeprefix('$')
  elif task_id=='TX02':
   selector='[aria-label^="Average Rating:"]';value=re.search(r'Average Rating: ([\d.]+) out of',page.locator(selector).get_attribute('aria-label')).group(1)
  elif task_id=='TX03':
   selector='heading Description / following sibling';value=page.get_by_role('heading',name='Description',exact=True).locator('xpath=following-sibling::*[1]').inner_text()
  elif task_id in ('TX04','TX05'):
   selector='.ant-list-item';reviews=[]
   for row in page.locator(selector).all():
    rates=row.locator('[aria-label^="Rating by"]')
    if rates.count():reviews.append((float(re.search(r': ([\d.]+) out of',rates.first.get_attribute('aria-label')).group(1)),row.locator('.ant-list-item-meta-description').inner_text()))
   value=(max if task_id=='TX04' else min)(reviews,key=lambda r:r[0])[1]
  elif task_id in ('TX06','TX07'):
   title='Blood Test' if task_id=='TX06' else 'Flu Shot';key='Doctor:' if task_id=='TX06' else 'Date:'
   selector=f'[aria-label="Medical Record: {title}"] p'
   value=next(v.split(key,1)[1].strip() for v in page.locator(selector).all_inner_texts() if v.startswith(key))
  elif task_id=='TX08':
   selector='#article-content .ant-typography';value=page.locator(selector).first.inner_text().split('. ',1)[0].strip()
   if not value.endswith('.'):value+='.'
  elif task_id=='TX09':selector='#article-title';value=page.locator(selector).inner_text()
  elif task_id=='TX10':
   selector='.ant-card';cards=page.locator(selector).filter(has=page.locator('a[href$="/artist/2"]'));value=cards.locator('.ant-card-meta-title').inner_text()
  else:raise ValueError(task_id)
  # This is an availability assertion, not an attention/comprehension claim.
  current=messages[-1]['content'];normalized=lambda s:re.sub(r'\s+',' ',s).casefold().strip()
  delivered=normalized(value).rstrip('.') in normalized(current)
  if not delivered:raise ValueError('Extracted browser answer not present in current delivered AX')
  self.extractions.append({'url':page.url,'selector':selector,'value':value,'in_current_delivered_text':delivered,'messages_sha256':__import__('hashlib').sha256(json.dumps(messages,sort_keys=True).encode()).hexdigest()})
  return value
 def complete(self,messages):
  if not self.actions:
   answer=self.answer if self.answer is not None else self.extract(messages)
   if self.case=='wrong_answer':answer='Tech Giants Rport Record Earnings' if self.task.contract['id']=='TX09' else 'Incorrect scripted control answer'
   write_json(self.task.trace.directory/'scripted-driver-evidence.json',{'extractions':self.extractions,'target_checks':self.target_checks,'grader_reference_used_by_driver':False})
   return Completion(f'send_msg_to_user({answer!r})',{'source':'privileged-scripted-lookup-driver','case':self.case},request={'messages':messages,'model':None})
  action,selector,value=self.actions.pop(0)
  if action=='capture_then_click':self.answer=self.extract(messages);action='click'
  loc=self.env['env'].unwrapped.page.locator(selector).last
  bid=loc.get_attribute('bid',timeout=4000)
  if not bid:raise ValueError('Missing current BrowserGym BID: '+selector)
  delivered=f'[{bid}]' in messages[-1]['content']
  self.target_checks.append({'selector':selector,'bid':bid,'in_current_delivered_text':delivered})
  if not delivered:raise ValueError('Target BID absent from current delivered AX: '+selector)
  return Completion(f'{action}({bid!r}'+(f', {value!r}' if value is not None else '')+')',{'source':'privileged-scripted-lookup-driver','case':self.case},request={'messages':messages,'model':None})

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--task',action='append');args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
 os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','')
 contracts=json.loads((HERE/'contracts.json').read_text())['tasks'];rows=[]
 for contract in contracts:
  if args.task and contract['id'] not in args.task:continue
  for case in ['positive','wrong_answer']+(['wrong_page'] if contract['id']=='TX09' else []):
   task=LookupTask(contract['id']);env={}
   def factory(video):env['env']=task.make_env(video,make_action_set().to_python_code);return env['env']
   try:
    folder,result=run_episode(factory,Driver(task,case,env),{'task':'tricky-expansion-original-lookup','task_id':contract['id'],'driver':'privileged-scripted','case':case,'model':None},output=args.output/'episodes',max_steps=8,episode_task=task,terminal_response_instruction=contract['policy_terminal_instruction'],observation_text_limit=48000)
    ev=result['evaluation'];steps=[json.loads(l) for l in (folder/'steps.jsonl').read_text().splitlines()];detail=json.loads((folder/'lookup-evaluation.json').read_text()) if (folder/'lookup-evaluation.json').exists() else {}
    errors=[s.get('action_error') for s in steps if s.get('action_error')]
    # Site evidence must support the expected answer even in the wrong-answer control.
    seen=detail.get('procedure_observations',{}).get('answer_text_observed_in_browser',False)
    passed=ev['task_completed']==(case=='positive') and ev['technical_error'] is None and not errors and (seen or case=='wrong_page')
    rows.append({'task_id':contract['id'],'site':contract['site'],'case':case,'trace':str(folder),'passed':passed,'evaluation':ev,'answer_observed_in_browser':seen,'action_errors':errors,'files':{str(f.relative_to(folder)):SHA(f) for f in folder.rglob('*') if f.is_file()}})
    report={'schema_version':1,'scope':'10 original clean lookup task contracts; scripted browser/answer controls, not model capability evidence','model_calls':0,'training_eligible':False,'independent_review':False,'source_sha256':{str(f.relative_to(ROOT)):SHA(f) for f in [HERE/'lookup_tasks.py',HERE/'verify_lookups.py',HERE/'contracts.json',ROOT/'environments/tricky_full/build-record.json']},'passed':all(r['passed'] for r in rows),'rows':rows}
    write_json(args.output/'report.json',report);print(contract['id'],case,passed,ev.get('technical_error'),flush=True)
   finally:task.close()
 if not all(r['passed'] for r in rows):raise SystemExit(1)
if __name__=='__main__':main()
