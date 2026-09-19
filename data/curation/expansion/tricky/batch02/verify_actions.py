"""Scripted comparison/cart/checkout validation via actual BrowserGym actions."""
import argparse,json,os,re
from pathlib import Path
from intent_browser.actions import make_action_set
from intent_browser.backend import Completion
from intent_browser.runner import run_episode
from intent_browser.trace import write_json
from data.curation.expansion.tricky.batch02.tasks import ActionTask,ROOT,HERE,sha

class Driver:
 def __init__(self,task,case,env):
  self.task,self.case,self.env=task,case,env;self.evidence=[];self.chosen=None
  if task.contract['id']=='TA11':
   self.plan=[('search','Dell Inspiron 15' if case=='wrong_product' else 'Bluff'),('choose','named'),('search','Lenovo ThinkPad X1 Carbon Ultra'),('choose','named')]
  else:self.plan=[('search','touch screen laptops' if task.contract['id']=='TA14' else 'toothbrush'),('choose','highest_rating' if task.contract['id']=='TA13' else 'lowest_price')]
  if case=='duplicate':self.plan.append(('repeat_add',None))
  self.plan.append(('cart',None))
  if task.contract['kind']=='purchase' and case!='abandon':self.plan.append(('checkout',None))
  if case=='reload':self.plan.append(('reload',None))
 def complete(self,messages):
  page=self.env['env'].unwrapped.page
  if not self.plan:
   write_json(self.task.trace.directory/'driver-evidence.json',{'checks':self.evidence,'reference_targets_read':False})
   return Completion("send_msg_to_user('Done')",{'source':'privileged-original-task-driver'},request={'messages':messages,'model':None})
  op,value=self.plan.pop(0);arg=None
  if op=='search':loc=page.get_by_placeholder('Search for products');action='fill';arg=value
  elif op=='choose':
   cards=[]
   for card in page.locator('[id^="product_card_"]').all():
    price=card.locator('[aria-label^="Price: $"]').get_attribute('aria-label');rating=card.locator('[aria-label^="Product Rating:"]').get_attribute('aria-label')
    cards.append({'id':card.get_attribute('id').removeprefix('product_card_'),'text':card.inner_text(),'price':float(price.split('$')[1]),'rating':float(re.search(r'Rating: ([\d.]+)',rating).group(1))})
   if not cards:raise ValueError('No visible search results')
   if value=='named':selected=cards[0]
   else:
    selected=(max if (value=='highest_rating')!=(self.case=='wrong_product') else min)(cards,key=lambda c:c['rating'] if value=='highest_rating' else c['price'])
    # For lowest-price choose min, wrong-product max; highest-rating opposite.
   self.chosen=selected['id'];self.evidence.append({'operation':'browser_card_selection','criterion':value,'candidates':cards,'selected':selected})
   loc=page.locator('#add_to_cart_'+self.chosen);action='click'
  elif op=='repeat_add':loc=page.locator('#add_to_cart_'+self.chosen);action='click'
  elif op=='cart':loc=page.get_by_role('menuitem',name='View Shopping Cart').locator('a');action='click'
  elif op=='checkout':loc=page.locator('#checkout-button');action='click'
  elif op=='reload':loc=page.locator('a').filter(has_text='Home').first;action='press';arg='Control+r'
  else:raise ValueError(op)
  bid=loc.get_attribute('bid');delivered=bid is not None and f'[{bid}]' in messages[-1]['content']
  self.evidence.append({'operation':op,'bid':bid,'in_current_delivered_AX':delivered})
  if not delivered:raise ValueError('Target not present in current delivered AX')
  return Completion(f'{action}({bid!r}'+(f',{arg!r}' if arg is not None else '')+')',{'source':'privileged-original-task-driver'},request={'messages':messages,'model':None})

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--task',action='append');a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
 os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','')
 tasks=json.loads((HERE/'contracts.json').read_text())['tasks'];rows=[]
 for c in tasks:
  if a.task and c['id'] not in a.task:continue
  for case in ['positive','wrong_product','duplicate','reload']+(['abandon'] if c['kind']=='purchase' else []):
   task=ActionTask(c['id']);env={}
   def factory(video):env['env']=task.make_env(video,make_action_set().to_python_code);return env['env']
   try:
    trace,result=run_episode(factory,Driver(task,case,env),{'task':'tricky-original-actions','task_id':c['id'],'case':case,'driver':'privileged-scripted','model':None},output=a.output/'episodes',max_steps=12,episode_task=task,observation_text_limit=48000)
    ev=result['evaluation'];steps=[json.loads(x) for x in (trace/'steps.jsonl').read_text().splitlines()];errors=[s.get('action_error') for s in steps if s.get('action_error')]
    passed=ev['task_completed']==(case in ['positive','reload']) and ev['technical_error'] is None and not errors
    rows.append({'task_id':c['id'],'case':case,'trace':str(trace),'passed':passed,'evaluation':ev,'action_errors':errors,'files':{str(f.relative_to(trace)):sha(f) for f in trace.rglob('*') if f.is_file()}})
    write_json(a.output/'report.json',{'schema_version':1,'passed':all(r['passed'] for r in rows),'model_calls':0,'independent_review':False,'training_eligible':False,'source_sha256':{str(p.relative_to(ROOT)):sha(p) for p in [HERE/'tasks.py',HERE/'verify_actions.py',HERE/'contracts.json']},'rows':rows});print(c['id'],case,passed,ev.get('technical_error'),flush=True)
   finally:task.close()
 if not all(r['passed'] for r in rows):raise SystemExit(1)
if __name__=='__main__':main()
