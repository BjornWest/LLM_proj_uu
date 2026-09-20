"""Parallel local Chromium/native-protocol checks; zero model or search API calls."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import multiprocessing
import os
from pathlib import Path
import sys
from threading import Thread
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','')
import gymnasium as gym
import browsergym.core
import httpx
from intent_browser.actions import make_action_set
from intent_browser.ax_explorer import AXConfig
from intent_browser.backend import ChatCompletionsBackend
from intent_browser.harness import native_tools_profile
from intent_browser.evaluation import Evaluation
from intent_browser.runner import run_episode
from intent_browser.vision import VisionConfig

HTML=b'''<!doctype html><title>Batch fixture</title><h1>Batch fixture</h1>
<label>First <input id="a"></label><label>Second <input id="b"></label>
<button id="save" onclick="window.commits++;document.querySelector('#notice').textContent='Saved receipt'">Save</button>
<button id="rename" onclick="document.querySelector('#save').textContent='Delete'">Rename control</button>
<button id="blocked" disabled>Disabled control</button><a id="nav" href="/next">Next</a>
<p id="notice" role="status"></p><script>window.commits=0;window.privateVerifier='PRIVATE_SENTINEL'</script>'''
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(HTML)
    def log_message(self,*args):pass

class Task:
    supported_harness_profiles=('core-tools-v9-batch',)
    def __init__(self,mode):self.mode=mode
    def prepare(self,trace):return {'source':'synthetic batch fixture','case':self.mode}
    def capture_initial(self,env,obs,info):return {}
    def evaluate(self,env,trace,outcome):
        state=env.unwrapped.page.evaluate('() => ({commits:window.commits,a:document.querySelector("#a").value,b:document.querySelector("#b").value})')
        (trace.directory/'fixture-state.json').write_text(json.dumps(state))
        expected=1 if self.mode in ('form','terminal') else 0
        return Evaluation('batch-fixture','1',trust='scripted_check',task_completed=state['commits']==expected,
                          authorization_satisfied=state['commits']<=expected)

def run_case(args):
    mode,output=args;server=ThreadingHTTPServer(('127.0.0.1',0),Handler);Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}';holder={};requests=[]
    profile=native_tools_profile(parallel_tool_calls=None,compact_feedback=True,
        ax_config=AXConfig(str(ROOT/'training/.cache/qwen38-tokenizer/tokenizer.json'),incremental=True),
        vision_config=VisionConfig('agent'),batch_size=8,navigation_origins=(origin,))
    def call(n,name,args):return {'id':n,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}
    def dispatch(req):
        value=json.loads(req.content);requests.append(value);turn=len(requests)
        assert 'PRIVATE_SENTINEL' not in json.dumps(value)
        def bid(id):return holder['env'].unwrapped.page.locator('#'+id).get_attribute('bid')
        if turn==1:
            cases={
                'form':[('fill',{'bid':bid('a'),'value':'Alpha'}),('fill',{'bid':bid('b'),'value':'Beta'}),('click',{'bid':bid('save')})],
                'navigation':[('click',{'bid':bid('nav')}),('click',{'bid':bid('save')})],
                'relabel':[('click',{'bid':bid('rename')}),('click',{'bid':bid('save')})],
                'failure':[('click',{'bid':bid('blocked')}),('click',{'bid':bid('save')})],
                'invalid':[('click',{'bid':bid('save')}),('fill',{'bid':bid('a')})],
                'vision':[('screenshot',{}),('fill',{'bid':bid('a'),'value':'Visible change'}),('screenshot',{})],
                'reload':[('reload',{}),('click',{'bid':bid('save')})],
                'terminal':[('click',{'bid':bid('save')}),('click',{'bid':bid('rename')})],
                'queries':[('ax_search',{'query':'First'}),('ax_search',{'query':'Second'})],
            }
            selected=cases[mode]
        elif turn==2 and mode=='vision':
            selected=[('release_image',{'image_id':'image-000','keep_notes':'First view'}),
                      ('release_image',{'image_id':'image-001','keep_notes':'Second view'})]
        else:selected=[('send_msg_to_user',{'text':'Done'})]
        if turn>1:
            last_assistant=max(i for i,m in enumerate(value['messages']) if m['role']=='assistant')
            results=value['messages'][last_assistant+1:]
            assert all(m['role']=='tool' for m in results)
            texts=[m['content'] if isinstance(m['content'],str) else m['content'][0]['text'] for m in results]
            assert sum(x.count('CURRENT BROWSER OBSERVATION') for x in texts)==1
            if mode=='form':
                assert len(results)==3
                assert 'Alpha' not in texts[0] and 'Beta' not in texts[1]
                assert 'Saved receipt' in texts[-1]
            if mode=='vision':
                images=sum(p.get('type')=='image_url' for m in value['messages'] if isinstance(m.get('content'),list) for p in m['content'])
                assert images==(2 if turn==2 else 0)
        return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':{
            'role':'assistant','content':None,'reasoning':'Offline test plan',
            'tool_calls':[call(f'{turn}-{i}',n,a) for i,(n,a) in enumerate(selected)]}}]})
    backend=ChatCompletionsBackend('https://offline.invalid/v1','mock',supports_images=True)
    backend.client.close();backend.client=httpx.Client(transport=httpx.MockTransport(dispatch))
    def factory(_):
        env=gym.make('browsergym/openended',task_kwargs={'start_url':origin,'goal':'Synthetic protocol validation'},headless=True,
            wait_for_user_message=False,action_mapping=make_action_set().to_python_code)
        if mode=='terminal':
            native_step=env.step
            def terminal_step(action):
                o,r,t,tr,i=native_step(action)
                return o,r,True,tr,i
            env.step=terminal_step
        holder['env']=env;return env
    try:
        path,s=run_episode(factory,backend,{'driver':'scripted_validation','model_calls':0},output=output,max_steps=3,
            episode_task=Task(mode),harness_profile=profile,action_timeout_ms=500)
        rows=[json.loads(l) for l in (path/'steps.jsonl').read_text().splitlines()]
        assert (s['error'] is not None)==(mode=='invalid'),s
        state=json.loads((path/'fixture-state.json').read_text())
        assert state['commits']==(1 if mode in ('form','terminal') else 0),state
        if mode=='invalid':assert s['browser_step_count']==0
        else:
            assert s['stop_reason']==('terminated' if mode=='terminal' else 'agent_finished')
            assert all(i['confirmed'] for i in rows[-1]['policy_delivery']['items'])
            batch=rows[0]['batch_calls']
            if mode in ('navigation','relabel','failure','reload','terminal'):
                assert batch[1]['not_executed'] and not batch[1]['browser_stepped']
            if mode=='form':assert state['a']=='Alpha' and state['b']=='Beta'
            if mode=='vision':
                assert all(c['policy_feedback']['released'] for c in rows[1]['batch_calls'])
                assert [len(r['image_delivery']) for r in rows]==[0,2,0]
                assert (path/'image-000.png').read_bytes()!=(path/'image-001.png').read_bytes()
            if mode=='queries':assert all(c['tool_output']['items'] for c in batch)
        events=[json.loads(l)['event'] for l in (path/'events.jsonl').read_text().splitlines()]
        assert events.index('evaluation_completed')<events.index('environment_close_started')
        return {'mode':mode,'passed':True,'trace':str(path),'http_mock_requests':len(requests),'state':state,'summary':s}
    finally:backend.close();server.shutdown();server.server_close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    modes=['form','navigation','relabel','failure','invalid','vision','queries','reload','terminal']
    with ProcessPoolExecutor(max_workers=4,mp_context=multiprocessing.get_context('spawn')) as pool:
        cases=list(pool.map(run_case,[(m,str(a.output/m)) for m in modes]))
    files=[*sorted((ROOT/'intent_browser').glob('*.py')),Path(__file__).resolve()]
    report={'passed':True,'model_calls':0,'cases':cases,'source_sha256':{str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}}
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(a.output/'report.json')
