"""Finite model-free native browser probe for the reviewed capacity RPC.

Uses three isolated subprocess/browser sessions and a local scripted HTTP service.
Synthetic metrics qualify consumer wiring only, never vLLM/MTP or real pressure.
"""
from contextlib import contextmanager
from dataclasses import replace
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen
import importlib.util,json,os,runpy,select,signal,socket,subprocess,sys,tempfile,threading,time,types


def load(p):return json.loads(Path(p).read_bytes())
def save(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x') as f:json.dump(x,f,indent=2,allow_nan=False);f.write('\n')
def pin(p):return {'path':str(Path(p).resolve()),'sha256':sha256(Path(p).read_bytes()).hexdigest()}
def checked(r):
    p=Path(r['path'])
    if p.is_symlink() or pin(p)!=r:raise ValueError('Changed source/input: '+str(p))
    return p

def module(name,p):
    spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec)
    sys.modules[name]=m;spec.loader.exec_module(m);return m

def bindings(s):
    for r in s['owned_sources'].values():checked(r)
    return (module('_native_capacity_rpc',checked(s['owned_sources']['rpc'])),
        module('_native_capacity_controller',checked(s['owned_sources']['controller'])),
        module('_native_capacity_queue',checked(s['queue'])),
        module('_native_capacity_channel',checked(s['channel'])))

def serve_native(connection,admission,parent,case,channel,queue,expected_root):
    """Direct channel path retains native/user cancellation classification."""
    try:return channel.serve_admission(connection,admission,expected_run_root=expected_root)
    except (type(parent).activate.__globals__['CapacitySuiteStopped'],queue.QueueCancelled) as exc:
        parent.abort_after_failure(case,exc,infrastructure=False)
        raise queue.QueueCancelled(str(exc)) from exc
    except BaseException as exc:
        parent.abort_after_failure(case,exc,infrastructure=True);raise

def terminal_proof(parent,case,process,record,verify_http):
    """Grade existence or clean EOF alone never proves a native completion."""
    if process.poll()!=0 or case in parent.errors or record.get('status')!='graded_and_projected':return False
    projection=record.get('projection',{})
    for key in ('automatic','canonical'):checked(projection[key])
    automatic=load(projection['automatic']['path']);canonical=load(projection['canonical']['path'])
    return (automatic.get('status')=='graded' and canonical.get('technical_error') is None
        and 'task_completed' in canonical and (canonical['task_completed'] is None or type(canonical['task_completed']) is bool) and verify_http(projection) is True)

class NativeProbeTermination(BaseException):
    """Owned termination must execute native runner/client finally blocks."""


def terminate_probe(*_):
    # Do not inject a second exception while native finally blocks unwind.
    signal.signal(signal.SIGTERM,signal.SIG_IGN)
    signal.signal(signal.SIGINT,signal.SIG_IGN)
    raise NativeProbeTermination('Owned native probe termination')


def start_ticks(pid):
    try:
        data=(Path('/proc')/str(pid)/'stat').read_text()
        return data[data.rfind(')')+2:].split()[19]
    except (FileNotFoundError,ProcessLookupError):return None


def remember_descendants(process):
    import psutil
    known=getattr(process,'_owned_descendants',{})
    # Never enumerate a reaped Popen PID: it can now identify another process.
    if process.poll() is not None:return known
    current=start_ticks(process.pid)
    if current is None:return known
    expected=getattr(process,'_owned_root_start',None)
    if expected is None:process._owned_root_start=current
    elif expected!=current:return known
    try:
        for child in psutil.Process(process.pid).children(recursive=True):
            identity=start_ticks(child.pid)
            if identity is not None:known[child.pid]=identity
    except psutil.NoSuchProcess:pass
    process._owned_descendants=known
    return known


def stop_process(process, timeout=5):
    """Allow cancelled native cleanup first; fence roots and descendants."""
    import psutil
    descendants=remember_descendants(process)
    if process.poll() is None:
        # RPC/admission cancellation already woke the child. Avoid injecting a
        # signal into cleanup which is already running.
        try:process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            descendants=remember_descendants(process)
            if start_ticks(process.pid)!=getattr(process,'_owned_root_start',None):
                raise RuntimeError('Native child root identity changed; refusing termination')
            process.terminate()
            try:process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                if start_ticks(process.pid)!=getattr(process,'_owned_root_start',None):
                    raise RuntimeError('Native child root identity changed; refusing kill')
                process.kill();process.wait(timeout=timeout)
    def live():
        rows=[]
        for pid,started in descendants.items():
            try:
                if start_ticks(pid)!=started:continue
                child=psutil.Process(pid)
                if child.is_running() and child.status()!=psutil.STATUS_ZOMBIE:rows.append(child)
            except psutil.NoSuchProcess:pass
        return rows
    deadline=time.monotonic()+timeout
    while live() and time.monotonic()<deadline:time.sleep(.05)
    remaining=live()
    for child in remaining:
        if start_ticks(child.pid)==descendants[child.pid]:child.terminate()
    _,alive=psutil.wait_procs(remaining,timeout=timeout)
    for child in alive:
        if start_ticks(child.pid)==descendants[child.pid]:child.kill()
    psutil.wait_procs(alive,timeout=timeout)
    if live():raise RuntimeError('Owned native browser descendants remain live')


def cleanup_resources(processes,service,poller,http,http_thread,pairs,parent,controller,drain):
    """One failure must not skip cleanup of independently owned resources."""
    errors=[]
    def attempt(name,operation):
        try:operation()
        except BaseException as exc:errors.append({'resource':name,'type':type(exc).__name__,'message':str(exc)})
    for case,process in processes.items():attempt(case,lambda p=process:stop_process(p))
    if service:attempt('tokenizer',lambda:stop_process(service))
    if poller:attempt('poller',poller.close)
    attempt('http_shutdown',http.shutdown);attempt('http_close',http.server_close)
    def join():
        http_thread.join(5)
        if http_thread.is_alive():raise TimeoutError('HTTP listener did not stop')
    attempt('http_listener',join)
    for case,(_,b) in pairs.items():attempt('child_socket:'+case,b.close)
    attempt('capacity_parent',parent.close);attempt('controller',controller.close)
    attempt('HTTP_workers',drain)
    return errors

def cleanup_early_resources(pairs,parent,controller):
    errors=[]
    for case,pair in pairs.items():
        for side,connection in enumerate(pair):
            try:connection.close()
            except BaseException as error:errors.append((case,str(side),type(error).__name__))
    for name,resource in (('parent',parent),('controller',controller)):
        if resource is not None:
            try:resource.close()
            except BaseException as error:errors.append((name,type(error).__name__))
    return errors


def child(s,case,admission_fd,capacity_fd):
    signal.signal(signal.SIGTERM,terminate_probe)
    signal.signal(signal.SIGINT,terminate_probe)
    rpc,_,_,channel=bindings(s);h=runpy.run_path(str(checked(s['helpers'])))
    c=dict(s['case'],id=case);run=h['configure_case'](s,c)
    from intent_browser.backend import ChatCompletionsBackend
    from intent_browser.runner import run_episode
    from intent_browser.episode_admission import EpisodeAdmissionCancelled
    from intent_browser.shared_tokenizer import SharedTokenizerConfig
    from intent_browser.input_budget import QwenInputCounter
    out=Path(s['output'])/case;out.mkdir(exist_ok=False)
    admission_socket=socket.socket(fileno=admission_fd);admission_socket.settimeout(150)
    admission=channel.ChildAdmission(admission_socket,case,EpisodeAdmissionCancelled)
    events=[];envs=[];reset_count=0;freshness=[]
    def event(row):
        events.append(row)
        with (out/'capacity-events.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
    client=rpc.CapacityClient(socket.socket(fileno=capacity_fd),deadline=s['deadline'],on_event=event)
    def guard():
        admission.before_dispatch();h['module_origins'](s,c)
        if time.monotonic()>=s['deadline']:raise TimeoutError('Native probe deadline')
    def fresh(phase):
        if phase=='formatter':
            traces=list((out/'live/runs').glob('*'))
            if len(traces)!=1:raise RuntimeError('Ambiguous external grading trace')
            declaration=load(traces[0]/'automatic-grading.json')
            answer=load(traces[0]/'natural-answer.json')
            if not declaration.get('binding') or answer['text']!=load(checked(s['scripted_answer']))['text']:
                raise RuntimeError('External formatter lost bound native answer/capture')
            freshness.append({'phase':phase,'monotonic':time.monotonic(),'answer':pin(traces[0]/'natural-answer.json'),'binding_sha256':sha256(json.dumps(declaration['binding'],sort_keys=True).encode()).hexdigest()})
            return
        if len(envs)!=1:raise RuntimeError('Expected one native environment')
        page=envs[0].unwrapped.page
        if page.is_closed():raise RuntimeError('Browser closed after parking')
        image=page.screenshot(timeout=5000)
        freshness.append({'phase':phase,'monotonic':time.monotonic(),'url':page.url,'screenshot_sha256':sha256(image).hexdigest()})
    def backend(phase):
        raw=ChatCompletionsBackend(s['http_url']+'/v1','scripted-'+phase+'-'+case,timeout=30,max_tokens=4096,supports_images=True)
        return rpc.CapacityBackend(raw,client,phase=phase,guard=guard,freshness_guard=lambda:fresh(phase),buffered_completion=True)
    @contextmanager
    def session(*,before_dispatch):
        b=backend('policy')
        # Consumer dispatch callback remains bound inside the underlying HTTP path.
        b.backend.client.event_hooks={'request':[lambda _:before_dispatch()]}
        try:yield b
        finally:b.close()
    def runner(factory,b,metadata,**kw):
        if kw['automatic_grading'].phase!='external':raise RuntimeError('Native grader required before any request')
        shared=SharedTokenizerConfig(s['tokenizer_socket']);profile=h['policy_profile'](kw['harness_profile'],discovery=False)
        kw.update(harness_profile=replace(profile,ax_config=replace(profile.ax_config,shared_tokenizer=shared)),
            input_counter=QwenInputCounter(checked(s['tokenizer']),shared_tokenizer=shared),
            environment_admission=admission.environment_admission,retry_policy=None)
        def environment(video=None):
            nonlocal reset_count
            env=factory(video);envs.append(env);original=env.reset
            def reset(*a,**k):
                nonlocal reset_count
                reset_count+=1;return original(*a,**k)
            env.reset=reset
            if s.get('fault')=='failed_close' and case=='native-a':
                original_close=env.close
                def close():
                    original_close()
                    raise RuntimeError('Injected native browser cleanup failure')
                env.close=close
            return env
        return run_episode(environment,b,metadata,**kw)
    def projection(*,trace,grade):return h['verify_projection'](s,trace)
    try:
        result=run(c['argument'],out/'live',policy_session=session,metadata={'suite':s['suite_id'],'case':case,'model':'scripted','tags':['scripted','capacity-native-probe']},
            runner_options={'max_steps':1,'max_input_tokens':120000,'trace_screenshots':True,'async_recording':False},
            viewer_projection=projection,quota_guard=lambda:None,runner=runner,**h['case_options']({**c,'id':c['task_id']},lambda _:backend('formatter')))
        save(out/'native-lifecycle-result.json',result)
        if result['status']!='graded_and_projected' or result['viewer_projection']['task_completed'] is not True:raise RuntimeError('Native positive grade/HTTP missing: '+str(result.get('reason',result.get('policy_summary',{}).get('error'))))
        if client.infrastructure_error or reset_count!=1:raise RuntimeError('Capacity release/reset failure')
        save(out/'result.json',{'status':'graded_and_projected','result':result,'projection':result['viewer_projection'],'reset_count':reset_count,'freshness':freshness,'events':events,'models':0,'providers':0})
    except BaseException as exc:
        save(out/'failure.json',{'type':type(exc).__name__,'message':str(exc),'infrastructure_error':client.infrastructure_error,'events':events});raise
    finally:
        try:client.close()
        finally:admission_socket.close()

def parent(s):
    signal.signal(signal.SIGTERM,terminate_probe)
    signal.signal(signal.SIGINT,terminate_probe)
    rpc,control,queue,channel=bindings(s);h=runpy.run_path(str(checked(s['helpers'])))
    if s.get('fault') not in (None,'cancel_warm','failed_close'):raise ValueError('Explicit supported model-free failure control required')
    answer=load(checked(s['scripted_answer']))['text'];claims=load(checked(s['scripted_claims']))
    out=Path(s['output']);out.mkdir(exist_ok=False);cases=['native-a','native-b','native-c']
    s=dict(s,deadline=time.monotonic()+160)
    h['register_roots']({**s,'cases':[dict(s['case'],id=i) for i in cases]})
    stop=threading.Event();pairs={i:socket.socketpair() for i in cases}
    controller=None;cap=None
    try:
        controller=control.EpisodeCapacityController(control.ParkingConfig(max_active_episodes=s['active_cap'],max_generation_requests=s['generation_cap'],fresh_seconds=2))
        cap=rpc.CapacityParent(controller,{i:p[0] for i,p in pairs.items()},deadline=s['deadline'],suite_stop_event=stop)
        cap.start()
    except BaseException as primary:
        errors=cleanup_early_resources(pairs,cap,controller)
        if errors:primary.add_note('Early capacity cleanup failures: '+repr(errors))
        raise
    lock=threading.Lock();state={'pressure':False,'policy':set(),'inflight':set(),'peak':0,'requests':[],'ready':{}};poller=None;service=None;processes={}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def reply(self,body):
            raw=body if isinstance(body,bytes) else json.dumps(body).encode()
            self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            with lock:pressure=state['pressure']
            self.reply(('vllm:num_requests_running{model_name="native-probe",engine="0"} 0\n'
                +'vllm:num_requests_waiting{model_name="native-probe",engine="0"} '+str(int(pressure))+'\n'
                +'vllm:num_requests_waiting_by_reason{model_name="native-probe",engine="0",reason="capacity"} '+str(int(pressure))+'\n'
                +'vllm:num_requests_waiting_by_reason{model_name="native-probe",engine="0",reason="deferred"} 0\n'
                +'vllm:kv_cache_usage_perc{model_name="native-probe",engine="0"} '+('.95' if pressure else '.1')+'\n'
                +'vllm:num_preemptions_total{model_name="native-probe",engine="0"} 0\n').encode())
        def do_POST(self):
            value=json.loads(self.rfile.read(int(self.headers['Content-Length'])));_,phase,case=value['model'].split('-',2)
            with lock:
                key=(case,phase);state['inflight'].add(key);state['peak']=max(state['peak'],len(state['inflight']))
                state['requests'].append({'case':case,'phase':phase,'monotonic':time.monotonic()})
                if phase=='policy':state['policy'].add(case)
            try:
                if s['require_parking'] and phase=='policy' and case in ('native-a','native-b'):
                    deadline=time.monotonic()+40
                    while True:
                        if stop.is_set():raise RuntimeError('Probe stopped during scripted HTTP')
                        with lock:both={'native-a','native-b'}<=state['policy']
                        if both:break
                        if time.monotonic()>deadline:raise TimeoutError('Initial native policies did not meet')
                        time.sleep(.01)
                    with lock:state['pressure']=True
                    while not controller.status()['episodes'].get('native-b',{}).get('park_requested'):
                        if stop.is_set():raise RuntimeError('Probe stopped during parking')
                        if time.monotonic()>deadline:raise TimeoutError('Sticky park not observed')
                        time.sleep(.01)
                    with lock:state['pressure']=False
                    while controller.status()['telemetry']['capacity_waiting']:
                        if stop.is_set():raise RuntimeError('Probe stopped during recovery')
                        if time.monotonic()>deadline:raise TimeoutError('Healthy telemetry not observed')
                        time.sleep(.01)
                if not s['require_parking'] and phase=='policy' and case=='native-a':
                    limit=time.monotonic()+40
                    while 'native-b' not in state['ready']:
                        if stop.is_set():raise RuntimeError('Probe stopped during warming')
                        if time.monotonic()>limit:raise TimeoutError('Warm browser never ready')
                        time.sleep(.01)
                if s.get('fault')=='cancel_warm' and phase=='policy' and case=='native-a':
                    cap.abort_after_failure(case,queue.QueueCancelled('Injected user cancellation with a warmed browser'),infrastructure=False)
                if phase=='policy':message={'role':'assistant','content':None,'tool_calls':[{'id':'positive','type':'function','function':{'name':'send_msg_to_user','arguments':json.dumps({'text':answer})}}]};finish='tool_calls'
                else:message={'role':'assistant','content':json.dumps(claims)};finish='stop'
                self.reply({'model':value['model'],'choices':[{'finish_reason':finish,'message':message}],'usage':{}})
            finally:
                with lock:state['inflight'].discard((case,phase))
    http=None;http_thread=None
    try:
        http=ThreadingHTTPServer(('127.0.0.1',0),Handler);http.daemon_threads=True
        http_thread=threading.Thread(target=http.serve_forever);http_thread.start();s['http_url']='http://127.0.0.1:'+str(http.server_port)
    except BaseException as primary:
        errors=cleanup_early_resources(pairs,cap,controller)
        if http is not None:
            try:http.server_close()
            except BaseException as error:errors.append(('http',type(error).__name__))
        if errors:primary.add_note('Early HTTP cleanup failures: '+repr(errors))
        raise
    try:
        poller=control.SharedMetricsPoller(s['http_url']+'/metrics',model='native-probe',interval=.05,timeout=1,on_snapshot=controller.observe).start()
        with tempfile.TemporaryDirectory(prefix='native-cap-') as temp:
            s['tokenizer_socket']=str(Path(temp)/'tokenizer.sock');assets=Path(temp)/'assets.json';save(assets,[{**s['tokenizer'],'normalization':'raw'}])
            service=subprocess.Popen([s['python'],'-I','-B','-c',"import sys;sys.path.insert(0,sys.argv[1]);from intent_browser.tokenizer_service import main;sys.argv=sys.argv[1:];sys.argv[0]='tokenizer_service';main()",s['case']['root'],'--socket',s['tokenizer_socket'],'--manifest',str(assets),'--max-clients','4'],stdout=subprocess.PIPE,stderr=(out/'tokenizer-stderr.log').open('x'),env={**os.environ,**s['cpu_thread_limits'],'LD_LIBRARY_PATH':s['library_path']})
            if not select.select([service.stdout],[],[],30)[0] or not json.loads(service.stdout.readline()).get('ready'):raise RuntimeError('Tokenizer not ready')
            runtime=out/'runtime.json';save(runtime,s)
            def verify_http(projection):
                with urlopen(s['viewer_url']+'/api/sessions/'+projection['trace_id'],timeout=10) as r:body=json.load(r)
                derived=body['derived_evaluation']
                canonical=load(projection['canonical']['path'])
                return derived.get('binding_status')=='verified' and derived.get('structured_claims_correct') is canonical['task_completed']
            def one(case,admission):
                a,b=socket.socketpair();process=None;wrapped=rpc.ActiveCapacityAdmission(admission,cap,case,priority=cases.index(case))
                original_ready=wrapped.environment_ready
                def ready(value=None):
                    with lock:state['ready'][case]={'monotonic':time.monotonic(),'directory':str(value.directory)}
                    remember_descendants(processes[case])
                    return original_ready(value)
                wrapped.environment_ready=ready
                try:
                    child_socket=pairs[case][1]
                    process=subprocess.Popen([s['python'],'-I','-B',str(checked(s['owned_sources']['probe'])),'child',str(runtime),case,str(b.fileno()),str(child_socket.fileno())],pass_fds=(b.fileno(),child_socket.fileno()),stdout=(out/(case+'-stdout.log')).open('x'),stderr=(out/(case+'-stderr.log')).open('x'),env={**os.environ,**s['cpu_thread_limits'],'LD_LIBRARY_PATH':s['library_path']})
                    processes[case]=process;remember_descendants(process);b.close();child_socket.close();a.settimeout(150)
                    wire=serve_native(a,wrapped,cap,case,channel,queue,out/case/'live/runs')
                    process.wait(timeout=max(1,s['deadline']-time.monotonic()))
                    if process.returncode!=0:
                        path=out/case/'failure.json'
                        if path.is_file():
                            failure=load(path)
                            raise RuntimeError('Native child '+failure['type']+': '+failure['message'])
                        raise RuntimeError('Native child exited '+str(process.returncode)+' before failure receipt; see '+str(out/(case+'-stderr.log')))
                    record=load(out/case/'result.json')
                    def cleanup():
                        with lock:no_http=all(k[0]!=case for k in state['inflight'])
                        return process.poll()==0 and no_http and case in cap.ended
                    cap.finish_after_cleanup(case,verify_cleanup=cleanup,record_terminal=lambda:terminal_proof(cap,case,process,record,verify_http))
                    if case not in cap.finished:raise RuntimeError('Actor never finished')
                    return {'wire':wire,'result':pin(out/case/'result.json'),'exitcode':process.returncode}
                except queue.QueueCancelled as exc:cap.abort_after_failure(case,exc,infrastructure=False);raise
                except BaseException as exc:cap.abort_after_failure(case,exc,infrastructure=True);raise
                finally:
                    a.close();b.close();pairs[case][1].close()
                    if process and process.poll() is None:stop_process(process)
            result=queue.run_ordered_suite({i:i for i in cases},one,max_concurrent_episodes=s['active_cap'],prewarm_count=s['prewarm_count'],stop_event=stop)
            status=controller.status();events=status['events']
            with lock:requests=list(state['requests']);peak=state['peak']
            passed=(not result['cancelled'] and all(r['status']=='completed' for r in result['cases'].values()) and set(cases)<=cap.finished
                and not cap.cleanup_failures and peak<=s['generation_cap']
                and (not s['require_parking'] or (any(e['kind']=='episode_parked' for e in events) and any(e['kind']=='resume_granted' for e in events)))
                and all(e['active']<=s['active_cap'] and e['warming_or_ready']<=s['prewarm_count'] for e in result['events']))
            if s.get('fault') in ('cancel_warm','failed_close'):
                cause=cap.stop_cause
                passed=(bool(cause) and cause['case']=='native-a'
                    and cause['infrastructure'] is (s['fault']=='failed_close')
                    and not cap.finished and peak<=s['generation_cap']
                    and not any(r['case']!='native-a' for r in requests)
                    and any(r['case']=='native-a' and r['phase']=='policy' for r in requests)
                    and 'native-b' in state['ready'] and stop.is_set()
                    and all(e['active']<=s['active_cap'] and e['warming_or_ready']<=s['prewarm_count'] for e in result['events']))
                if s['fault']=='failed_close':
                    native=load(out/'native-a/native-lifecycle-result.json')
                    passed=passed and native['status']=='system_failure' and 'Injected native browser cleanup failure' in native.get('policy_summary',{}).get('error','')
            save(out/'terminal.json',{'passed':passed,'fault':s.get('fault'),'stop_cause':cap.stop_cause,'secondary_exits':list(cap.secondary_exits),'queue':result,'controller':status,'parent_errors':cap.errors,'finished':sorted(cap.finished),'cleanup_failures':cap.cleanup_failures,'ready':state['ready'],'actual_requests':requests,'peak_HTTP':peak,'models':0,'providers':0,'GPU':0,'synthetic_metrics_only':True})
            if not passed:raise RuntimeError('Native capacity qualification failed')
    finally:
        stop.set()
        primary=sys.exc_info()[1]
        def drain():
            limit=time.monotonic()+5
            while True:
                with lock:pending=bool(state['inflight'])
                if not pending:return
                if time.monotonic()>limit:raise TimeoutError('Local scripted HTTP not drained')
                time.sleep(.01)
        errors=cleanup_resources(processes,service,poller,http,http_thread,pairs,cap,controller,drain)
        save(out/'cleanup.json',{'passed':not errors,'errors':errors,'child_exits':{k:p.poll() for k,p in processes.items()},'owned_descendants':{k:getattr(p,'_owned_descendants',{})for k,p in processes.items()},'tokenizer_exit':service.poll() if service else None,'parent_threads_stopped':all(not t.is_alive() for t in cap.threads.values()),'listener_stopped':not http_thread.is_alive()})
        if errors:
            if primary is not None:primary.add_note('Native probe cleanup failures retained in cleanup.json')
            else:raise RuntimeError('Native probe cleanup failed: '+str(errors))

if __name__=='__main__':
    mode,config,*args=sys.argv[1:];s=load(config)
    if mode=='child':child(s,args[0],int(args[1]),int(args[2]))
    elif mode=='parent':parent(s)
    else:raise ValueError('Unknown finite probe mode')
