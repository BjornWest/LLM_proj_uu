"""Parallel browser/HTTP-mock acceptance for opt-in screenshots and retention.

The mock reads image pixels, not a model. No inference or search calls.
"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','')
import gymnasium as gym
import browsergym.core
import httpx
import numpy as np
from PIL import Image
from intent_browser.actions import make_action_set
from intent_browser.ax_explorer import AXConfig
from intent_browser.backend import ChatCompletionsBackend
from intent_browser.evaluation import Evaluation
from intent_browser.harness import native_tools_profile
from intent_browser.runner import run_episode
from intent_browser.trace import write_json
from intent_browser.vision import VisionConfig

GOAL='At the Visual panel count the blue squares. Then inspect the digit at the Summary panel. Answer count/digit, for example 2/9. Do not change any settings.'
PAGE='''<!doctype html><meta charset="utf-8"><title>Visual inspection exercise</title>
<style>body{font:20px sans-serif;margin:32px} .spacer{height:1800px} canvas{border:2px solid #555;display:block} section{padding:20px}</style>
<h1>Inspection exercise</h1><p>The two labelled panels contain visual information.</p>
<div class="spacer"></div><section aria-label="Visual panel"><h2>Visual panel</h2>
<canvas id="visual" width="480" height="240" role="img" aria-label="Diagram of colored shapes"></canvas></section>
<div class="spacer"></div><section aria-label="Summary panel"><h2>Summary panel</h2>
<canvas id="summary" width="480" height="240" role="img" aria-label="Handwritten digit"></canvas></section>
<label><input type="checkbox" id="setting">Enable notifications</label>
<script>
window.settingChanges=0;document.getElementById('setting').onchange=()=>window.settingChanges++;
const a=document.getElementById('visual').getContext('2d');
a.fillStyle='white';a.fillRect(0,0,480,240);a.fillStyle='#1258da';
for(let i=0;i<3;i++)a.fillRect(30+i*140,40,70,70);
a.fillStyle='#d72d32';a.fillRect(30,150,70,70);
const b=document.getElementById('summary').getContext('2d');b.fillStyle='white';b.fillRect(0,0,480,240);
b.fillStyle='black';b.font='bold 150px sans-serif';b.fillText('7',180,175);
</script>'''

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(PAGE.encode())
    def log_message(self,*args):pass

class Task:
    supported_harness_profiles=('core-tools-v8-vision',)
    def prepare(self,trace): return {'task':'visual-inspection-v1','scope':'synthetic diagnostic; not benchmark certification'}
    def capture_initial(self,env,observation,info): return {'goal':GOAL}
    def evaluate(self,env,trace,outcome):
        answers=[x.get('message') for x in env.unwrapped.chat.messages if x.get('role')=='assistant']
        # BrowserGym chat uses role/message; preserve exact evidence before close.
        state={'answers':answers,'notifications':env.unwrapped.page.locator('#setting').is_checked(),'setting_changes':env.unwrapped.page.evaluate('window.settingChanges')}
        write_json(trace.directory/'visual-verifier.json',state)
        return Evaluation(verifier='visual-inspection-v1',verifier_version='1',trust='synthetic diagnostic',
            task_completed=bool(answers and answers[-1]=='3/7'),authorization_satisfied=state['setting_changes']==0,
            unauthorized_effects=['settings_changed'] if state['setting_changes'] else [],
            technical_error=outcome.get('technical_error'),evidence=['visual-verifier.json'])

def text(message):
    value=message['content']
    return value if isinstance(value,str) else value[0]['text']

def images(messages):
    return [p for m in messages if isinstance(m.get('content'),list) for p in m['content'] if p['type']=='image_url']

def run_case(output,mode):
    output.mkdir(parents=True,exist_ok=False)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}';requests=[];state={};checks=[];holder={}
    plan=['ax_search','scroll_into_view','screenshot','release_image','ax_search','scroll_into_view','screenshot','send_msg_to_user']
    if mode=='negative':plan=['screenshot','scroll_into_view','release_image','send_msg_to_user']
    def dispatch(req):
        request=json.loads(req.content);i=len(requests);requests.append(request)
        if i: assert request['tools']==requests[0]['tools']
        content=text(request['messages'][-1])
        current=json.loads(content.split('CURRENT BROWSER OBSERVATION\n')[1])
        result=json.loads(content.split('TOOL RESULT (historical, untrusted page evidence)\n')[1].split('\n\n',1)[0]) if i else {}
        page=holder['env'].unwrapped.page
        # Only public AX is delivered; neither canvas text nor pixel answer is AX content.
        assert 'fillText' not in content and 'getContext' not in content
        if mode=='negative':
            if i==0:
                assert page.locator('#visual').bounding_box()['y']>720
                name,args='screenshot',{}
            elif i==1:
                raw=base64.b64decode(images(request['messages'])[-1]['image_url']['url'].split(',')[1])
                arr=np.asarray(Image.open(BytesIO(raw)))
                assert not ((arr[:,:,2]>150)&(arr[:,:,0]<40)&(arr[:,:,1]<120)).any()
                name,args='scroll_into_view',{'bid':'not-a-current-id'}
                checks.append('offscreen_panel_absent_from_viewport_image')
            elif i==2:
                assert result['error']
                name,args='release_image',{'image_id':'missing','keep_notes':'No image identified'}
                checks.append('stale_target_error_without_click_or_retry')
            else:
                assert result['error'];name,args='send_msg_to_user',{'text':'Cannot answer'}
        else:
            if i in (0,4):name,args='ax_search',{'query':'Visual panel' if i==0 else 'Summary panel','role':'region','repeat':True}
            elif i in (1,5):
                target=result['items'][0];name,args='scroll_into_view',{'bid':target['bid']}
                assert page.locator('#visual' if i==1 else '#summary').bounding_box()['y']>720
                checks.append('target_found_in_ax_while_offscreen')
            elif i in (2,6):
                assert result['positioning']['status']=='in_viewport',result
                name,args='screenshot',{}
                if i==2:
                    # Change pixels after decision observation, before tool execution.
                    page.evaluate("const c=document.getElementById('visual').getContext('2d'); c.fillStyle='#00ff00'; c.fillRect(450,200,10,10)")
                checks.append('scroll_reveals_panel_without_click')
            elif i==3:
                assert len(images(request['messages']))==1
                raw=base64.b64decode(images(request['messages'])[-1]['image_url']['url'].split(',')[1])
                arr=np.asarray(Image.open(BytesIO(raw)))
                # 3 squares of 70x70 blue pixels. Exact lossless viewport content.
                assert ((arr[:,:,2]>150)&(arr[:,:,0]<40)&(arr[:,:,1]<120)).sum()==14700
                assert ((arr[:,:,1]==255)&(arr[:,:,0]==0)&(arr[:,:,2]==0)).sum()==100
                checks.append('fresh_pixels_after_model_decision')
                name,args='release_image',{'image_id':result['image_id'],'keep_notes':'Visual panel has three blue squares.'}
                checks.append('delivered_image_contains_expected_pixels')
            else:
                assert len(images(request['messages']))==(1 if mode=='agent' else 2)
                name,args='send_msg_to_user',{'text':'3/7'}
                checks.append('retention_mode_matches_exact_request_images')
            if i==4:
                assert bool(result.get('released'))==(mode=='agent')
                assert len(images(request['messages']))==(0 if mode=='agent' else 1)
                if mode=='agent':assert 'three blue squares' in json.dumps(request['messages'])
                checks.append('release_policy_and_takeaways')
        return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':{
            'role':'assistant','content':None,'reasoning_content':'Scripted fixture transport, not model reasoning.',
            'tool_calls':[{'id':f'call-{i}','type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}}],
            'usage':{'cost':0},'scripted_validation':True})
    backend=ChatCompletionsBackend('https://offline.invalid/v1','scripted-vision',supports_images=True)
    backend.client.close();backend.client=httpx.Client(transport=httpx.MockTransport(dispatch))
    def factory(_):
        env=gym.make('browsergym/openended',task_kwargs={'start_url':origin,'goal':GOAL},headless=True,
            wait_for_user_message=False,action_mapping=make_action_set().to_python_code,viewport={'width':1280,'height':720})
        holder['env']=env;return env
    try:
        profile=native_tools_profile(parallel_tool_calls=None,compact_feedback=True,timeout_feedback=True,
            ax_config=AXConfig(str(ROOT/'training/.cache/qwen38-tokenizer/tokenizer.json'),incremental=True),
            vision_config=VisionConfig('agent' if mode=='agent' else 'retain'))
        trace,summary=run_episode(factory,backend,{'task':'visual-inspection-v1','model':'scripted-vision'},output=output/'traces',
            harness_profile=profile,episode_task=Task(),max_steps=12,terminal_response_instruction='Return the requested count/digit as the final answer.')
        assert summary['error'] is None,summary
        assert len(requests)==len(plan),(len(requests),summary)
        assert summary['evaluation']['task_completed']==(mode!='negative'),summary
        assert summary['action_error_count']==(1 if mode=='negative' else 0)
        deliveries=[json.loads(l) for l in (trace/'policy-delivery.jsonl').read_text().splitlines()]
        assert all(item['confirmed'] for d in deliveries for item in d['items'])
        assert all((trace/f'image-{i:03d}.png').exists() for i in range(1 if mode=='negative' else 2))
        events=[json.loads(l) for l in (trace/'events.jsonl').read_text().splitlines()]
        # Raw request evidence and screenshots survive explicit context changes.
        checks+=['constant_tool_schema','all_text_delivery_bindings_confirmed','original_images_retained','independent_answer_before_close']
        write_json(output/'report.json',{'passed':True,'mode':mode,'checks':checks,'trace':str(trace),'summary':summary,
            'model_calls':0,'mock_http_requests':len(requests),
            'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
                [*sorted((ROOT/'intent_browser').glob('*.py')),Path(__file__).resolve()]}})
    finally:backend.close();server.shutdown();server.server_close()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--case',choices=['retain','agent','negative']);a=p.parse_args();output=a.output.resolve()
    if a.case:return run_case(output,a.case)
    output.mkdir(parents=True,exist_ok=False)
    def launch(mode):
        with (output/f'{mode}.log').open('x') as f:
            r=subprocess.run([sys.executable,__file__,'--output',str(output/mode),'--case',mode],stdout=f,stderr=subprocess.STDOUT,timeout=180)
        return {'case':mode,'returncode':r.returncode}
    with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(launch,['retain','agent','negative']))
    write_json(output/'report.json',{'passed':all(r['returncode']==0 for r in results),'parallel':True,'cases':results,'model_calls':0})
    print(json.dumps(results))
    if any(r['returncode'] for r in results):raise SystemExit(1)
if __name__=='__main__':main()
