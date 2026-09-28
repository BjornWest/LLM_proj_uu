"""Local mocked inference through actual runner during continuing iframe churn."""
from verify_human_capture_race import *
import httpx,time
from intent_browser.backend import ChatCompletionsBackend
from intent_browser.ax_explorer import AXConfig
from intent_browser.standard_profile import tokenizer_path
from intent_browser.harness import native_tools_profile
from intent_browser.open_internet import open_profile,with_human_handover
from intent_browser.runner import run_episode


def main(out):
    out.mkdir(parents=True,exist_ok=False);held={};requests=[];actions=[];state={};armed=False;churn=0
    profile=with_human_handover(open_profile(native_tools_profile(parallel_tool_calls=None,compact_feedback=True,
        ax_config=AXConfig(tokenizer_path(),incremental=True),batch_size=8)),wait_for_human=True,compact_tabs=True,stable_frames=True)
    class Task(OpenEndedTask):
        def setup(self,page):
            def route(r):
                html=("<h1>Stable product page</h1><button id=accept onclick='window.commits++;this.disabled=true'>Consent</button>"
                    "<iframe src='http://ad.invalid/'></iframe><script>window.commits=0</script>" if r.request.url.startswith(ORIGIN)
                    else '<h2>Changing advertisement</h2><button>Advertisement action</button>')
                r.fulfill(content_type='text/html',body=html)
            page.route('**/*',route);return super().setup(page)
    def factory(_):
        env=BrowserEnv(task_entrypoint=Task,task_kwargs={'start_url':ORIGIN,'goal':'Accept once and inspect the product page.'},headless=True,
            action_mapping=make_action_set(profile.tools.names).to_python_code)
        held['env']=env;reset=env.reset;close=env.close
        original_step={}
        def tracked(action):
            nonlocal armed
            actions.append(action)
            if action.startswith('click('):armed=True
            return original_step['fn'](action)
        def closing():state['commits']=env.page.evaluate('window.commits');return close()
        def resetting(*a,**kw):
            result=reset(*a,**kw);original_step['fn']=env.step;env.step=tracked;return result
        env.reset=resetting;env.close=closing;return env
    native=capture_native
    def capture(view,budget):
        nonlocal churn
        obs=native(view,budget)
        if armed:
            child=next(f for f in view.page.frames if f is not view.page.main_frame)
            churn+=1;child.goto(f'http://ad.invalid/?generation={churn}')
        return obs
    def transport(req):
        request=json.loads(req.content);requests.append(request);n=len(requests)
        if n==1:
            name,args='click',{'bid':held['env'].page.locator('#accept').get_attribute('bid')}
        elif n==2:
            assert 'FRAME COVERAGE' in json.dumps(request['messages'])
            assert 'UNKNOWN' in json.dumps(request['messages'])
            name,args='ax_search',{'query':'Stable product'}
        else:name,args='send_msg_to_user',{'text':'Inspected the stable product page; the changing frame remains unobserved.'}
        return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
            'tool_calls':[{'id':f'call-{n}','type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}}]})
    backend=ChatCompletionsBackend('https://offline.invalid/v1','scripted');backend.client.close()
    backend.client=httpx.Client(transport=httpx.MockTransport(transport));backend.requires_browser_thread=True
    sources=[*Path('intent_browser').glob('*.py'),Path(__file__)];hashes=lambda:{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources};before=hashes()
    try:
        with patch('intent_browser.human_browser.capture_native',capture):
            path,summary=run_episode(factory,backend,{'driver':'scripted_churn_after_consent','model_calls':0},output=out/'runs',max_steps=3,
                harness_profile=profile,human_handover=HumanHandoverController(),observation_pipeline=ObservationPipelineConfig((),full_capture_only=True))
    finally:backend.close()
    assert before==hashes()
    rows=[json.loads(x) for x in (path/'steps.jsonl').read_text().splitlines()]
    assert summary['error'] is None and summary['stop_reason']=='agent_finished',summary
    assert state['commits']==1 and len([a for a in actions if a.startswith('click(')])==1,actions
    assert len(requests)==3 and all(not c.get('not_executed') and not c.get('action_error') for r in rows for c in r['batch_calls'])
    assert rows[0]['batch_calls'][0]['action_execution']['action_error']==''
    write_json(out/'report.json',{'passed':True,'trace':str(path),'summary':summary,'actions':actions,'churn_events':churn,
        'model_calls':0,'scripted_requests':len(requests),'source_sha256':before})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();main(a.output)
