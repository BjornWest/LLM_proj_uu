"""Offline parallel BrowserGym checks of generation recovery; no real inference."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import multiprocessing
import os
from pathlib import Path
import re
import sys
from threading import Thread
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','')
import gymnasium as gym
import browsergym.core
import httpx
from intent_browser.actions import make_action_set
from intent_browser.backend import ChatCompletionsBackend
from intent_browser.evaluation import Evaluation
from intent_browser.harness import native_tools_profile
from intent_browser.retry_policy import DecisionRetryPolicy
from intent_browser.runner import run_episode

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers()
        self.wfile.write(b'<!doctype html><title>Retry check</title><h1 id="fresh">Initial</h1><button onclick="window.commits++;this.textContent=\'Committed\'">Commit</button><script>window.commits=0;window.privateVerifier="PRIVATE_SENTINEL"</script>')
    def log_message(self,*args):pass

class Task:
    supported_harness_profiles=('core-tools-v3',)
    def prepare(self,trace):return {'source':'offline retry fixture'}
    def capture_initial(self,env,obs,info):
        return {'commits':env.unwrapped.page.evaluate('window.commits')}
    def evaluate(self,env,trace,outcome):
        count=env.unwrapped.page.evaluate('window.commits')
        return Evaluation('retry-fixture','1',trust='scripted_check',task_completed=count==1,
                          authorization_satisfied=count<=1,unauthorized_effects=[] if count<=1 else ['duplicate_commit'])

def run_case(input):
    mode,output=input;output=Path(output);holder={};requests=[];responses=[];raw_rejected=None
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    def dispatch(req):
        nonlocal raw_rejected
        value=json.loads(req.content);requests.append(value);n=len(requests)
        assert 'PRIVATE_SENTINEL' not in json.dumps(value)
        if n>1:assert value['messages'][:len(requests[-2]['messages'])]==requests[-2]['messages']
        assert f'Capture {n}' in value['messages'][-1]['content']
        if n==1 and mode=='429':
            raw={'error':{'code':429,'metadata':{'provider_name':'offline'}}};responses.append(raw)
            return httpx.Response(429,json=raw,headers={'Retry-After':'2'})
        message={'role':'assistant','content':None,'reasoning':'Synthetic retained plan'}
        if n==1:
            if mode=='multiple':message['tool_calls']=[{'id':f'bad-{i}','type':'function','function':{'name':'noop','arguments':'{}'}} for i in range(2)]
            raw_rejected={'choices':[{'finish_reason':'tool_calls','message':message}]};responses.append(raw_rejected);return httpx.Response(200,json=raw_rejected)
        if n==2:
            assert holder['env'].unwrapped.page.evaluate('window.commits')==0
            assert 'HARNESS RECOVERY NOTICE' in value['messages'][-1]['content']
            bid=re.findall(r"\[([^\]]+)\] button 'Commit'",value['messages'][-1]['content']);assert len(bid)==1
            name,args='click',{'bid':bid[0]}
        else:name,args='send_msg_to_user',{'text':'Done'}
        message['tool_calls']=[{'id':f'good-{n}','type':'function','function':{'name':name,'arguments':json.dumps(args)}}]
        raw={'choices':[{'finish_reason':'tool_calls','message':message}]};responses.append(raw);return httpx.Response(200,json=raw)
    backend=ChatCompletionsBackend('https://offline.invalid/v1','mock');backend.client.close();backend.client=httpx.Client(transport=httpx.MockTransport(dispatch))
    def factory(_):
        env=gym.make('browsergym/openended',task_kwargs={'start_url':origin,'goal':'Press Commit once and finish.'},headless=True,wait_for_user_message=False,action_mapping=make_action_set().to_python_code);holder['env']=env;return env
    def pace():
        holder['env'].unwrapped.page.evaluate('(n)=>document.querySelector("h1").textContent="Capture "+n',len(requests)+1)
        return {'offline_capture_marker':len(requests)+1}
    try:
        path,s=run_episode(factory,backend,{'driver':'scripted_validation','model_calls':0},output=output,max_steps=3,
            episode_task=Task(),before_observation=pace,harness_profile=native_tools_profile(compact_feedback=True,parallel_tool_calls=None),retry_policy=DecisionRetryPolicy())
        rows=[json.loads(line) for line in (path/'steps.jsonl').read_text().splitlines()]
        assert s['error'] is None and s['evaluation']['safe_success'] is True
        assert len(requests)==3 and s['decision_retry_count']==1 and s['browser_step_count']==2
        assert rows[0]['action'] is None and rows[0]['error'] and rows[1]['retry_of_step']==0
        assert all(row['model_request']==req and row['model_response']==resp for row,req,resp in zip(rows,requests,responses,strict=True))
        events=[json.loads(x)['event'] for x in (path/'events.jsonl').read_text().splitlines()]
        assert events.index('evaluation_completed')<events.index('environment_close_started')
        assert all(item['confirmed'] for item in rows[-1]['policy_delivery']['items'])
        return {'mode':mode,'passed':True,'trace':str(path),'http_mock_requests':3,'browser_commits':1,'summary':s}
    finally:backend.close();server.shutdown();server.server_close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    with ProcessPoolExecutor(max_workers=3,mp_context=multiprocessing.get_context('spawn')) as pool:
        cases=list(pool.map(run_case,[(mode,str(a.output/mode)) for mode in ['missing','multiple','429']]))
    files=['intent_browser/runner.py','intent_browser/native_tools.py','intent_browser/backend.py','intent_browser/retry_policy.py','scripts/verify_decision_retry.py']
    report={'passed':True,'model_calls':0,'cases':cases,'source_sha256':{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files}}
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(a.output/'report.json')
