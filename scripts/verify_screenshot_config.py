"""Automatic screenshot opt-out across capture paths; scripted, no model calls."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import gzip
import hashlib
import json
import multiprocessing
from pathlib import Path
import sys
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import httpx
from browsergym.core.env import BrowserEnv
from browsergym.core.task import OpenEndedTask
from playwright.sync_api import CDPSession, Page
from intent_browser.actions import make_action_set
from intent_browser.backend import ChatCompletionsBackend
from intent_browser.runner import run_episode
from intent_browser.standard_profile import standard_profile
from intent_browser.observation_pipeline import ObservationPipelineConfig
from intent_browser.open_internet import open_profile, with_human_handover
from intent_browser.human_handover import HumanHandoverController
from intent_browser.trace import write_json

CASES=('off','on','static_off','fallback_off','config_off','human_off','human_dynamic_off')


def case(args):
    name,directory=args;out=Path(directory);out.mkdir(parents=True,exist_ok=False)
    profile=standard_profile(helpers=False,data_tools=False)
    options={};requests=[];captures=[];held={}
    if name!='on':options['trace_screenshots']=False
    if name=='static_off':options['observation_pipeline']=ObservationPipelineConfig(('http://fixture.invalid',))
    if name in ('fallback_off','config_off'):
        options['observation_pipeline']=ObservationPipelineConfig((),full_capture_only=True,trace_screenshots=name!='config_off')
        if name=='config_off':options.pop('trace_screenshots')
    if name.startswith('human'):
        profile=with_human_handover(open_profile(profile),stable_frames=True,capture_timeout_mode='diagnostic')
        options.update(human_handover=HumanHandoverController(),observation_pipeline=ObservationPipelineConfig(
            (),full_capture_only=True,dynamic_preview=name=='human_dynamic_off'))
    class Fixture(OpenEndedTask):
        def setup(self,page):
            page.route('**/*',lambda r:r.fulfill(content_type='text/html',body='<h1>Local capture test</h1><button>Commit</button>'))
            return super().setup(page)
    def factory(video):
        env=BrowserEnv(task_entrypoint=Fixture,task_kwargs={'start_url':'http://fixture.invalid/main','goal':'Inspect the viewport and finish.'},
                       headless=True,action_mapping=make_action_set(profile.tools.names).to_python_code)
        held['env']=env;return env
    def respond(req):
        row=json.loads(req.content);requests.append(row)
        name,args=(('screenshot',{}) if len(requests)==1 else ('noop',{}) if len(requests)==2 else ('send_msg_to_user',{'text':'Done'}))
        return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
            'tool_calls':[{'id':f'call-{len(requests)}','type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}}],
            'usage':{'prompt_tokens':100,'completion_tokens':10,'cost':0}})
    backend=ChatCompletionsBackend('https://offline.invalid/v1','scripted',supports_images=True)
    backend.client.close();backend.client=httpx.Client(transport=httpx.MockTransport(respond))
    original=CDPSession.send;original_page=Page.screenshot
    def send(self,method,*args,**kwargs):
        if method=='Page.captureScreenshot':captures.append({'api':'CDP','requests_completed':len(requests)})
        return original(self,method,*args,**kwargs)
    def screenshot(self,*args,**kwargs):
        captures.append({'api':'Page','requests_completed':len(requests)})
        return original_page(self,*args,**kwargs)
    try:
        with patch.object(CDPSession,'send',send),patch.object(Page,'screenshot',screenshot):
            path,summary=run_episode(factory,backend,{'case':name},out/'runs',max_steps=3,harness_profile=profile,**options)
    finally:backend.close()
    assert summary['error'] is None,summary
    assert summary['stop_reason']=='agent_finished',summary
    assert summary['action_error_count']==0
    enabled=name=='on'
    assert json.loads((path/'metadata.json').read_text())['trace_screenshots']==enabled
    obs_files=list(path.glob('*observation-*.json.gz'));assert obs_files
    pngs=list(path.glob('*observation-*.png'))
    assert bool(pngs)==enabled,(name,pngs)
    for p in obs_files:
        obs=json.loads(gzip.decompress(p.read_bytes()))
        assert obs['axtree_object']['nodes']
    assert len(requests)==3
    # Image explicitly requested on turn 1 reaches the next model input.
    assert any(isinstance(m.get('content'),list) and any(x.get('type')=='image_url' for x in m['content']) for m in requests[1]['messages'])
    assert requests[0]['tools']==requests[1]['tools']==requests[2]['tools']
    if not enabled:
        assert captures and all(c['requests_completed']==1 for c in captures),captures
        assert len(captures)==1,captures
    else:assert any(c['requests_completed']==0 for c in captures)
    report={'passed':True,'case':name,'automatic_screenshots':enabled,'captures':captures,
            'observation_files':len(obs_files),'automatic_pngs':len(pngs),'explicit_image_delivered':True,
            'tools_unchanged':True,'trace':str(path),'model_calls':0}
    write_json(out/'report.json',report);return report


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    paths=[*Path('intent_browser').glob('*.py'),Path(__file__)]
    hashes=lambda:{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    before=hashes()
    with ProcessPoolExecutor(max_workers=2,mp_context=multiprocessing.get_context('spawn')) as pool:
        results=list(pool.map(case,[(c,str(a.output/c)) for c in CASES]))
    assert hashes()==before
    write_json(a.output/'report.json',{'passed':True,'cases':results,'source_sha256':before,'model_calls':0})

if __name__=='__main__':main()
