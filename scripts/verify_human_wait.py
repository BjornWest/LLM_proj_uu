"""Local actual runner/CDP/HTTP handover checks; scripted responses, no model calls."""
from verify_human_tabs import *
from intent_browser.human_handover_ui import HumanHandoverUI
from intent_browser.tab_context import TabContext
from measure_tab_context import replay
import gzip,re


def run_wait(args):
    mode,out,*options=args;stable_frames=bool(options and options[0]);out=Path(out);out.mkdir(parents=True,exist_ok=False)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body=b'<title>Wait fixture</title><h1 id="state">Needs human verification</h1>'
            self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def log_message(self,*a):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));cdp_port=sock.getsockname()[1]
    controller=HumanHandoverController();panel=HumanHandoverUI(controller)
    profile=with_human_handover(open_profile(native_tools_profile(parallel_tool_calls=None,compact_feedback=True,
        ax_config=AXConfig(tokenizer_path(),incremental=True),batch_size=8)),wait_for_human=True,compact_tabs=True,stable_frames=stable_frames)
    held={};requests=[];errors=[];finish=Event();thread=None;state={}
    def factory(_):
        env=BrowserEnv(task_entrypoint=OpenEndedTask,task_kwargs={'start_url':origin,'goal':'Request human verification and wait here.'},
            headless=True,action_mapping=make_action_set(profile.tools.names).to_python_code)
        held['env']=env;close=env.close
        def capture_close():
            state['pages']=len(env.context.pages);state['controller']=controller.snapshot()
            return close()
        env.close=capture_close;return env
    def human():
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.connect_over_cdp(f'http://127.0.0.1:{cdp_port}')
                page=next(p for p in browser.contexts[0].pages if p.url.startswith(origin))
                deadline=time.monotonic()+20
                while True:
                    tabs=httpx.get(panel.origin+'/state').json()['tabs']
                    pending=next((t for t in tabs if t['state']=='awaiting_human'),None)
                    if pending:break
                    if time.monotonic()>deadline:raise TimeoutError('No handover')
                    time.sleep(.05)
                assert len(requests)==1
                time.sleep(5.2 if mode=='complete' else .4);assert len(requests)==1  # No model calls during wait.
                def signal(event):
                    r=httpx.post(panel.origin+'/signal',headers={'Origin':panel.origin,'X-Handover-Token':panel._token},
                        json={'tab_id':pending['tab_id'],'handover_id':pending['handover_id'],'event':event})
                    assert r.status_code==200,r.text
                if mode=='close':page.close()
                else:
                    if mode=='complete':
                        signal('start');page.locator('#state').evaluate("e=>e.textContent='Human changed page, inspect this result'")
                    signal(mode)
                finish.wait(20)
        except Exception as e:errors.append(repr(e));controller.close('tab-1')
    def transport(req):
        nonlocal thread
        request=json.loads(req.content);requests.append(request);n=len(requests)
        if n==1:
            thread=Thread(target=human,daemon=True);thread.start()
            calls=[('handover_tab',{'tab_id':'tab-1','reason':'Please complete human verification here.'})]
        elif n==2:
            if mode=='complete':assert 'Human changed page, inspect this result' in json.dumps(request['messages'])
            calls=[('new_tab',{})]  # Runtime rejects rather than opening a replacement.
        else:calls=[('send_msg_to_user',{'text':'Inspected the returned page.'})]
        return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
            'tool_calls':[{'id':f'{n}-{i}','type':'function','function':{'name':name,'arguments':json.dumps(value)}} for i,(name,value) in enumerate(calls)]}}]})
    backend=ChatCompletionsBackend('https://offline.invalid/v1','mock');backend.client.close()
    backend.client=httpx.Client(transport=httpx.MockTransport(transport));backend.requires_browser_thread=True
    launch_original=BrowserType.launch
    def launch(bt,**kwargs):
        kwargs['args']=[*kwargs.get('args',[]),f'--remote-debugging-port={cdp_port}']
        return launch_original(bt,**kwargs)
    try:
        with patch.object(BrowserType,'launch',launch):
            path,summary=run_episode(factory,backend,{'driver':'offline_wait','model_calls':0},output=out/'runs',max_steps=3,
                harness_profile=profile,human_handover=controller,human_handover_ui=panel,
                observation_pipeline=ObservationPipelineConfig((),full_capture_only=True))
    finally:
        finish.set()
        if thread:thread.join(10)
        backend.close();panel.close();server.shutdown();server.server_close()
    assert not errors,errors
    events=[json.loads(s) for s in (path/'events.jsonl').read_text().splitlines()]
    rows=[json.loads(s) for s in (path/'steps.jsonl').read_text().splitlines()]
    assert not any(e['event']=='human_tab_workspace_created' for e in events)
    assert state['pages']==(0 if mode=='close' else 1),state
    assert all(r['tools']==requests[0]['tools'] for r in requests)
    reconstructed=None;previous_messages=[]
    for i,request in enumerate(requests):
        # Every earlier message remains byte-identical as new history is appended.
        assert request['messages'][:len(previous_messages)]==previous_messages
        previous_messages=request['messages']
        text=(path/rows[i]['observation']['text']).read_text()
        match=re.search(r'(?m)^BROWSER TABS [^\n]*?: (\{[^\n]*\})$',text)
        assert match,text[:300]
        projected=json.loads(match[1]);reconstructed=replay(reconstructed,projected)
        with gzip.open(path/rows[i]['observation']['raw'],'rt') as f:raw=json.load(f)
        assert reconstructed==TabContext.state(raw['human_tabs'])
        assert match[0] in json.dumps(request['messages'],ensure_ascii=False).replace('\\"','"') or any(
            match[0] in m.get('content','') for m in request['messages'] if isinstance(m.get('content'),str))

    if mode=='close':
        assert summary['error'] and len(requests)==1,summary
    else:
        assert summary['error'] is None,summary
        assert rows[0]['batch_calls'][0]['tool_output']['human_return']==mode
        assert rows[1]['batch_calls'][0]['tool_output']['execution']=='not_executed'
        assert any(e['event']=='human_tab_return_observed' for e in events)
        assert len([e for e in events if e['event']=='tab_context_constructed'])==len(requests)
    result={'passed':True,'case':mode,'trace':str(path),'summary':summary,'model_calls':0,'requests':len(requests)}
    (out/'report.json').write_text(json.dumps(result,indent=2));return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--stable-frames',action='store_true');a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    sources=list((ROOT/'intent_browser').glob('*.py'))+[Path(__file__).resolve()]
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    with ProcessPoolExecutor(max_workers=3,mp_context=multiprocessing.get_context('spawn')) as pool:
        cases=list(pool.map(run_wait,[(m,str(a.output/m),a.stable_frames) for m in ('complete','cancel','close')]))
    assert hashes=={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    (a.output/'report.json').write_text(json.dumps({'passed':True,'cases':cases,'source_sha256':hashes,'model_calls':0,
        'artifacts_sha256':{str(p.relative_to(a.output)):hashlib.sha256(p.read_bytes()).hexdigest() for p in a.output.rglob('*') if p.is_file()}},indent=2))
