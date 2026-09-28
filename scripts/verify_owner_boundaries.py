"""Actual Chromium owner-read stalls, late completion, nested/sandbox parity."""
from verify_native_quarantine import *
from playwright._impl._frame import Frame as ImplFrame

def run_boundary(args):
    mode,output=args;out=Path(output);out.mkdir(parents=True,exist_ok=False)
    class Task(OpenEndedTask):
        def setup(self,page):
            def route(r):
                if r.request.url.startswith(ORIGIN):
                    body='<h1>Main</h1><button>Continue</button><iframe id=bad src="http://child.invalid/bad"></iframe><iframe src="http://child.invalid/good"></iframe>'
                    if mode=='sandbox':body+='<iframe sandbox src="http://child.invalid/sandbox"></iframe>'
                else:
                    body='<h2>Child</h2><button>Child control</button>'
                    if mode=='nested' and '/bad' in r.request.url:
                        body+='<div id=host></div><script>host.attachShadow({mode:"open"}).innerHTML=\'<iframe src="http://nested.invalid/inner"></iframe>\'</script>'
                r.fulfill(content_type='text/html',body=body)
            page.route('**/*',route);return super().setup(page)
    env=BrowserEnv(task_entrypoint=Task,task_kwargs={'start_url':ORIGIN,'goal':'Inspect'},headless=True)
    trace=Trace(out/'runs',{'driver':'owner_boundaries','model_calls':0,'case':mode})
    pipeline=human=None;calls=[]
    try:
        env.reset();page=env.page
        baseline=env._get_obs()
        pipeline=ObservationPipeline(env,ObservationPipelineConfig((),full_capture_only=True),trace)
        human=HumanBrowser(env,HumanHandoverController(),trace,pipeline,stable_frames=True);human.start()
        bad=page.frame(url='http://child.invalid/bad');original=ImplFrame.frame_element
        async def owner(frame):
            if frame is bad._impl_obj and mode in ('owner_stall','owner_late'):
                calls.append(mode)
                await frame.evaluate('()=>new Promise(resolve=>setTimeout(()=>{window.ownerLate=1;resolve()},1500))'
                    if mode=='owner_late' else '()=>new Promise(()=>{})')
            return await original(frame)
        with patch.object(ImplFrame,'frame_element',owner):
            started=time.monotonic();obs=human.capture();elapsed=time.monotonic()-started
            if mode.startswith('owner_'):
                assert obs['frame_capture']['partial'] and obs['frame_capture']['native_exclusions']['all_children']
                assert len(obs['frame_capture']['included_frames'])==1
                assert bad in human.quarantined_frames and len(calls)==1
                again=human.capture();assert again['frame_capture']['partial'] and len(calls)==1
                if mode=='owner_late':
                    page.wait_for_timeout(1700)
                    assert bad.evaluate('window.ownerLate')==1
                    assert human.capture()['frame_capture']['partial'] and len(calls)==1
            else:
                semantic=lambda o:[{k:n[k] for k in ('role','name','value','browsergym_id','ignored','properties') if k in n} for n in o['axtree_object']['nodes']]
                assert semantic(obs)==semantic(baseline)
                assert obs['extra_element_properties']==baseline['extra_element_properties']
            trace.observation(0,obs,'Local owner read boundary')
        if mode.startswith('owner_'):
            page.evaluate("()=>new Promise(resolve=>{bad.remove();const f=document.createElement('iframe');f.src='http://child.invalid/new';f.onload=resolve;document.body.append(f)})")
            assert not human.capture()['frame_capture']['partial']
    finally:
        if human:human.close()
        if pipeline:pipeline.close()
        env.close()
    result={'passed':True,'case':mode,'trace':str(trace.directory),'seconds':elapsed,'model_calls':0,'blocked_owner_calls':len(calls)}
    write_json(out/'report.json',result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    paths=[*Path('intent_browser').glob('*.py'),Path(__file__)]
    hashes=lambda:{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths};before=hashes()
    with ProcessPoolExecutor(max_workers=2,mp_context=multiprocessing.get_context('spawn')) as pool:
        cases=list(pool.map(run_boundary,[(m,str(a.output/m)) for m in ('owner_stall','owner_late','nested','sandbox')]))
    assert hashes()==before
    write_json(a.output/'report.json',{'passed':True,'cases':cases,'source_sha256':before,'model_calls':0})
