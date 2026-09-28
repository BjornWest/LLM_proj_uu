"""Local runner/Chromium screenshot guards, HTTP mock only; no paid/web calls."""
from verify_capture_shutdown import *
from intent_browser.vision import VisionConfig
from playwright.sync_api import Page
from PIL import Image
import intent_browser.human_browser as hb

CASES=('fresh_large','before_navigation','during_navigation','during_handover','during_cycle',
       'blocked_visual','blocked_pixels','mutation_after_image')

def run_viewport(args):
    mode,output=args;out=Path(output);out.mkdir(parents=True,exist_ok=False)
    profile=with_human_handover(open_profile(native_tools_profile(parallel_tool_calls=None,compact_feedback=True,
        ax_config=AXConfig(tokenizer_path(),incremental=True),vision_config=VisionConfig(),batch_size=8)),
        wait_for_human=False,compact_tabs=True,stable_frames=True,capture_timeout_mode='bounded')
    held={};requests=[];native_guards=[];pending={'name':None};controller=HumanHandoverController()
    class Task(OpenEndedTask):
        def setup(self,page):
            def route(r):
                rows=''.join(f'<p>Public product row {i}</p>' for i in range(2600 if mode=='fresh_large' else 5))
                body='<style>body{background:rgb(240,30,30)}</style><h1>Viewport</h1><button id=action>Continue</button>'+rows+'<script>window.commits=0;action.onclick=()=>window.commits++</script>'
                r.fulfill(content_type='text/html',body=body)
            page.route('**/*',route);return super().setup(page)
    def factory(_):
        env=BrowserEnv(task_entrypoint=Task,task_kwargs={'start_url':ORIGIN,'goal':'Inspect current page pixels, then finish.'},
            headless=True,action_mapping=make_action_set(profile.tools.names).to_python_code)
        held['env']=env;return env
    def dispatch(req):
        request=json.loads(req.content);requests.append(request);n=len(requests);page=held['env'].page
        if n==1:
            page.evaluate("document.body.style.background='rgb(20,70,230)'")
            if mode=='before_navigation':page.goto(ORIGIN+'?replacement')
            name,arguments='screenshot',{}
        elif mode=='mutation_after_image':
            bid=page.locator('#action').get_attribute('bid')
            page.evaluate("action.outerHTML='<button id=action>Replaced control</button>'")
            name,arguments='click',{'bid':bid}
        else:name,arguments='send_msg_to_user',{'text':'Inspected available pixels.'}
        pending['name']=name
        return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
            'tool_calls':[{'id':f'call-{n}','type':'function','function':{'name':name,'arguments':json.dumps(arguments)}}]}}]})
    native_capture=hb.capture_native
    def capture(view,budget):
        # Prohibit the unnecessary full capture on the exact failed path. Actual
        # decision/transition captures and mutation guards remain native.
        if held.get('human') is not None and held['human'].association.get('phase')=='batch_guard':
            native_guards.append(pending['name'])
            if pending['name']=='screenshot':raise AssertionError('Screenshot invoked full native DOM/AX extraction')
        return native_capture(view,budget)
    native_start=hb.HumanBrowser.start
    def start(self):held['human']=self;return native_start(self)
    native_screenshot=ObservationPipeline.screenshot
    def screenshot(self,index):
        if mode=='blocked_visual':return self.env.page.evaluate('()=>new Promise(()=>{})')
        result=native_screenshot(self,index)
        if mode=='during_navigation':self.env.page.goto(ORIGIN+'?changed-during-capture')
        elif mode in ('during_handover','during_cycle'):
            tab=held['human'].active;controller.handover(tab,'Synthetic custody race')
            if mode=='during_cycle':
                state=next(t for t in controller.snapshot()['tabs'] if t['tab_id']==tab)
                controller.signal(tab,'start',handover_id=state['handover_id'])
                controller.signal(tab,'complete',handover_id=state['handover_id'])
        return result
    native_pixels=Page.screenshot
    def pixels(page,*a,**kw):
        if mode=='blocked_pixels' and 'visual-capture-' in str(kw.get('path','')):
            return page.evaluate('()=>new Promise(()=>{})')
        return native_pixels(page,*a,**kw)
    backend=ChatCompletionsBackend('https://offline.invalid/v1','scripted',supports_images=True);backend.client.close()
    backend.client=httpx.Client(transport=httpx.MockTransport(dispatch));backend.requires_browser_thread=True
    try:
        with patch.object(hb.HumanBrowser,'start',start),patch.object(hb,'capture_native',capture),patch.object(ObservationPipeline,'screenshot',screenshot),patch.object(Page,'screenshot',pixels):
            path,summary=run_episode(factory,backend,{'driver':'scripted_viewport_guard','model_calls':0},output=out/'runs',max_steps=2,
                harness_profile=profile,human_handover=controller,observation_pipeline=ObservationPipelineConfig((),full_capture_only=True))
    finally:backend.close()
    rows=[json.loads(x) for x in (path/'steps.jsonl').read_text().splitlines()]
    events=[json.loads(x) for x in (path/'events.jsonl').read_text().splitlines()]
    first=rows[0]['batch_calls'][0]
    image_parts=[p for req in requests for m in req['messages'] if isinstance(m.get('content'),list)
        for p in m['content'] if p.get('type')=='image_url']
    captures=[e for e in events if e['event']=='viewport_capture_completed']
    assert 'screenshot' not in native_guards,native_guards
    if mode in ('fresh_large','mutation_after_image'):
        assert summary['error'] is None,summary
        assert image_parts and len(list(path.glob('image-*.png')))==1
        with Image.open(path/'image-000.png') as im:
            assert im.convert('RGB').getpixel((2,2))==(20,70,230)
        assert first['tool_output']['url_at_capture']==ORIGIN+'/'
        assert first['observation_reused'] and not captures[0]['error']
        if mode=='fresh_large':assert first['tool_output']['visual_readiness']['reason']=='region_element_limit'
        else:
            assert rows[1]['batch_calls'][0]['not_executed']
            assert 'click' in native_guards
    else:
        assert not image_parts and not list(path.glob('image-*.png'))
        if mode.startswith('blocked_'):
            assert len(requests)==1 and summary['error']
            assert captures[0]['error'] and 4.9<=captures[0]['seconds']<6
        else:
            assert summary['error'] is None,summary
            assert first.get('not_executed') or first.get('batch_guard_error')
            if mode=='before_navigation':assert not captures and not first['action_dispatch_started']
            else:assert captures[0]['error'] and list(path.glob('visual-capture-*.png'))
    result={'passed':True,'case':mode,'trace':str(path),'summary':summary,'viewport_captures':captures,
        'native_guard_tools':native_guards,'delivered_images':len(image_parts),'model_calls':0}
    write_json(out/'report.json',result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    sources=[*Path('intent_browser').glob('*.py'),Path(__file__)];hashes=lambda:{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources};before=hashes()
    with ProcessPoolExecutor(max_workers=3,mp_context=multiprocessing.get_context('spawn')) as pool:
        cases=list(pool.map(run_viewport,[(m,str(a.output/m)) for m in CASES]))
    assert hashes()==before
    write_json(a.output/'report.json',{'passed':True,'cases':cases,'source_sha256':before,'model_calls':0})
