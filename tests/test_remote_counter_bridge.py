import unittest
import tempfile
import json
from pathlib import Path
from copy import deepcopy
from scripts.remote_counter_bridge import Bridge,digest,canonical,wire_bytes,wire_digest
import os

class Controls(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.m=100;self.u=1000;self.calls=[];self.tokens=100000
        self.identity=dict(model='Qwen/Qwen3.8-27B-FP8',serving_revision='017b9c7af6b5689d5dd426a76e0bc077eb5ca20a',tokenizer_sha256='0997f410c57a1f4e53b09e4be8f4a172d90edd9564368fb0847030937229b9f3',template_sha256='c3cf9e34abf4f9e36c2d72165aa9c132d3e2a725b6c2586aaa3a8af9d7a81041',image_processor_sha256=digest({'fixture_processor':'official-config'} ),tool_parser='qwen3_coder',source_commit='95e9ac988ea515f7194cbdc82ae327e248fc94fa')
        serving=dict(first_case={'commit':self.identity['source_commit']},model=dict(repository=self.identity['model'],revision=self.identity['serving_revision']),tokenizer={'tokenizer.json':{'sha256':self.identity['tokenizer_sha256']},'chat_template.jinja':{'sha256':self.identity['template_sha256']}})
        gates=dict(ready=True,identity=self.identity,server_context=131072,isl=100000,vision=True,native_tools=True,exact_complete_request_counter=True)
        def pin(name,value):
            f=Path(self.tmp.name)/name;f.write_bytes(canonical(value));return dict(path=str(f),sha256=__import__('hashlib').sha256(f.read_bytes()).hexdigest())
        self.server=dict(identity=self.identity,server_context=131072,isl=100000,vision=True,native_tools=True,serving_session_id='unit-server',deadline=1500,ready=False,exact_complete_request_counter=False,processor={'fixture_processor':'official-config'})
        self.live=dict(dispatch_authorized=True,pilot_id='unit-only',relay_base_url='http://127.0.0.1:18000/v1',api_key_env='LOCAL_TEST_RELAY_TOKEN',identity=self.identity,server_context=131072,isl=100000,gpu_deadline_utc=1500,serving_session_id='unit-server',qualification_receipt=pin('gates.json',gates),serving_binding=pin('serving.json',serving),deployment_receipt=pin('deploy.json',{'qualification':self.server,'serving_session_id':'unit-server','deadline':1500}),processor_parity_proof=pin('processor.json',{'passed':True,'official_processor':self.server['processor'],'image_processor_sha256':self.identity['image_processor_sha256']}),complete_wire_count_parity_proof=pin('count.json',self.wire_proof()))
        relay=Path(os.environ.get('FROZEN_TRAINING_RELAY',str(Path(__file__).parent/'fixtures/modal_tokenize_projection.py'))).resolve();self.live['relay_source']={'path':str(relay),'sha256':__import__('hashlib').sha256(relay.read_bytes()).hexdigest()}
        self.raw=dict(count=100000,max_model_len=131072,token_ids_sha256='4'*64)
        def exchange(method,path,body=None):
            self.calls.append((method,path,deepcopy(body)))
            if path=='/health':return None
            if path=='/qualification':return deepcopy(self.server)
            if path=='/tokenize':return {**self.raw,'count':self.tokens}
            raise AssertionError('Unknown endpoint')
        self.exchange=exchange;self.b=Bridge(self.live,400,exchange=exchange,mono=lambda:self.m,utc=lambda:self.u,environ={'LOCAL_TEST_RELAY_TOKEN':'do-not-log-secret'})
        self.request=dict(model=self.identity['model'],messages=[{'role':'assistant','reasoning_content':'retained'},{'role':'user','content':[{'type':'image_url','image_url':{'url':'data:image/png;base64,AA=='}}]}],temperature=0,max_tokens=131072,stream=False,tools=[{'type':'function','function':{'name':'click'}}],tool_choice='auto',parallel_tool_calls=False)
    def wire_proof(self):
        from hashlib import sha256
        relay=Path(os.environ.get('FROZEN_TRAINING_RELAY',str(Path(__file__).parent/'fixtures/modal_tokenize_projection.py'))).resolve()
        rows=[]
        for label in ['image-64x64','image-1280x720','image-2048x1024','retained-history','100000-input-boundary']:
            n=100000 if label=='100000-input-boundary' else 77
            row=dict(probe=label,input_tokens=n,server=dict(count=n,max_model_len=131072,token_ids_sha256='4'*64))
            if label in ['retained-history','100000-input-boundary']:row['generation']={'prompt_tokens':n}
            if label=='retained-history':row['alternate_controls_generation']={'prompt_tokens':n}
            rows.append(row)
        return dict(wire_serialization='json-insertion-order-v1',counter_wire_function_sha256='f21b9f8becf3a8713ad3bcf59d610cc59f97406a5d17b6396013191dd5ad2de3',passed=True,ready=True,identity=self.identity,exact_complete_request_counter=True,parity_probes=rows,output_controls_prompt_independent=True,parallel_tool_calls_prompt_independent=True,tokenize_projection_source_sha256=sha256(relay.read_bytes()).hexdigest())
    def posts(self):return [x for x in self.calls if x[0]=='POST']
    def test_real_raw_count_and_output_recount(self):
        a=self.b.count(self.request);r=deepcopy(self.request);r['max_tokens']=31072;b=self.b.count(r)
        self.assertEqual(a['input_tokens'],100000);self.assertTrue(b['reused_output_cap_only']);self.assertEqual(len(self.posts()),1)
        expected=deepcopy({k:self.request[k] for k in ['model','messages','tools']})
        expected['messages'][0]['reasoning']=expected['messages'][0].pop('reasoning_content')
        self.assertEqual(self.posts()[0][2],expected)
        self.assertEqual(b['counted_request_sha256'],wire_digest(self.request));self.assertEqual(b['request_sha256'],wire_digest(r))
        self.assertNotIn('do-not-log-secret',json.dumps(b))
    def test_runner_complete_request_identical(self):
        self.b.runner_count(self.request['messages'],self.request['tools']);r=self.b.count(self.request)
        self.assertTrue(r['reused_output_cap_only']);self.assertEqual(len(self.posts()),1)
    def test_not_expired_after60_with_fresh_health(self):
        self.b.count(self.request);self.m=200;self.u=1100;self.b.count(self.request)
        self.assertEqual(len(self.posts()),2);self.assertGreaterEqual(sum(x[1]=='/health' for x in self.calls),4)
    def test_native_prompt_change_forces_actual_count(self):
        self.b.count(self.request);r=deepcopy(self.request);r['messages'][0]['reasoning_content']='new';self.b.count(r)
        self.assertEqual(len(self.posts()),2)
    def test_limits_return_real100001(self):
        self.tokens=100001;self.assertEqual(self.b.count(self.request)['input_tokens'],100001)
    def test_session_change_blocks_cached_count(self):
        self.b.count(self.request);self.server['serving_session_id']='other'
        with self.assertRaises(ValueError):self.b.count(self.request)
        self.assertEqual(len(self.posts()),1)
    def test_deadline_and_backward_clock(self):
        self.m=400
        with self.assertRaises(TimeoutError):self.b.count(self.request)
        self.m=99
        with self.assertRaises(ValueError):self.b.count(self.request)
    def test_bad_raw_receipt(self):
        for change in [dict(count=True),dict(count=-1),dict(token_ids_sha256=None),dict(max_model_len=262144)]:
            self.b.cache=None;original=deepcopy(self.raw);self.raw.update(change)
            if 'count' in change:self.tokens=change['count']
            with self.assertRaises(ValueError):self.b.count(self.request)
            self.raw=original;self.tokens=100000
    def test_tool_choice_none_omits_tools(self):
        r=deepcopy(self.request);r['tool_choice']='none';r['tools']=[];self.b.count(r)
        self.assertNotIn('tools',self.posts()[0][2])
    def test_tools_with_none_rejected_like_training(self):
        r=deepcopy(self.request);r['tool_choice']='none'
        with self.assertRaises(ValueError):self.b.count(r)
        self.assertEqual(self.posts(),[])
    def test_reasoning_alias_precedence(self):
        cases=[({'reasoning_content':'alias'},'alias'),({'reasoning_content':'alias','reasoning':None},'alias'),({'reasoning_content':'alias','reasoning':''},''),({'reasoning_content':'alias','reasoning':'canonical'},'canonical'),({'reasoning_content':'','reasoning':None},''),({'reasoning_content':None,'reasoning':'canonical'},'canonical')]
        for fields,expected in cases:
            r=deepcopy(self.request);r['messages']=[{'role':'assistant','content':None,**fields}];self.b.count(r)
            measured=self.posts()[-1][2]['messages'][0]
            self.assertNotIn('reasoning_content',measured);self.assertEqual(measured['reasoning'],expected)
            self.assertEqual(r['messages'][0],{'role':'assistant','content':None,**fields})
    def test_no_generation_or_history_mutation(self):
        original=deepcopy(self.request)
        def exchange(method,path,body=None):
            if path=='/tokenize':
                body['messages'][0]['reasoning']='mutated-copy';body['tools'][0]['function']['name']='mutated-copy'
                return deepcopy(self.raw)
            return self.exchange(method,path,body)
        self.b.exchange=exchange;result=self.b.count(self.request)
        self.assertEqual(self.request,original);self.assertEqual(result['request_sha256'],wire_digest(original))
    def test_wrong_projection_source_fingerprint(self):
        from hashlib import sha256
        wrong=Path(self.tmp.name)/'relay.py';wrong.write_text('def tokenize_payload(body):\n    return body\n')
        proof_path=Path(self.live['complete_wire_count_parity_proof']['path']);proof=json.loads(proof_path.read_text());proof['tokenize_projection_source_sha256']=sha256(wrong.read_bytes()).hexdigest();proof_path.write_bytes(canonical(proof))
        live=deepcopy(self.live);live['complete_wire_count_parity_proof']['sha256']=sha256(proof_path.read_bytes()).hexdigest();live['relay_source']={'path':str(wrong),'sha256':proof['tokenize_projection_source_sha256']}
        with self.assertRaises(ValueError):Bridge(live,400,exchange=self.exchange,mono=lambda:self.m,utc=lambda:self.u,environ={'LOCAL_TEST_RELAY_TOKEN':'unit-only'})
        self.assertEqual(self.calls,[])
    def test_unqualified_options(self):
        for change in [dict(tool_choice='required'),dict(provider={}),dict(stream=True),dict(parallel_tool_calls='no')]:
            with self.assertRaises(ValueError):self.b.count({**self.request,**change})
        self.assertEqual(self.posts(),[])
    def test_pin_tamper_blocks_before_http(self):
        Path(self.live['processor_parity_proof']['path']).write_text('{}')
        with self.assertRaises(ValueError):self.b.count(self.request)
        self.assertEqual(self.calls,[])
    def test_exchange_failure_no_retry(self):
        attempts=[]
        def broken(*args):attempts.append(args);raise RuntimeError('unavailable')
        self.b.exchange=broken
        with self.assertRaises(RuntimeError):self.b.count(self.request)
        self.assertEqual(len(attempts),1)
    def test_wrong_endpoint_missing_auth(self):
        for live,env in [({**self.live,'relay_base_url':'https://example.com/v1'},{'LOCAL_TEST_RELAY_TOKEN':'x'}),(self.live,{})]:
            with self.assertRaises(ValueError):Bridge(live,400,exchange=self.exchange,mono=lambda:self.m,utc=lambda:self.u,environ=env)

    def test_reordered_schema_invalidates_cache_despite_semantic_hash(self):
        r=deepcopy(self.request)
        properties={'query':{'anyOf':[{'type':'string'},{'type':'array','items':{'type':'string'}}]},'limit':{'type':'integer'}}
        r['tools'][0]['function']['parameters']={'type':'object','properties':properties}
        self.b.count(r)
        other=deepcopy(r)
        other['tools'][0]['function']['parameters']['properties']=dict(reversed(list(properties.items())))
        self.assertEqual(digest(r),digest(other))
        self.assertNotEqual(wire_digest(r),wire_digest(other))
        self.b.count(other)
        self.assertEqual(len(self.posts()),2)

    def test_real_http_wire_preserves_nested_keys_and_matches_httpx(self):
        import httpx
        body={'model':'Qwen','tools':[{'function':{'parameters':{'properties':{'query':{'type':'string','description':'café 🧦'},'limit':{'type':'integer'}}}}}]}
        sent=[]
        class Response:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,n):return b'{"count": 77}'
        class Opener:
            def open(self,request,timeout):sent.append(request.data);return Response()
        self.b.opener=Opener()
        self.b.http('POST','/tokenize',body)
        expected=httpx.Request('POST','http://127.0.0.1:18000/v1/chat/completions',json=body).content
        self.assertEqual(sent,[expected])
        self.assertEqual(list(json.loads(sent[0])['tools'][0]['function']['parameters']['properties']),['query','limit'])
        self.assertNotEqual(sent[0],canonical(body))

    def test_wire_receipts_and_cap_only_reuse(self):
        a=self.b.count(self.request)
        r=deepcopy(self.request);r['max_tokens']=31072;b=self.b.count(r)
        self.assertEqual(b['wire_serialization'],'json-insertion-order-v1')
        self.assertEqual(b['request_sha256'],wire_digest(r))
        self.assertEqual(b['counted_request_sha256'],wire_digest(self.request))
        self.assertEqual(b['tokenize_payload_sha256'],wire_digest(self.posts()[0][2]))
        self.assertEqual(b['semantic_request_sha256'],digest(r))
        self.assertTrue(b['reused_output_cap_only'])
        self.assertEqual(a['prompt_sha256'],b['prompt_sha256'])

    def test_missing_explicit_relay_source_rejected(self):
        live=deepcopy(self.live);live.pop('relay_source')
        with self.assertRaises(ValueError):Bridge(live,400,exchange=self.exchange,mono=lambda:self.m,utc=lambda:self.u,environ={'LOCAL_TEST_RELAY_TOKEN':'unit-only'})

    def test_wire_nonfinite_values_rejected(self):
        for value in [float('nan'),float('inf'),-float('inf')]:
            with self.assertRaises(ValueError):wire_bytes({'value':value})

    def test_count_to_http_projection_retains_schema_wire_order(self):
        import httpx
        bodies=[]
        b=self.b;raw=deepcopy(self.raw);server=deepcopy(self.server)
        r=deepcopy(self.request)
        r['tools']=[{'type':'function','function':{'name':'ax_search','description':'café 🧦','parameters':{'type':'object','properties':{'query':{'type':'string'},'limit':{'type':'integer'}},'required':['query']}}}]
        class Response:
            status=200
            def __init__(self,body):self.body=body
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,n):return self.body
        class Opener:
            def open(self,request,timeout):
                if request.full_url.endswith('/tokenize'):
                    bodies.append(request.data);return Response(wire_bytes(raw))
                if request.full_url.endswith('/qualification'):return Response(wire_bytes(server))
                return Response(b'{}')
        b.opener=Opener();b.exchange=b.http
        result=b.count(r)
        tool_bytes=wire_bytes(r['tools'])
        self.assertIn(tool_bytes,bodies[0])
        self.assertIn(tool_bytes,httpx.Request('POST','http://127.0.0.1:18000/v1/chat/completions',json=r).content)
        parsed=json.loads(bodies[0])
        self.assertEqual(list(parsed['tools'][0]['function']),['name','description','parameters'])
        self.assertEqual(list(parsed['tools'][0]['function']['parameters']['properties']),['query','limit'])
        self.assertEqual(result['tokenize_payload_sha256'],__import__('hashlib').sha256(bodies[0]).hexdigest())

    def test_missing_order_qualification_rejected(self):
        for field in ['wire_serialization','counter_wire_function_sha256']:
            original=Path(self.live['complete_wire_count_parity_proof']['path']).read_bytes()
            proof=json.loads(original);proof.pop(field)
            path=Path(self.live['complete_wire_count_parity_proof']['path']);path.write_bytes(canonical(proof))
            live=deepcopy(self.live);live['complete_wire_count_parity_proof']['sha256']=__import__('hashlib').sha256(path.read_bytes()).hexdigest()
            with self.assertRaises(ValueError):Bridge(live,400,exchange=self.exchange,mono=lambda:self.m,utc=lambda:self.u,environ={'LOCAL_TEST_RELAY_TOKEN':'unit-only'})
            path.write_bytes(original)
        self.assertEqual(self.calls,[])

    def test_unsupported_httpx_serializer_rejected(self):
        from unittest.mock import patch
        with patch('scripts.remote_counter_bridge.importlib.metadata.version',return_value='0.27.0'):
            with self.assertRaises(ValueError):Bridge(self.live,400,exchange=self.exchange,mono=lambda:self.m,utc=lambda:self.u,environ={'LOCAL_TEST_RELAY_TOKEN':'unit-only'})

    def test_relative_or_invalid_relay_path_rejected(self):
        for path in ['relative.py',None,42]:
            live=deepcopy(self.live);live['relay_source']['path']=path
            with self.assertRaises(ValueError):Bridge(live,400,exchange=self.exchange,mono=lambda:self.m,utc=lambda:self.u,environ={'LOCAL_TEST_RELAY_TOKEN':'unit-only'})

if __name__=='__main__':unittest.main()
