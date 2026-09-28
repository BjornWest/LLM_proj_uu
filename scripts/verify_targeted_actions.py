"""Real Chromium/runner acceptance of targeted guards and deferred observations.

HTTPX transport is scripted; no inference, external sites or network credentials.
"""
import argparse,json,gzip,hashlib,threading,time,multiprocessing
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from unittest.mock import patch
import httpx
from browsergym.core.env import BrowserEnv
from browsergym.core.task import OpenEndedTask
from intent_browser.actions import make_action_set
from intent_browser.backend import ChatCompletionsBackend
from intent_browser.standard_profile import standard_profile
from intent_browser.open_internet import open_profile,with_human_handover
from intent_browser.human_handover import HumanHandoverController
from intent_browser.dynamic_preview import DynamicPreview
from intent_browser.observation_pipeline import ObservationPipelineConfig
from intent_browser.runner import run_episode
import intent_browser.targeted_guard as targeted

CASES=('click','baseline','unrelated_change','label_change','disabled','replace','bid_change','duplicate','moved',
       'document_change','custody_change','late_custody','frame_fallback','batch_fill_press','deferred_fresh','paced_change','error_receipt')

def case(args):
    mode,directory,products,*options=args;runtime_defaults=bool(options and options[0]);out=Path(directory);out.mkdir(parents=True,exist_ok=False)
    effects=[];requests=[];held={};controller=HumanHandoverController()
    profile=with_human_handover(open_profile(standard_profile(helpers=False)),stable_frames=True,compact_tabs=True,capture_timeout_mode='diagnostic')
    class Fixture(OpenEndedTask):
        def setup(self,page):
            held['page']=page
            page.expose_function('recordEffect',lambda value:effects.append(value))
            rows=''.join(f'<article><h2>Product {i}</h2><p>Stock {i%5}</p></article>' for i in range(products))
            body='''<h1 id="news">Store</h1><section aria-label="Original"><button id="commit" onclick="recordEffect('commit');document.querySelector('#status').textContent='Commit confirmed'">Commit</button></section><section id="other" aria-label="Other"></section><input aria-label="Search" onkeydown="if(event.key==='Enter') recordEffect(this.value)"><p id="status" role="status"></p><main>'''+rows+'</main><iframe src="http://child.invalid/child"></iframe>'
            page.route('**/*',lambda r:r.fulfill(content_type='text/html',body='<button onclick="recordEffect(\'child\')">Child</button>' if r.request.url.endswith('/child') else body))
            return super().setup(page)
    def factory(_):
        env=BrowserEnv(task_entrypoint=Fixture,task_kwargs={'start_url':'http://fixture.invalid/main','goal':'Click Commit once.'},headless=True,action_mapping=make_action_set(profile.tools.names).to_python_code)
        held['env']=env;return env
    def bids(req,name):
        def walk(x):
            if isinstance(x,dict):
                if x.get('name')==name and x.get('bid'):yield x['bid']
                for v in x.values():yield from walk(v)
            elif isinstance(x,list):
                for v in x:yield from walk(v)
        found=[]
        for m in req['messages']:
            if isinstance(m.get('content'),str):
                for line in m['content'].splitlines():
                    try:found.extend(walk(json.loads(line)))
                    except ValueError:pass
        return found[-1] if found else None
    def response(request):
        q=json.loads(request.content);requests.append(q);time.sleep(.05)
        n=len(requests)
        if mode=='frame_fallback':
            calls=[('ax_search',{'query':'Child'})] if n==1 else [('click',{'bid':bids(q,'Child')})]
        elif mode=='batch_fill_press':
            bid=bids(q,'Search');assert bid
            calls=[('fill',{'bid':bid,'value':'typed'}),('press',{'bid':bid,'key_comb':'Enter'})]
        elif n==2:
            calls=[('ax_search',{'query':'Paced update' if mode=='paced_change' else 'Commit confirmed'})]
        else:
            bid=bids(q,'Commit');assert bid,'BID must come from exact request, not private browser'
            calls=[('click',{'bid':bid})]
        return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,'tool_calls':[{'id':f'call-{n}-{i}','type':'function','function':{'name':name,'arguments':json.dumps(a)}} for i,(name,a) in enumerate(calls)]}}],'usage':{'prompt_tokens':100,'completion_tokens':10,'cost':0}})
    backend=ChatCompletionsBackend('https://offline.invalid/v1','scripted',supports_images=True);backend.client.close();backend.client=httpx.Client(transport=httpx.MockTransport(response))
    original_capture=DynamicPreview.capture;original_check=targeted.check
    def capture(self):
        result=original_capture(self);page=held['page']
        if len(requests)!=1:return result
        scripts={
         'unrelated_change':"document.querySelector('#news').textContent='Updated news'",
         'label_change':"document.querySelector('#commit').textContent='Subscribe'",
         'disabled':"document.querySelector('#commit').disabled=true",
         'replace':"let e=document.querySelector('#commit');e.outerHTML=e.outerHTML",
         'bid_change':"document.querySelector('#commit').setAttribute('bid','999999')",
         'duplicate':"document.body.appendChild(document.querySelector('#commit').cloneNode(true))",
         'moved':"document.querySelector('#other').appendChild(document.querySelector('#commit'))"}
        if mode in scripts:page.evaluate(scripts[mode])
        if mode=='document_change':page.reload()
        if mode=='custody_change':controller.handover(self.human.active,'test')
        return result
    def check(*args):
        value=original_check(*args)
        if mode=='late_custody' and value is not None and value.get('reason') is None:
            controller.handover(args[0].active,'test after targeted check')
        return value
    waits=0
    def before():
        nonlocal waits
        waits+=1
        if mode=='paced_change' and waits==2:held['page'].evaluate("document.querySelector('#news').textContent='Paced update'")
        return {'scripted_pacing_boundary':waits}
    original_step=__import__('intent_browser.observation_pipeline',fromlist=['ObservationPipeline']).ObservationPipeline.step
    def step(self,action):
        if mode=='error_receipt':
            # Actual action attempt times out on a newly hidden element; never retry.
            held['page'].locator('#commit').evaluate("e=>e.style.display='none'")
        return original_step(self,action)
    try:
        with patch.object(DynamicPreview,'capture',capture),patch.object(targeted,'check',check),patch('intent_browser.observation_pipeline.ObservationPipeline.step',step):
            path,summary=run_episode(factory,backend,{'driver':'targeted_action_acceptance','paid_model_calls':0},output=out/'runs',
              max_steps=2 if mode in ('deferred_fresh','paced_change','frame_fallback') else 1,
              harness_profile=profile,human_handover=controller,before_observation=before,
              **({} if runtime_defaults and mode!='baseline' else {'observation_pipeline':
                  ObservationPipelineConfig((),full_capture_only=True,dynamic_preview=True,shallow_depth=3,
                    trace_screenshots=False,targeted_actions=mode!='baseline'),'trace_screenshots':False}))
    finally:backend.close()
    rows=[json.loads(l) for l in (path/'steps.jsonl').read_text().splitlines()];events=[json.loads(l) for l in (path/'events.jsonl').read_text().splitlines()]
    assert summary['error'] is None,(mode,summary['error'])
    if runtime_defaults and mode!='baseline':
        metadata=json.loads((path/'metadata.json').read_text())
        assert metadata['runtime_selection']['selected']=='preview_targeted'
        assert metadata['trace_screenshots'] is False
    expected=['typed'] if mode=='batch_fill_press' else ['child'] if mode=='frame_fallback' else ['commit'] if mode in ('click','baseline','unrelated_change','deferred_fresh','paced_change') else []
    assert effects==expected,(mode,effects,[r.get('batch_stop_reason') for r in rows])
    for r,q in zip(rows,requests):
        assert r['model_request']==q
        assert all(i['confirmed'] for i in r['policy_delivery']['items'])
    native=sum(e['event']=='native_capture_completed' for e in events);deferred=sum(e['event']=='post_action_capture_deferred' for e in events)
    if mode=='baseline':assert deferred==0
    if expected and mode!='baseline':assert deferred==1,(mode,deferred)
    if mode=='click':assert native==3,(mode,native)
    if mode=='baseline':assert native==5,(mode,native)
    if mode=='frame_fallback':assert rows[-1]['batch_calls'][0].get('targeted_guard') is None
    if mode=='batch_fill_press':assert len(rows[0]['batch_calls'])==2 and all(c['action_dispatch_started'] for c in rows[0]['batch_calls'])
    if mode in ('deferred_fresh','paced_change'):
        raw=json.loads(gzip.decompress((path/rows[0]['next_observation']['raw']).read_bytes()));assert raw['observation_capture']['deferred'];assert raw['axtree_object']['nodes']==[]
        result=rows[1]['batch_calls'][0]['tool_output'];assert result['items'],result
    if mode=='error_receipt':assert summary['action_error_count']==1 and not effects
    assert next(i for i,e in enumerate(events) if e['event']=='evaluation_completed')<next(i for i,e in enumerate(events) if e['event']=='environment_close_started')
    report={'passed':True,'case':mode,'trace':str(path),'effects':effects,'native_captures':native,'deferred_captures':deferred,'requests':len(requests),'stop_reasons':[r.get('batch_stop_reason') for r in rows],'paid_model_calls':0}
    (out/'report.json').write_text(json.dumps(report,indent=2));return report

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--case',choices=CASES);p.add_argument('--products',type=int,default=100);p.add_argument('--workers',type=int,default=2);p.add_argument('--runtime-defaults',action='store_true');args=p.parse_args()
    out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    paths=[*Path('intent_browser').glob('*.py'),*Path('intent_browser').glob('*.js'),Path(__file__)]
    hashes=lambda:{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths};before=hashes()
    with ProcessPoolExecutor(max_workers=args.workers,mp_context=multiprocessing.get_context('spawn')) as pool:
        reports=list(pool.map(case,[(c,str(out/c),args.products,args.runtime_defaults) for c in ([args.case] if args.case else CASES)]))
    assert before==hashes(),'Source changed during acceptance'
    (out/'report.json').write_text(json.dumps({'passed':True,'cases':reports,'source_sha256':before,'runtime_defaults':args.runtime_defaults,'paid_model_calls':0},indent=2))
    print(json.dumps({'passed':True,'cases':len(reports)}))
if __name__=='__main__':main()
