"""Many-frame old/new cleanup comparison. Local Chromium only, no inference."""
from verify_native_capture import *
from types import SimpleNamespace
from browsergym.core import observation as core

CASES=[(path,n) for n in (16,64,96) for path in ('previous','candidate')]
def previous_cleanup(self,page):
    for frame in list(page.frames):
        if frame in self.quarantined:continue
        view=SimpleNamespace(frames=[frame],main_frame=page.main_frame)
        if frame is page.main_frame:core._post_extract(view)
        else:self.child_call(frame,'frame_cleanup',lambda:core._post_extract(view))

def run_many(args):
    mode,count,output=args;out=Path(output);out.mkdir(parents=True,exist_ok=False)
    class Task(OpenEndedTask):
        def setup(self,page):
            def route(r):
                body='<h1>Main</h1><button>Continue</button>' if r.request.url=='http://main.invalid/' else '<h2>Child data</h2><button>Child action</button>'
                r.fulfill(content_type='text/html',body=body)
            page.route('**/*',route);return super().setup(page)
    env=BrowserEnv(task_entrypoint=Task,task_kwargs={'start_url':'http://main.invalid/','goal':'Inspect public content'},headless=True)
    trace=Trace(out/'runs',{'driver':'many_frame_capture','model_calls':0,'mode':mode,'children':count})
    human=pipeline=None;attempts=[]
    try:
        env.reset();page=env.page
        page.evaluate('''n=>Promise.all(Array.from({length:n},(_,i)=>new Promise(resolve=>{
          const f=document.createElement('iframe');f.style.height='25px';f.src='http://child.invalid/'+i;
          f.onload=resolve;document.body.append(f)})))''',count)
        pipeline=ObservationPipeline(env,ObservationPipelineConfig((),full_capture_only=True),trace)
        human=HumanBrowser(env,HumanHandoverController(),trace,pipeline,stable_frames=True);human.start()
        method=previous_cleanup if mode=='previous' else CaptureBudget.scoped_unmark
        with patch.object(CaptureBudget,'scoped_unmark',method):
            for i in range(2):
                start=time.monotonic();error=None;obs=None
                try:obs=human.capture()
                except Exception as exc:error={'type':type(exc).__name__,'message':str(exc)}
                seconds=time.monotonic()-start
                if obs:
                    assert not obs['frame_capture']['partial'],obs['frame_capture']
                    names=[n.get('name',{}).get('value') for n in obs['axtree_object']['nodes'] if n.get('role',{}).get('value')=='button']
                    assert names.count('Child action')==count,names.count('Child action')
                    assert len(obs['dom_object']['documents'])==count+1
                    trace.observation(i,obs,'Full unchanged many-frame fixture')
                    for frame in page.frames:
                        assert not frame.locator('[aria-description^="browsergym_id"],[aria-roledescription^="browsergym_id"]').count()
                attempts.append({'seconds':seconds,'error':error,'documents':len(obs['dom_object']['documents']) if obs else None})
                if error:break  # No timed-out capture retry on the same context.
    finally:
        if human:human.close()
        if pipeline:pipeline.close()
        env.close()
    events=[json.loads(s) for s in (trace.directory/'events.jsonl').read_text().splitlines()]
    phases=[e for e in events if e['event']=='native_capture_phase_completed']
    result={'case':f'{mode}-{count}','mode':mode,'children':count,'attempts':attempts,
        'completed':all(a['error'] is None for a in attempts),'trace':str(trace.directory),'phases':phases,'model_calls':0}
    write_json(out/'report.json',result);return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--counts',type=int,nargs='+',default=[16,64,96]);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    sources=[*Path('intent_browser').glob('*.py'),Path(__file__)];hashes=lambda:{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources};before=hashes()
    with ProcessPoolExecutor(max_workers=3,mp_context=multiprocessing.get_context('spawn')) as pool:
        cases=list(pool.map(run_many,[(m,n,str(a.output/f'{m}-{n}')) for n in a.counts for m in ('previous','candidate')]))
    assert hashes()==before
    write_json(a.output/'report.json',{'cases':cases,'source_sha256':before,'model_calls':0})
