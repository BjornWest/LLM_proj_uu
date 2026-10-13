"""Zero-provider hosted admission and exact once-only extraction controls."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
import sys
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT/file)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


hosted = module('hosted_qwen_test_subject', 'scripts/openrouter_qwen_runtime.py')
caller = module('hosted_caller_test_subject', 'scripts/comparison_suite.py')


class HostedAdmissionTests(unittest.TestCase):
    def backend(self, tokens, *, phase='policy', directory=None, response_status=200, deadline=100):
        from intent_browser.backend import ChatCompletionsBackend
        raw = ChatCompletionsBackend('https://openrouter.ai/api/v1', hosted.MODEL,
            supports_images=True, session_routing=True, request_options={'provider':{'only':['akashml']}})
        raw.client.close()
        seen, measurements, observed = [], [], []
        def response(request):
            seen.append(json.loads(request.content))
            return httpx.Response(response_status, json={'choices':[{'message':{'content':'{}'}}],
                'usage':{'prompt_tokens':123, 'completion_tokens':4, 'cost':0.001}})
        raw.client = httpx.Client(transport=httpx.MockTransport(response))
        def count(messages, tools):
            measurements.append((deepcopy(messages),deepcopy(tools)))
            return {'input_tokens':tokens if len(measurements)==1 else 50,'scope':'local estimate'}
        count.observe_completion=lambda request,result:observed.append((request,result))
        wrapped = hosted.HostedQwenBackend(raw,count,phase=phase,maximum=16384,
            deadline=deadline,timeout=600,directory=directory,clock=lambda:1)
        wrapped.begin_episode('test/session')
        self.addCleanup(wrapped.close)
        return wrapped,seen,measurements,observed

    def test_wire_tools_retained_and_output_clipped_at_hard_input_boundary(self):
        backend,seen,measurements,observed=self.backend(150000)
        tool={'type':'function','function':{'name':'ax_read','parameters':{'type':'object'}}}
        backend.configure_tools({'tools':[tool],'tool_choice':'auto'})
        messages=[{'role':'user','content':'read this'}]
        result=backend.complete(messages)
        self.assertEqual(seen[0]['max_tokens'],16384)
        self.assertEqual(seen[0]['tools'],[tool])
        self.assertEqual(seen[0]['session_id'],'test/session')
        self.assertEqual(measurements[0],(messages,[tool]))
        self.assertEqual(len(observed),0)
        self.assertEqual(result.raw['usage']['prompt_tokens'],123)  # No exact-parity rejection.
        self.assertEqual(backend.raw.client.timeout.read,99)

    def test_larger_output_budget_keeps_actual_context_headroom(self):
        backend,seen,_,_=self.backend(150000)
        backend.maximum=65536;backend.timeout=1800
        backend.complete([])
        self.assertEqual(seen[0]['max_tokens'],65536)
        self.assertLessEqual(seen[0]['max_tokens']+150000,hosted.CONTEXT)

    def test_over_limit_and_expired_suite_never_dispatch(self):
        backend,seen,_,_=self.backend(150001)
        with self.assertRaisesRegex(ValueError,'no dispatch'):backend.complete([])
        self.assertEqual(seen,[])
        backend,seen,_,_=self.backend(12)
        backend.clock=lambda:101
        with self.assertRaisesRegex(TimeoutError,'no dispatch'):backend.complete([])
        self.assertEqual(seen,[])

    def test_invalid_counter_types_fail_before_wire(self):
        for value in (True,-1,None,3.5):
            with self.subTest(value=value):
                backend,seen,_,_=self.backend(value)
                with self.assertRaisesRegex(ValueError,'estimate'):backend.complete([])
                self.assertEqual(seen,[])

    def test_formatter_uses_actual_schema_adds_bound_and_does_not_retry_failed_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)/'transport';schema_path=Path(tmp)/'extraction/schema.json'
            schema_path.parent.mkdir();schema={'type':'object','properties':{'value':{'type':'boolean'}},
                'required':['value'],'additionalProperties':False}
            schema_path.write_text(json.dumps(schema))
            backend,seen,measurements,_=self.backend(149960,phase='formatter',directory=directory,response_status=503)
            # The wire schema's 50-token estimate pushes the complete request over the ceiling.
            with self.assertRaisesRegex(ValueError,'no dispatch'):backend.complete([])
            self.assertEqual(seen,[])
            backend,seen,measurements,_=self.backend(149900,phase='formatter',directory=directory,response_status=503)
            from intent_browser.backend import BackendResponseError
            with self.assertRaises(BackendResponseError):backend.complete([])
            self.assertEqual(seen[0]['response_format']['json_schema']['schema'],schema)
            self.assertTrue(seen[0]['response_format']['json_schema']['strict'])
            self.assertNotIn('tools',seen[0])
            self.assertEqual(len(measurements),2)
            with self.assertRaisesRegex(RuntimeError,'no retry'):backend.complete([])
            self.assertEqual(len(seen),1)

    def test_real_saved_extractor_configures_options_and_dispatches_actual_schema(self):
        import subprocess
        frozen=Path('/home/bjorn/code/LLM_proj_uu/.local/coordination/openrouter-qwen-suite-20261013-v1/source-v1/roots/a58f1ad4')
        code=r"""
import sys, runpy, tempfile, json, time
from pathlib import Path
import httpx
sys.path.insert(0,sys.argv[1])
from experiments.answer_grading.listed_offer import extract_and_grade
from intent_browser.backend import ChatCompletionsBackend
Hosted=runpy.run_path(sys.argv[2])['HostedQwenBackend']
with tempfile.TemporaryDirectory()as tmp:
    base=Path(tmp);raw=ChatCompletionsBackend('https://openrouter.ai/api/v1','qwen/qwen3.8-27b',request_options={'provider':{'only':['akashml'],'require_parameters':True},'reasoning':{'enabled':True}})
    raw.client.close();wire=[]
    def response(req):
        wire.append(json.loads(req.content))
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"value":true}'}}],'usage':{}})
    raw.client=httpx.Client(transport=httpx.MockTransport(response))
    backend=Hosted(raw,lambda messages,tools:{'input_tokens':10},phase='formatter',maximum=16384,timeout=10,deadline=time.time()+30,directory=base/'transport')
    schema={'type':'object','properties':{'value':{'type':'boolean'}},'required':['value'],'additionalProperties':False}
    class Grader:
        contract={'version':'mock-interface-test'}
        def grade(self,claims,answer):
            assert claims=={'value':True} and answer=='answer'
            return {'structured_claims_correct':True}
    grader=Grader();grader.schema=schema
    result=extract_and_grade(grader,{'user_message':'task'},'answer',base/'extraction',backend)
    assert result['structured_claims_correct']is True
    assert len(wire)==1 and wire[0]['response_format']['json_schema']['schema']==schema
    assert wire[0]['provider']['only']==['akashml'] and wire[0]['provider']['require_parameters']is True
    assert 'tools'not in wire[0]
    assert json.load(open(base/'extraction/completed.json'))['status']=='graded'
    backend.close()
"""
        result=subprocess.run([sys.executable,'-I','-B','-c',code,str(frozen),str(ROOT/'scripts/openrouter_qwen_runtime.py')],capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_formatter_missing_schema_and_inherited_tools_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend,seen,_,_=self.backend(5,phase='formatter',directory=Path(tmp)/'transport')
            with self.assertRaisesRegex(ValueError,'schema'):backend.complete([])
            backend.raw.request_options['tools']=[]
            with self.assertRaisesRegex(ValueError,'tool-free'):backend.complete([])
            self.assertEqual(seen,[])

    def test_opt_in_wire_schema_rejects_saved_malformed_pairs_and_is_counted(self):
        from jsonschema import validate, ValidationError
        with tempfile.TemporaryDirectory() as tmp:
            schema={'type':'object','properties':{'population_count':{
                'type':'object','properties':{'value':{'type':['integer','null']},
                    'evidence':{'type':['string','null']}},
                'required':['value','evidence'],'additionalProperties':False}},
                'required':['population_count'],'additionalProperties':False}
            schema_path=Path(tmp)/'extraction/schema.json';schema_path.parent.mkdir()
            schema_path.write_text(json.dumps(schema));original=schema_path.read_bytes()
            backend,seen,measured,_=self.backend(20,phase='formatter',directory=Path(tmp)/'transport')
            backend.quote_pair_schema=True;backend.complete([])
            wire=seen[0]['response_format']['json_schema']['schema']
            for value in ({'value':None,'evidence':'conflicting counts'},
                          {'value':0,'evidence':None}):
                with self.assertRaises(ValidationError):validate({'population_count':value},wire)
            validate({'population_count':{'value':None,'evidence':None}},wire)
            validate({'population_count':{'value':0,'evidence':'No priced models'}},wire)
            self.assertEqual(schema_path.read_bytes(),original)
            self.assertEqual(json.loads((Path(tmp)/'transport/response-format-schema.json').read_text()),wire)
            self.assertEqual(json.loads(measured[1][0][0]['content'])['json_schema']['schema'],wire)

    def test_quote_schema_preserves_instance_data_and_null_field_constraints(self):
        from jsonschema import validate, ValidationError
        claim={'type':'object','properties':{'value':{'type':['integer','null'],'enum':[0,1]},
            'evidence':{'type':['string','null']}},'required':['value','evidence'],
            'additionalProperties':False}
        schema={'type':'object','properties':{'claim':deepcopy(claim)},
            'enum':[{'claim':deepcopy(claim)}],'default':deepcopy(claim),
            'examples':[deepcopy(claim)],'const':deepcopy(claim)}
        wire=hosted.coherent_claim_schema(schema)
        for key in ('enum','default','examples','const'):
            self.assertEqual(wire[key],schema[key])
        branches=wire['properties']['claim']['anyOf']
        self.assertEqual(len(branches),1)
        with self.assertRaises(ValidationError):validate({'value':None,'evidence':None},branches[0])
        validate({'value':0,'evidence':'zero'},branches[0])
        self.assertEqual(hosted.coherent_claim_schema(wire),wire)

    def test_quote_schema_artifact_requires_successful_input_admission(self):
        with tempfile.TemporaryDirectory() as tmp:
            schema={'type':'object','properties':{'value':{'type':['integer','null']},
                'evidence':{'type':['string','null']}},'required':['value','evidence'],
                'additionalProperties':False}
            path=Path(tmp)/'extraction/schema.json';path.parent.mkdir();path.write_text(json.dumps(schema))
            backend,seen,_,_=self.backend(150001,phase='formatter',directory=Path(tmp)/'transport')
            backend.quote_pair_schema=True
            backend.counter=lambda messages,tools:{'input_tokens':150001}
            for _ in range(2):
                with self.assertRaisesRegex(ValueError,'no dispatch'):backend.complete([])
                self.assertFalse((Path(tmp)/'transport/response-format-schema.json').exists())
            self.assertEqual(seen,[])

    def test_counter_is_reused_and_usage_is_observed_once_by_runner(self):
        calls, observed = [], []
        def counter(messages, tools):
            calls.append((deepcopy(messages), deepcopy(tools)))
            return {'input_tokens': 1}
        counter.observe_completion=lambda request,response:observed.append((request,response))
        memo=hosted.MemoizedCounter(counter)
        messages=[{'role':'user','content':'hello'}]
        memo(messages, []); memo(messages, [])
        self.assertEqual(len(calls),1)
        memo.observe_completion({}, {})
        memo(messages, [])
        self.assertEqual((len(calls),len(observed)),(2,1))
        memo([{'content':'hello','role':'user'}], [])
        self.assertEqual(len(calls),3)  # Render-sensitive key order is retained.

    def test_total_request_watchdog_interrupts_a_dripping_transport_and_restores_signal(self):
        import signal, time
        previous=signal.getsignal(signal.SIGALRM)
        with self.assertRaises(hosted.HostedRequestDeadline):
            with hosted.request_watchdog(.02):time.sleep(.2)
        self.assertIs(signal.getsignal(signal.SIGALRM),previous)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0],0)

    def test_message_history_is_not_rewritten(self):
        backend,seen,_,_=self.backend(5)
        messages=[{'role':'assistant','reasoning_details':[{'type':'reasoning.text','text':'retained'}],
            'content':None,'tool_calls':[{'id':'1','type':'function','function':{'name':'ax_search','arguments':'{"query":"42"}'}}]}]
        before=deepcopy(messages);backend.complete(messages)
        self.assertEqual(messages,before)
        self.assertEqual(seen[0]['messages'],before)


class HostedSupervisorTests(unittest.TestCase):
    def test_canary_failure_blocks_future_admission_without_stopping_healthy_siblings(self):
        import threading
        stop=threading.Event();gate=caller.CanaryBarrier(['one','two'],stop,admission_only=True)
        gate.fail('one')
        self.assertFalse(stop.is_set())
        gate.wait('two');gate.complete('two')
        with self.assertRaises(RuntimeError):gate.wait('later')
        self.assertFalse(stop.is_set())

    def test_canary_route_requires_one_formatter_not_successful_native_verdicts(self):
        import threading
        gate=caller.CanaryBarrier(['one','two'],threading.Event(),admission_only=True)
        gate.complete('one',formatter_exercised=False);gate.complete('two',formatter_exercised=True)
        gate.wait('later');self.assertFalse(gate.failed)
        gate=caller.CanaryBarrier(['one'],threading.Event(),admission_only=True)
        gate.complete('one',formatter_exercised=False)
        with self.assertRaises(RuntimeError):gate.wait('later')

    def test_later_infrastructure_failure_drains_healthy_cases_and_blocks_future_admission(self):
        import threading
        stop=threading.Event();gate=caller.CanaryBarrier(['first'],stop,admission_only=True)
        gate.complete('first');gate.wait('later')
        gate.fail('later');self.assertFalse(stop.is_set())
        with self.assertRaises(RuntimeError):gate.wait('future')
        native=caller.CanaryBarrier(['cart'],threading.Event(),admission_only=True,require_formatter=False)
        native.complete('cart',formatter_exercised=False);native.wait('next')

    def test_finalization_preserves_claimed_rows_and_completes_pending_rows(self):
        import runpy
        # Use the actual frozen Events API contract, without model/provider dispatch.
        source=Path('/home/bjorn/code/LLM_proj_uu/.local/coordination/qwen-shared-harness-20261012-v1/Evaluation-real-qwen-caller-v1/worker-external-bindings-v1/episode_events_frozen.py')
        Events=runpy.run_path(str(source))['Events']
        with tempfile.TemporaryDirectory()as tmp:
            events=Events(Path(tmp)/'events.sqlite');events.register('suite',['claimed','pending']);events.start('suite','claimed')
            caller.finalize_unclaimed({'suite_id':'suite'},events,'cancelled')
            with events.transaction()as db:states=dict(db.execute('SELECT id,state FROM episodes'))
            self.assertEqual(states,{'claimed':'running','pending':'not_started'})

class HostedSourceAdmissionTests(unittest.TestCase):
    def spec(self):
        return {'runtime_mode':'qwen-openrouter-v1','max_steps':None,'episode_timeout':None,
            'max_input_tokens':150000,'server_context_tokens':262144,'max_tokens':16384,
            'request_timeout':600,'startup_timeout':180,'suite_timeout':36000,
            'shared_tokenizer':True,'shared_chromium':True,
            'cases':[{'id':'qwen-B02','task_id':'B02','policy_model':hosted.MODEL,'max_input_tokens':150000}]}

    def test_explicit_hosted_mode_admits_pool_without_private_serving(self):
        spec=self.spec();hosted.validate_limits(spec)
        hosted.validate_limits({**spec,'max_tokens':65536,'request_timeout':1800})
        self.assertTrue(caller.pooled_model_mode(spec));self.assertFalse(caller.qwen_mode(spec))
        with patch.object(caller,'check_release',side_effect=RuntimeError('review gate reached')):
            with self.assertRaisesRegex(RuntimeError,'review gate'):caller.execute(spec,{},scripted=False)

    def test_quote_pair_schema_option_is_explicit_boolean(self):
        hosted.validate_limits({**self.spec(),'formatter_quote_pair_schema':True})
        for value in (None,0,1,'true'):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'boolean'):
                hosted.validate_limits({**self.spec(),'formatter_quote_pair_schema':value})

    def test_private_and_legacy_mode_semantics_preserved(self):
        self.assertTrue(caller.qwen_mode({'runtime_mode':'qwen-private-v1'}))
        self.assertFalse(caller.hosted_qwen_mode({'runtime_mode':'qwen-private-v1'}))
        with self.assertRaisesRegex(ValueError,'model-free'):
            caller.execute({'shared_chromium':True},{},scripted=False)

    def test_no_gpu_controller_model_substitution_or_added_turn_cap(self):
        spec=self.spec()
        for key,value in [('max_steps',200),('episode_timeout',900),('runtime_limits',{}),
                          ('server_context_tokens',131072),('max_input_tokens',100000)]:
            with self.subTest(key=key),self.assertRaises(ValueError):hosted.validate_limits({**spec,key:value})
        for key in ('max_steps','episode_timeout'):
            missing=deepcopy(spec);del missing[key]
            with self.subTest(missing=key),self.assertRaises(ValueError):hosted.validate_limits(missing)
        for value in [True,0,1801]:
            with self.subTest(timeout=value),self.assertRaises(ValueError):hosted.validate_limits({**spec,'request_timeout':value})
        case={**spec['cases'][0],'policy_model':'xiaomi/mimo-v2.6-pro'}
        with self.assertRaises(ValueError):hosted.validate_limits({**spec,'cases':[case]})

    def test_resume_retains_every_native_result_even_if_cleanup_failed(self):
        import runpy
        source=Path('/home/bjorn/code/LLM_proj_uu/.local/coordination/qwen-shared-harness-20261012-v1/Evaluation-real-qwen-caller-v1/worker-external-bindings-v1/episode_events_frozen.py')
        Events=runpy.run_path(str(source))['Events']
        with tempfile.TemporaryDirectory()as tmp:
            d=Path(tmp);out=d/'prior-output';trace=out/'qwen-one/live/runs/trace';trace.mkdir(parents=True)
            def write(path,value):
                path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value));return caller.pin(path)
            cases=[{'id':'qwen-one','task_id':'one'},{'id':'qwen-two','task_id':'two'}]
            driver=write(d/'driver',{});auth=write(d/'auth',{})
            prior={'runtime_mode':'qwen-openrouter-v1','authorization':auth,'cases':cases,'driver':driver,'caller_commit':'prior','start_order':[c['id']for c in cases],'suite_id':'prior','output':str(out),'completion_db':str(out/'completion.sqlite')}
            events=Events(out/'completion.sqlite');events.register('prior',prior['start_order']);events.start('prior','qwen-one');events.finish('prior','qwen-one','failed',{'reason':'cleanup_after_native_result'});events.finish('prior','qwen-two','not_started',{})
            canonical=write(trace/'evaluation.json',{'task_completed':False,'technical_error':None});automatic=write(trace/'automatic-grading.json',{'status':'graded'})
            result=write(out/'qwen-one/result.json',{'case':'qwen-one','scripted':False,'status':'graded_and_projected','caller_driver':driver,'caller_commit':'prior','case_binding_sha256':caller.case_binding(cases[0]),'execution_binding_sha256':caller.execution_binding(prior,cases[0]),'result':{'trace':str(trace),'viewer_projection':{'task_completed':False}}})
            viewer=write(out/'qwen-one/grade-viewer.json',{'status':'verified','task_completed':False,'canonical':canonical,'automatic':automatic})
            priorpin=write(d/'launch-spec-approved-v1.json',prior)
            write(out/'supervisor-start.json',{'pid':0})
            terminal=write(out/'terminal-artifacts.json',{'suite_id':'prior','source_driver':driver,'rejected_symlinks':[],'files':[{'relative_path':str(path.relative_to(out)),'sha256':caller.pin(path)['sha256']}for path in out.rglob('*')if path.is_file()]})
            spec={**deepcopy(prior),'suite_id':'new','output':str(d/'new-output'),'completion_db':str(d/'new-output/completion.sqlite'),'start_order':['qwen-two'],'resume':[{'spec':priorpin,'result':result,'viewer':viewer}],'resume_attempts':[{'spec':priorpin,'completion_db':caller.pin(out/'completion.sqlite'),'terminal_inventory':terminal}]}
            self.assertEqual(caller.hosted_attempt_ids(spec,{}),['qwen-two'])
            # Omitting a native failure cannot silently turn it into a rerun.
            with self.assertRaisesRegex(ValueError,'Every prior'):caller.hosted_attempt_ids({**spec,'resume':[],'start_order':['qwen-one','qwen-two']},{})
            wrong=deepcopy(spec);wrong['resume'][0]['viewer']=canonical
            with self.assertRaisesRegex(ValueError,'misbinds'):caller.hosted_attempt_ids(wrong,{})
            changed=deepcopy(spec);changed['cases'][0]['task_id']='changed'
            with self.assertRaises(ValueError):caller.hosted_attempt_ids(changed,{})
            with self.assertRaises(ValueError):caller.hosted_attempt_ids({**spec,'start_order':['qwen-one','qwen-two']},{})
            initial=deepcopy(spec);initial.pop('resume');initial.pop('resume_attempts');initial['start_order']=['qwen-one','qwen-two']
            with self.assertRaisesRegex(ValueError,'Measured prior'):caller.hosted_attempt_ids(initial,{})

    def test_actual_counter_bundle_and_case_sources_are_required(self):
        from hashlib import sha256
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'root';assets=Path(tmp)/'assets';bundle=assets/'qwen';bundle.mkdir(parents=True)
            (root/'intent_browser').mkdir(parents=True)
            expected=[]
            def write(path,data):
                path.write_bytes(data);digest=sha256(data).hexdigest()
                expected.append({'path':str(path),'sha256':digest})
                return digest
            files={name:{'sha256':write(bundle/name,name.encode())}for name in ('tokenizer.json','tokenizer_config.json','chat_template.jinja')}
            registry={'models':{hosted.MODEL:{'repository':'official','revision':'pinned','bundle':'qwen','files':files}}}
            write(root/'intent_browser/model_tokenizers.json',json.dumps(registry).encode())
            for name in ('input_budget.py','model_input_budget.py'):write(root/'intent_browser'/name,name.encode())
            readiness={'exact_existing_asset_and_counter_pins':expected,'official_tokenizer_repository':'official','official_tokenizer_revision':'pinned'}
            receipt=Path(tmp)/'ready.json';receipt.write_text(json.dumps(readiness))
            spec={'hosted_readiness':caller.pin(receipt),'counter_assets_root':str(assets),'tokenizer':caller.pin(bundle/'tokenizer.json')}
            case={'root':str(root),'commit':'pinned','source_export':{}}
            with patch.object(caller,'helper',return_value={'verify_source_export':lambda *args:None}):
                caller.hosted_counter_bindings(spec,[case])
                (bundle/'chat_template.jinja').write_text('wrong')
                with self.assertRaisesRegex(ValueError,'Pinned input changed'):caller.hosted_counter_bindings(spec,[case])
                (bundle/'chat_template.jinja').write_bytes(b'chat_template.jinja')
                (root/'intent_browser/input_budget.py').write_text('wrong')
                with self.assertRaisesRegex(ValueError,'Pinned input changed'):caller.hosted_counter_bindings(spec,[case])

    def test_transient_suite_deadline_does_not_invalidate_frozen_acceptance(self):
        spec=self.spec();case=spec['cases'][0]
        self.assertEqual(caller.config_hash(spec),caller.config_hash({**spec,'suite_deadline_utc':1}))
        self.assertEqual(caller.execution_binding(spec,case),caller.execution_binding({**spec,'suite_deadline_utc':2},case))
        self.assertNotEqual(caller.config_hash(spec),caller.config_hash({**spec,'suite_timeout':5}))

    def test_release_binds_new_finite_list_providers_and_every_scripted_acceptance(self):
        spec=self.spec();spec['cases']=[{**spec['cases'][0],'id':'qwen-X'+str(i),'task_id':'X'+str(i),'public_request':'request'+str(i)}for i in range(34)]
        spec.update(start_order=[c['id']for c in spec['cases']],max_concurrent_episodes=4,prewarm_count=1,
            authorization={'path':'authorization','sha256':'a'},hosted_readiness={'path':'readiness','sha256':'b'},
            review={'path':'review','sha256':'c'},ready={'path':'ready','sha256':'d'},driver={'path':'driver','sha256':'e'})
        spec['canary_task_ids']=[c['task_id']for c in spec['cases'][:4]]
        options={'order':['akashml'],'only':['akashml'],'require_parameters':True}
        spec.update(provider_options=options,extractor_provider_options=deepcopy(options))
        records={'authorization':{'case_ids':spec['start_order'],'dispatch_authorized':True,'request':{'path':'request','sha256':'r'},
            'policy_model':hosted.MODEL,'formatter_model':hosted.MODEL,'max_input_tokens':150000,
            'max_active_combined':4,'prewarm_count':1},
            'request':{'finite_episode_list':[{'id':c['task_id'],'request':c['public_request']}for c in spec['cases']]},
            'readiness':{'status':'read_only_model_key_assets_and_CPU_counter_verified_no_provider_completion',
                'model':hosted.MODEL,'key_authentication_HTTP':200,'common_context_ceiling':262144,
                'architecture':{'input_modalities':['text','image']},'endpoints_in_existing_order':[
                    {'configured_name':'akashml','context_length':262144,'max_completion_tokens':65536,
                     'required_tools_and_structured_parameters_present':True}],
                'counter_smoke':{'path':'smoke','sha256':'f'},'exact_existing_asset_and_counter_pins':[],
                'exact_existing_request_options':{'provider':options,'reasoning':{'enabled':True}}},
            'smoke':{'status':'passed'},'review':{'status':'approved','configuration_sha256':caller.config_hash(spec)},
            'ready':{'status':'passed','driver':spec['driver'],'cases':[{'case':c['id']}for c in spec['cases']]}}
        def run(value):
            with patch.object(caller,'checked',side_effect=lambda row:Path(row['path'])),\
                 patch.object(caller,'load',side_effect=lambda path:records[str(path)]),\
                 patch.object(caller,'hosted_runtime',return_value={'validate_limits':hosted.validate_limits}),\
                 patch.object(caller,'hosted_prior_specs',return_value={}),\
                 patch.object(caller,'verify_ready_case') as accepted:
                caller.check_hosted_release(value)
                self.assertEqual(accepted.call_count,34)
        run(spec)
        old=records['authorization']['dispatch_authorized'];records['authorization']['dispatch_authorized']=False
        with self.assertRaisesRegex(ValueError,'authorization'):run(spec)
        records['authorization']['dispatch_authorized']=old
        records['ready']['cases']=records['ready']['cases'][:-1]
        with self.assertRaisesRegex(ValueError,'all34'):run(spec)
        records['ready']['cases'].append({'case':spec['cases'][-1]['id']})
        records['readiness']['endpoints_in_existing_order'][0]['context_length']=65536
        with self.assertRaisesRegex(ValueError,'readiness'):run(spec)



class HostedClaimWireSchemaTests(unittest.TestCase):
    def claim(self,kind,**constraints):
        return {'type':'object','properties':{'value':{'type':[kind,'null'],**constraints},
            'evidence':{'type':['string','null']}},'required':['value','evidence'],
            'additionalProperties':False}

    def test_false_is_nonnull_and_native_enums_ranges_remain_enforced(self):
        from jsonschema import validate, ValidationError, Draft202012Validator
        original={'type':'object','properties':{'undefined':self.claim('boolean'),
            'count':self.claim('integer',minimum=0),'colour':self.claim('string',enum=['navy',None])},
            'required':['undefined','count','colour'],'additionalProperties':False}
        before=deepcopy(original);wire=hosted.coherent_claim_schema(original)
        Draft202012Validator.check_schema(wire);self.assertEqual(original,before)
        good={'undefined':{'value':False,'evidence':'The median is defined'},
            'count':{'value':0,'evidence':'No models'},'colour':{'value':'navy','evidence':'navy'}}
        validate(good,wire);validate(good,original)
        for field,value in [('undefined',{'value':False,'evidence':None}),
                            ('count',{'value':-1,'evidence':'-1'}),
                            ('colour',{'value':'red','evidence':'red'})]:
            bad=deepcopy(good);bad[field]=value
            with self.subTest(field=field),self.assertRaises(ValidationError):validate(bad,wire)

    def test_nested_arrays_only_null_claim_and_composite_schemas(self):
        from jsonschema import validate, ValidationError, Draft202012Validator
        null_only=self.claim('string',enum=[None])
        original={'type':'array','items':null_only};wire=hosted.coherent_claim_schema(original)
        Draft202012Validator.check_schema(wire)
        validate([{'value':None,'evidence':None}],wire)
        with self.assertRaises(ValidationError):validate([{'value':None,'evidence':'absent'}],wire)
        composite=self.claim('integer');composite['anyOf']=[{'properties':{'value':{'const':0}}}]
        self.assertEqual(hosted.coherent_claim_schema(composite),composite)
        plain={'type':'object','properties':{'value':{'type':'string'},'evidence':{'type':'string'}},
            'required':['value','evidence'],'additionalProperties':False}
        self.assertEqual(hosted.coherent_claim_schema(plain),plain)

if __name__ == '__main__':unittest.main()
