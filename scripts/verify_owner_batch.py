"""Local sibling owner-read comparison with synthetic RPC latency; no inference."""
from verify_many_frame_capture import *
import asyncio
from contextlib import ExitStack
from playwright._impl._frame import Frame as ImplFrame
from playwright._impl._element_handle import ElementHandle as ImplElement
from playwright._impl._js_handle import JSHandle as ImplHandle
from intent_browser.native_capture import CHILD_RPC_SECONDS, _SKIPPED


def serial_owners(self,children):
    results=[]
    for child in children:
        if child in self.quarantined:results.append(_SKIPPED);continue
        local=CaptureBudget(self.page,self.trace,seconds=CHILD_RPC_SECONDS)
        try:
            with local.rpc_deadline():
                element=child.frame_element()
                attrs=(element.evaluate("el=>({sandbox:el.getAttribute('sandbox'),bid:el.getAttribute('bid')})")
                       if element.content_frame()==child else None)
        except CaptureDeadlineExceeded:
            self.check();self.quarantined[child]={'reason':'owner_lookup_deadline'};attrs=_SKIPPED
        results.append(attrs)
    return results


def run_comparison(args):
    mode,count,delay,output=args;out=Path(output);out.mkdir(parents=True,exist_ok=False)
    class Task(OpenEndedTask):
        def setup(self,page):
            page.route('**/*',lambda r:r.fulfill(content_type='text/html',body=
                '<h1>Main</h1><button>Continue</button>' if r.request.url=='http://main.invalid/' else
                '<h2>Child</h2><button>Child action</button><input value=child>'))
            return super().setup(page)
    env=BrowserEnv(task_entrypoint=Task,task_kwargs={'start_url':'http://main.invalid/','goal':'Inspect'},headless=True)
    trace=Trace(out/'runs',{'driver':'owner_batch','mode':mode,'children':count,'synthetic_rpc_delay_seconds':delay,'model_calls':0})
    human=pipeline=None;attempts=[]
    try:
        env.reset();page=env.page
        page.evaluate('''n=>Promise.all(Array.from({length:n},(_,i)=>new Promise(resolve=>{
            let f=document.createElement('iframe');f.src='http://child.invalid/'+i;
            f.style.height='25px';f.onload=resolve;document.body.append(f)})))''',count)
        pipeline=ObservationPipeline(env,ObservationPipelineConfig((),full_capture_only=True),trace)
        human=HumanBrowser(env,HumanHandoverController(),trace,pipeline,stable_frames=True);human.start()
        def delayed(fn):
            async def wrapped(obj,*a,**kw):
                # Delay only the same three owner reads in both paths.
                if fn.__name__!='evaluate' or (a and 'sandbox:el.getAttribute' in str(a[0])):
                    await asyncio.sleep(delay)
                return await fn(obj,*a,**kw)
            return wrapped
        with ExitStack() as stack:
            if mode=='serial':stack.enter_context(patch.object(CaptureBudget,'owner_attributes',serial_owners))
            for cls,name in ((ImplFrame,'frame_element'),(ImplElement,'content_frame'),(ImplHandle,'evaluate')):
                stack.enter_context(patch.object(cls,name,delayed(getattr(cls,name))))
            for index in range(2):
                start=time.monotonic();error=None;obs=None
                try:obs=human.capture()
                except Exception as exc:error={'type':type(exc).__name__,'message':str(exc)}
                elapsed=time.monotonic()-start
                if obs:
                    trace.observation(index,obs,'Synthetic sibling frame observation')
                    assert not obs['frame_capture']['partial'],obs['frame_capture']
                    buttons=[n for n in obs['axtree_object']['nodes'] if n.get('name',{}).get('value')=='Child action'
                             and n.get('role',{}).get('value')=='button']
                    assert len(buttons)==count and all(n.get('browsergym_id') for n in buttons), {
                        'expected_child_buttons':count,'actual_child_buttons':len(buttons),
                        'actionable_child_buttons':sum(bool(n.get('browsergym_id')) for n in buttons)}
                    assert len(obs['dom_object']['documents'])==count+1
                attempts.append({'seconds':elapsed,'error':error})
                if error:break
    finally:
        if human:human.close()
        if pipeline:pipeline.close()
        env.close()
    result={'mode':mode,'children':count,'delay_seconds':delay,'attempts':attempts,'trace':str(trace.directory),
            'completed':all(a['error'] is None for a in attempts),'model_calls':0}
    write_json(out/'report.json',result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    paths=[*Path('intent_browser').glob('*.py'),Path(__file__)]
    hashes=lambda:{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths};before=hashes()
    specs=[(m,n,d,str(a.output/f'{m}-{n}-{d}')) for n,d in ((20,0),(20,.04),(64,.04)) for m in ('serial','parallel')]
    with ProcessPoolExecutor(max_workers=2,mp_context=multiprocessing.get_context('spawn')) as pool:
        cases=list(pool.map(run_comparison,specs))
    assert hashes()==before
    write_json(a.output/'report.json',{'cases':cases,'source_sha256':before,'model_calls':0,
        'scope':'Injected owner-read delay on local Chromium, not measured Windows relay latency.'})
