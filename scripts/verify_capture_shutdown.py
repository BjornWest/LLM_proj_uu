"""Actual runner snapshot-read and terminal-cleanup failure tests; no model calls."""
from verify_native_quarantine import *
import httpx
from intent_browser.backend import ChatCompletionsBackend
from intent_browser.ax_explorer import AXConfig
from intent_browser.standard_profile import tokenizer_path
from intent_browser.harness import native_tools_profile
from intent_browser.open_internet import open_profile,with_human_handover
from intent_browser.runner import run_episode
from intent_browser.browser_feedback import CoreBrowserFeedback
from playwright.sync_api import BrowserContext

CASES=('cached_query','feedback_shutdown','feedback_deadline','close_deadline',
       'chat_context_deadline','task_context_deadline','task_teardown_error')

def run_shutdown(args):
    mode,output=args;out=Path(output);out.mkdir(parents=True,exist_ok=False)
    profile=with_human_handover(open_profile(native_tools_profile(parallel_tool_calls=None,compact_feedback=True,
        ax_config=AXConfig(tokenizer_path(),incremental=True),batch_size=8)),wait_for_human=False,compact_tabs=True,stable_frames=True,
        capture_timeout_mode='bounded' if mode=='cached_query' else 'diagnostic')
    held={};requests=[];blocked=[];cleanup_calls=[];armed=False;native=Frame.evaluate
    class Task(OpenEndedTask):
        def setup(self,page):
            page.route('**/*',lambda r:r.fulfill(content_type='text/html',body=(
                '<h1>Useful main page</h1><iframe src="http://child.invalid/bad"></iframe>' if r.request.url.startswith(ORIGIN)
                else '<h2>Child content</h2>')))
            return super().setup(page)
        def teardown(self):
            if mode=='task_teardown_error':raise RuntimeError('Injected task teardown failure')
            return super().teardown()
    def factory(_):
        env=BrowserEnv(task_entrypoint=Task,task_kwargs={'start_url':ORIGIN,'goal':'Inspect the main page and finish.'},headless=True,
            action_mapping=make_action_set(profile.tools.names).to_python_code)
        held['env']=env
        if mode=='close_deadline':env.close=lambda:env.page.evaluate('()=>new Promise(()=>{})')
        return env
    def transport(req):
        nonlocal armed
        request=json.loads(req.content);requests.append(request);n=len(requests)
        if n==1:armed=True;name,arguments='ax_search',{'query':'Useful main'}
        else:name,arguments='send_msg_to_user',{'text':'Inspected main-page evidence.'}
        return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
            'tool_calls':[{'id':f'call-{n}','type':'function','function':{'name':name,'arguments':json.dumps(arguments)}}]}}]})
    def evaluate(frame,expr,*a,**kw):
        if armed and mode=='cached_query' and frame.url.startswith('http://child.invalid') and expr==START:
            blocked.append(len(requests));return native(frame,'()=>new Promise(()=>{})')
        if mode=='feedback_shutdown' and expr=='(key) => window[key]?.close()':
            cleanup_calls.append(1);return native(frame,'()=>new Promise(()=>{})')
        return native(frame,expr,*a,**kw)
    old_shutdown=CoreBrowserFeedback.close_for_context_shutdown
    def shutdown(self,env):
        if mode=='feedback_deadline':env.page.evaluate('()=>new Promise(()=>{})')
        return old_shutdown(self,env)
    native_close=BrowserContext.close
    def close_context(context,*a,**kw):
        env=held['env'];chat=getattr(env,'chat',None)
        if mode=='chat_context_deadline' and chat is not None and context is chat.context:
            return env.page.evaluate('()=>new Promise(()=>{})')
        if mode=='task_context_deadline' and context is env.context:
            return env.page.evaluate('()=>new Promise(()=>{})')
        return native_close(context,*a,**kw)
    backend=ChatCompletionsBackend('https://offline.invalid/v1','scripted');backend.client.close()
    backend.client=httpx.Client(transport=httpx.MockTransport(transport));backend.requires_browser_thread=True
    try:
        with patch.object(Frame,'evaluate',evaluate),patch.object(CoreBrowserFeedback,'close_for_context_shutdown',shutdown),patch.object(BrowserContext,'close',close_context):
            path,summary=run_episode(factory,backend,{'driver':'scripted_terminal_cleanup','model_calls':0},output=out/'runs',max_steps=2,
                harness_profile=profile,human_handover=HumanHandoverController(),observation_pipeline=ObservationPipelineConfig((),full_capture_only=True))
    finally:backend.close()
    rows=[json.loads(s) for s in (path/'steps.jsonl').read_text().splitlines()]
    events=[json.loads(s) for s in (path/'events.jsonl').read_text().splitlines()]
    assert len(requests)==2 and rows[0]['batch_calls'][0]['observation_reused']
    assert not rows[0]['batch_calls'][0].get('not_executed')
    # Guard used cached AX, not full marking between response and local query.
    query=next(i for i,e in enumerate(events) if e['event']=='captured_ax_query')
    done=next(i for i in range(query,len(events)) if events[i]['event']=='tool_completed')
    assert not any(e['event']=='native_capture_completed' for e in events[query:done])
    start=next(i for i,e in enumerate(events) if e['event']=='environment_close_started')
    evaluation=next(i for i,e in enumerate(events) if e['event']=='evaluation_completed')
    assert start==evaluation+1
    if mode=='cached_query':assert blocked==[1],blocked
    if mode=='feedback_shutdown':assert not cleanup_calls
    phases={e['phase']:e for e in events if e['event']=='cleanup_phase_completed'}
    if mode=='feedback_deadline':
        assert phases['feedback']['error'] and 1.9<=phases['feedback']['seconds']<3
        assert not phases['task_context_close']['error']
    if mode=='close_deadline':
        assert summary['error'] and phases['browsergym_close']['error']
        assert 4.9<=phases['browsergym_close']['seconds']<6
        assert not phases['browser_close_fallback']['error']
    elif mode in ('chat_context_deadline','task_context_deadline','task_teardown_error'):
        failed={'chat_context_deadline':'chat_context_close','task_context_deadline':'task_context_close',
            'task_teardown_error':'task_teardown'}[mode]
        assert summary['error'] and phases[failed]['error']
        if mode.endswith('deadline'):assert 4.9<=phases[failed]['seconds']<6
        assert not phases['chat_browser_close']['error'] and not phases['task_browser_close']['error']
        assert held['env'].chat is None and held['env'].browser is None
        before=json.loads((path/'evaluation-before-close.json').read_text())
        assert before['technical_error'] is None and summary['execution_error'] is None
        assert summary['cleanup_errors'] and summary['stop_reason']=='agent_finished'
    else:assert summary['error'] is None,summary
    result={'passed':True,'case':mode,'trace':str(path),'summary':summary,'cleanup':phases,'blocked_marker_calls':blocked,'model_calls':0}
    write_json(out/'report.json',result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    sources=[*Path('intent_browser').glob('*.py'),Path(__file__)];hashes=lambda:{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources};before=hashes()
    with ProcessPoolExecutor(max_workers=3,mp_context=multiprocessing.get_context('spawn')) as pool:
        cases=list(pool.map(run_shutdown,[(m,str(a.output/m)) for m in CASES]))
    assert hashes()==before
    write_json(a.output/'report.json',{'passed':True,'cases':cases,'source_sha256':before,'model_calls':0})
