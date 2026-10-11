import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

PATH=Path(__file__).resolve().parents[1]/"scripts/spec_decode_benchmark.py"
spec=importlib.util.spec_from_file_location("spec_bench_test",PATH)
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)

class BenchmarkTests(unittest.TestCase):
    def test_hybrid_capacity_observation_does_not_mutate_live_config(self):
        draft=SimpleNamespace(max_model_len=262144)
        config=SimpleNamespace(model_config=SimpleNamespace(max_model_len=262144),
            speculative_config=SimpleNamespace(draft_model_config=draft),
            scheduler_config=SimpleNamespace(max_num_seqs=32))
        cache=SimpleNamespace(num_blocks=1001)
        def original(probe,cache):
            self.assertEqual(probe.model_config.max_model_len,61040)
            self.assertEqual(probe.speculative_config.draft_model_config.max_model_len,61040)
            return cache.num_blocks/50
        result=b.probe_capacity(config,cache,original)
        self.assertEqual(result['cache_max_requests'],20)
        self.assertEqual(result['common_batch_predicted_fraction'],.8)
        self.assertEqual(config.model_config.max_model_len,262144)
        self.assertEqual(draft.max_model_len,262144)

    def test_first_engine_selects_common_batch_and_later_engines_preserve_it(self):
        low=dict(cache_max_requests=2,scheduler_max_requests=32)
        high=dict(cache_max_requests=24,scheduler_max_requests=32)
        self.assertEqual(b.choose_common_batch(low),2)
        self.assertEqual(b.choose_common_batch(high,2),2)
        self.assertEqual(b.choose_common_batch(high),16)
        with self.assertRaises(ValueError):b.choose_common_batch(low,16)
        with self.assertRaises(ValueError):b.choose_common_batch(dict(cache_max_requests=1,scheduler_max_requests=32))

    def test_invalid_capacity_fails(self):
        config=SimpleNamespace(model_config=SimpleNamespace(max_model_len=262144),speculative_config=None,
            scheduler_config=SimpleNamespace(max_num_seqs=32))
        for value in (0,float('nan'),4.123):
            with self.assertRaises(ValueError):
                b.probe_capacity(config,SimpleNamespace(num_blocks=101),lambda *_:value)

    def test_exact_three_configs_preserve_target_context_and_precision(self):
        for arm in b.ARMS:
            argv=b.command('/base','/draft',arm)
            self.assertEqual(argv[argv.index('--max-model-len')+1],'262144')
            self.assertEqual(argv[argv.index('--kv-cache-dtype')+1],'fp8_e4m3')
            self.assertEqual(argv[argv.index('--block-size')+1],'1664')
            self.assertNotIn('--enforce-eager',argv)
            if arm!='baseline':
                cfg=json.loads(argv[argv.index('--speculative-config')+1])
                self.assertEqual(cfg['num_speculative_tokens'],3 if arm=='mtp3' else 7)
                if arm=='dflash':self.assertEqual(cfg['kv_cache_dtype'],'auto')
        with self.assertRaises(ValueError):b.command('/base','/draft','unknown')

    def test_stream_counts_tokens_in_speculative_bursts(self):
        chunks=[{'choices':[{'text':'abc','logprobs':{'tokens':['token_id:1','token_id:2','token_id:3']}}]},
                {'choices':[{'text':'de','logprobs':{'tokens':['token_id:4','token_id:5']},'finish_reason':'length'}]},
                {'choices':[],'usage':{'prompt_tokens':60000,'completion_tokens':5}},None]
        wire=b''.join(b'data: '+(b'[DONE]' if x is None else json.dumps(x).encode())+b'\n\n' for x in chunks)
        with tempfile.TemporaryDirectory() as d,patch.object(b.urllib.request,'urlopen',return_value=io.BytesIO(wire)),\
                patch.object(b.time,'perf_counter',side_effect=[10,11,11,13,13,13,13,14,14]):
            row=b.request([1],0,5,b.time.time()+60,Path(d))
        self.assertEqual(row['token_ids'],[1,2,3,4,5])
        self.assertEqual(row['stream_decode_tps'],1.)

    def test_deadline_interrupts_stalled_stream(self):
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        import threading,time,urllib.request
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                self.wfile.write(b'data: {"choices":[{"text":"a","logprobs":{"tokens":["token_id:1"]}}]}\n\n')
                self.wfile.flush();time.sleep(2)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        original=urllib.request.urlopen
        def open_local(request,**kwargs):
            request.full_url=f'http://127.0.0.1:{server.server_port}/v1/completions'
            return original(request,**kwargs)
        try:
            with tempfile.TemporaryDirectory() as d,patch.object(b.urllib.request,'urlopen',side_effect=open_local):
                started=time.perf_counter()
                with self.assertRaises((ValueError,OSError,TimeoutError)):
                    b.request([1],0,5,time.time()+.2,Path(d))
                self.assertLess(time.perf_counter()-started,1.5)
        finally:server.shutdown();server.server_close()

    def test_no_cache_no_speculation_is_not_a_valid_speculative_result(self):
        rows=[dict(first=10,last=30,started=9,ended=31,usage={'prompt_tokens_details':{'cached_tokens':0}},
            ttft_seconds=1,stream_decode_tps=40)]
        result=b.summarize(rows,{}, {},[], 'dflash')
        self.assertFalse(result['passed'])
        self.assertFalse(result['checks']['cached_prefix'])
        self.assertFalse(result['checks']['speculation_active'])
        self.assertIsNone(result['guarded_aggregate_decode_tps'])

    def test_aggregate_decode_excludes_prefill_and_partial_batches(self):
        rows=[dict(first=10,last=30,started=9,ended=31,
            usage={'prompt_tokens_details':{'cached_tokens':59000}},ttft_seconds=1,stream_decode_tps=40)]
        samples=[]
        for t,g,p in [(12,0,60000),(18,240,60000),(24,480,60010)]:
            samples.append(dict(time=t,metrics={'vllm:num_requests_running':1,'vllm:num_requests_waiting':0,
                'vllm:generation_tokens_total':g,'vllm:prompt_tokens_total':p,'vllm:num_preemptions_total':0,
                'vllm:kv_cache_usage_perc':.25}))
        result=b.summarize(rows,{}, {},samples,'baseline')
        self.assertTrue(result['passed']);self.assertEqual(result['guarded_aggregate_decode_tps'],40)
        self.assertEqual(result['guarded_seconds'],6)
        self.assertEqual(result['kv_headroom_fraction'],.75)

if __name__=='__main__':unittest.main()
