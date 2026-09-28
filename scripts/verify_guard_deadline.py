"""Offline post-capture guard stalls and races, using real local Chromium."""
from verify_capture_shutdown import *
from playwright.sync_api import BrowserContext,CDPSession
import intent_browser.human_browser as hb

CASES=('healthy','cookies','session_create','frame_tree','main_document','session_detach','navigation','custody')

def run_guard(args):
    mode,output=args;out=Path(output);out.mkdir(parents=True,exist_ok=False)
    profile=with_human_handover(open_profile(native_tools_profile(parallel_tool_calls=None,compact_feedback=True,
        ax_config=AXConfig(tokenizer_path(),incremental=True),batch_size=8)),wait_for_human=False,compact_tabs=True,stable_frames=True,
        capture_timeout_mode='bounded')
    held={};requests=[];blocked=[];armed=False;controller=HumanHandoverController()
    class Task(OpenEndedTask):
        def setup(self,page):
            self.page=page
            page.route('**/*',lambda r:r.fulfill(content_type='text/html',body='<h1>Guard target</h1><input id=target value=unchanged><script>window.inputs=0;target.oninput=()=>window.inputs++</script>'))
            return super().setup(page)
        def teardown(self):
            held['final']=self.page.evaluate('({value:target.value,inputs:window.inputs})')
            return super().teardown()
    def factory(_):
        env=BrowserEnv(task_entrypoint=Task,task_kwargs={'start_url':ORIGIN,'goal':'Fill the public input once.'},headless=True,
            action_mapping=make_action_set(profile.tools.names).to_python_code);held['env']=env;return env
    def transport(req):
        requests.append(json.loads(req.content));bid=held['env'].page.locator('#target').get_attribute('bid')
        return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
            'tool_calls':[{'id':'fill-1','type':'function','function':{'name':'fill','arguments':json.dumps({'bid':bid,'value':'updated'})}}]}}]})
    native_event=Trace.event
    def event(self,name,**data):
        nonlocal armed
        value=native_event(self,name,**data)
        if name=='native_capture_completed' and data.get('observed_at',{}).get('phase')=='batch_guard' and not armed:
            armed=True
            if mode=='navigation':held['env'].page.goto(ORIGIN+'/?new-document')
            if mode=='custody':controller.handover('tab-1','Synthetic post-capture custody change')
        return value
    def hang(label):
        blocked.append(label);return held['env'].page.evaluate('()=>new Promise(()=>{})')
    native_cookies=BrowserContext.cookies;native_create=BrowserContext.new_cdp_session;native_send=CDPSession.send;native_detach=CDPSession.detach
    def cookies(self,*a,**kw):
        if armed and mode=='cookies' and not blocked:return hang('cookies')
        return native_cookies(self,*a,**kw)
    def create(self,*a,**kw):
        if armed and mode=='session_create' and not blocked:return hang('session_create')
        return native_create(self,*a,**kw)
    def send(self,method,*a,**kw):
        if armed and not blocked and (mode,method) in [('frame_tree','Page.getFrameTree'),('main_document','DOM.getDocument')]:return hang(mode)
        return native_send(self,method,*a,**kw)
    def detach(self,*a,**kw):
        if armed and mode=='session_detach' and not blocked:return hang('session_detach')
        return native_detach(self,*a,**kw)
    backend=ChatCompletionsBackend('https://offline.invalid/v1','scripted');backend.client.close()
    backend.client=httpx.Client(transport=httpx.MockTransport(transport));backend.requires_browser_thread=True
    try:
        with patch.object(Trace,'event',event),patch.object(BrowserContext,'cookies',cookies),patch.object(BrowserContext,'new_cdp_session',create),patch.object(CDPSession,'send',send),patch.object(CDPSession,'detach',detach):
            path,summary=run_episode(factory,backend,{'driver':'scripted_guard_deadline','model_calls':0},output=out/'runs',max_steps=1,
                harness_profile=profile,human_handover=controller,observation_pipeline=ObservationPipelineConfig((),full_capture_only=True))
    finally:backend.close()
    rows=[json.loads(s) for s in (path/'steps.jsonl').read_text().splitlines()];member=rows[0]['batch_calls'][0]
    events=[json.loads(s) for s in (path/'events.jsonl').read_text().splitlines()]
    assert len(requests)==1 and armed
    errors=[e for e in events if e['event']=='browser_guard_completed' and e['error']]
    if mode=='healthy':
        assert summary['error'] is None and held['final']=={'value':'updated','inputs':1}
        assert member['action_dispatch_started'] and not errors
    else:
        assert held['final']=={'value':'unchanged','inputs':0},held
        assert not member['action_dispatch_started']
        if mode in ('navigation','custody'):assert summary['error'] is None and member['not_executed']
        else:
            assert blocked==[mode] and summary['error'] and len(errors)==1
            assert 1.9<=errors[0]['seconds']<3,errors
            assert member['batch_guard_error']['scope']=='browser_guard'
            assert any(e['event']=='browser_guard_phase_completed' and e['error'] for e in events)
    result={'passed':True,'case':mode,'trace':str(path),'summary':summary,'guard_failures':errors,'final_state':held['final'],'model_calls':0}
    write_json(out/'report.json',result);return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    sources=[*Path('intent_browser').glob('*.py'),Path(__file__)];hashes=lambda:{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources};before=hashes()
    with ProcessPoolExecutor(max_workers=3,mp_context=multiprocessing.get_context('spawn')) as pool:
        cases=list(pool.map(run_guard,[(m,str(a.output/m)) for m in CASES]))
    assert hashes()==before
    write_json(a.output/'report.json',{'passed':True,'cases':cases,'source_sha256':before,'model_calls':0})
