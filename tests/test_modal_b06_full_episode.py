"""CPU-only caller gates. All server/proof records here are synthetic fixtures."""
import hashlib
import json
import os
from types import SimpleNamespace
from pathlib import Path
import signal
import tempfile
import time
import unittest
from unittest.mock import patch
from scripts import modal_b06_full_episode as caller


def pin(path, value):
    path.write_text(json.dumps(value))
    return {'path':str(path.resolve()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def require_events_helper(test):
    path=os.environ.get('FULL_B06_EVENTS_HELPER')
    if not path or not Path(path).is_file():
        test.skipTest('Pinned Events fixture absent; set FULL_B06_EVENTS_HELPER')
    return Path(path)


def lifetime(now=1000):
    return {'mode':'episode-owned','expiry_kind':'provider-platform-maximum',
            'started_at_utc':now,'expires_at_utc':now+86400,'provider_max_seconds':86400}


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.utc=1001;self.mono=50
        self.live={'platform_lifetime':lifetime(),'gpu_deadline_utc':87400}
        self.w=caller.Watchdogs(self.live,utc=lambda:self.utc,mono=lambda:self.mono)

    def test_no_fifteen_or_thirty_minute_episode_budget(self):
        self.utc+=7200;self.mono+=7200
        self.assertGreater(self.w.remaining(),79000)
        self.assertEqual(self.w.timeout(),600)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0],0)

    def test_actual_platform_expiry_stops(self):
        self.utc=87400
        with self.assertRaises(TimeoutError):self.w.remaining()

    def test_monotonic_expiry_survives_wall_clock_regression(self):
        self.utc=900;self.mono+=86400
        with self.assertRaises(TimeoutError):self.w.remaining()

    def test_declared_arbitrary_deadline_is_rejected(self):
        for field,value in [('mode','fixed-episode'),('expiry_kind','user-cutoff'),('expires_at_utc',2080),('provider_max_seconds',True)]:
            live=json.loads(json.dumps(self.live));live['platform_lifetime'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):caller.Watchdogs(live,utc=lambda:1001)

    def test_expired_startup_or_nonfinite_limits_rejected(self):
        for value in [True,0,-1,float('inf'),float('nan')]:
            with self.subTest(value=value),self.assertRaises(ValueError):caller.Watchdogs(self.live,startup_seconds=value,utc=lambda:1001)
        with self.assertRaises(ValueError):caller.Watchdogs(self.live,utc=lambda:87400)

    def test_operation_arms_then_disarms_and_restores_handler(self):
        old=signal.getsignal(signal.SIGALRM)
        with self.w.operation('setup',2):
            self.assertGreater(signal.getitimer(signal.ITIMER_REAL)[0],0)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0],0)
        self.assertEqual(signal.getsignal(signal.SIGALRM),old)

    def test_actual_stalled_operation_times_out(self):
        with self.assertRaisesRegex(TimeoutError,'request watchdog'):
            with self.w.operation('request',.02):time.sleep(.2)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0],0)

    def test_operation_failure_disarms(self):
        with self.assertRaises(RuntimeError):
            with self.w.operation('setup',2):raise RuntimeError('setup failed')
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0],0)

    def test_nested_watchdog_fails_closed_without_disarming_outer(self):
        with self.w.operation('outer',2):
            with self.assertRaises(RuntimeError):
                with self.w.operation('inner',1):pass
            self.assertGreater(signal.getitimer(signal.ITIMER_REAL)[0],0)

    def test_remaining_platform_time_bounds_request(self):
        self.utc=87399;self.mono+=86398
        self.assertLessEqual(self.w.timeout(),1)

    def test_self_declared_shorter_platform_max_rejected(self):
        for seconds in [60,900,1080]:
            value=lifetime();value.update(expires_at_utc=1000+seconds,provider_max_seconds=seconds)
            with self.subTest(seconds=seconds),self.assertRaises(ValueError):
                caller.Watchdogs({'platform_lifetime':value,'gpu_deadline_utc':value['expires_at_utc']},utc=lambda:1001)

    def test_swallowed_soft_timeout_cannot_report_success(self):
        with self.assertRaises(TimeoutError):
            with self.w.operation('request',.02):
                try:time.sleep(.2)
                except TimeoutError:pass

    def test_browser_timer_never_raises_into_dispatcher(self):
        reasons=[]
        self.w.emergency_stop=reasons.append
        with self.assertRaises(TimeoutError):
            with self.w.operation('browser',.02,browser=True):time.sleep(.06)
        self.assertEqual(reasons,['browser watchdog expired'])
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0],0)

    def test_browser_timer_disarmed_after_return(self):
        reasons=[];self.w.emergency_stop=reasons.append
        with self.w.operation('browser',.03,browser=True):pass
        time.sleep(.05)
        self.assertEqual(reasons,[])

    def test_browser_timer_requires_emergency_recording(self):
        with self.assertRaises(ValueError):
            with self.w.operation('browser',1,browser=True):pass


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.binding={'original_source_sha256':'1'*64,'patched_source_sha256':'2'*64,'patch_sha256':'3'*64}
        self.spec={'schema':'modal-full-B06-v1','case':'B06','parser_patch_binding':self.binding,
                   'watchdogs':{'startup_seconds':180,'request_seconds':600}}
        self.regression={'passed':True,'patched_source_sha256':'2'*64,'serving_session_id':'session'}
        self.receipt={**self.binding,'passed':True,'serving_session_id':'session',
                      'regression_receipt':pin(self.root/'regression.json',self.regression)}
        self.identity={'source_commit':'95e9ac988ea515f7194cbdc82ae327e248fc94fa'}
        self.deployment={'qualification':{'identity':self.identity,'parser_patch_sha256':'3'*64},'platform_lifetime':lifetime(time.time()-1)}
        self.count={'parser_patch_sha256':'3'*64}
        self.live={'dispatch_authorized':True,'platform_lifetime':self.deployment['platform_lifetime'],
                   'gpu_deadline_utc':self.deployment['platform_lifetime']['expires_at_utc'],
                   'identity':self.identity,'server_context':131072,'isl':100000,'serving_session_id':'session',
                   'parser_patch_receipt':pin(self.root/'parser.json',self.receipt),
                   'deployment_receipt':pin(self.root/'deploy.json',self.deployment),
                   'complete_wire_count_parity_proof':pin(self.root/'count.json',self.count),
                   'serving_binding':pin(self.root/'serving.json',{'first_case':{'commit':self.identity['source_commit']}})}

    def repin(self,key,file,value):self.live[key]=pin(self.root/file,value)

    def test_correct_actual_parser_binding_and_platform_accepted(self):
        self.assertEqual(caller.verify_parser(self.spec,self.live),self.receipt)
        w=caller.preflight(self.spec,self.live)
        self.assertGreater(w.remaining(),80000)

    def test_no_dispatch_without_explicit_authorization(self):
        self.live['dispatch_authorized']=False
        with self.assertRaises(ValueError):caller.preflight(self.spec,self.live)

    def test_original_episode_budget_spec_rejected(self):
        for name in ['maximum_episode_seconds','episode_deadline_utc','policy_grading_reserve_seconds']:
            with self.subTest(name=name),self.assertRaises(ValueError):caller.preflight({**self.spec,name:1080},self.live)

    def test_changed_operation_watchdog_bounds_rejected(self):
        for values in [{'startup_seconds':1,'request_seconds':600},{'startup_seconds':180,'request_seconds':86400}]:
            with self.subTest(values=values),self.assertRaises(ValueError):
                caller.preflight({**self.spec,'watchdogs':values},self.live)

    def test_wrong_task_case_and_schema_rejected(self):
        for name,value in [('case','B07'),('schema','modal-V2-real-B06-v1')]:
            with self.subTest(name=name),self.assertRaises(ValueError):caller.preflight({**self.spec,name:value},self.live)

    def test_wrong_installed_parser_hash_rejected(self):
        for key in self.binding:
            changed={**self.receipt,key:'f'*64};self.repin('parser_patch_receipt','parser.json',changed)
            with self.subTest(key=key),self.assertRaises(ValueError):caller.verify_parser(self.spec,self.live)

    def test_missing_reviewed_hash_or_malformed_binding_rejected(self):
        for binding in [{}, {**self.binding,'extra':'a'*64},{**self.binding,'patch_sha256':None}]:
            with self.subTest(binding=binding),self.assertRaises(ValueError):caller.verify_parser({**self.spec,'parser_patch_binding':binding},self.live)

    def test_wrong_session_or_unpassed_parser_regression_rejected(self):
        for changed in [{**self.receipt,'serving_session_id':'other'},{**self.receipt,'passed':False}]:
            self.repin('parser_patch_receipt','parser.json',changed)
            with self.assertRaises(ValueError):caller.verify_parser(self.spec,self.live)
        for changed in [{**self.regression,'serving_session_id':'other'},{**self.regression,'passed':False}]:
            self.receipt['regression_receipt']=pin(self.root/'regression.json',changed)
            self.repin('parser_patch_receipt','parser.json',self.receipt)
            with self.assertRaises(ValueError):caller.verify_parser(self.spec,self.live)

    def test_old_count_or_serving_proof_cannot_hide_patch(self):
        for key,file,value in [('complete_wire_count_parity_proof','count.json',{}),('deployment_receipt','deploy.json',{'qualification':{'identity':self.identity}})]:
            original=self.live[key];self.repin(key,file,value)
            with self.subTest(key=key),self.assertRaises(ValueError):caller.verify_parser(self.spec,self.live)
            self.live[key]=original
            # Restore bytes as well as pin, preserving the next independent case.
            pin(self.root/file,self.count if file=='count.json' else self.deployment)

    def test_tampered_receipt_rejected(self):
        (self.root/'parser.json').write_text('{}')
        with self.assertRaises(ValueError):caller.verify_parser(self.spec,self.live)

    def test_platform_deployment_mismatch_rejected(self):
        self.live['platform_lifetime']={**self.live['platform_lifetime'],'provider_max_seconds':900}
        with self.assertRaises(ValueError):caller.preflight(self.spec,self.live)

    def test_composite_fingerprint_binds_all_five_sources(self):
        source='def tokenize_payload(body):\n    return body\n'
        relay=self.root/'relay.py';relay.write_text(source)
        self.live['relay_source']={'path':str(relay),'sha256':hashlib.sha256(relay.read_bytes()).hexdigest()}
        projection={'counter_source_sha256':'3b89ffe833520c9ec94cf290e30d3aa127241c1ed904754e73c3d4141ea9f29b',
                    'counter_wire_function_sha256':'f21b9f8becf3a8713ad3bcf59d610cc59f97406a5d17b6396013191dd5ad2de3',
                    'tokenize_projection_source_sha256':self.live['relay_source']['sha256'],
                    'relay_source_sha256':self.live['relay_source']['sha256'],
                    'tokenize_projection_function_sha256':hashlib.sha256(source.rstrip().encode()).hexdigest()}
        digest=hashlib.sha256(json.dumps(projection,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
        self.count.update(runtime_projection=projection,counter_projection_sha256=digest,counter_projection_digest_format='sha256-compact-sorted-utf8-json-of-runtime-projection-v1')
        self.deployment['qualification']['counter_projection_sha256']=digest
        self.repin('complete_wire_count_parity_proof','count.json',self.count);self.repin('deployment_receipt','deploy.json',self.deployment)
        self.assertEqual(caller.verify_projection(self.live),digest)
        for field in projection:
            bad=json.loads(json.dumps(self.count));bad['runtime_projection'][field]='f'*64
            self.repin('complete_wire_count_parity_proof','count.json',bad)
            with self.subTest(field=field),self.assertRaises(ValueError):caller.verify_projection(self.live)



class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.trace=self.root/'trace';self.trace.mkdir()
        self.result=self.result_for(True)

    def result_for(self, verdict):
        canonical=pin(self.trace/'evaluation.json',{'task_completed':verdict,'technical_error':None,'limitations':['Explicit fixture inconclusive reason'] if verdict is None else []})
        derived=pin(self.trace/'derived-answer-grade.json',{'structured_claims_correct':verdict,'binding_status':'verified'})
        proof=pin(self.root/'HTTP-proof.json',{'status':'verified','url':'http://localhost:8878/#fixture-only',
                                             'canonical_grade':canonical,'derived_grade':derived})
        return {'trace':str(self.trace),'task_verdict':verdict,
                'native_grade':{'structured_claims_correct':verdict},'canonical':canonical,'HTTP_proof':proof}

    def test_task_failure_and_inconclusive_are_valid_graded_completions(self):
        for verdict in [True,False,None]:
            with self.subTest(verdict=verdict):
                self.assertIs(caller.verify_terminal(self.result_for(verdict)),verdict)

    def test_missing_grade_and_missing_projection_fail_closed(self):
        for key in ['canonical','HTTP_proof','native_grade']:
            changed=dict(self.result);changed.pop(key)
            with self.subTest(key=key),self.assertRaises((KeyError,ValueError)):caller.verify_terminal(changed)

    def test_mismatched_or_tampered_grade_fails_closed(self):
        changed={**self.result,'task_verdict':False}
        with self.assertRaises(ValueError):caller.verify_terminal(changed)
        (self.trace/'evaluation.json').write_text('{}')
        with self.assertRaises(ValueError):caller.verify_terminal(self.result)

    def test_actual_sqlite_events_follow_grade_and_projected_completion(self):
        # Only Events SQLite is real. Policy/extractor/browser/network are mocked;
        # flush is deliberately suppressed so tests cannot notify other agents.
        import runpy
        helper=require_events_helper(self)
        api=runpy.run_path(str(helper));api['flush']=lambda registry:None
        spec_path=self.root/'spec.json';live_path=self.root/'live.json'
        spec={'claims_directory':str(self.root/'claims'),'events_helper':caller.pin(helper)}
        live={'pilot_id':'fixture-only'}
        spec_pin=pin(spec_path,spec);live_pin=pin(live_path,live)
        order=[]
        real_verify=caller.verify_terminal
        def verify(result):order.append('grade_verified');return real_verify(result)
        with patch.object(caller.runpy,'run_path',return_value=api),patch.object(caller,'preflight',return_value=SimpleNamespace()),patch.object(caller,'episode',return_value=self.result),patch.object(caller,'verify_terminal',side_effect=verify):
            caller.run_inner(spec_path,spec_pin['sha256'],live_path,live_pin['sha256'],self.root/'output')
        db=self.root/'claims'/ (hashlib.sha256(b'fixture-only').hexdigest()+'.sqlite')
        registry=api['Events'](db);snapshot=registry.snapshot()
        self.assertEqual(order,['grade_verified'])
        self.assertEqual(snapshot['episodes'][0]['state'],'succeeded')
        self.assertEqual(len(registry.notices()),2)
        # A new output must not allow duplicate dispatch for the same pilot.
        with patch.object(caller.runpy,'run_path',return_value=api),patch.object(caller,'episode') as policy:
            with self.assertRaises(FileExistsError):caller.run_inner(spec_path,spec_pin['sha256'],live_path,live_pin['sha256'],self.root/'different-output')
            policy.assert_not_called()

    def test_missing_grade_is_failed_event_not_task_failure(self):
        import runpy
        helper=require_events_helper(self)
        api=runpy.run_path(str(helper));api['flush']=lambda registry:None
        spec_path=self.root/'spec.json';live_path=self.root/'live.json'
        spec_pin=pin(spec_path,{'claims_directory':str(self.root/'claims'),'events_helper':caller.pin(helper)})
        live_pin=pin(live_path,{'pilot_id':'missing-grade-fixture'})
        bad=dict(self.result);bad.pop('HTTP_proof')
        with patch.object(caller.runpy,'run_path',return_value=api),patch.object(caller,'preflight',return_value=SimpleNamespace()),patch.object(caller,'episode',return_value=bad):
            with self.assertRaises(KeyError):caller.run_inner(spec_path,spec_pin['sha256'],live_path,live_pin['sha256'],self.root/'output')
        db=self.root/'claims'/ (hashlib.sha256(b'missing-grade-fixture').hexdigest()+'.sqlite')
        row=api['Events'](db).snapshot()['episodes'][0]
        self.assertEqual(row['state'],'failed')
        self.assertIsNone(row['payload']['task_verdict'])

    def test_null_verdict_does_not_hide_missing_keys_or_failed_grade(self):
        original=self.result_for(None)
        for key in ['task_verdict','native_grade']:
            bad=dict(original);bad.pop(key)
            with self.subTest(key=key),self.assertRaises((KeyError,ValueError)):caller.verify_terminal(bad)
        for grade in [{},{'task_completed':None},{'task_completed':None,'limitations':['reason'],'technical_error':'Grading failed'}]:
            bad=dict(original);bad['canonical']=pin(self.trace/'evaluation.json',grade)
            proof=json.loads((self.root/'HTTP-proof.json').read_text());proof['canonical_grade']=bad['canonical']
            bad['HTTP_proof']=pin(self.root/'HTTP-proof.json',proof)
            with self.subTest(grade=grade),self.assertRaises((KeyError,ValueError)):caller.verify_terminal(bad)
        original=self.result_for(None)
        for grade in [{},{'structured_claims_correct':None},{'structured_claims_correct':None,'binding_status':'unverified'}]:
            proof=json.loads((self.root/'HTTP-proof.json').read_text())
            proof['derived_grade']=pin(self.trace/'derived-answer-grade.json',grade)
            original['HTTP_proof']=pin(self.root/'HTTP-proof.json',proof)
            with self.subTest(derived=grade),self.assertRaises((KeyError,ValueError)):caller.verify_terminal(original)

    def test_notification_failure_preserves_completed_grade_and_outbox(self):
        import runpy
        helper=require_events_helper(self)
        api=runpy.run_path(str(helper))
        def fail_flush(registry):raise RuntimeError('Delivery unavailable')
        api['flush']=fail_flush
        spec_path=self.root/'spec.json';live_path=self.root/'live.json'
        spec_pin=pin(spec_path,{'claims_directory':str(self.root/'claims'),'events_helper':caller.pin(helper)})
        live_pin=pin(live_path,{'pilot_id':'notification-failure-fixture'})
        with patch.object(caller.runpy,'run_path',return_value=api),patch.object(caller,'preflight',return_value=SimpleNamespace()),patch.object(caller,'episode',return_value=self.result):
            caller.run_inner(spec_path,spec_pin['sha256'],live_path,live_pin['sha256'],self.root/'output')
        prefix=self.root/'claims'/hashlib.sha256(b'notification-failure-fixture').hexdigest()
        row=api['Events'](prefix.with_suffix('.sqlite')).snapshot()['episodes'][0]
        self.assertEqual(row['state'],'succeeded')
        self.assertIs(row['payload']['task_verdict'],True)
        self.assertFalse(prefix.with_name(prefix.name+'-failure.json').exists())
        self.assertTrue(prefix.with_name(prefix.name+'-notification-error.json').exists())

    def test_interrupt_after_verified_completion_preserves_recorded_verdict(self):
        import runpy
        helper=require_events_helper(self);api=runpy.run_path(str(helper))
        stop=SimpleNamespace(record=None)
        api['flush']=lambda registry:stop.record('Signal during notification delivery')
        spec_path=self.root/'spec.json';live_path=self.root/'live.json'
        spec_pin=pin(spec_path,{'claims_directory':str(self.root/'claims'),'events_helper':caller.pin(helper)})
        live_pin=pin(live_path,{'pilot_id':'late-interrupt-fixture'})
        result=self.result_for(False)
        with patch.object(caller.runpy,'run_path',return_value=api),patch.object(caller,'preflight',return_value=SimpleNamespace()),patch.object(caller,'episode',return_value=result):
            caller.run_inner(spec_path,spec_pin['sha256'],live_path,live_pin['sha256'],self.root/'output',emergency_stop=stop)
        prefix=self.root/'claims'/hashlib.sha256(b'late-interrupt-fixture').hexdigest()
        self.assertFalse(prefix.with_name(prefix.name+'-failure.json').exists())
        note=json.loads(prefix.with_name(prefix.name+'-terminal-interruption.json').read_text())
        self.assertEqual(note['episode_state'],'succeeded')
        self.assertIs(note['task_verdict'],False)
        self.assertIs(note['retained_evidence']['native_grade']['structured_claims_correct'],False)


class BrowserEmergencyTests(unittest.TestCase):
    def test_real_browser_stall_and_signal_end_with_durable_failed_events(self):
        import subprocess
        import sys
        import runpy
        import ctypes
        import importlib.util
        require_events_helper(self)
        if importlib.util.find_spec('playwright') is None:
            self.skipTest('Real Playwright fixture unavailable')
        try:ctypes.CDLL('libasound.so.2')
        except OSError:self.skipTest('Chromium system libs absent; supply accepted LD_LIBRARY_PATH')
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            if not Path(p.chromium.executable_path).is_file():
                self.skipTest('Existing Chromium fixture absent; no download authorized')
        with tempfile.TemporaryDirectory() as folder:
            for mode in ['watchdog','signal','signal_resource']:
                output=Path(folder)/mode;output.mkdir()
                program=r"""
import json,os,runpy,signal,socket,sys,threading,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from scripts import modal_b06_full_episode as caller
from playwright.sync_api import sync_playwright
out=Path(sys.argv[2]);mode=sys.argv[3]
api=runpy.run_path(os.environ['FULL_B06_EVENTS_HELPER'])
registry=api['Events'](out/'events.sqlite')
registry.register('fixture',['B06']);registry.start('fixture','B06')
def record(reason):
    (out/'failure.json').write_text(json.dumps({'reason':reason,'task_verdict':None,'tags':['scripted']}))
    registry.finish('fixture','B06','failed',{'reason':reason,'task_verdict':None})
stop=caller.EmergencyStop(record)
server=socket.socket();server.bind(('127.0.0.1',0));server.listen(8)
held=[]
threading.Thread(target=lambda:[held.append(server.accept()) for _ in range(8)],daemon=True).start()
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page()
    now=time.time();life={'mode':'episode-owned','expiry_kind':'provider-platform-maximum','started_at_utc':now-1,'expires_at_utc':now-1+86400,'provider_max_seconds':86400}
    w=caller.Watchdogs({'platform_lifetime':life,'gpu_deadline_utc':life['expires_at_utc']},emergency_stop=stop)
    if mode in ('signal','signal_resource'):
        signal.signal(signal.SIGTERM,lambda signum,frame:stop('Operator SIGTERM'))
        threading.Timer(.2,lambda:os.kill(os.getpid(),signal.SIGTERM)).start()
    with w.operation('browser setup',.2 if mode=='watchdog' else 10,browser=True):
        if mode=='signal_resource':
            def no_threads(*args,**kwargs):raise RuntimeError('Synthetic thread cap reached')
            threading.Thread.start=no_threads
        page.goto('http://127.0.0.1:'+str(server.getsockname()[1])+'/',timeout=60000)
"""
                command=[sys.executable,'-B','-c',program,str(Path(caller.__file__).resolve().parents[1]),str(output),mode]
                before=time.monotonic()
                run=subprocess.run(command,capture_output=True,text=True,timeout=20)
                with self.subTest(mode=mode):
                    self.assertEqual(run.returncode,124,run.stderr)
                    self.assertLess(time.monotonic()-before,10)
                    self.assertIsNone(json.loads((output/'failure.json').read_text())['task_verdict'])
                    api=runpy.run_path(os.environ['FULL_B06_EVENTS_HELPER'])
                    row=api['Events'](output/'events.sqlite').snapshot()['episodes'][0]
                    self.assertEqual(row['state'],'failed')
                    self.assertIsNone(row['payload']['task_verdict'])

if __name__=='__main__':unittest.main()
