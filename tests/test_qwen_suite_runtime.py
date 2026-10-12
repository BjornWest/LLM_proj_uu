"""CPU-only serving/formatter contracts; fixtures are never dispatch releases."""
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import json
import runpy
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
API=runpy.run_path(str(ROOT/'scripts/qwen_suite_runtime.py'))


def pin(path):return {'path':str(path),'sha256':sha256(path.read_bytes()).hexdigest()}


class Fixture:
    def __init__(self, root):
        self.root=root;self.now=100.;self.changed=None;self.calls=[]
        self.identity=dict(model=API['MODEL'],serving_revision=API['REVISION'],tokenizer_sha256='a'*64,
            template_sha256='b'*64,image_processor_sha256='c'*64,tool_parser='qwen3_coder')
        compat=dict(runtime=dict(vllm_version='0.28',vllm_source_patch_sha256='d'*64,pytorch_version='2.11+cu130',
             cuda_runtime_version='13.0',runtime_lock_sha256='e'*64,kernel_versions={'tokenizers':'0.23.2'},
             counter_projection_sha256=API['projection_sha256']()),hardware={'gpu_architecture':'sm120'},
             model={'repository':API['MODEL'],'revision':API['REVISION']},assets=dict(tokenizer_sha256='a'*64,template_sha256='b'*64,processor_sha256='c'*64),
             serving=dict(context_tokens=262144,image_limits={'limit_mm_per_prompt':{'image':2},'mm_processor_kwargs':{}},
                weight_quantization='fp8',kv_cache_dtype='fp8_e4m3',kv_scales_sha256=None,thinking=True,preserve_thinking=True,
                tool_parser='qwen3_coder',reasoning_parser='qwen3',mtp_mode={'num_speculative_tokens':3},lora_mode=None,
                attention_backend={k:'fixed' for k in ['prefill','decode','linear_attention','weight_compute']}))
        fingerprint=API['digest'](compat,sorted_keys=True)
        proof=self.write('proof.json',{'passed':True,'test_only':True})
        cap=self.write('cap.json',dict(schema='serving-stack-capability-v1',status='passed',synthetic=False,fingerprint=fingerprint,compatibility=compat,
            checks={k:True for k in API['CHECKS']},proofs={k:proof for k in ['qualification','deployment','processor']}))
        dep=self.write('deploy.json',dict(serving_session_id='test-session',identity=self.identity,deadline_utc=200.,allocation_utc=50.,
            approved_rental_seconds=150,observed_compatibility=compat,synthetic=False))
        inst=self.write('instance.json',dict(schema='serving-instance-readiness-v1',status='ready',capability=cap, deployment_receipt=dep,
            fingerprint=fingerprint,observed_compatibility=compat,identity=self.identity,base_url='http://127.0.0.1:8000/v1',
            serving_session_id='test-session',gpu_deadline_utc=200.,server_context=262144,isl=250000,
            vision_configured=True,native_tools_configured=True,exact_request_counter=True,issued_at_utc=90.,expires_at_utc=200.))
        self.live=dict(schema='qualified-serving-live-v1',base_url='http://127.0.0.1:8000/v1',qualification_base_url='http://127.0.0.1:8001',
            identity=self.identity,server_context=262144,isl=250000,deadline_utc=200.,serving_session_id='test-session',
            capability_receipt=cap,instance_readiness_receipt=inst,deployment_receipt=dep)
        self.live_pin=self.write('live.json',self.live)
        self.actual=dict(status='ready',exact_request_counter=True,serving_session_id='test-session',identity=self.identity,
            fingerprint=fingerprint,server_context=262144,isl=250000,deadline_utc=200.,observed_compatibility=compat)

    def write(self,name,value):
        path=self.root/name;path.write_text(json.dumps(value));return pin(path)

    def exchange(self,destination,method,path,body=None):
        self.calls.append((destination,method,path,deepcopy(body)))
        if path=='/health':return {'http_status':200}
        if path=='/qualification':
            value=deepcopy(self.actual)
            if self.changed:value[self.changed]='changed'
            return value
        return {'count':3,'tokens':[1,2,3],'max_model_len':262144}

    def admission(self):return API['ServingAdmission'](self.live_pin,exchange=self.exchange,clock=lambda:self.now)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.fixture=Fixture(Path(self.tmp.name))

    def request(self):return dict(model=API['MODEL'],messages=[{'role':'user','content':'hello'}],temperature=0,max_tokens=16384,stream=False)

    def test_split_readiness_and_health_count(self):
        x=self.fixture.admission();receipt=x.count(self.request())
        self.assertEqual(receipt['input_tokens'],3)
        self.assertEqual(receipt['request_sha256'],API['digest'](self.request()))
        self.assertTrue(any(c[:3]==('raw','GET','/health') for c in self.fixture.calls))
        self.assertTrue(any(c[:3]==('qualification','GET','/qualification') for c in self.fixture.calls))
        self.assertTrue(any(c[:3]==('raw','POST','/tokenize') for c in self.fixture.calls))

    def test_token_cache_never_crosses_session_or_expiry(self):
        x=self.fixture.admission();x.count(self.request());req=self.request();req['max_tokens']=20
        self.assertTrue(x.count(req)['reused_output_only'])
        self.fixture.changed='serving_session_id'
        with self.assertRaises(ValueError):x.count(req)
        self.fixture.changed=None;self.fixture.now=200
        with self.assertRaises(TimeoutError):x.readiness()

    def test_every_required_parity_gate_rejects_missing(self):
        for key in API['CHECKS']:
            with self.subTest(key=key):
                fixture=Fixture(Path(self.tmp.name));cap=json.loads(Path(fixture.live['capability_receipt']['path']).read_bytes())
                del cap['checks'][key]
                fixture.live['capability_receipt']=fixture.write('cap.json',cap)
                fixture.live_pin=fixture.write('live.json',fixture.live)
                with self.assertRaises(ValueError):fixture.admission()

    def test_stripped_fingerprint_and_synthetic_proof_rejected(self):
        for change in ['synthetic','runtime']:
            fixture=Fixture(Path(self.tmp.name));cap=json.loads(Path(fixture.live['capability_receipt']['path']).read_bytes())
            if change=='synthetic':cap['synthetic']=True
            else:del cap['compatibility']['runtime']['runtime_lock_sha256']
            fixture.live['capability_receipt']=fixture.write('cap.json',cap);fixture.live_pin=fixture.write('live.json',fixture.live)
            with self.assertRaises(ValueError):fixture.admission()

    def test_changed_pinned_instance_rejected(self):
        x=self.fixture.admission();Path(self.fixture.live['instance_readiness_receipt']['path']).write_text('{}')
        with self.assertRaises(ValueError):x.readiness()

    def test_loopback_and_no_case95_identity(self):
        for url in ['https://example.com/v1','http://localhost:8000/v1','http://127.0.0.1:8000/v1?key=x']:
            with self.assertRaises(ValueError):API['loopback'](url,'/v1')
        self.assertNotIn('source_commit',self.fixture.admission().identity)

    def test_ordered_tool_projection_and_retained_reasoning(self):
        r=self.request();r['messages'].append({'role':'assistant','reasoning_content':'think','content':None})
        r['tools']=[{'type':'function','function':{'name':'a','parameters':{'type':'object','properties':{'z':{},'a':{}}}}}]
        original=deepcopy(r);payload=API['tokenize_payload'](r)
        self.assertEqual(r,original);self.assertEqual(payload['messages'][-1]['reasoning'],'think')
        self.assertEqual(list(payload['tools'][0]['function']['parameters']['properties']),['z','a'])
        other=deepcopy(payload);other['tools'][0]['function']['parameters']['properties']={'a':{},'z':{}}
        self.assertNotEqual(API['digest'](payload),API['digest'](other))

    def test_reasoning_alias_precedence_and_wire_rejections(self):
        r=self.request();r['messages']=[{'role':'assistant','reasoning':'first','reasoning_content':'second'}]
        self.assertEqual(API['tokenize_payload'](r)['messages'][0]['reasoning'],'first')
        for key,value in [('provider',{}),('stream',True),('parallel_tool_calls',1),('max_tokens',False)]:
            with self.subTest(key=key):
                req=self.request();req[key]=value
                with self.assertRaises(ValueError):API['tokenize_payload'](req)

    def test_schema_is_explicit_and_count_projection_requires_tool_free(self):
        r=self.request();r['response_format']={'type':'json_schema','json_schema':{'name':'answer','strict':True,'schema':{'type':'object'}}}
        self.assertNotIn('response_format',API['tokenize_payload'](r))
        r['tools']=[{}]
        with self.assertRaises(ValueError):API['tokenize_payload'](r)


class FactoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.directory=Path(self.tmp.name)
        self.events=[];self.calls=[];self.n=250000
        fixture=Fixture(self.directory);self.admission=fixture.admission()
        def count(request):return dict(input_tokens=self.n,identity=fixture.identity,exact_complete_request=True,
            serving_session_id='test-session',request_sha256=API['digest'](request))
        self.admission.count=count
        outer=self
        class Backend:
            def __init__(self,*args,**kwargs):self.request_options=kwargs['request_options'];self.max_tokens=kwargs['max_tokens'];self.last_request=None
            def configure_tools(self,options):self.request_options.update(options)
            def begin_episode(self,episode_id):pass
            def complete(self,messages):
                request=dict(model=API['MODEL'],messages=deepcopy(messages),temperature=0,max_tokens=self.max_tokens,stream=False,**deepcopy(self.request_options))
                self.last_request=request;outer.calls.append(request)
                return SimpleNamespace(request=request,raw={'usage':{'prompt_tokens':outer.n}},text='answer')
            def close(self):pass
        @contextmanager
        def turn(phase):
            self.events.append('turn:'+phase)
            try:yield
            finally:self.events.append('end:'+phase)
        self.factories=API['QwenFactories'](backend_class=Backend,admission=self.admission,
            before_policy=lambda:self.events.append('policy'),before_formatter=lambda:self.events.append('formatter'),
            meter=lambda row:self.events.append(row['event']),freshness_guard=lambda phase:self.events.append('fresh:'+phase),turn=turn)

    def test_headroom_and_consumer_guard_once(self):
        with self.factories.policy_session(before_dispatch=lambda:self.events.append('consumer')) as b:
            b.configure_tools({'tools':[{'type':'function','function':{'name':'a'}}]})
            b.complete([{'role':'user','content':'hello'}])
        self.assertEqual(self.calls[0]['max_tokens'],12144)
        self.assertEqual(self.events.count('consumer'),1)
        self.assertEqual(self.events.count('policy'),1)
        self.assertEqual(self.events[0],'turn:policy')
        self.assertEqual(self.events[-1],'end:policy')

    def test_hard_input_limit_skips_generation(self):
        self.n=250001
        with self.factories.policy_session(before_dispatch=lambda:None) as b:
            with self.assertRaises(ValueError):b.complete([{'role':'user','content':'hi'}])
        self.assertFalse(self.calls)

    def test_independent_formatter_explicit_schema_once(self):
        with self.factories.policy_session(before_dispatch=lambda:None) as b:b.complete([{'role':'user','content':'hi'}])
        schema={'type':'object','additionalProperties':False,'properties':{'value':{'type':'string'}},'required':['value']}
        (self.directory/'extraction').mkdir(exist_ok=True)
        (self.directory/'extraction'/'schema.json').write_text(json.dumps(schema))
        b=self.factories.extraction_backend_factory(self.directory/'transport')
        b.complete([{'role':'system','content':'schema'},{'role':'user','content':'answer'}])
        self.assertEqual(self.calls[-1]['response_format']['json_schema']['schema'],schema)
        self.assertNotIn('tools',self.calls[-1])
        with self.assertRaises(RuntimeError):b.complete([])
        b.close()

    def test_formatter_missing_schema_and_policy_open_reject(self):
        with self.factories.policy_session(before_dispatch=lambda:None) as b:
            with self.assertRaises(RuntimeError):self.factories.extraction_backend_factory(self.directory/'transport')
        b=self.factories.extraction_backend_factory(self.directory/'transport')
        with self.assertRaises(ValueError):b.complete([])
        b.close();self.assertFalse(self.calls)

    def test_malformed_count_receipt_cannot_dispatch(self):
        self.admission.count=lambda request:{'input_tokens':1,'request_sha256':API['digest'](request)}
        with self.factories.policy_session(before_dispatch=lambda:None) as b:
            with self.assertRaises(ValueError):b.complete([])
        self.assertFalse(self.calls)

    def test_changed_browser_after_parking_rejects_before_dispatch(self):
        def stale(phase):raise RuntimeError('state changed')
        self.factories.freshness_guard=stale
        with self.factories.policy_session(before_dispatch=lambda:None) as b:
            with self.assertRaisesRegex(RuntimeError,'state changed'):b.complete([])
        self.assertFalse(self.calls)

    def test_actual_httpx_backend_wire_unicode_schema_and_usage_parity(self):
        import importlib.util,sys,types,httpx
        name='_qwen_real_backend_'+str(id(self))
        package=types.ModuleType(name);package.__path__=[str(ROOT/'intent_browser')];sys.modules[name]=package
        location=ROOT/'intent_browser/backend.py';spec=importlib.util.spec_from_file_location(name+'.backend',location)
        module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
        wire=[]
        def respond(request):
            wire.append(request.content)
            return httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':'answer'},'finish_reason':'stop'}],
                 'usage':{'prompt_tokens':self.n}})
        def backend(*args,**kwargs):
            b=module.ChatCompletionsBackend(*args,**kwargs);b.client.close();b.client=httpx.Client(transport=httpx.MockTransport(respond));return b
        self.factories.backend_class=backend
        with self.factories.policy_session(before_dispatch=lambda:None) as b:
            b.configure_tools({'tools':[{'type':'function','function':{'name':'å','parameters':{'properties':{'z':{},'a':{}}}}}],
                               'tool_choice':'auto','parallel_tool_calls':False})
            b.complete([{'role':'user','content':'åäö 漢字'}]);b.complete([{'role':'user','content':'next'}])
        schema={'type':'object','properties':{'x':{'type':'string'}},'required':['x'],'additionalProperties':False}
        (self.directory/'extraction').mkdir(exist_ok=True)
        (self.directory/'extraction'/'schema.json').write_text(json.dumps(schema))
        b=self.factories.extraction_backend_factory(self.directory/'transport');b.complete([{'role':'user','content':'å'}]);b.close()
        self.assertEqual(len(wire),3)
        self.assertEqual(json.loads(wire[-1])['response_format']['json_schema']['schema'],schema)
        self.assertEqual(list(json.loads(wire[0])['tools'][0]['function']['parameters']['properties']),['z','a'])

    def test_wire_reorder_detected_and_cleanup_poisoned(self):
        with self.factories.policy_session(before_dispatch=lambda:None) as b:
            original=b.raw.complete
            def altered(messages):
                r=original(messages);r.request=dict(reversed(list(r.request.items())));return r
            b.raw.complete=altered
            with self.assertRaises(RuntimeError):b.complete([])
        def fail():raise RuntimeError('close')
        b=self.factories.backend('policy');b.raw.close=fail
        with self.assertRaises(RuntimeError):b.close()
        with self.assertRaises(RuntimeError):self.factories.check()

if __name__=='__main__':unittest.main()

class ReviewRuntimeRegressionTests(unittest.TestCase):
    setUp=FactoryTests.setUp
    def test_policy_backend_readiness_failure_does_not_mark_session_open(self):
        self.factories.backend_class=lambda *a,**kw:(_ for _ in ()).throw(RuntimeError('readiness'))
        with self.assertRaisesRegex(RuntimeError,'readiness'):
            with self.factories.policy_session(before_dispatch=lambda:None):pass
        self.assertFalse(self.factories.policy_active)

    def test_formatter_uses_actual_consumer_transport_sibling_and_rejects_wrong_path(self):
        with self.factories.policy_session(before_dispatch=lambda:None):pass
        (self.directory/'transport').mkdir();(self.directory/'extraction').mkdir()
        schema={'type':'object','properties':{},'additionalProperties':False}
        (self.directory/'extraction'/'schema.json').write_text(json.dumps(schema))
        b=self.factories.extraction_backend_factory(self.directory/'transport')
        b.complete([{'role':'user','content':'answer'}]);b.close()
        self.assertEqual(self.calls[-1]['response_format']['json_schema']['schema'],schema)

    def test_short_readiness_expiry_rejected_before_backend(self):
        fixture=Fixture(self.directory);instance=json.loads(Path(fixture.live['instance_readiness_receipt']['path']).read_text())
        instance['expires_at_utc']=199.
        fixture.live['instance_readiness_receipt']=fixture.write('instance.json',instance)
        fixture.live_pin=fixture.write('live.json',fixture.live)
        with self.assertRaisesRegex(ValueError,'expiry'):fixture.admission()

class ActualSavedConsumerSchemaTests(unittest.TestCase):
    setUp=FactoryTests.setUp

    def test_real_saved_consumer_writes_schema_for_transport_factory(self):
        # Execute the accepted consumer's actual extraction function (without
        # importing unrelated graders), with the real Qwen formatter wrapper.
        import ast,datetime
        path=Path('/home/bjorn/code/LLM_proj_uu/.local/coordination/qwen-shared-harness-20261012-v1/prospective-roots-v2/77c1f27b/experiments/answer_grading/listed_offer.py')
        tree=ast.parse(path.read_text());functions=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in {'write','extract_and_grade'}]
        namespace={'Path':Path,'json':json,'deepcopy':deepcopy,'datetime':datetime.datetime,'timezone':datetime.timezone,
            'messages':lambda public,answer,schema:[{'role':'user','content':answer}], 'strict_loads':json.loads}
        exec(compile(ast.Module(body=functions,type_ignores=[]),str(path),'exec'),namespace)
        with self.factories.policy_session(before_dispatch=lambda:None):pass
        b=self.factories.extraction_backend_factory(self.directory/'transport');original=b.raw.complete
        def response(messages):
            result=original(messages);result.text='{}';result.raw['choices']=[{'finish_reason':'stop','message':{'content':'{}'}}];return result
        b.raw.complete=response
        schema={'type':'object','properties':{},'additionalProperties':False}
        grader=SimpleNamespace(schema=schema,contract={'version':'cpu-contract'},grade=lambda claims,answer:{'passed':claims=={}})
        try:grade=namespace['extract_and_grade'](grader,{},'answer',self.directory/'extraction',b)
        finally:b.close()
        self.assertTrue(grade['passed']);self.assertEqual(self.calls[-1]['response_format']['json_schema']['schema'],schema)
        self.assertEqual(json.loads((self.directory/'extraction'/'schema.json').read_text()),schema)
