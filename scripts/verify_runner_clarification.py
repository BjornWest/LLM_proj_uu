"""Actual BrowserGym clarification rehearsal, scripted HTTP transport; no model calls."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from browsergym.core.env import BrowserEnv
from browsergym.core.task import OpenEndedTask
from intent_browser.actions import make_action_set
from intent_browser.backend import ChatCompletionsBackend
from intent_browser.harness import native_tools_profile, with_clarification
from intent_browser.ax_explorer import AXConfig
from intent_browser.standard_profile import tokenizer_path
from intent_browser.runner import run_episode
from intent_browser.trace import write_json

HTML='''<!doctype html><title>Clarification rehearsal</title><main>
<label>Note <input id=note></label><label>Size <input id=size></label>
<button type=button onclick="document.querySelector('#receipt').textContent=document.querySelector('#size').value">Save</button>
<p id=receipt></p></main>'''


def run(out,fail=False):
    held={};requests=[];questions=[];counts=[];actions=[]
    profile=with_clarification(native_tools_profile(parallel_tool_calls=None, compact_feedback=True,
        ax_config=AXConfig(tokenizer_path(),incremental=True),batch_size=8))
    class Task(OpenEndedTask):
        def setup(self,page):
            page.route('http://clarification.invalid/**',lambda route:route.fulfill(content_type='text/html',body=HTML))
            return super().setup(page)
        def validate(self,page,chat_messages):
            counts.append(page.locator('#size').input_value())
            return super().validate(page,chat_messages)
    class Env(BrowserEnv):
        def step(self,action):actions.append(action);return super().step(action)
    def factory(video):
        env=Env(task_entrypoint=Task,task_kwargs={'start_url':'http://clarification.invalid/',
            'goal':'Keep my note, ask my size, and save that size.'},headless=True,
            action_mapping=make_action_set().to_python_code)
        held['env']=env;return env
    def callback(question):
        page=held['env'].page
        assert page.locator('#note').input_value()=='Keep this note'
        assert page.locator('#size').input_value()==''
        questions.append(question);held['page']=page;held['validate_at_ask']=len(counts)
        if fail:raise RuntimeError('Scripted responder unavailable')
        return 'Please use EU 40.\nThank you.'
    def transport(req):
        requests.append(json.loads(req.content));page=held['env'].page;n=len(requests)
        def bid(selector):return page.locator(selector).get_attribute('bid')
        if n==1:
            calls=[('fill',{'bid':bid('#note'),'value':'Keep this note'}),
                   ('ask_user',{'question':'Which size would you like?'})]
        elif n==2:
            assert page is held['page']
            assert len(counts)==held['validate_at_ask'], 'ask_user stepped or validated the environment'
            assert 'Please use EU 40.' in json.dumps(requests[-1]['messages'])
            calls=[('fill',{'bid':bid('#size'),'value':'EU 40'}),('click',{'bid':bid('button')})]
        else:
            assert page.locator('#receipt').inner_text()=='EU 40'
            calls=[('send_msg_to_user',{'text':'Saved EU 40 and kept your note.'})]
        return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':{
            'role':'assistant','content':None,'tool_calls':[{'id':f'call-{n}-{i}','type':'function',
            'function':{'name':name,'arguments':json.dumps(args)}} for i,(name,args) in enumerate(calls)]}}]})
    backend=ChatCompletionsBackend('https://offline.invalid/v1','scripted-clarification')
    backend.client.close();backend.client=httpx.Client(transport=httpx.MockTransport(transport))
    try:
        path,summary=run_episode(factory,backend,{'task':'clarification-rehearsal','inference':'offline scripted transport'},
            output=out,max_steps=4,harness_profile=profile,clarification_callback=callback,
            clarification_audit_id='private-scripted-callback')
    finally:backend.close()
    rows=[json.loads(line) for line in (path/'steps.jsonl').read_text().splitlines()]
    reply_artifact=json.loads(next(path.glob('clarification-*.json')).read_text())
    assert len(questions)==1
    assert not any('ask_user' in action for action in actions)
    assert 'private-scripted-callback' not in json.dumps(requests)
    assert summary['action_error_count']==0
    if fail:
        assert 'Scripted responder unavailable' in summary['error']
        assert len(requests)==1 and len(actions)==1 and reply_artifact['reply'] is None
    else:
        assert summary['error'] is None and summary['stop_reason']=='agent_finished'
        assert len(requests)==3 and len(actions)==4
        assert rows[0]['batch_stop_reason']=='clarification_boundary'
        assert any(i['kind']=='clarification_result' and i['confirmed']
                   for i in rows[1]['policy_delivery']['items'])
    return {'trace':str(path.resolve()),'passed':True,'callback_failure':fail,'requests':len(requests),
            'browser_steps':len(actions),'actual_model_calls':0,'summary':summary}


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    paths=['intent_browser/runner.py','intent_browser/clarification.py','intent_browser/native_tools.py',
           'intent_browser/harness.py','intent_browser/policy_delivery.py',__file__]
    hashes={str(path):hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in paths}
    result={'cases':[run(args.output/'success'),run(args.output/'failure',True)],'actual_model_calls':0}
    assert hashes=={str(path):hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in paths}, 'Source changed during browser validation'
    result['source_sha256']=hashes
    write_json(args.output/'report.json',result)

if __name__=='__main__':main()
