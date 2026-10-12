"""Real poller/controller composition with a model-free HTTP fixture.

Fixture transfer counters are synthetic; these controls never qualify GPU KV.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import capacity_kv_offload_probe as p
import serve_qwen_cpu_offload as serving


class CompositionTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('prometheus_client'),'Run HTTP composition in RL environment with prometheus-client')
    def test_real_poller_controller_http_boundary_parks_until_terminal(self):
        lock=threading.Lock()
        state={'capacity':0,'kv':.4,'pressure_polls':0,'burst_started':0,
               'burst_ended':0,'generation':0,'loads':0,'hits':0,'drafts':0}
        def metrics():
            with lock:
                labels=f'model_name="{p.MODEL}",engine="0"'
                values={p.RUNNING:0,p.WAITING:state['capacity'],p.GENERATION:state['generation'],
                    'vllm:kv_cache_usage_perc':state['kv'],p.LOAD:state['loads'],
                    p.HITS:state['hits'],p.STORE:1<<35,p.CORRUPTED:0,
                    p.PREEMPTIONS:0,p.ALLOCATION_FAILURES:0,p.DRAFT_TOKENS:state['drafts']}
                # Like the actual GPU captures, load/store counters are lazy;
                # healthy allocation-failure counter is never emitted.
                values.pop(p.ALLOCATION_FAILURES)
                if state['burst_started']==0:
                    values.pop(p.LOAD);values.pop(p.STORE)
                text='\n'.join(f'{k}{{{labels}}} {v}' for k,v in values.items())
                return text+f'\nvllm:num_requests_waiting_by_reason{{{labels},reason="capacity"}} {state["capacity"]}'+f'\nvllm:num_requests_waiting_by_reason{{{labels},reason="deferred"}} 0\n'
        class Handler(BaseHTTPRequestHandler):
            protocol_version='HTTP/1.1'
            def do_GET(self):
                with lock:
                    if state['capacity']:state['pressure_polls']+=1
                body=metrics().encode()
                self.send_response(200);self.send_header('Content-Length',str(len(body)))
                self.end_headers();self.wfile.write(body)
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        class HTTP:
            def call(self,path,payload=None,timeout=None):
                if path=='/metrics':return metrics()
                if path!='/v1/completions':raise AssertionError(path)
                tokens=payload['max_tokens']
                if tokens==p.BURST_OUTPUT:
                    with lock:
                        state['burst_started']+=1
                        if state['burst_started']==p.EPISODES:state.update(capacity=2,kv=.95)
                    p.wait_for(lambda:state['pressure_polls']>=3,time.time()+10)
                with lock:
                    state['generation']+=tokens;state['drafts']+=tokens
                    if tokens==p.BURST_OUTPUT:
                        state['burst_ended']+=1
                        state['loads']+=1<<30;state['hits']+=58240
                        if state['burst_ended']==p.EPISODES:state.update(capacity=0,kv=.4)
                    elif state['burst_ended']==p.EPISODES:
                        state['loads']+=1<<30;state['hits']+=58240
                return json.dumps({'usage':{'prompt_tokens':len(payload['prompt']),
                    'completion_tokens':tokens,'prompt_tokens_details':{'cached_tokens':58240}},
                    'choices':[{'finish_reason':'length','text':'fixture','logprobs':{
                        'tokens':['token_id:7']*tokens}}]})
        actual=p.SharedMetricsPoller
        def poller(url,**kwargs):
            kwargs.update(interval=.01,timeout=.3)
            return actual(f'http://127.0.0.1:{server.server_port}/metrics',**kwargs)
        try:
            with tempfile.TemporaryDirectory()as folder,patch.object(p,'SharedMetricsPoller',side_effect=poller):
                result=p.exercise(Path(folder),time.time()+15,[[i+1]*p.PROMPT_TOKENS for i in range(p.EPISODES)],HTTP())
                self.assertTrue(result['passed'])
                self.assertEqual(result['checks']['parked_episodes'],['4','5'])
                self.assertEqual(result['checks']['cpu_restored_episodes'],['4','5'])
                self.assertEqual(len(result['requests']),14)
                self.assertTrue(result['active_cap_preserved'])
                self.assertTrue(result['held_without_dispatch']['episodes']['4']['waiting'])
                self.assertEqual(result['controller']['resume_credits'],0)
                self.assertTrue((Path(folder)/'capacity-evidence.json').is_file())
        finally:
            server.shutdown();server.server_close();thread.join(2)

    def test_assessment_rejects_unbalanced_permit_and_early_resume(self):
        rows={str(i):dict(done=True,request_id=None,waiting=False,parked=False,dispatch_retired=True)for i in range(p.EPISODES)}
        events=[dict(kind='episode_parked',episode_id='5',sequence=1),
            dict(kind='resume_granted',episode_id='5',sequence=2),
            dict(kind='episode_resumed',episode_id='5',sequence=3),
            dict(kind='turn_started',episode_id='5',request_id='5:resume',sequence=4),
            dict(kind='turn_finished',episode_id='5',request_id='5:resume',sequence=5)]
        before={};after={p.DRAFT_TOKENS:1}
        self.assertTrue(p.assess(events,rows,[],before,after)['parking_passed'])
        self.assertFalse(p.assess(events[:-1],rows,[],before,after)['parking_passed'])
        altered=[dict(e)for e in events];altered[1]['sequence']=6
        self.assertFalse(p.assess(altered,rows,[],before,after)['parking_passed'])
        corrupted=p.assess(events,rows,[],before,{p.CORRUPTED:1})
        self.assertTrue(corrupted['parking_passed'])
        self.assertFalse(corrupted['model_cache_health_passed'])
        result=p.assess(events,rows,[],before,{p.ALLOCATION_FAILURES:1},dict(cpu_load_bytes=1024,external_hits=100))
        self.assertTrue(result['parking_passed'])
        self.assertTrue(result['natural_cpu_restore_observed'])
        self.assertFalse(result['parked_cpu_restore_observed'])
        self.assertEqual(result['cpu_allocation_failures'],1)

    def test_constrained_profile_preserves_context_mtp_and_null_hash_default(self):
        argv=p.command('/snapshot')
        self.assertEqual(argv[argv.index('--kv-cache-memory-bytes')+1],str(12<<30))
        self.assertEqual(argv[argv.index('--max-model-len')+1],'262144')
        self.assertNotIn('--prefix-match-unit',argv)
        self.assertNotIn('--reset-prefix-cache',argv)
        self.assertEqual(json.loads(argv[argv.index('--speculative-config')+1])['num_speculative_tokens'],3)

    def test_fresh_installed_patch_check_is_mandatory_for_serving(self):
        with patch.object(serving,'apply_patch',side_effect=RuntimeError('removed by sync')):
            with self.assertRaisesRegex(RuntimeError,'removed by sync'):
                serving.fingerprint(serving.command('/snapshot'))
        for kwargs in ({'port':0},{'max_num_seqs':33},{'memory_fraction':float('nan')}):
            with self.assertRaises(ValueError):serving.command('/snapshot',**kwargs)

    def test_pressure_requires_distinct_first_blocks(self):
        prompts=[[i+1]*p.PROMPT_TOKENS for i in range(p.EPISODES)]
        p.validate_prompts(prompts)
        for row in prompts:row[:p.CACHE_BLOCK_SIZE]=[1]*p.CACHE_BLOCK_SIZE
        with self.assertRaisesRegex(ValueError,'shared first cache block'):p.validate_prompts(prompts)

    def test_guarded_ssh_launch_reaches_exec_with_resolved_offline_environment(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory()as folder:
            root=Path(folder);snapshot=root/'models--Qwen--Qwen3.8-27B-FP8'/'snapshots'/p.REVISION
            snapshot.mkdir(parents=True);(snapshot/'config.json').write_text('{}')
            alias=root/'alias';alias.symlink_to(snapshot,target_is_directory=True)
            receipt=root/'receipt.json'
            with patch.object(sys,'argv',['serve','--snapshot',str(alias),'--receipt',str(receipt),'--cuda-home',str(root/'cuda')]),patch.object(serving,'apply_patch',return_value={'status':'verified'}),patch.object(serving,'compiler_environment',return_value={'PATH':'compiler','HF_TOKEN':'must_drop'}),patch.object(serving.os,'statvfs',return_value=SimpleNamespace(f_bavail=21<<30,f_frsize=1)),patch.dict(serving.os.environ,{'CUDA_HOME':str(root/'cuda')}),patch.object(serving.os,'execve')as execute:
                serving.main()
            _,argv,env=execute.call_args.args
            self.assertEqual(argv[argv.index('serve')+1],str(snapshot))
            self.assertEqual(env['HF_HUB_OFFLINE'],'1')
            self.assertEqual(env['TRANSFORMERS_OFFLINE'],'1')
            self.assertNotIn('HF_TOKEN',env)
            self.assertIn('checkpoint_config_sha256',json.loads(receipt.read_text()))

    def test_stock_package_cannot_start_capacity_server(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory()as folder:
            args=SimpleNamespace(output=Path(folder)/'result',deadline=time.time()+600,
                                 prompts=Path(folder)/'absent.json',snapshot='/snapshot')
            with patch.object(p,'apply_patch',side_effect=RuntimeError('Backport missing')),patch.object(p.subprocess,'Popen')as start:
                result=p.run(args)
            start.assert_not_called()
            self.assertFalse(result['passed'])
            self.assertIn('Backport missing',result['error'])
            self.assertTrue((args.output/'report.json').is_file())

    def test_normal_launcher_checks_server_environment_and_records_patch(self):
        from browser_training import launch
        import contextlib,io
        with patch.object(sys,'argv',['launch']),contextlib.redirect_stdout(io.StringIO()):
            with patch.object(launch.subprocess,'check_output',side_effect=RuntimeError('patch removed')),patch.object(launch.os,'execve')as execute:
                with self.assertRaisesRegex(RuntimeError,'patch removed'):launch.main()
                execute.assert_not_called()
            with patch.object(launch.subprocess,'check_output',return_value='{"patch_id":"test"}')as verify,patch.object(launch.subprocess,'run')as provenance,patch.object(launch.os,'execve')as execute:
                launch.main()
                self.assertTrue(verify.call_args.args[0][0].endswith('envs/rl/.venv/bin/python'))
                self.assertIn('--verify-only',verify.call_args.args[0])
                manifest=json.loads(provenance.call_args.args[0][-1])
                self.assertEqual(manifest['vllm_cpu_kv_patch'],{'patch_id':'test'})
                execute.assert_called_once()


if __name__=='__main__':unittest.main()
