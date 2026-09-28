"""Native scoped close with real HAR/video finalization, local HTTP mock only."""
from verify_capture_shutdown import *
import random,zipfile

def run_recording(args):
    count,output=args;out=Path(output);out.mkdir(parents=True,exist_ok=False)
    held={};requests=[];blob=random.Random(17).randbytes(1024*1024)
    class Task(OpenEndedTask):
        def setup(self,page):
            def route(r):
                if '/asset/' in r.request.url:r.fulfill(content_type='application/octet-stream',body=blob)
                else:r.fulfill(content_type='text/html',body='<h1>Local recorded fixture</h1><p>No external requests.</p>')
            page.route('**/*',route);result=super().setup(page)
            page.evaluate('n=>Promise.all(Array.from({length:n},(_,i)=>fetch("/asset/"+i).then(r=>r.arrayBuffer())))',count)
            return result
    profile=with_human_handover(open_profile(native_tools_profile(parallel_tool_calls=None,compact_feedback=True,
        ax_config=AXConfig(tokenizer_path(),incremental=True),batch_size=8)),wait_for_human=False,compact_tabs=True,stable_frames=True)
    def factory(video):
        env=BrowserEnv(task_entrypoint=Task,task_kwargs={'start_url':ORIGIN,'goal':'Report that the page is visible.'},headless=True,
            action_mapping=make_action_set(profile.tools.names).to_python_code,record_video_dir=video,
            pw_context_kwargs={'record_har_path':str(out/'network.har.zip'),'record_har_content':'attach','record_har_mode':'full'})
        held['env']=env;return env
    def transport(req):
        requests.append(json.loads(req.content));held['browser']=held['env'].browser;held['chat_browser']=held['env'].chat.browser
        return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
            'tool_calls':[{'id':'answer-1','type':'function','function':{'name':'send_msg_to_user','arguments':json.dumps({'text':'The local recorded page is visible.'})}}]}}]})
    backend=ChatCompletionsBackend('https://offline.invalid/v1','scripted');backend.client.close()
    backend.client=httpx.Client(transport=httpx.MockTransport(transport));backend.requires_browser_thread=True
    try:
        path,summary=run_episode(factory,backend,{'driver':'recording_shutdown_fixture','model_calls':0},output=out/'runs',max_steps=1,record_video=True,
            harness_profile=profile,human_handover=HumanHandoverController(),observation_pipeline=ObservationPipelineConfig((),full_capture_only=True))
    finally:backend.close()
    assert summary['error'] is None and summary['stop_reason']=='agent_finished' and not summary['cleanup_errors'],summary
    assert len(requests)==1 and not held['browser'].is_connected() and not held['chat_browser'].is_connected()
    with zipfile.ZipFile(out/'network.har.zip') as z:
        assert z.testzip() is None
        har=json.loads(z.read(next(n for n in z.namelist() if n.endswith('.har'))))
        entries=[e for e in har['log']['entries'] if '/asset/' in e['request']['url']]
        assert len(entries)==count and all(e['response']['status']==200 for e in entries)
        for e in entries:
            content=e['response']['content'];assert z.read(content['_file'])==blob
    videos=list(path.rglob('*.webm'));assert videos and all(p.stat().st_size>0 for p in videos)
    events=[json.loads(l) for l in (path/'events.jsonl').read_text().splitlines()]
    result={'passed':True,'assets':count,'trace':str(path),'asset_body_bytes':count*len(blob),'har_bytes':(out/'network.har.zip').stat().st_size,
        'videos':[{'path':str(p),'bytes':p.stat().st_size} for p in videos],
        'cleanup':[e for e in events if e['event']=='cleanup_phase_completed'],'model_calls':0}
    write_json(out/'report.json',result);return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    sources=[*Path('intent_browser').glob('*.py'),Path(__file__)];hashes=lambda:{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources};before=hashes()
    with ProcessPoolExecutor(max_workers=2,mp_context=multiprocessing.get_context('spawn')) as pool:
        cases=list(pool.map(run_recording,[(n,str(a.output/str(n))) for n in [1,16]]))
    assert hashes()==before
    write_json(a.output/'report.json',{'passed':True,'cases':cases,'source_sha256':before,'model_calls':0})
