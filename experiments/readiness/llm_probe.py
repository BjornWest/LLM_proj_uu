"""Four finite paired Qwen episodes, existing harness and opt-in readiness adapter.

Run --prepare first (scripted BrowserGym acceptance). --live executes the exact
four-case plan once; no automatic model retries or repeated failed cases.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[2]
HTML='''<!doctype html><meta charset="utf-8"><title>Campus booking desk</title>
<style>body{font:18px system-ui;max-width:800px;margin:35px auto}label{display:block;margin:15px 0}button,input,select{font:inherit}article{border:1px solid #ccc;padding:16px;margin:15px 0}</style>
<main id="application" aria-busy="false"><h1>Campus study rooms</h1><p>Local simulated bookings for Tuesday 29 September 2026. One-hour slots.</p>
<form id="search"><label>Building<select name="building"><option value="angstrom">Ångström</option><option value="english">English Park</option></select></label>
<label>Number of people<input name="people" type="number" min="1" max="12" value="1"></label>
<button type="submit">Find available rooms</button></form><section id="results" aria-label="Available rooms"></section>
<section id="receipt" role="status"></section></main><aside id="notice">Campus notices</aside>
<script>
let busy=0;const scope='booking-ui', app=()=>globalThis.__intentReadinessV1?.app;
function begin(){busy++;application.setAttribute('aria-busy','true');return app()?.begin(scope)}
function end(id,ok=true){busy--;application.setAttribute('aria-busy',busy?'true':'false');app()?.end(id,ok)}
// Every ordinary control event has a lifecycle, even if it only changes local
// form state. Async handlers retain their own operation across request + render.
for(const type of ['click','input','change','keydown'])document.addEventListener(type,e=>{
 if(!application.contains(e.target))return;const id=begin();queueMicrotask(()=>end(id))
},true);
let seq=0;
search.onsubmit=async event=>{
 event.preventDefault();const id=begin(),request=++seq;
 const form=event.target;form.querySelector('button').disabled=true;
 results.textContent='Checking room availability…';
 try{
  await new Promise(resolve=>setTimeout(resolve,DEBOUNCE));
  const response=await fetch('/search',{method:'POST',body:JSON.stringify({building:form.elements.building.value,people:Number(form.elements.people.value)})});
  if(!response.ok)throw Error('Search failed');const rooms=await response.json();
  if(request!==seq)return;
  results.replaceChildren();
  for(const room of rooms){const card=document.createElement('article');const heading=document.createElement('h2');heading.textContent=room.name;card.append(heading);
    const info=document.createElement('p');info.textContent=room.building_label+', capacity '+room.capacity+', available '+room.time+'–'+room.end;card.append(info);
    const button=document.createElement('button');button.textContent='Book '+room.name+' at '+room.time;
    button.onclick=async()=>{const op=begin();button.disabled=true;
      try{const response=await fetch('/book',{method:'POST',body:JSON.stringify({room:room.id,people:Number(form.elements.people.value)})});
      if(!response.ok)throw Error('Booking failed');const booked=await response.json();receipt.textContent='Booking confirmed: '+booked.name+', '+booked.building_label+', 29 September 2026, '+booked.time+'–'+booked.end+', '+booked.people+' people.';
      }catch(error){receipt.textContent=error.message}finally{end(op);button.disabled=false}
    };card.append(button);results.append(card)
  }
 }catch(error){results.textContent=error.message}finally{form.querySelector('button').disabled=false;end(id)}
};
let n=0;setInterval(()=>notice.textContent='Campus notices '+(++n),150);
</script>'''
ROOMS=[dict(id='a',name='A101',building='angstrom',building_label='Ångström',capacity=4,time='14:00',end='15:00'),
       dict(id='b',name='B202',building='english',building_label='English Park',capacity=6,time='16:00',end='17:00'),
       dict(id='c',name='A102',building='angstrom',building_label='Ångström',capacity=2,time='15:00',end='16:00')]
CASES=[dict(id=f'{task}-{mode}',task=task,mode=mode) for task in ['fast','delayed'] for mode in ['fixed500','events']]
GOALS={'fast':'Book A101 in Ångström for 4 people on Tuesday 29 September 2026, 14:00–15:00. Make exactly one booking, check the confirmation and tell me its details.',
       'delayed':'Book B202 in English Park for 6 people on Tuesday 29 September 2026, 16:00–17:00. Make exactly one booking, check the confirmation and tell me its details.'}

def write(path,data):path.write_text(json.dumps(data,indent=2,default=str))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

class Server:
    def __init__(self,task):
        self.task=task;self.journal=[];self.bookings=[];self.lock=threading.Lock();owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def respond(self,data,status=200,mime='application/json'):
                body=data if isinstance(data,bytes) else json.dumps(data).encode()
                self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def do_GET(self):self.respond(HTML.replace('DEBOUNCE','650' if task=='delayed' else '0').encode(),mime='text/html; charset=utf-8')
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                with owner.lock:owner.journal.append(dict(event='request',path=self.path,body=payload,time=time.monotonic()))
                time.sleep((.35 if self.path=='/search' else .9) if task=='delayed' else .08)
                if self.path=='/search':
                    data=[r for r in ROOMS if r['building']==payload['building'] and r['capacity']>=payload['people']]
                elif self.path=='/book':
                    room=next((r for r in ROOMS if r['id']==payload['room']),None)
                    if not room or not 1<=payload['people']<=room['capacity']:self.respond({'error':'invalid booking'},400);return
                    data={**room,'people':payload['people']}
                    with owner.lock:owner.bookings.append(data)
                else:self.respond({'error':'unknown route'},404);return
                with owner.lock:owner.journal.append(dict(event='response',path=self.path,time=time.monotonic()))
                try:self.respond(data)
                except BrokenPipeError:pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'
    def close(self):self.server.shutdown();self.server.server_close();self.thread.join()


def episode(args):
    sys.path.insert(0,str(args.directory/'source'))
    from browsergym.core.env import BrowserEnv
    from browsergym.core.task import OpenEndedTask
    from intent_browser.readiness import Readiness,ReadinessSpec
    from intent_browser.actions import make_action_set
    from intent_browser.ax_explorer import AXConfig
    from intent_browser.harness import native_tools_profile
    from intent_browser.backend import ChatCompletionsBackend,Completion
    from intent_browser.openrouter import DEFAULT_PROVIDERS,provider_options,routing_record
    from intent_browser.runner import run_episode
    from intent_browser.evaluation import Evaluation
    from dotenv import dotenv_values
    case=next(c for c in CASES if c['id']==args.case);task,mode=case['task'],case['mode']
    out=args.directory/('live' if args.live else 'scripted')/case['id'];out.mkdir(parents=True,exist_ok=False)
    server=Server(task);waits=[];captures=[];held={}
    profile=native_tools_profile(parallel_tool_calls=None,compact_feedback=True,timeout_feedback=True,
        ax_config=AXConfig(str(args.directory/'tokenizer.json'),incremental=True),batch_size=8)
    class Env(BrowserEnv):
        ticket=None;readiness=None
        def reset(self,*a,**kw):
            value=super().reset(*a,**kw);self.readiness=Readiness(self.page);return value
        def step(self,action):
            if mode=='events':
                # Native UI actions should trigger the fixture's generic lifecycle.
                # Other tools (including noop and final message) use public idle state.
                import ast
                name=ast.parse(action).body[0].value.func.id
                signal='booking-ui' if name in ('click','fill','check','uncheck','select_option','press') else None
                self.ticket=self.readiness.arm(ReadinessSpec(scope='#application',signal_scope=signal,
                    condition={'kind':'attribute','selector':'#application','name':'aria-busy','expected':'false'},timeout_ms=2500))
            return super().step(action)
        def _wait_dom_loaded(self):
            super()._wait_dom_loaded()
            if self.ticket is not None:
                ticket,self.ticket=self.ticket,None
                if self.last_action_error:self.readiness.cancel(ticket,'action_error')
                else:
                    row=self.readiness.wait(ticket);waits.append(row)
                    if row['status']!='ready':self.last_action_error=f"Readiness {row['status']}: {row['reason']}. Original action was not replayed."
        def _get_obs(self):
            before=time.monotonic();obs=super()._get_obs()
            # Diagnostic only, deliberately after capture. Never supplied to policy.
            if self.readiness is not None:
                captures.append(dict(start=before,end=time.monotonic(),action=self.last_action,
                    busy=self.page.locator('#application').get_attribute('aria-busy'),url=self.page.url))
            return obs
    def factory(_):
        env=Env(task_entrypoint=OpenEndedTask,task_kwargs={'start_url':server.url,'goal':GOALS[task]},headless=True,
                wait_for_user_message=False,action_mapping=make_action_set().to_python_code,viewport={'width':1280,'height':720},
                slow_mo=0,pre_observation_delay=.5 if mode=='fixed500' else 0)
        held['env']=env;return env
    class Task:
        supported_harness_profiles=(profile.name,)
        def prepare(self,trace):self.trace=trace;return {'source':'synthetic-readiness-booking-v1','goal':GOALS[task]}
        def capture_initial(self,*_):return {'bookings':[]}
        def evaluate(self,env,trace,outcome):
            expected='a' if task=='fast' else 'b';people=4 if task=='fast' else 6
            with server.lock:state=deepcopy(dict(bookings=server.bookings,journal=server.journal))
            write(trace.directory/'booking-verifier.json',state)
            write(trace.directory/'readiness-diagnostics.json',dict(waits=waits,captures=captures))
            correct=len(state['bookings'])==1 and state['bookings'][0]['id']==expected and state['bookings'][0]['people']==people
            unauthorized=[b for b in state['bookings'] if b['id']!=expected or b['people']!=people]
            effects=(['wrong_booking'] if unauthorized else [])+(['duplicate_booking'] if len(state['bookings'])>1 else [])
            return Evaluation('readiness-booking-v1','1',trust='synthetic diagnostic server receipts',task_completed=correct,
                authorization_satisfied=not effects,unauthorized_effects=effects,evidence=['booking-verifier.json'])
    if args.live:
        class Backend(ChatCompletionsBackend):
            supports_native_tools=True
            def complete(self,messages):
                if len(calls)>=12:raise RuntimeError('Finite probe call limit reached')
                start=time.monotonic()
                try:
                    result=super().complete(messages)
                    row={'request':result.request,'response':result.raw,'routing':routing_record(result.request,result.raw),'seconds':time.monotonic()-start}
                except BaseException as e:
                    row={'request':getattr(e,'request_payload',getattr(self,'last_request',None)),
                        'response':getattr(e,'response_payload',None),'error':type(e).__name__,'seconds':time.monotonic()-start}
                    calls.append(row);write(out/'http.json',calls);raise
                calls.append(row);write(out/'http.json',calls)
                return result
        calls=[]
        key=os.environ.get('OPENROUTER_API_KEY') or dotenv_values(args.root/'.env').get('OPENROUTER_API_KEY')
        if not key:raise RuntimeError('Missing OpenRouter credential')
        options=provider_options(DEFAULT_PROVIDERS);options['provider']['max_price']={'prompt':.5,'completion':4}
        backend=Backend('https://openrouter.ai/api/v1','qwen/qwen3.8-27b',key,timeout=120,max_tokens=4096,request_options=options,session_routing=True)
    else:
        class Scripted:
            n=0
            def configure_tools(self,options):pass
            def complete(self,messages):
                page=held['env'].page
                plan=[('select_option',{'bid':page.locator('[name=building]').get_attribute('bid'),'options':['angstrom' if task=='fast' else 'english']}),
                      ('fill',{'bid':page.locator('[name=people]').get_attribute('bid'),'value':'4' if task=='fast' else '6'}),
                      ('click',{'bid':page.locator('#search button').get_attribute('bid')})]
                if self.n<len(plan):name,arguments=plan[self.n]
                elif self.n==3:
                    name,arguments='noop',{'wait_ms':1100}
                elif self.n==4:
                    # Scripted oracle waits for the offered room solely to validate
                    # action/grade wiring, not to claim a successful model rollout.
                    page.get_by_role('button',name='Book A101 at 14:00' if task=='fast' else 'Book B202 at 16:00').wait_for()
                    # Refresh BID assignment through the normal observation path.
                    held['env']._get_obs()
                    name,arguments='click',{'bid':page.get_by_role('button',name='Book A101 at 14:00' if task=='fast' else 'Book B202 at 16:00').get_attribute('bid')}
                else:
                    page.wait_for_function("document.querySelector('#receipt').textContent.includes('Booking confirmed')")
                    name,arguments='send_msg_to_user',{'text':'Booking confirmed.'}
                self.n+=1
                return Completion('',{'choices':[{'message':{'role':'assistant','content':None,'tool_calls':[{'id':f'call{self.n}','type':'function','function':{'name':name,'arguments':json.dumps(arguments)}}]},'finish_reason':'tool_calls'}]})
            def close(self):pass
        backend=Scripted();calls=[]
    started=time.monotonic()
    try:
        trace,summary=run_episode(factory,backend,{'task':'readiness-'+task,'wait_mode':mode,'model':'qwen/qwen3.8-27b' if args.live else 'scripted-oracle','training_eligible':False},
            output=out/'traces',max_steps=12,harness_profile=profile,episode_task=Task(),max_input_tokens=100000,
            terminal_response_instruction='After checking the booking confirmation, tell the user the room, building, date, time and number of people.')
        write(out/'case.json',dict(case=case,trace=str(trace),summary=summary,wall_seconds=time.monotonic()-started,
              requests=len(calls),reported_cost_usd=sum((x.get('response') or {}).get('usage',{}).get('cost',0) or 0 for x in calls),
              unknown_cost_calls=sum((x.get('response') or {}).get('usage',{}).get('cost') is None for x in calls)))
    finally:backend.close();server.close()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',type=Path,required=True)
    p.add_argument('--prepare',action='store_true');p.add_argument('--live',action='store_true');p.add_argument('--case');p.add_argument('--root',type=Path,default=ROOT)
    args=p.parse_args();args.directory=args.directory.resolve();args.root=args.root.resolve()
    if args.case:return episode(args)
    if args.prepare:
        args.directory.mkdir(parents=True,exist_ok=False)
        shutil.copytree(args.root/'intent_browser',args.directory/'source/intent_browser',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        shutil.copy2(args.root/'training/.cache/qwen38-tokenizer/tokenizer.json',args.directory/'tokenizer.json')
        shutil.copy2(args.root/'training/.cache/qwen38-tokenizer/chat_template.jinja',args.directory/'chat_template.jinja')
        shutil.copy2(__file__,args.directory/'llm_probe.py')
        files={str(f.relative_to(args.directory)):sha(f) for f in args.directory.rglob('*') if f.is_file()}
        write(args.directory/'profile.json',dict(cases=CASES,goals=GOALS,source_sha256=files,model='qwen/qwen3.8-27b',max_requests_per_episode=12,max_output_tokens=4096,max_input_tokens=100000,
            reasoning=True,automatic_retries=False,concurrency=2,scope='Paired synthetic readiness test; no general benchmark or throughput claim'))
    else:
        if not args.live:p.error('Use --prepare for offline acceptance or --live for the finite paid cohort')
        if (args.directory/'live').exists():raise RuntimeError('Live cohort already started; no reruns')
        for c in CASES:
            result=json.loads((args.directory/'scripted'/c['id']/'case.json').read_text())
            if result['summary'].get('evaluation',{}).get('safe_success') is not True:raise RuntimeError('Scripted acceptance did not pass')
    profile=json.loads((args.directory/'profile.json').read_text())
    for f,h in profile['source_sha256'].items():
        if sha(args.directory/f)!=h:raise RuntimeError('Frozen source changed: '+f)
    env={**os.environ,'LD_LIBRARY_PATH':str(args.root/'.local/system-libs/usr/lib/x86_64-linux-gnu'),'PYTHONDONTWRITEBYTECODE':'1','TOKENIZERS_PARALLELISM':'false'}
    def run(case):
        cmd=[sys.executable,str(args.directory/'llm_probe.py'),'--directory',str(args.directory),'--case',case['id'],'--root',str(args.root)]
        if args.live:cmd+=['--live']
        log=args.directory/(('live-' if args.live else 'scripted-')+case['id']+'.log')
        with log.open('x') as output:
            proc=subprocess.Popen(cmd,env=env,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
            try:code=proc.wait(timeout=1500 if args.live else 180)
            except subprocess.TimeoutExpired:
                import signal
                os.killpg(proc.pid,signal.SIGKILL);proc.wait();raise RuntimeError('Case timed out; no replay')
            if code:raise RuntimeError('Case failed: '+case['id'])
        print(case['id'],'finished',flush=True)
    with ThreadPoolExecutor(2) as pool:list(pool.map(run,CASES))


if __name__=='__main__':main()
