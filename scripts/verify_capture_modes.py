"""Delayed local captures/guards in both timeout modes; mocked model only."""
from verify_guard_deadline import *
from playwright._impl._frame import Frame as ImplFrame
from intent_browser.native_capture import START


def run_mode(args):
    kind,mode,output=args;out=Path(output);out.mkdir(parents=True,exist_ok=False)
    profile=with_human_handover(open_profile(native_tools_profile(parallel_tool_calls=None,compact_feedback=True,
        ax_config=AXConfig(tokenizer_path(),incremental=True),batch_size=8)),compact_tabs=True,stable_frames=True,
        capture_timeout_mode=mode)
    held={};requests=[];delays=[];armed=False;observed_overruns=[]
    class Task(OpenEndedTask):
        def setup(self,page):
            self.page=page
            page.route('**/*',lambda r:r.fulfill(content_type='text/html',body=(
                '<h1>Timing test</h1><input id=target value=unchanged><script>window.inputs=0;target.oninput=()=>window.inputs++</script>'
                '<iframe src="http://child.invalid/child"></iframe>' if r.request.url.startswith(ORIGIN) else '<button>Child content</button>')))
            return super().setup(page)
        def teardown(self):
            held['final']=self.page.evaluate('({value:target.value,inputs:window.inputs})')
            return super().teardown()
    def factory(_):
        held['env']=BrowserEnv(task_entrypoint=Task,task_kwargs={'start_url':ORIGIN,'goal':'Fill the public input once with updated.'},
            headless=True,action_mapping=make_action_set(profile.tools.names).to_python_code)
        return held['env']
    def transport(req):
        requests.append(json.loads(req.content));index=len(requests)
        name,arguments=(('ax_search',{'query':'Timing'}) if index==1 else
            ('fill',{'bid':held['env'].page.locator('#target').get_attribute('bid'),'value':'updated'}) if index==2 else
            ('send_msg_to_user',{'text':'Filled the input.'}))
        return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
            'tool_calls':[{'id':f'call-{index}','type':'function','function':{'name':name,'arguments':json.dumps(arguments)}}]}}]})
    native_event=Trace.event;native_evaluate=Frame.evaluate;native_cookies=BrowserContext.cookies;native_owner=ImplFrame.frame_element
    def event(trace,name,**data):
        nonlocal armed
        result=native_event(trace,name,**data)
        if name=='native_capture_completed' and data.get('observed_at',{}).get('phase')=='batch_guard':armed=True
        if name.endswith('_budget_overrun'):observed_overruns.append({'event':name,'while_delay_pending':bool(delays and not delays[-1]['finished']),**data})
        return result
    def delay(seconds):
        delays.append({'seconds':seconds,'finished':False})
        result=native_evaluate(held['env'].page.main_frame,'ms=>new Promise(resolve=>setTimeout(resolve,ms))',seconds*1000)
        delays[-1]['finished']=True
        return result
    def evaluate(frame,expression,*a,**kw):
        if kind=='capture' and len(requests)==1 and not delays and expression==START:delay(5.6)
        return native_evaluate(frame,expression,*a,**kw)
    def cookies(context,*a,**kw):
        if kind=='guard' and armed and not delays:delay(2.3)
        return native_cookies(context,*a,**kw)
    async def owner(frame):
        if kind=='owner' and len(requests)==1 and not delays and '/child' in frame.url:
            delays.append({'seconds':.75,'finished':False})
            await frame.evaluate('()=>new Promise(resolve=>setTimeout(resolve,750))')
            delays[-1]['finished']=True
        return await native_owner(frame)
    backend=ChatCompletionsBackend('https://offline.invalid/v1','scripted');backend.client.close()
    backend.client=httpx.Client(transport=httpx.MockTransport(transport));backend.requires_browser_thread=True
    try:
        with patch.object(Trace,'event',event),patch.object(Frame,'evaluate',evaluate), \
                patch.object(BrowserContext,'cookies',cookies),patch.object(ImplFrame,'frame_element',owner):
            path,summary=run_episode(factory,backend,{'driver':'capture_modes','model_calls':0},output=out/'runs',max_steps=3,
                harness_profile=profile,human_handover=HumanHandoverController(),
                observation_pipeline=ObservationPipelineConfig((),full_capture_only=True))
    finally:backend.close()
    assert len(delays)==1 and not summary['cleanup_errors'],(delays,summary)
    metadata=json.loads((path/'metadata.json').read_text())
    assert metadata['human_handover']['capture_timeout_mode']==mode
    assert metadata['human_handover']['capture_deadlines_enforced']==(mode=='bounded')
    events=[json.loads(l) for l in (path/'events.jsonl').read_text().splitlines()]
    if mode=='bounded' and kind!='owner':
        assert 'CaptureDeadlineExceeded' in summary['error'] and held['final']['inputs']==0,summary
    else:
        assert summary['error'] is None and summary['stop_reason']=='agent_finished',summary
        assert held['final']=={'value':'updated','inputs':1},held
    if mode=='diagnostic':
        assert delays[0]['finished']
        if kind!='owner':assert any(e['while_delay_pending'] and not e['enforced'] for e in observed_overruns),observed_overruns
        assert not any(e['event']=='native_frame_quarantined' for e in events)
        if kind=='owner':
            assert not any(e['event']=='human_tab_frame_coverage' and e['partial'] for e in events)
    elif kind=='owner':assert any(e['event']=='human_tab_frame_coverage' and e['partial'] for e in events)
    result={'passed':True,'case':kind,'mode':mode,'trace':str(path),'summary':summary,'delay':delays,
        'overruns':observed_overruns,'final_state':held['final'],'mock_requests':len(requests),'model_calls':0}
    write_json(out/'report.json',result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    paths=[*Path('intent_browser').glob('*.py'),Path(__file__)]
    hashes=lambda:{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths};before=hashes()
    with ProcessPoolExecutor(max_workers=3,mp_context=multiprocessing.get_context('spawn')) as pool:
        cases=list(pool.map(run_mode,[(kind,mode,str(a.output/f'{kind}-{mode}')) for kind in ('capture','guard','owner') for mode in ('bounded','diagnostic')]))
    assert hashes()==before
    write_json(a.output/'report.json',{'passed':True,'cases':cases,'source_sha256':before,'model_calls':0})
