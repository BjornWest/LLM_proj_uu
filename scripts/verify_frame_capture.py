"""Scripted frame churn, coverage, target fencing and native parity; no inference."""
from verify_human_capture_race import *
from intent_browser.frame_capture import frame_documents, main_signature, target_document_error
from intent_browser.actions import Decision
import time

MODES=('stable','attach','detach','navigate','main_navigation','custody','target_navigation','target_removed','unrelated','continuous','baseline_churn','deadline','main_hash','main_rewrite','main_reload','target_reload','timer_churn')


def run_scoped(args):
    mode,output=args;out=Path(output);out.mkdir(parents=True,exist_ok=False)
    html='''<title>Scoped fixture</title><h1>Main stable content</h1><button id=accept onclick="window.commits++">Accept</button>
    <iframe id=target src="http://child.invalid/target"></iframe><iframe id=ad src="http://child.invalid/ad"></iframe>
    <script>window.commits=0</script>'''
    class Task(OpenEndedTask):
        def setup(self,page):
            page.route('**/*',lambda r:r.fulfill(content_type='text/html',body=html if '/main' in r.request.url else '<h2>Child content</h2><button id=child>Child control</button>'))
            return super().setup(page)
    env=BrowserEnv(task_entrypoint=Task,task_kwargs={'start_url':ORIGIN+'/main','goal':'Accept once, inspect page'},
        headless=True,action_mapping=make_action_set(('click',)).to_python_code)
    trace=Trace(out/'runs',{'driver':'scripted_frame_churn','model_calls':0})
    pipeline=ObservationPipeline(env,ObservationPipelineConfig((),full_capture_only=True),trace)
    human=HumanBrowser(env,HumanHandoverController(),trace,pipeline,stable_frames=mode!='baseline_churn')
    result={};injected=[];original=capture_native
    try:
        env.reset();human.start();page=env.page
        before=human.capture();ticket=human.ticket(before)
        parent_bid=page.locator('#accept').get_attribute('bid')
        child=page.frame(url='http://child.invalid/target');child_bid=child.locator('#child').get_attribute('bid')
        native=original(type('View',(),{'__getattr__':lambda _,key:getattr(env,key)})(),__import__('intent_browser.native_capture',fromlist=['CaptureBudget']).CaptureBudget(page,trace))
        if mode=='stable':
            semantic=lambda o:[{k:n[k] for k in ('role','name','value','browsergym_id','ignored','properties') if k in n} for n in o['axtree_object']['nodes']]
            assert semantic(before)==semantic(native)
            assert before['extra_element_properties']==native['extra_element_properties']
            assert before['dom_object']==native['dom_object']
        # A real consent-like mutation occurs exactly once before the new capture.
        env.step(f'click({parent_bid!r})');assert page.evaluate('window.commits')==1
        ticket=human.ticket(human.capture())
        def capture(view,budget):
            obs=original(view,budget)
            if mode=='deadline':return view.page.evaluate('()=>new Promise(()=>{})')
            if injected and mode not in ('continuous','baseline_churn'):return obs
            if mode in ('attach','continuous','baseline_churn'):
                page.evaluate("()=>{document.querySelector('#ad').remove();let f=document.createElement('iframe');f.id='ad';f.src='http://child.invalid/ad';document.body.append(f)}")
            elif mode in ('detach','target_removed'):page.locator('#target' if mode=='target_removed' else '#ad').evaluate('e=>e.remove()')
            elif mode in ('navigate','target_navigation'):page.frame(url='http://child.invalid/target' if mode=='target_navigation' else 'http://child.invalid/ad').goto('http://child.invalid/changed')
            elif mode=='main_navigation':page.goto(ORIGIN+'/main-new')
            elif mode=='main_reload':page.reload()
            elif mode=='target_reload':page.frame(url='http://child.invalid/target').goto('http://child.invalid/target')
            elif mode=='main_hash':page.evaluate("location.hash='changed'")
            elif mode=='main_rewrite':page.evaluate("()=>{document.open();document.write('<h1>Main stable content</h1>');document.close()}")
            elif mode=='custody':human.controller.handover(human.active,'Test custody change')
            elif mode=='unrelated':raise RuntimeError('Deliberate unrelated failure')
            else:return obs
            injected.append(mode);return obs
        if mode=='timer_churn':
            page.evaluate("()=>{window.churnTicks=0;window.churn=setInterval(()=>{document.querySelector('#ad').src='http://child.invalid/ad?timer='+window.churnTicks++},80)}")
        start=time.monotonic();error=None;current=None
        with patch('intent_browser.human_browser.capture_native',capture):
            try:current=human.capture()
            except Exception as e:error={'type':type(e).__name__,'message':str(e)}
        seconds=time.monotonic()-start
        if mode=='timer_churn':
            page.evaluate('clearInterval(window.churn)')
            assert page.evaluate('window.churnTicks')>0
            assert current and current['frame_capture']['partial'],error
        if mode in ('custody','unrelated','baseline_churn','deadline'):
            assert error,error
            if mode=='baseline_churn':
                assert error['type']=='DocumentScanInvalidated' and len(injected)==3,(error,injected)
            if mode=='deadline':assert error['type']=='CaptureDeadlineExceeded' and 4.9<=seconds<7,(error,seconds)
        else:
            assert error is None,error
            names=[n.get('name',{}).get('value') for n in current['axtree_object']['nodes']]
            assert 'Main stable content' in names
            if mode in ('attach','detach','navigate','continuous','target_navigation','target_removed','target_reload'):
                assert current['human_tab_capture']['attempts']==1
                assert current['frame_capture']['partial']
                assert human.guard(ticket,decision=Decision('click',{'bid':parent_bid},'')) is None
                target_error=human.guard(ticket,decision=Decision('click',{'bid':child_bid},''))
                if mode in ('target_navigation','target_removed','target_reload'):
                    assert target_error=='target_frame_document_changed',target_error
                    assert human.confirmation_guard({'ticket':ticket,'decision':Decision('click',{'bid':child_bid},''),'target_identity':None},current)==target_error
                else:assert target_error is None,target_error
                # Same unchanged main control can actually execute; no consent replay.
                assert page.evaluate('window.commits')==1
                # Explicit next capture restores readable current child content.
                fresh=human.capture();assert not fresh['frame_capture']['partial'],fresh['frame_capture']
                assert fresh['human_tab_capture']['attempts']==1
            if mode in ('main_navigation','main_hash','main_reload'):
                assert human.guard(ticket)=='tab_document_changed'
                assert current['human_tab_capture']['attempts']==2
            if mode=='main_rewrite':
                # document.open rewrites the SAME Document; target/content checks, not loader identity, fence it.
                fresh=human.capture();decision=Decision('click',{'bid':parent_bid},'')
                # Removed targets now fail the explicit current-capture BID
                # check before the broader content-change comparison.
                assert human.guard(ticket,fresh,decision=decision)=='target_not_in_captured_stable_document'
                review=human.content_review(ticket,fresh,decision,step=0,call_id='rewrite')
                assert review['reason']=='target_removed_replaced_or_disabled' and 'confirmation' not in review
            trace.observation(0,current,'scripted partial coverage evidence')
        if mode not in ('main_navigation','main_reload'):assert page.evaluate('window.commits')==1
        result={'case':mode,'passed':True,'seconds':seconds,'error':error,'injected':injected,
            'coverage':current.get('frame_capture') if current else None,'trace':str(trace.directory),'model_calls':0}
    finally:
        human.close();pipeline.close();env.close()
    write_json(out/'report.json',result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);p.add_argument('--cases',nargs='+',choices=MODES,default=MODES);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    sources=[*Path('intent_browser').glob('*.py'),Path(__file__)];hashes=lambda:{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources};before=hashes()
    with ProcessPoolExecutor(max_workers=3,mp_context=multiprocessing.get_context('spawn')) as pool:
        results=list(pool.map(run_scoped,[(m,str(a.output/m)) for m in a.cases]))
    assert hashes()==before
    write_json(a.output/'report.json',{'passed':True,'cases':results,'source_sha256':before,'model_calls':0})
