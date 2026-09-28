"""Runner + native chat and dynamic-page regression; local mock inference only."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import multiprocessing
import re
from pathlib import Path
import socket
import sys
from threading import Event, Thread
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import httpx
from browsergym.core.env import BrowserEnv
from browsergym.core.task import OpenEndedTask
from playwright.sync_api import BrowserType, sync_playwright
from intent_browser.actions import make_action_set
from intent_browser.ax_explorer import AXConfig
from intent_browser.backend import ChatCompletionsBackend
from intent_browser.harness import native_tools_profile
from intent_browser.human_handover import HumanHandoverController
from intent_browser.human_handover_ui import HumanHandoverUI
from intent_browser.observation_pipeline import ObservationPipelineConfig
from intent_browser.open_internet import open_profile,with_human_handover
from intent_browser.runner import run_episode
from intent_browser.standard_profile import tokenizer_path

PAGE='''<!doctype html><title>Local store</title><h1>Search catalogue</h1>
<label>Search <input type=search></label><article id=carousel><h2>News</h2></article>
<button id=commit onclick="window.commits++">Save</button><script>window.commits=0</script>'''
NOTE='Please stop the pending action and tell me what happened.'


def port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]


def run_case(args):
    mode,out=args;out=Path(out);out.mkdir(parents=True,exist_ok=False)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body=PAGE.encode();self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def log_message(self,*a):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    agent_port,chat_port=port(),port();controller=HumanHandoverController();ui=HumanHandoverUI(controller)
    held={};requests=[];state={};errors=[];thread=None
    profile=with_human_handover(open_profile(native_tools_profile(compact_feedback=True,parallel_tool_calls=None,
        ax_config=AXConfig(tokenizer_path(),incremental=True),batch_size=8)))
    def factory(_):
        env=BrowserEnv(task_entrypoint=OpenEndedTask,task_kwargs={'start_url':origin,'goal':'Inspect the local catalogue.'},
            headless=True,action_mapping=make_action_set(profile.tools.names).to_python_code)
        held['env']=env;close=env.close
        def end():
            state['commits']=sum(p.evaluate('window.commits || 0') for p in env.context.pages)
            state['page_count']=len(env.context.pages)
            state['chat']=env.chat.messages
            state['embedded']=env.chat.page.locator('#human-handover-controls').count()
            return close()
        env.close=end;return env
    def human(done):
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.connect_over_cdp(f'http://127.0.0.1:{chat_port}')
                page=browser.contexts[0].pages[0]
                # Queue the real upstream JS binding without waiting for its
                # Playwright-owner callback while that owner is in model I/O.
                page.evaluate("text=>{window.chatDelivery=send_user_message(text)}",NOTE)
                if mode=='duplicate_chat':page.evaluate("text=>{window.chatDelivery2=send_user_message(text)}",NOTE)
                done.set()
                # Retain the independent connection until the owner resumes.
                held['human_release'].wait(20)
        except Exception as e:errors.append(str(e));done.set()
    def transport(req):
        nonlocal thread
        body=json.loads(req.content);requests.append(body);n=len(requests);env=held['env']
        if mode.startswith('confirm_') and n>1:
            if n==2:
                content='\n'.join(m['content'] for m in body['messages'] if m['role']=='tool')
                held['confirmation_id']=re.findall(r'"confirmation_id": "(proceed-[0-9]+)"',content)[-1]
                assert 'change_review' in content and 'before' in content and 'after' in content
            if mode=='confirm_inspect' and n==2:
                choices=[('ax_search',{'query':['Search'],'limit':2})]
            elif n==(3 if mode=='confirm_inspect' else 2):
                env.page.locator('#carousel').evaluate("el=>el.innerHTML += '<p>Changed again since confirmation</p>'")
                if mode=='confirm_replace':env.page.locator('#commit').evaluate('el=>el.replaceWith(el.cloneNode(true))')
                if mode=='confirm_disabled':env.page.locator('#commit').evaluate('el=>el.disabled=true')
                if mode=='confirm_reload':env.page.reload()
                if mode=='confirm_close':env.page.close()
                if mode=='confirm_removed':env.page.locator('#commit').evaluate('el=>el.remove()')
                if mode=='confirm_human':controller.handover('tab-1','Human took over')
                if mode=='confirm_chat':
                    done=Event();held['human_release']=Event();thread=Thread(target=human,args=(done,),daemon=True);thread.start()
                    assert done.wait(15) and not errors,errors
                if mode=='confirm_error':env.page.evaluate("()=>{const el=document.createElement('div');el.style='position:fixed;inset:0;z-index:9999';document.body.append(el)}")
                choices=[('proceed_action',{'confirmation_id':held['confirmation_id']})]
            elif n==3:
                choices=[('proceed_action',{'confirmation_id':held['confirmation_id']})]
            else:choices=[('send_msg_to_user',{'text':'Inspected the fresh state.'})]
        elif n==1:
            if mode in ('chat_action','chat_finish','duplicate_chat'):
                done=Event();held['human_release']=Event();thread=Thread(target=human,args=(done,),daemon=True);thread.start()
                assert done.wait(15) and not errors,errors
                choices=[('send_msg_to_user',{'text':'Stale finish'})] if mode=='chat_finish' else [('click',{'bid':env.page.locator('#commit').get_attribute('bid')})]
            elif mode=='workspace':choices=[('handover_tab',{'tab_id':'tab-1','reason':'Human verification required'})]
            else:
                # Page changes after exact request capture, before dispatch.
                env.page.locator('#carousel').evaluate("el=>el.innerHTML += '<button>Next</button>'")
                choices=([('click',{'bid':env.page.locator('#commit').get_attribute('bid')})] if mode.startswith('confirm_') else {
                    'carousel_search':[('ax_search',{'query':['Search'],'limit':2})],
                    'carousel_wait':[('noop',{'wait_ms':0})],
                    'carousel_goto':[('goto',{'url':origin+'/other'})],
                    'carousel_new_tab':[('new_tab',{})],
                    'carousel_click':[('click',{'bid':env.page.locator('#commit').get_attribute('bid')})],
                }[mode])
        elif mode=='workspace' and n==2:
            assert len(env.context.pages)==2
            assert env.page.url=='about:blank'
            choices=[('goto',{'url':origin+'/work'})]
        else:choices=[('send_msg_to_user',{'text':'Inspected the fresh state.'})]
        return httpx.Response(200,json={'usage':{'prompt_tokens':0,'completion_tokens':0},'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
            'tool_calls':[{'id':f'{n}-{i}','type':'function','function':{'name':name,'arguments':json.dumps(value)}} for i,(name,value) in enumerate(choices)]}}]})
    backend=ChatCompletionsBackend('https://offline.invalid/v1','mock');backend.client.close();backend.client=httpx.Client(transport=httpx.MockTransport(transport));backend.requires_browser_thread=True
    launch_count=0;original=BrowserType.launch
    def launch(browser_type,**kw):
        nonlocal launch_count
        launch_count+=1;kw['args']=[*kw.get('args',[]),f'--remote-debugging-port={agent_port if launch_count==1 else chat_port}']
        return original(browser_type,**kw)
    try:
        with patch.object(BrowserType,'launch',launch):
            path,summary=run_episode(factory,backend,{'driver':'scripted_chat_regression','model_calls':0},output=out/'runs',max_steps=4 if mode.startswith('confirm_') else 3,
                harness_profile=profile,human_handover=controller,human_handover_ui=ui,
                observation_pipeline=ObservationPipelineConfig((),full_capture_only=True))
    finally:
        if 'human_release' in held:held['human_release'].set()
        if thread:thread.join(timeout=5)
        backend.close();ui.close();server.shutdown();server.server_close()
    assert not errors,errors
    assert summary['error'] is None,summary
    rows=[json.loads(l) for l in (path/'steps.jsonl').read_text().splitlines()]
    events=[json.loads(l) for l in (path/'events.jsonl').read_text().splitlines()]
    assert any(e['event']=='human_chat_controls_attached' for e in events)
    assert state['embedded']==1
    first=rows[0]['batch_calls'][0]
    if mode.startswith('confirm_'):
        assert first['not_executed'] and first['policy_feedback']['confirmation']['confirmation_id']==held['confirmation_id']
        target=rows[2 if mode=='confirm_inspect' else 1]['batch_calls'][0]
        if mode in ('confirm_once','confirm_inspect'):
            assert target['action_dispatch_started'] and not target.get('action_error'),target
            assert state['commits']==1,state
            assert target['confirmation']['resolved_action'].startswith('click(')
        elif mode=='confirm_error':
            assert target['action_dispatch_started'] and target.get('action_error'),target
            assert state['commits']==0
        else:
            assert target['not_executed'] and not target['action_dispatch_started'],target
            assert state['commits']==0
        if mode!='confirm_inspect':
            repeated=rows[2]['batch_calls'][0]
            assert repeated['not_executed'] and repeated['policy_feedback']['reason']=='confirmation_unknown_expired_or_consumed'
        reviews=[e for e in events if e['event']=='human_tab_change_review']
        assert len(reviews)==1,reviews
    elif mode.startswith('chat_') or mode=='duplicate_chat':
        assert first['not_executed'] and first['policy_feedback']['reason']=='human_message_pending',first
        assert state['commits']==0 and not any(m['message']=='Stale finish' for m in state['chat'])
        count=2 if mode=='duplicate_chat' else 1
        assert sum(m['role']=='user' and m['content']==NOTE for m in requests[1]['messages'])==count
        assert not any(m.get('content')==NOTE for m in requests[0]['messages'])
        confirmed=[i for i in rows[1]['policy_delivery']['items'] if i['kind']=='human_message']
        assert len(confirmed)==count and all(i['confirmed'] for i in confirmed)
        assert requests[1]['messages'][:len(requests[0]['messages'])]==requests[0]['messages']
    elif mode=='carousel_click':
        assert first['not_executed'] and first['policy_feedback']['reason']=='tab_content_changed_since_decision'
        assert state['commits']==0
    else:
        assert first['action_dispatch_started'] and not first.get('not_executed') and not first.get('action_error'),first
        if mode=='carousel_search':assert not first.get('tool_error'),first
        if mode=='workspace':assert state['page_count']==2
    assert all(r['tools']==requests[0]['tools'] for r in requests)
    result={'passed':True,'case':mode,'trace':str(path),'summary':summary,'state':state,'model_calls':0,
        'scope':'Actual runner/native BrowserGym; scripted HTTP model responses, no external page or inference'}
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);p.add_argument('--cases',nargs='+',default=['chat_action','chat_finish','duplicate_chat','carousel_search','carousel_wait','carousel_goto','carousel_new_tab','carousel_click','workspace']);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    sources=list((ROOT/'intent_browser').glob('*.py'))+[Path(__file__).resolve()]
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    with ProcessPoolExecutor(max_workers=3,mp_context=multiprocessing.get_context('spawn')) as pool:
        cases=list(pool.map(run_case,[(mode,str(a.output/mode)) for mode in a.cases]))
    assert hashes=={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    (a.output/'report.json').write_text(json.dumps({'passed':True,'cases':cases,'model_calls':0,'source_sha256':hashes,
        'artifacts_sha256':{str(p.relative_to(a.output)):hashlib.sha256(p.read_bytes()).hexdigest() for p in a.output.rglob('*') if p.is_file()}},indent=2)+'\n')
