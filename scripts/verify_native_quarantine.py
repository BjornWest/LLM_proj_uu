"""Actual local browser tests of bounded child marking and late RPC completion."""
from verify_frame_capture import *
from intent_browser.native_capture import START
from playwright.sync_api import Frame
import pkgutil

CASES=('child_stall','child_late','child_cleanup','main_stall')
UNMARK=pkgutil.get_data('browsergym.core.observation','javascript/frame_unmark_elements.js').decode()

def run_quarantine(args):
    mode,output=args;out=Path(output);out.mkdir(parents=True,exist_ok=False)
    class Task(OpenEndedTask):
        def setup(self,page):
            def route(r):
                body=('<h1>Main usable</h1><button id=action>Continue</button><iframe id=bad src="http://child.invalid/bad"></iframe><iframe src="http://child.invalid/good"></iframe>'
                    if r.request.url.startswith(ORIGIN) else '<h2>Child document</h2><button id=inside>Child action</button>')
                r.fulfill(content_type='text/html',body=body)
            page.route('**/*',route);return super().setup(page)
    env=BrowserEnv(task_entrypoint=Task,task_kwargs={'start_url':ORIGIN,'goal':'Inspect main page'},headless=True)
    trace=Trace(out/'runs',{'driver':'local_native_frame_deadline','model_calls':0})
    pipeline=ObservationPipeline(env,ObservationPipelineConfig((),full_capture_only=True),trace)
    human=HumanBrowser(env,HumanHandoverController(),trace,pipeline,stable_frames=True)
    native=Frame.evaluate;calls=[];samples=[];error=None;obs=None
    try:
        env.reset();human.start();page=env.page;initial=human.capture();ticket=human.ticket(initial)
        bad=page.frame(url='http://child.invalid/bad');bad_bid=bad.locator('#inside').get_attribute('bid')
        def evaluate(frame,expr,*a,**kw):
            selected=(frame is page.main_frame if mode=='main_stall' else frame is bad)
            targeted=expr==(UNMARK if mode=='child_cleanup' else START)
            if selected and targeted:
                calls.append(expr[:30])
                if mode=='child_late':
                    return native(frame,'''async ({source,args})=>{await new Promise(r=>setTimeout(r,1500));
                        window.lateMark=(window.lateMark||0)+1;return await eval('('+source+')')(args)}''',
                        {'source':expr,'args':a[0]})
                return native(frame,'()=>new Promise(()=>{})')
            return native(frame,expr,*a,**kw)
        with patch.object(Frame,'evaluate',evaluate):
            started=time.monotonic()
            try:obs=human.capture()
            except Exception as exc:error={'type':type(exc).__name__,'message':str(exc)}
            samples.append(time.monotonic()-started)
            if mode=='main_stall':
                assert error and error['type']=='CaptureDeadlineExceeded',error
                assert 4.9<=samples[0]<7.5
            else:
                assert error is None,error
                assert obs['frame_capture']['partial'] and 'native_exclusions' in obs['frame_capture']
                assert bad_bid not in obs['frame_capture']['bid_frames']
                assert human.guard(ticket,obs,decision=Decision('click',{'bid':bad_bid},''))=='target_not_in_captured_stable_document'
                assert len(human.quarantined_frames)==1
                assert len(obs['frame_capture']['included_frames'])==2,obs['frame_capture']
                assert samples[0]<2.5,samples
                started=time.monotonic();again=human.capture();samples.append(time.monotonic()-started)
                assert len(calls)==1 and again['frame_capture']['partial'],calls
                if mode=='child_late':
                    page.wait_for_timeout(1700)
                    assert native(bad,'window.lateMark')==1
                    assert human.capture()['frame_capture']['partial'] and len(calls)==1
                # A new Frame object, rather than a late response from the old
                # one, can become independently usable after fresh capture.
                page.evaluate("()=>new Promise(resolve=>{bad.remove();let f=document.createElement('iframe');f.src='http://child.invalid/replacement';f.onload=resolve;document.body.append(f)})")
                restored=human.capture();assert not restored['frame_capture']['partial']
                trace.observation(0,obs,'Explicitly incomplete child; main and good child remain usable')
    finally:
        human.close();pipeline.close();env.close()
    result={'passed':True,'case':mode,'seconds':samples,'error':error,'blocked_calls':len(calls),
        'coverage':obs.get('frame_capture') if obs else None,'trace':str(trace.directory),'model_calls':0}
    write_json(out/'report.json',result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    sources=[*Path('intent_browser').glob('*.py'),Path(__file__)];hashes=lambda:{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources};before=hashes()
    with ProcessPoolExecutor(max_workers=3,mp_context=multiprocessing.get_context('spawn')) as pool:
        cases=list(pool.map(run_quarantine,[(m,str(a.output/m)) for m in CASES]))
    assert hashes()==before
    write_json(a.output/'report.json',{'passed':True,'cases':cases,'source_sha256':before,'model_calls':0})
