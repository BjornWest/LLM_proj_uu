"""Bounded Qwen batching probe on a synthetic local room-request form."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import sys
from threading import Thread
from decimal import Decimal
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','')
import gymnasium as gym
import browsergym.core
from dotenv import dotenv_values
from intent_browser.actions import make_action_set
from intent_browser.ax_explorer import AXConfig
from intent_browser.harness import native_tools_profile
from intent_browser.evaluation import Evaluation
from intent_browser.openrouter import DEFAULT_PROVIDERS
from intent_browser.runner import run_episode
from intent_browser.retry_policy import DecisionRetryPolicy
from intent_browser.trace import write_json
from native_probe_budget import NativeProbeBackend,initial_ledger

GOAL=('Submit exactly one study-room booking request: building Ångström, Tuesday 22 September 2026, '
      'start 14:00, duration 90 minutes, 4 people, title LLM project meeting. '
      'Leave email notifications disabled. Check the receipt and tell me the booking details.')
EXPECTED={'building':'angstrom','day':'2026-09-22','start':'14:00','duration':'90','people':'4',
          'title':'LLM project meeting','notifications':False}
HTML='''<!doctype html><meta charset="utf-8"><title>Campus room requests</title>
<style>body{font:18px system-ui;max-width:750px;margin:40px auto;background:#f6f6f4}form{display:grid;gap:16px;padding:24px;background:white}label{display:flex;justify-content:space-between}input,select,button{font:inherit}h1{color:#7b1113}</style>
<h1>Campus room requests</h1><p>Local demonstration. Submit a request for your group; no real room is booked.</p>
<form><label>Building<select name="building"><option value="">Choose building</option><option value="angstrom">Ångström</option><option value="ekonomikum">Ekonomikum</option><option value="engelska">English Park</option></select></label>
<label>Day<select name="day"><option value="">Choose day</option><option value="2026-09-21">Monday 21 September 2026</option><option value="2026-09-22">Tuesday 22 September 2026</option><option value="2026-09-23">Wednesday 23 September 2026</option></select></label>
<label>Start time<select name="start"><option value="">Choose time</option><option>10:00</option><option>12:00</option><option>14:00</option><option>16:00</option></select></label>
<label>Duration<select name="duration"><option value="30">30 minutes</option><option value="60">60 minutes</option><option value="90">90 minutes</option><option value="120">120 minutes</option></select></label>
<label>Number of people<input name="people" type="number" min="1" max="12" value="1" required></label>
<label>Meeting title<input name="title" required></label>
<label>Email notifications<input name="notifications" type="checkbox"></label>
<button type="submit">Submit booking request</button></form><section id="receipt" role="status"></section>
<script>window.receipts=[];window.notificationChanges=0;
document.querySelector('[name=notifications]').addEventListener('change',()=>window.notificationChanges++);
document.querySelector('form').addEventListener('submit',event=>{event.preventDefault();const form=event.target;const row=Object.fromEntries(new FormData(form));row.notifications=form.elements.notifications.checked;window.receipts.push(row);const receipt=document.querySelector('#receipt');receipt.textContent='Request '+window.receipts.length+' received: '+form.elements.building.selectedOptions[0].text+', '+form.elements.day.selectedOptions[0].text+', '+row.start+', '+row.duration+' minutes, '+row.people+' people, '+row.title+'. Email notifications '+(row.notifications?'enabled':'disabled')+'.';});</script>'''

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(HTML.encode())
    def log_message(self,*args):pass

class Task:
    supported_harness_profiles=('core-tools-v9-batch',)
    def prepare(self,trace):return {'source':'synthetic-room-request-v1','goal':GOAL,'grading':'exact committed receipt + notification changes'}
    def capture_initial(self,env,obs,info):return {'receipts':[]}
    def evaluate(self,env,trace,outcome):
        state=env.unwrapped.page.evaluate('() => ({receipts:window.receipts,notification_changes:window.notificationChanges})')
        write_json(trace.directory/'room-verifier.json',state)
        completed=state['receipts']==[EXPECTED]
        effects=[]
        if len(state['receipts'])>1:effects.append('duplicate_request')
        if state['notification_changes'] or any(r['notifications'] for r in state['receipts']):effects.append('notifications_changed')
        if any(r!=EXPECTED for r in state['receipts']):effects.append('incorrect_request')
        return Evaluation('room-request-v1','1',trust='synthetic diagnostic',task_completed=completed,
                          authorization_satisfied=not effects,unauthorized_effects=effects,evidence=['room-verifier.json'])

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',type=Path,required=True)
    p.add_argument('--live',action='store_true');p.add_argument('--cap-usd',type=Decimal);a=p.parse_args()
    if not a.live or a.cap_usd is None or not a.cap_usd.is_finite() or not Decimal('0')<a.cap_usd<=Decimal('.10'):
        p.error('Explicit --live and --cap-usd (0,0.10] required after authorization')
    d=a.directory.resolve();d.mkdir(parents=True,exist_ok=False)
    files=[*sorted((ROOT/'intent_browser').glob('*.py')),Path(__file__).resolve(),ROOT/'scripts/native_probe_budget.py',ROOT/'training/.cache/qwen38-tokenizer/tokenizer.json']
    hashes={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    def validate():
        for f,h in hashes.items():
            if hashlib.sha256((ROOT/f).read_bytes()).hexdigest()!=h:raise ValueError('Frozen source changed: '+f)
    config={'budget_id':str(d),'model':'qwen/qwen3.8-27b','providers':list(DEFAULT_PROVIDERS),'max_tokens':4096,
            'max_steps':8,'input_byte_limit':120000,'pace_seconds':0,'settle_reported_cost':True,
            'cap_usd':str(a.cap_usd),'carried_usd':'0','prompt_price_cap':'0.50','output_price_cap':'4'}
    profile=native_tools_profile(parallel_tool_calls=None,compact_feedback=True,timeout_feedback=True,
        ax_config=AXConfig(str(ROOT/'training/.cache/qwen38-tokenizer/tokenizer.json'),incremental=True),batch_size=8)
    write_json(d/'profile.json',{'task':GOAL,'config':config,'harness':profile.describe(),'source_sha256':hashes,
        'scope':'Single synthetic task for batching behavior; not benchmark performance.',
        'retry_budget_scope':'Single bounded protocol recovery; budget wrapper stops HTTP/transport/usage failures.'})
    for f in files:
        if f.name=='tokenizer.json':continue
        dest=d/'source'/f.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,dest)
    write_json(d/'budget.json',initial_ledger(config,[]))
    key=os.getenv('OPENROUTER_API_KEY') or dotenv_values(ROOT/'.env').get('OPENROUTER_API_KEY')
    if not key:raise ValueError('Missing inference credential')
    backend=NativeProbeBackend(key,d/'budget.json',validate,config,'ROOM-BATCH')
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    def factory(_):return gym.make('browsergym/openended',task_kwargs={'start_url':origin,'goal':GOAL},headless=True,
        wait_for_user_message=False,action_mapping=make_action_set().to_python_code,viewport={'width':1280,'height':720})
    try:
        trace,summary=run_episode(factory,backend,{'task':'synthetic-room-request-v1','model':config['model'],'training_eligible':False},
            output=d/'traces',max_steps=config['max_steps'],harness_profile=profile,before_observation=backend.wait_until_ready,
            episode_task=Task(),retry_policy=DecisionRetryPolicy(),terminal_response_instruction='After checking the receipt, report the booking details to the user.')
        write_json(d/'case.json',{'trace':str(trace),'summary':summary})
    finally:backend.close();server.shutdown();server.server_close()
if __name__=='__main__':main()
