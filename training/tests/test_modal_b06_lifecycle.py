"""Source-only controller tests; no Modal API, GPU or model requests."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import importlib.util
import ast
import types
import json
import os
import queue
import runpy
import sqlite3
import time
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS=Path(__file__).resolve().parents[1]/'scripts/modal_b06'
sys.path.insert(0,str(SCRIPTS))
import lifecycle
import controller
import producer_transport
import qualify_full
from pilot_relay import canonical

PROJECT=Path(os.environ.get('B06_TEST_PROJECT_ROOT','/home/bjorn/code/LLM_proj_uu'))
REMOTE=PROJECT/'.local/coordination/qwen-capability-sweep-20261010/remote-infrastructure-v1'
COUNTER=Path('/home/bjorn/code/LLM_proj_uu-worktrees/eval-modal-counter-order-20261011-v1/scripts/remote_counter_bridge.py')
REQUEST=REMOTE/'modal-pilot-v2/Evaluation-turn-replay-v1/saved-failing-request.json'

class WorkerControls(unittest.TestCase):
 def loop(self,index):
  source=ast.parse((SCRIPTS/'serving_worker.py').read_text())
  worker=next(node for node in source.body if isinstance(node,ast.FunctionDef) and node.name=='gpu_server')
  loops=[node for node in ast.walk(worker) if isinstance(node,ast.While)]
  return compile(ast.fix_missing_locations(ast.Module(body=[loops[index]],type_ignores=[])),str(SCRIPTS/'serving_worker.py'),'exec')
 def test_post_startup_heartbeats_refresh_until_stop(self):
  clock=types.SimpleNamespace(now=0)
  class Messages:
   calls=0
   def get(self,**kwargs):
    self.calls+=1;clock.now+=100
    return 'heartbeat' if self.calls<6 else 'stop'
  messages=Messages();report={}
  scope=dict(time=types.SimpleNamespace(time=lambda:clock.now,monotonic=lambda:clock.now,sleep=lambda _:None),deadline=86400,server=types.SimpleNamespace(poll=lambda:None),last_heartbeat=0,last_controller=0,messages=messages,report=report,stdqueue=queue)
  exec(self.loop(1),scope)
  self.assertEqual(report['status'],'STOPPED_BY_CLIENT')
  self.assertEqual(messages.calls,6)
 def test_startup_stop_is_terminal(self):
  class Response:
   status=200
   def __enter__(self):return self
   def __exit__(self,*args):pass
  scope=dict(time=types.SimpleNamespace(time=lambda:1000,monotonic=lambda:1000,sleep=lambda _:None),started=1000,last_controller=1000,messages=types.SimpleNamespace(get=lambda **kwargs:'stop'),report={},stdqueue=queue,server=types.SimpleNamespace(poll=lambda:None),urllib=types.SimpleNamespace(request=types.SimpleNamespace(urlopen=lambda *args,**kwargs:Response())))
  with self.assertRaises(InterruptedError):exec(self.loop(0),scope)

class Messages:
    def __init__(self,fail=False):self.values=[];self.fail=fail
    def put(self,value,**kwargs):
        if self.fail:raise OSError('Mock failure')
        self.values.append(value)

class Call:
    def __init__(self,fail=False):self.cancelled=False;self.fail=fail
    def get(self,**kwargs):
        if self.fail:raise TimeoutError('Mock failure')
        return {'status':'STOPPED'}
    def cancel(self,**kwargs):self.cancelled=kwargs['terminate_containers']

class Tests(unittest.TestCase):
    @unittest.skipUnless((PROJECT/'.local/coordination/qwen-capability-sweep-20261010/sol-random4-v1/episode_events_frozen.py').is_file(), 'Pinned Events helper absent')
    def test_committed_grade_survives_hot_notification_journal(self):
        import subprocess
        helper=PROJECT/'.local/coordination/qwen-capability-sweep-20261010/sol-random4-v1/episode_events_frozen.py'
        api=runpy.run_path(str(helper))
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);run='hot-pilot';trace=root/'trace';trace.mkdir()
            (trace/'steps.jsonl').write_text('{"model_response": {}}\n')
            (trace/'metadata.json').write_text(json.dumps({'model':'Qwen/Qwen3.8-27B-FP8','driver':'modal-real-model','tags':['model']}))
            caller=root/'caller';caller.write_text('')
            database=root/(sha256(run.encode()).hexdigest()+'.sqlite')
            events=api['Events'](database);events.register(run,['B06'])
            events.subscribe('test',run,'unused-test-recipient',final=True);events.start(run,'B06')
            events.finish(run,'B06','succeeded',{'trace':str(trace),'task_verdict':False})
            code="import sqlite3,os,sys; c=sqlite3.connect(sys.argv[1],isolation_level=None); c.execute('PRAGMA cache_size=1'); c.execute('BEGIN IMMEDIATE'); c.execute(\"UPDATE notices SET state='delivering'\"); c.execute('UPDATE notices SET delivery=?',('x'*200000,)); os._exit(124)"
            self.assertEqual(subprocess.run([sys.executable,'-B','-c',code,str(database)],timeout=10).returncode,124)
            self.assertTrue(Path(str(database)+'-journal').exists())
            with patch.object(controller.runpy,'run_path',return_value={'verify_terminal':lambda result:result['task_verdict']}):
                result=controller.completed_episode({'claims_directory':d},run,caller,sha256(b'').hexdigest())
            self.assertIs(result['task_verdict'],False)
            with sqlite3.connect(database) as db:
                self.assertEqual(db.execute('SELECT state FROM notices').fetchone()[0],'pending')
    def test_exit124_after_verified_completion_retains_false_verdict(self):
        # Notification/completion-file interruption must not lose a failed task
        # that was already successfully graded and projected into the viewer.
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);run='test-pilot';trace=root/'trace';trace.mkdir()
            (trace/'steps.jsonl').write_text('{"model_response": {}}\n')
            (trace/'metadata.json').write_text(json.dumps({'model':'Qwen/Qwen3.8-27B-FP8','driver':'modal-real-model','tags':['model']}))
            (root/'caller').write_text('')
            evidence={'trace':str(trace),'task_verdict':False}
            database=root/(sha256(run.encode()).hexdigest()+'.sqlite')
            with sqlite3.connect(database) as db:
                db.execute('CREATE TABLE episodes(suite,id,state,payload)')
                db.execute('INSERT INTO episodes VALUES (?,?,?,?)',(run,'B06','succeeded',json.dumps(evidence)))
            with patch.object(controller.runpy,'run_path',return_value={'verify_terminal':lambda result:result['task_verdict']}):
                result=controller.completed_episode({'claims_directory':d},run,root/'caller',sha256(b'').hexdigest())
            self.assertIs(result['task_verdict'],False)
            self.assertIsNone(result['completion_receipt'])
            self.assertEqual(result['model_episodes'],1)
            completion=root/(sha256(run.encode()).hexdigest()+'-completion.json')
            for partial in ('','{','{"evidence":'):
                completion.write_text(partial)
                with patch.object(controller.runpy,'run_path',return_value={'verify_terminal':lambda result:result['task_verdict']}):
                    recovered=controller.completed_episode({'claims_directory':d},run,root/'caller',sha256(b'').hexdigest())
                self.assertIs(recovered['task_verdict'],False)
                self.assertIsNone(recovered['completion_receipt'])
                self.assertIsNotNone(recovered['completion_receipt_error'])
            completion.write_text(json.dumps({'evidence':{'task_verdict':True}}))
            with self.assertRaisesRegex(ValueError,'differs from durable Events'):
                controller.completed_episode({'claims_directory':d},run,root/'caller',sha256(b'').hexdigest())
            completion.unlink()
            (root/'caller').write_text('# source changed after launch')
            with self.assertRaisesRegex(ValueError,'Pinned input changed'):
                controller.completed_episode({'claims_directory':d},run,root/'caller',sha256(b'').hexdigest())
    def test_exit124_before_completion_cannot_become_task_result(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);run='test-pilot';database=root/(sha256(run.encode()).hexdigest()+'.sqlite')
            with sqlite3.connect(database) as db:
                db.execute('CREATE TABLE episodes(suite,id,state,payload)')
                db.execute('INSERT INTO episodes VALUES (?,?,?,?)',(run,'B06','failed','{}'))
            with self.assertRaises(ValueError):controller.completed_episode({'claims_directory':d},run,root/'caller',sha256(b'').hexdigest())
    def test_completed_events_still_require_canonical_HTTP_verification(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);run='test-pilot';database=root/(sha256(run.encode()).hexdigest()+'.sqlite')
            (root/'caller').write_text('')
            with sqlite3.connect(database) as db:
                db.execute('CREATE TABLE episodes(suite,id,state,payload)')
                db.execute('INSERT INTO episodes VALUES (?,?,?,?)',(run,'B06','succeeded','{}'))
            def invalid(result):raise ValueError('Unverified canonical/HTTP grade')
            with patch.object(controller.runpy,'run_path',return_value={'verify_terminal':invalid}):
                with self.assertRaises(ValueError):controller.completed_episode({'claims_directory':d},run,root/'caller',sha256(b'').hexdigest())
    def test_scripted_trace_cannot_count_as_real_model_completion(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);run='test-pilot';trace=root/'trace';trace.mkdir()
            (trace/'steps.jsonl').write_text('{"model_response": {}}\n')
            (trace/'metadata.json').write_text(json.dumps({'model':'scripted','driver':'scripted','tags':['scripted']}))
            (root/'caller').write_text('')
            database=root/(sha256(run.encode()).hexdigest()+'.sqlite')
            with sqlite3.connect(database) as db:
                db.execute('CREATE TABLE episodes(suite,id,state,payload)')
                db.execute('INSERT INTO episodes VALUES (?,?,?,?)',(run,'B06','succeeded',json.dumps({'trace':str(trace),'task_verdict':True})))
            with patch.object(controller.runpy,'run_path',return_value={'verify_terminal':lambda result:result['task_verdict']}):
                with self.assertRaisesRegex(ValueError,'not the authorized real model'):
                    controller.completed_episode({'claims_directory':d},run,root/'caller',sha256(b'').hexdigest())
    def test_child_failure_preserves_exit_code(self):
        with tempfile.TemporaryDirectory() as d:
            with lifecycle.Heartbeat(Messages()) as heartbeat:
                with self.assertRaises(lifecycle.ChildFailure) as caught:
                    lifecycle.run_child([sys.executable,'-c','raise SystemExit(124)'],Path(d)/'log',cwd=d,env=controller.child_environment(),heartbeat=heartbeat)
            self.assertEqual(caught.exception.returncode,124)
    def lifetime(self):
        return dict(mode='episode-owned',expiry_kind='provider-platform-maximum',
                    started_at_utc=1000,expires_at_utc=87400,provider_max_seconds=86400)
    def test_long_active_episode_valid(self):
        self.assertEqual(lifecycle.validate_platform(self.lifetime(),now=1000+7200),87400)
    def test_custom_episode_alarm_rejected(self):
        v=self.lifetime();v.update(expires_at_utc=1900,provider_max_seconds=900)
        with self.assertRaises(ValueError):lifecycle.validate_platform(v,now=1100)
    def test_nonfinite_lifetime_rejected(self):
        v=self.lifetime();v['started_at_utc']=float('nan')
        with self.assertRaises(ValueError):lifecycle.validate_platform(v,now=1100)
    def test_empty_health_200(self):
        class Response:
            status=200
            def read(self):return b''
            def __enter__(self):return self
            def __exit__(self,*args):pass
        with patch('urllib.request.urlopen',return_value=Response()):
            self.assertEqual(producer_transport.http('http://127.0.0.1:1234','/health',expect_json=False)['body_bytes'],0)
            with self.assertRaises(json.JSONDecodeError):producer_transport.http('http://127.0.0.1:1234','/qualification')
    def test_heartbeat_stops(self):
        messages=Messages()
        with lifecycle.Heartbeat(messages,interval=.01) as heartbeat:
            import time
            time.sleep(.025);heartbeat.check()
        self.assertGreaterEqual(len(messages.values),2)
        self.assertFalse(heartbeat.thread.is_alive())
    def test_heartbeat_error(self):
        with lifecycle.Heartbeat(Messages(fail=True),interval=.01,grace=.01) as heartbeat:
            time.sleep(.03)
            with self.assertRaises(RuntimeError):heartbeat.check()
    def test_transient_heartbeat_error_recovers(self):
        messages=Messages(fail=True)
        with lifecycle.Heartbeat(messages,interval=.01,grace=1) as heartbeat:
            time.sleep(.02);heartbeat.check()
            messages.fail=False
            time.sleep(.03);heartbeat.check()
            self.assertIsNone(heartbeat.error)
    def test_child_environment_allowlist(self):
        with patch.dict(os.environ,{'PYTHONOPTIMIZE':'1','AWS_SECRET_ACCESS_KEY':'secret','VERDA_CLIENT_SECRET':'secret','WANDB_API_KEY':'secret','PATH':'/usr/bin'},clear=True):
            env=controller.child_environment()
        self.assertEqual(env['PATH'],'/usr/bin')
        self.assertNotIn('PYTHONOPTIMIZE',env)
        self.assertNotIn('AWS_SECRET_ACCESS_KEY',env)
        self.assertNotIn('VERDA_CLIENT_SECRET',env)
        self.assertNotIn('WANDB_API_KEY',env)
    @unittest.skipUnless(COUNTER.is_file(), "Pinned counter not installed")
    def test_changed_relay_rejected_before_allocation(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'relay.py';p.write_bytes((SCRIPTS/'pilot_relay.py').read_bytes()+b'\n# unexpected change\n')
            with self.assertRaises(ValueError):producer_transport.projection_binding(p,COUNTER)
    def test_descendant_group_killed_when_leader_exits(self):
        # Same-session descendant deliberately ignores SIGTERM. The browser's
        # own bounded launcher handles descendants that detach into a session.
        with tempfile.TemporaryDirectory() as d:
            code="import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)']); print(p.pid,flush=True); time.sleep(.3)"
            with lifecycle.Heartbeat(Messages()) as heartbeat:
                lifecycle.run_child([sys.executable,'-c',code],Path(d)/'log',cwd=d,env=controller.child_environment(),heartbeat=heartbeat)
            pid=int((Path(d)/'log').read_text().strip())
            status=Path('/proc')/str(pid)/'stat'
            deadline=time.monotonic()+1
            while status.exists() and status.read_text().split()[2]!='Z' and time.monotonic()<deadline:time.sleep(.01)
            if status.exists():self.assertEqual(status.read_text().split()[2],'Z')

    @unittest.skipUnless(COUNTER.is_file() and REQUEST.is_file(), "Pinned assets not installed")
    def test_optimized_python_cannot_skip_template_gate(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            code="""import sys,json
from pathlib import Path
from hashlib import sha256
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
import qualify_full as q
from producer_transport import projection_binding
from pilot_relay import canonical
binding=json.loads(Path(sys.argv[2]).read_bytes())
projection=projection_binding(Path(sys.argv[1])/'pilot_relay.py',Path(sys.argv[4]))
identity={'counter_projection_sha256':sha256(canonical(projection)).hexdigest(),'hardware':{'capability':[12,0]}}
def exchange(origin,path,*args,**kwargs):
 if path=='/qualification':return identity
 if path=='/v1/models':return {'data':[{'id':binding['model']['repository'],'max_model_len':131072}]}
 if path=='/tokenizer_info':return {'chat_template':'wrong template'}
 raise AssertionError('Must fail before any token count or generation')
with patch.object(q,'request',exchange):
 try:q.qualify('mock',binding,identity,Path(sys.argv[5]),Path(sys.argv[3]),Path(sys.argv[4]))
 except ValueError:raise SystemExit(0)
raise SystemExit(99)
"""
            run=subprocess.run([sys.executable,'-O','-B','-c',code,str(SCRIPTS),str(REMOTE/'Training-serving-binding-v1.json'),str(REQUEST),str(COUNTER),d],env=controller.child_environment(),text=True,capture_output=True,timeout=30)
            self.assertEqual(run.returncode,0,run.stderr)

    def test_cleanup_on_receipt_write_failure(self):
        with tempfile.TemporaryDirectory() as d:
            call=Call();messages=Messages();report={'status':'FAIL'}
            with self.assertRaises(OSError):
                with lifecycle.cleanup_gpu(call,messages,report,Path(d)/'report.json'):
                    raise OSError('Mock failed local receipt write')
            self.assertTrue(call.cancelled);self.assertIn('stop',messages.values)
            self.assertTrue(lifecycle.read(Path(d)/'report.json')['cancellation_api_accepted'])
    def test_cleanup_if_stop_queue_fails(self):
        with tempfile.TemporaryDirectory() as d:
            call=Call();report={}
            with lifecycle.cleanup_gpu(call,Messages(fail=True),report,Path(d)/'r.json'):pass
            self.assertTrue(call.cancelled)
    def test_failed_child_reaped(self):
        with tempfile.TemporaryDirectory() as d:
            with lifecycle.Heartbeat(Messages()) as heartbeat:
                with self.assertRaises(RuntimeError):
                    lifecycle.run_child([sys.executable,'-c','raise SystemExit(124)'],Path(d)/'log',cwd=d,env=os.environ.copy(),heartbeat=heartbeat)
    def test_child_operation_watchdog(self):
        with tempfile.TemporaryDirectory() as d:
            with lifecycle.Heartbeat(Messages()) as heartbeat:
                with self.assertRaises(TimeoutError):
                    lifecycle.run_child([sys.executable,'-c','import time; time.sleep(30)'],Path(d)/'log',cwd=d,env=os.environ.copy(),heartbeat=heartbeat,operation_timeout=.01)
    @unittest.skipUnless(importlib.util.find_spec('modal') is not None, "Modal SDK not in this interpreter")
    def test_worker_container_import_without_workstation_environment(self):
        import modal
        path=SCRIPTS/'serving_worker.py'
        spec=importlib.util.spec_from_file_location('test_b06_remote_module',path)
        module=importlib.util.module_from_spec(spec)
        with patch.dict(os.environ,{},clear=True), patch.dict(sys.modules,{spec.name:module}), patch('modal.is_local',return_value=False):
            spec.loader.exec_module(module)
        self.assertIsNone(module.image)
        self.assertEqual(module.PYTHON,'/opt/rl/.venv/bin/python')

    @unittest.skipUnless(COUNTER.is_file() and REQUEST.is_file(), "Pinned B06 integration assets not installed")
    def test_source_fingerprints(self):
        projection=producer_transport.projection_binding(SCRIPTS/'pilot_relay.py',COUNTER)
        self.assertEqual(projection['relay_source_sha256'],'74d209d90fdc07687205f1b06fe8cc74bea29395962fb403948078a5018517e3')
        self.assertEqual(projection['tokenize_projection_function_sha256'],'6b4dc9a1ab5b10217a6b475f2aa3989941e41f5f5a080a9873f970fb51380955')
    @unittest.skipUnless(REQUEST.is_file(), "Saved B06 request not installed")
    def test_all_saved_tool_payloads_match_httpx(self):
        import httpx
        self.assertEqual(httpx.__version__,'0.28.1')
        body=json.loads(REQUEST.read_bytes())
        self.assertEqual(len(body['tools']),22)
        self.assertEqual(producer_transport.wire_bytes(body),httpx.Request('POST','http://localhost',json=body).content)
    @unittest.skipUnless(COUNTER.is_file() and REQUEST.is_file(), "Pinned B06 integration assets not installed")
    def test_prepare_live_installed_receipt(self):
        with tempfile.TemporaryDirectory() as d:
            projection=producer_transport.projection_binding(SCRIPTS/'pilot_relay.py',COUNTER)
            life=self.lifetime()
            q=dict(platform_lifetime=life,deadline=life['expires_at_utc'],serving_session_id='test',
                   counter_projection_sha256=sha256(canonical(projection)).hexdigest(),parser_patch_sha256=controller.PATCH['patch_sha256'],
                   parser_patch_receipt=dict(manifest=[dict(original_sha256=controller.PATCH['original_source_sha256'],patched_sha256=controller.PATCH['patched_source_sha256'])],vllm_source_patch_sha256=controller.PATCH['patch_sha256']),
                   parser_regression=dict(passed=True,serving_session_id='test',patched_source_sha256=controller.PATCH['patched_source_sha256']),processor={},identity=dict(image_processor_sha256='test'))
            with patch('lifecycle.time.time',return_value=1100):
                live=controller.prepare_live(Path(d),q,projection,{},'http://127.0.0.1:1234','test')
            receipt=lifecycle.read(lifecycle.checked(live['parser_patch_receipt']))
            self.assertEqual(receipt['patch_sha256'],controller.PATCH['patch_sha256'])
            self.assertEqual(receipt['serving_session_id'],'test')
            self.assertNotIn('dispatch_authorized',live)
    @unittest.skipUnless(COUNTER.is_file() and REQUEST.is_file(), "Pinned B06 integration assets not installed")
    def test_mock_full_qualification_22_tools(self):
        # Uses the actual accepted tokenizer/template estimator, but every HTTP
        # response is a CPU mock. This is plumbing evidence, never live parity.
        with tempfile.TemporaryDirectory() as d:
            binding=lifecycle.read(REMOTE/'Training-serving-binding-v1.json')
            path=Path(binding['first_case']['source_root'])/'intent_browser/input_budget.py'
            spec=importlib.util.spec_from_file_location('test_accepted_budget',path)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            counter=module.QwenInputCounter(binding['tokenizer']['tokenizer.json']['path'])
            projection=producer_transport.projection_binding(SCRIPTS/'pilot_relay.py',COUNTER)
            q=lifecycle.read(REMOTE/'modal-pilot-v2/gpu-attempt-v2/server-identity.json')
            started=time.time()-1
            life=dict(mode='episode-owned',expiry_kind='provider-platform-maximum',started_at_utc=started,expires_at_utc=started+86400,provider_max_seconds=86400)
            q.update(platform_lifetime=life,deadline=life['expires_at_utc'],serving_session_id='mock',
                   counter_projection_sha256=sha256(canonical(projection)).hexdigest(),parser_patch_sha256=controller.PATCH['patch_sha256'],
                   parser_patch_receipt=dict(manifest=[dict(original_sha256=controller.PATCH['original_source_sha256'],patched_sha256=controller.PATCH['patched_source_sha256'])],vllm_source_patch_sha256=controller.PATCH['patch_sha256']),
                   parser_regression=dict(passed=True,serving_session_id='mock',patched_source_sha256=controller.PATCH['patched_source_sha256']))
            calls=[]
            def request(origin,path,body=None,**kwargs):
                if path=='/health':return None
                if path=='/qualification':return q
                if path=='/v1/models':return {'data':[dict(id=binding['model']['repository'],max_model_len=131072)]}
                if path=='/tokenizer_info':return {'chat_template':Path(binding['tokenizer']['chat_template.jinja']['path']).read_text()}
                # The local estimator needs original reasoning_content; reverse
                # the documented alias solely inside this synthetic mock.
                messages=deepcopy(body['messages'])
                for m in messages:
                    if 'reasoning' in m:m['reasoning_content']=m.pop('reasoning')
                count=counter(messages,body['tools'])['input_tokens'];ids=list(range(count))
                if path=='/tokenize':return dict(count=count,max_model_len=131072,token_ids_sha256=sha256(canonical(ids)).hexdigest())
                if path=='/v1/chat/completions':
                    calls.append(body)
                    return dict(usage=dict(prompt_tokens=count,completion_tokens=body['max_tokens']),prompt_token_ids=ids)
                raise AssertionError(path)
            with patch.object(qualify_full,'request',side_effect=request):
                proof=qualify_full.qualify('mock',binding,q,Path(d),REQUEST,COUNTER)
            self.assertTrue(proof['passed']);self.assertEqual(len(calls),3)
            self.assertEqual(sum(c['max_tokens'] for c in calls),5)
            self.assertTrue(all(len(c['tools'])==22 for c in calls))
            self.assertEqual(proof['runtime_projection'],projection)
            self.assertEqual(proof['wire_serialization'],'json-insertion-order-v1')
            controller.admit_count_proof(proof,q,projection)
            stale=deepcopy(proof);stale['serving_session_id']='old'
            with self.assertRaises(ValueError):controller.admit_count_proof(stale,q,projection)
            # Actual released consumer code must accept the producer's receipt
            # shapes. Everything here is synthetic and confined to temp files.
            lifecycle.save(Path(d)/'mock-readiness.json',proof)
            live=controller.prepare_live(Path(d),q,projection,lifecycle.pin(REMOTE/'Training-serving-binding-v1.json'),'http://127.0.0.1:1234','mock')
            live.update(qualification_receipt=lifecycle.pin(Path(d)/'mock-readiness.json'),complete_wire_count_parity_proof=lifecycle.pin(Path(d)/'mock-readiness.json'),dispatch_authorized=True)
            api=runpy.run_path(str(COUNTER))
            bridge=api['Bridge'](live,time.monotonic()+86390,exchange=lambda method,path,body=None:request('mock',path,body))
            self.assertTrue(bridge.readiness()['ready'])
            actual=bridge.count(json.loads(REQUEST.read_bytes()))
            self.assertEqual(actual['input_tokens'],35370)
            consumer=runpy.run_path(str(REMOTE/'Evaluation-full-B06-v1/source/scripts/modal_b06_full_episode.py'))
            consumer['verify_parser'](dict(parser_patch_binding=controller.PATCH),live)
            self.assertEqual(consumer['verify_projection'](live),q['counter_projection_sha256'])


if __name__=='__main__':unittest.main()
