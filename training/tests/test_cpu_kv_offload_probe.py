"""Protocol/check gates for the isolated GPU probe; tests never use a GPU."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
import cpu_kv_offload_probe as p


def response(prompt, cached=0):
    return {'usage':{'prompt_tokens':len(prompt),'completion_tokens':p.OUTPUT_TOKENS,
                    'prompt_tokens_details':{'cached_tokens':cached}},
            'choices':[{'finish_reason':'length','text':'answer','logprobs':{
                        'tokens':['token_id:7']*p.OUTPUT_TOKENS}}]}


def metrics(model=p.MODEL, engine='0'):
    labels=f'model_name="{model}",engine="{engine}"'
    names={p.RUNNING:0,p.WAITING:0,p.GENERATION:64,'vllm:kv_cache_usage_perc':.3,
           p.LOAD:1024,p.HITS:2048,p.STORE:1024,p.DRAFT_TOKENS:192,p.CORRUPTED:0,p.PREEMPTIONS:0}
    text='\n'.join(f'{name}{{{labels}}} {value}'for name,value in names.items())+'\n'
    return text+f'vllm:num_requests_waiting_by_reason{{{labels},reason="capacity"}} 0\n'+f'vllm:num_requests_waiting_by_reason{{{labels},reason="deferred"}} 0\n'


class ProbeGateTests(unittest.TestCase):
    def test_command_retains_native_context_fp8_mtp_and_explicit_native_lru(self):
        argv=p.server_command('/snapshot')
        self.assertEqual(argv[1:4],['-m','vllm.entrypoints.cli.main','serve'])
        self.assertEqual(argv[argv.index('--max-model-len')+1],'262144')
        self.assertEqual(argv[argv.index('--kv-cache-dtype')+1],'fp8_e4m3')
        self.assertEqual(json.loads(argv[argv.index('--speculative-config')+1]),{'method':'mtp','num_speculative_tokens':3})
        kv=json.loads(argv[argv.index('--kv-transfer-config')+1])
        self.assertEqual(kv['kv_connector'],'OffloadingConnector')
        self.assertEqual(kv['kv_connector_extra_config']['cpu_bytes_to_use'],20<<30)
        self.assertEqual(kv['kv_connector_extra_config']['eviction_policy'],'lru')
        self.assertTrue(kv['kv_connector_extra_config']['offload_prompt_only'])
        self.assertNotIn('--enforce-eager',argv)

    def test_metrics_keeps_selected_engine_and_ignores_reason_dimensions(self):
        values=p.selected_metrics(metrics()+metrics(engine='1')+metrics(model='other'))
        self.assertEqual(values[p.LOAD],1024)
        self.assertNotIn('vllm:num_requests_waiting_by_reason',values)
        with self.assertRaises(ValueError):p.selected_metrics(metrics()+metrics())
        with self.assertRaises(ValueError):p.selected_metrics(metrics().replace('} 1024','} NaN'))
        with self.assertRaises(ValueError):p.selected_metrics(metrics(model='other'))
        for name in (p.CORRUPTED,p.PREEMPTIONS):
            with self.assertRaises(ValueError):
                p.selected_metrics('\n'.join(row for row in metrics().splitlines() if not row.startswith(name+'{')))

    def test_parses_actual_tokens_and_cached_usage(self):
        row=p.parse_completion(response([1,2,3],2),[1,2,3])
        self.assertEqual(row['token_ids'],[7]*64)
        self.assertEqual(row['cached_tokens'],2)
        for bad in [
            {'usage':{'prompt_tokens':2,'completion_tokens':64}},
            {'choices':[{'finish_reason':'stop','text':'answer','logprobs':{'tokens':['token_id:7']*64}}]},
            {'choices':[{'finish_reason':'length','text':'answer','logprobs':{'tokens':['7']*64}}]},
        ]:
            data=response([1,2,3]);data.update(bad)
            with self.assertRaises((ValueError,KeyError)):p.parse_completion(data,[1,2,3])

    def test_pass_requires_actual_cpu_load_hits_and_mtp_execution(self):
        prompt=[1]*p.PROMPT_TOKENS
        cold=p.parse_completion(response(prompt),prompt)
        cached=(p.PROMPT_TOKENS//p.CACHE_BLOCK_SIZE-1)*p.CACHE_BLOCK_SIZE
        warm=p.parse_completion(response(prompt,cached),prompt)
        before={p.LOAD:0,p.HITS:0,p.DRAFT_TOKENS:0}
        after={p.LOAD:1<<30,p.HITS:cached,p.DRAFT_TOKENS:192,p.STORE:1<<30}
        checks=p.restore_checks(cold,warm,warm,before,after,{}, {},True,{})
        self.assertTrue(p.restore_pass(checks))
        for name in ('cpu_to_gpu_bytes','external_hit_tokens','cycle_store_bytes','mtp_draft_tokens'):
            self.assertFalse(p.restore_pass(dict(checks,**{name:0})),name)
        for name in ('gpu_reset','identical_prompt','warm_cached_prefix','restore_cached_prefix','gpu_warm_used_no_cpu_load','gpu_control_output_matches','restored_output_matches'):
            self.assertFalse(p.restore_pass(dict(checks,**{name:False})),name)
        for name in ('new_corrupted_requests','new_preemptions','new_allocation_failures'):
            self.assertFalse(p.restore_pass(dict(checks,**{name:1})),name)
        self.assertTrue(p.restore_path_pass(dict(checks,gpu_control_output_matches=False)))
        self.assertFalse(p.restore_pass(dict(checks,gpu_control_output_matches=False)))
        self.assertFalse(p.restore_pass(dict(checks,external_hit_tokens=p.CACHE_BLOCK_SIZE)))
        self.assertFalse(p.restore_pass(dict(checks,cpu_to_gpu_bytes=checks['cycle_store_bytes']+1)))
        no_new_stores=p.restore_checks(cold,warm,warm,before,after,{}, {},True,{p.STORE:after[p.STORE]})
        self.assertFalse(p.restore_path_pass(no_new_stores))
        with self.assertRaises(ValueError):p.delta({p.HITS:1},{p.HITS:0},p.HITS)

    def test_server_validation_uses_actual_info_shape_without_version_key(self):
        argv=p.server_command('/snapshot')
        config={'model_config':{'model':'/snapshot'},'speculative_config':{'method':'mtp','num_speculative_tokens':3},
            'kv_transfer_config':json.loads(argv[argv.index('--kv-transfer-config')+1]),
            'cache_config':{'block_size':p.CACHE_BLOCK_SIZE}}
        self.assertEqual(p.validate_server({'vllm_config':config},'/snapshot'),config)
        for key,value in [('num_speculative_tokens',2),('method','eagle')]:
            bad=copy.deepcopy(config);bad['speculative_config'][key]=value
            with self.assertRaises(ValueError):p.validate_server({'vllm_config':bad},'/snapshot')
        bad=copy.deepcopy(config);bad['kv_transfer_config']['kv_connector']='Other'
        with self.assertRaises(ValueError):p.validate_server({'vllm_config':bad},'/snapshot')

    def test_latency_excludes_artifact_writes_and_response_is_saved_once(self):
        import tempfile,time
        from types import SimpleNamespace
        from unittest.mock import patch
        clock=[0.0];events=[]
        def write(path,value):
            events.append(path.name);clock[0]+=50
        def request(*args):
            clock[0]+=2
            return json.dumps(response([1,2,3]))
        with tempfile.TemporaryDirectory()as tmp:
            probe=p.Probe(Path(tmp),time.time()+10,[],[1])
            probe.http=SimpleNamespace(call=request)
            samples=iter([{p.GENERATION:0},{p.GENERATION:64,p.RUNNING:0,p.WAITING:0}])
            probe.metrics=lambda *a:next(samples)
            with patch.object(p,'save',side_effect=write),patch.object(p.time,'monotonic',side_effect=lambda:clock[0]):
                row,_,_=probe.request('timing',[1,2,3])
            self.assertEqual(row['seconds'],2)
            self.assertEqual(events,['timing-request.json','timing-response.json'])

    def test_reset_preserves_CPU_and_has_finite_tick_allowance(self):
        class HTTP:
            def __init__(self):self.paths=[]
            def call(self,path,payload,timeout):
                self.paths.append(path)
                return json.dumps({'success':len(self.paths)==3})
        probe=p.Probe(Path('/unused'),0,[],[1]);probe.http=HTTP()
        tick_calls=[];probe.request=lambda label,prompt,tick:tick_calls.append((label,tick))
        self.assertTrue(probe.reset('GPU-only',False))
        self.assertEqual(len(tick_calls),2)
        self.assertTrue(all('reset_external=false&reset_running_requests=false'in path for path in probe.http.paths))
        probe.http.call=lambda *a,**k:json.dumps({'success':False})
        tick_calls.clear()
        with self.assertRaises(RuntimeError):probe.reset('bounded',False)
        self.assertEqual(len(tick_calls),p.RESET_ATTEMPTS-1)
        self.assertEqual(p.MAX_REQUESTS,32)




class LocalHTTPIntegrationTests(unittest.TestCase):
    def test_full_restore_and_negative_control_over_real_localhost_http(self):
        import http.server, tempfile, threading, time
        state={'GPU':set(),'CPU':set(),'generation':0,'load':0,'store':0,'hits':0,'draft':0}
        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version='HTTP/1.1'
            def send(self,body):
                encoded=body.encode();self.send_response(200)
                self.send_header('Content-Length',str(len(encoded)));self.end_headers();self.wfile.write(encoded)
            def do_GET(self):
                values={p.RUNNING:0,p.WAITING:0,p.GENERATION:state['generation'],p.LOAD:state['load'],
                    p.STORE:state['store'],p.HITS:state['hits'],p.DRAFT_TOKENS:state['draft'],
                    'vllm:kv_cache_usage_perc':.2,p.CORRUPTED:0,p.PREEMPTIONS:0}
                self.send('\n'.join(f'{name}{{model_name="{p.MODEL}",engine="0"}} {value}'for name,value in values.items())+'\n')
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if self.path.startswith('/reset_prefix_cache'):
                    state['GPU'].clear()
                    if 'reset_external=true'in self.path:state['CPU'].clear()
                    self.send(json.dumps({'success':True}));return
                prompt=payload['prompt'];key=p.prompt_hash(prompt)
                cached=0
                if key in state['GPU'] or key in state['CPU']:
                    cached=(len(prompt)//p.CACHE_BLOCK_SIZE-1)*p.CACHE_BLOCK_SIZE
                if key not in state['GPU'] and key in state['CPU']:
                    state['load']+=1<<30;state['hits']+=cached
                if key not in state['CPU']:state['store']+=1<<30
                state['GPU'].add(key);state['CPU'].add(key)
                state['generation']+=64;state['draft']+=192
                self.send(json.dumps(response(prompt,cached)))
            def log_message(self,*a):pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory()as tmp:
                prompt=[1]*p.PROMPT_TOKENS
                probe=p.Probe(Path(tmp),time.time()+10,[prompt],[2])
                probe.http=p.LocalHTTP(probe.deadline,server.server_port)
                probe.reset('cold-reset',True)
                cold,cb,ca=probe.request('cold',prompt)
                warm,wb,wa=probe.request('warm',prompt)
                reset=probe.reset('GPU-only',False)
                restored,rb,ra=probe.request('restore',prompt)
                checks=p.restore_checks(cold,warm,restored,rb,ra,wb,wa,reset,cb)
                self.assertTrue(p.restore_pass(checks))
                self.assertEqual(cold['request_body_sha256'],warm['request_body_sha256'])
                self.assertEqual(warm['request_body_sha256'],restored['request_body_sha256'])
                probe.reset('full',True)
                negative,nb,na=probe.request('negative',prompt)
                self.assertEqual(negative['cached_tokens'],0)
                self.assertEqual(p.delta(nb,na,p.HITS),0)
                self.assertEqual(p.delta(nb,na,p.LOAD),0)
                self.assertEqual(len(probe.requests),4)
        finally:
            server.shutdown();server.server_close();thread.join(2)

    def test_absolute_http_watchdog_rejects_trickling_response(self):
        import http.server, threading, time
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200);self.send_header('Content-Length','100');self.end_headers()
                try:
                    for _ in range(100):self.wfile.write(b'x');self.wfile.flush();time.sleep(.02)
                except (BrokenPipeError,ConnectionResetError):pass
            def log_message(self,*a):pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            start=time.monotonic()
            with self.assertRaises((OSError,ValueError)):
                p.LocalHTTP(time.time()+.10,server.server_port).call('/health')
            self.assertLess(time.monotonic()-start,.6)
        finally:
            server.shutdown();server.server_close();thread.join(2)

class DriverLifecycleTests(unittest.TestCase):
    def test_real_cycle_loop_detects_broken_final_clear_and_saves_slow_cleanup(self):
        import tempfile, time
        from types import SimpleNamespace
        from unittest.mock import patch, Mock
        snapshot='/snapshot'
        argv=p.server_command(snapshot)
        config={'model_config':{'model':snapshot},'speculative_config':{'method':'mtp','num_speculative_tokens':3},
            'kv_transfer_config':json.loads(argv[argv.index('--kv-transfer-config')+1]),
            'cache_config':{'block_size':p.CACHE_BLOCK_SIZE}}
        for ignore_final,slow_cleanup in [(False,False),(True,False),(False,True)]:
            with self.subTest(ignore_final=ignore_final,slow_cleanup=slow_cleanup),tempfile.TemporaryDirectory()as tmp:
                root=Path(tmp);prompts=root/'prompts.json'
                histories=[[1]*p.PROMPT_TOKENS,[2]*p.PROMPT_TOKENS]
                prompts.write_text(json.dumps(dict(main=histories,tick=[3])))
                calls=[]
                class FakeProbe:
                    def __init__(self,*args):
                        self.requests=[];self.resets=[];self.gpu=set();self.cpu=set()
                        self.values={p.LOAD:0,p.STORE:0,p.HITS:0,p.DRAFT_TOKENS:0,p.CORRUPTED:0,p.PREEMPTIONS:0}
                        self.http=SimpleNamespace(call=lambda *a,**k:json.dumps({'vllm_config':config}))
                    def reset(self,label,external):
                        if ignore_final and label=='negative-full-reset':return True
                        self.gpu.clear()
                        if external:self.cpu.clear()
                        return True
                    def request(self,label,prompt):
                        key=p.prompt_hash(prompt);before=dict(self.values);cached=0
                        if key in self.gpu or key in self.cpu:
                            cached=(p.PROMPT_TOKENS//p.CACHE_BLOCK_SIZE-1)*p.CACHE_BLOCK_SIZE
                        if key in self.cpu and key not in self.gpu:
                            self.values[p.LOAD]+=1<<30;self.values[p.HITS]+=cached
                        if key not in self.cpu:self.values[p.STORE]+=1<<30
                        self.gpu.add(key);self.cpu.add(key);self.values[p.DRAFT_TOKENS]+=192
                        calls.append((label,key));row=p.parse_completion(response(prompt,cached),prompt)
                        return row,before,dict(self.values)
                server=Mock(pid=999999);server.poll.return_value=None
                if slow_cleanup:server.wait.side_effect=p.subprocess.TimeoutExpired('test-server',15)
                with patch('importlib.metadata.version',return_value='0.28.0'),patch.object(p,'Probe',FakeProbe),\
                        patch.object(p.os,'statvfs',return_value=SimpleNamespace(f_bavail=32<<30,f_frsize=1)),\
                        patch.object(p.subprocess,'Popen',return_value=server),patch.object(p.os,'killpg')as kill:
                    report=p.run(SimpleNamespace(output=root/'result',prompts=prompts,snapshot=snapshot,deadline=time.time()+900))
                self.assertEqual(calls[-1],('negative-cold',p.prompt_hash(histories[1])))
                self.assertEqual(report['passed'],not(ignore_final or slow_cleanup))
                self.assertEqual(report, json.loads((root/'result/report.json').read_text()))
                self.assertIn(unittest.mock.call(server.pid,p.signal.SIGKILL),kill.call_args_list)
                if ignore_final:self.assertGreater(report['negative_control']['cached_tokens'],0)
                if slow_cleanup:self.assertIn('cleanup_error',report)

    def test_late_start_is_rejected_without_starting_model(self):
        import tempfile,time
        from types import SimpleNamespace
        from unittest.mock import patch
        with tempfile.TemporaryDirectory()as tmp:
            root=Path(tmp);prompts=root/'prompts.json'
            prompts.write_text(json.dumps(dict(main=[[1]*p.PROMPT_TOKENS,[2]*p.PROMPT_TOKENS],tick=[3])))
            with patch('importlib.metadata.version',return_value='0.28.0'),patch.object(p.subprocess,'Popen')as popen:
                result=p.run(SimpleNamespace(output=root/'out',prompts=prompts,snapshot='/snapshot',deadline=time.time()+60))
                popen.assert_not_called()
            self.assertFalse(result['passed']);self.assertIn('refuse model startup',result['error'])

if __name__=='__main__':unittest.main()
