"""Actual pinned recording package must propagate caller termination."""
import asyncio,importlib.util,json,signal,sys,unittest,tempfile,threading
from unittest.mock import patch
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
path=ROOT/'scripts/comparison_suite.py';spec=importlib.util.spec_from_file_location('comparison_deadline_subject',path)
caller=importlib.util.module_from_spec(spec);sys.modules[spec.name]=caller;spec.loader.exec_module(caller)

class RecordingTerminationTests(unittest.TestCase):
    def test_signal_during_recording_observe_does_not_replay_operation(self):
        receipt_path=Path('/home/bjorn/code/LLM_proj_uu/.local/coordination/inspect-pilot-mapping-20261011-v1/package-v2-receipt.json')
        receipt=json.loads(receipt_path.read_text());loader=caller.runpy.run_path(str(caller.checked(receipt['loader'])))
        recording,pins=loader['load_recording'](receipt['package_root'],receipt['relative_source_sha256'])
        class Page:
            url='http://offline.invalid/native-probe'
            def evaluate(self,*a):signal.raise_signal(signal.SIGALRM)
        old={kind:signal.getsignal(kind) for kind in (signal.SIGTERM,signal.SIGINT,signal.SIGALRM)};signal.signal(signal.SIGALRM,caller.signal_deadline);operations=[]
        try:
            provider=recording.NativeSuiteProvider(enabled=True,expected_sources=pins);provider.page=Page()
            with self.assertRaises(caller.EpisodeDeadline):provider.observe(lambda:operations.append('replayed'))
            self.assertEqual(operations,[])
            self.assertFalse(issubclass(caller.EpisodeDeadline,Exception))
        finally:
            for kind,handler in old.items():signal.signal(kind,handler)
            recording.release_package()

class AddressProjectionTests(unittest.TestCase):
    def test_verified_address_scope_preserved_and_mismatched_verdict_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            trace=Path(temp);(trace/'evaluation.json').write_text(json.dumps({'task_completed':True}));(trace/'automatic-grading.json').write_text('{}')
            published={'status':'verified','native_verdict':'pass','scoring_scope':'observed_checkout_or_submitted_address_only','full_order_completion':'not_assessed'}
            result=caller.address_projection_result(trace,published)
            self.assertIs(result['task_completed'],True)
            self.assertEqual(result['full_order_completion'],'not_assessed')
            self.assertEqual(result['scoring_scope'],published['scoring_scope'])
            with self.assertRaises(ValueError):caller.address_projection_result(trace,{**published,'native_verdict':'fail'})

class SubscriptionLoopTests(unittest.TestCase):
    def test_actual_frozen_guard_reads_fresh_quota_inside_active_loop(self):
        quota_path=Path('/home/bjorn/code/LLM_proj_uu/.local/coordination/luna34-parallel-20261011/transport-quota-reviewed-v1/subscription_quota.py')
        quota=caller.runpy.run_path(str(quota_path));guard_type=quota['SubscriptionQuotaGuard']
        globals_=quota['_read_sync'].__globals__;reads=[];used=[10,20,99]
        async def read():
            reads.append((threading.get_ident(),id(asyncio.get_running_loop())))
            return {'ordinaryUsageAllowed':True,'rateLimits':{'limitId':'codex','planType':'pro',
                'primary':{'usedPercent':used.pop(0),'windowDurationMins':10080,'resetsAt':1792305291},'secondary':None}}
        with tempfile.TemporaryDirectory() as tmp,patch.dict(globals_,{'_read':read}):
            guard=caller.subscription_guard(guard_type,Path(tmp))
            async def dispatch():
                outer=(threading.get_ident(),id(asyncio.get_running_loop()))
                for remaining in (90,80):
                    result=guard(require_complete_windows=True)
                    self.assertEqual(result['windows'][0]['remaining_percent'],remaining)
                with self.assertRaises(quota['SubscriptionQuotaExhausted']):guard(require_complete_windows=True)
                self.assertEqual(len(reads),3)
                self.assertTrue(all(thread!=outer[0] and loop!=outer[1] for thread,loop in reads))
            asyncio.run(dispatch())
            receipts=[json.loads(row)for row in (Path(tmp)/'checks.jsonl').read_text().splitlines()]
            self.assertEqual([r['status']for r in receipts],['admitted','admitted','held_at_floor'])

class PooledSourceQualificationTests(unittest.TestCase):
    def test_pool_option_rejects_model_dispatch_before_setup(self):
        with patch.object(caller,'check_release',side_effect=AssertionError('must not reach release/model setup')):
            with self.assertRaisesRegex(ValueError,'model-free qualification only'):
                caller.execute({'shared_chromium':True},{},scripted=False)
            with self.assertRaisesRegex(ValueError,'model-free qualification only'):
                caller.supervise({'shared_chromium':True},scripted=False)

class PoolServiceCleanupTests(unittest.TestCase):
    def test_private_admin_shutdown_precedes_normal_launcher_exit(self):
        from unittest.mock import Mock
        proc=Mock();proc.poll.side_effect=[None,None,0];proc.returncode=0
        with patch.object(caller.subprocess,'run') as rpc:
            caller.stop_pool_service({'python':'qualified-python','chromium_descriptor':'private/pool/descriptor.json'},'root','output',proc)
            rpc.assert_called_once();proc.wait.assert_called_once_with(timeout=45)
            proc.terminate.assert_not_called();proc.kill.assert_not_called()
            self.assertEqual(rpc.call_args.kwargs['timeout'],15)
            self.assertEqual(rpc.call_args.args[0][-2:],['root','private/pool'])

    def test_already_dead_abnormal_service_is_a_failure(self):
        from unittest.mock import Mock
        proc=Mock();proc.poll.return_value=137;proc.returncode=137
        with patch.object(caller.subprocess,'run') as rpc:
            with self.assertRaisesRegex(RuntimeError,'graceful shutdown'):
                caller.stop_pool_service({'python':'qualified-python','chromium_descriptor':'private/pool/descriptor.json'},'root','output',proc)
            rpc.assert_not_called();proc.terminate.assert_not_called()

    def test_premature_zero_exit_is_not_normal_suite_shutdown(self):
        from unittest.mock import Mock
        proc=Mock();proc.poll.return_value=0;proc.returncode=0
        with patch.object(caller.subprocess,'run') as rpc:
            with self.assertRaisesRegex(RuntimeError,'graceful shutdown'):
                caller.stop_pool_service({'python':'qualified-python','chromium_descriptor':'private/pool/descriptor.json'},'root','output',proc)
            rpc.assert_not_called()

    def test_failed_admin_rpc_contains_owned_scope_without_claiming_success(self):
        from unittest.mock import Mock
        proc=Mock();proc.poll.return_value=None
        with patch.object(caller.subprocess,'run',side_effect=TimeoutError('admin timeout')):
            with self.assertRaisesRegex(RuntimeError,'graceful shutdown'):
                caller.stop_pool_service({'python':'qualified-python','chromium_descriptor':'private/pool/descriptor.json'},'root','output',proc)
            proc.terminate.assert_called_once();proc.wait.assert_called_once_with(timeout=15)

class PoolOwnerFenceTests(unittest.TestCase):
    def test_owner_identity_fails_closed_on_missing_or_reused_pid(self):
        import os
        service=caller.runpy.run_path(str(ROOT/'scripts/shared_chromium_service.py'))
        stat=(Path('/proc')/str(os.getpid())/'stat').read_text()
        start=stat[stat.rfind(')')+2:].split()[19]
        self.assertTrue(service['owner_alive'](os.getpid(),start))
        self.assertFalse(service['owner_alive'](os.getpid(),'wrong-start-identity'))
        self.assertFalse(service['owner_alive'](999999999,'absent'))

    def test_pool_flag_rejects_non_boolean_before_setup(self):
        for value in ('false',1,None):
            with self.assertRaisesRegex(ValueError,'must be boolean'):
                caller.execute({'shared_chromium':value},{},scripted=True)
            with self.assertRaisesRegex(ValueError,'must be boolean'):
                caller.supervise({'shared_chromium':value},scripted=True)

class ReadyBindingTests(unittest.TestCase):
    def test_ready_pin_is_in_reviewed_configuration(self):
        left={'ready':{'path':'a','sha256':'one'},'review':{},'sockets':{},'tokenizer_socket':'socket'}
        right={**left,'ready':{'path':'b','sha256':'two'}}
        self.assertNotEqual(caller.config_hash(left),caller.config_hash(right))
        self.assertEqual(caller.config_hash(left),caller.config_hash({**left,'review':{'different':True},'sockets':{'dynamic':True}}))

    def test_same_success_cannot_be_reused_for_other_case_recipe_or_driver(self):
        from copy import deepcopy
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'result.json';case={'id':'mimo-B02','task_id':'B02','policy_model':'xiaomi/mimo-v2.6-pro','root':'frozen-root','commit':'one','recipe':'frozen-recipe','recipe_manifest':{'sha256':'recipe1'},'max_input_tokens':120000}
            spec={'driver':{'path':'driver','sha256':'source1'},'caller_commit':'one'}
            valid={'case':case['id'],'scripted':True,'case_binding_sha256':caller.case_binding(case),'execution_binding_sha256':caller.execution_binding(spec,case),'caller_driver':spec['driver'],'caller_commit':spec['caller_commit'],'status':'graded_and_projected','result':{'viewer_projection':{'task_completed':True}}}
            def check(value,c=case,s=spec):
                path.write_text(json.dumps(value));caller.verify_ready_case(s,c,{'case':c['id'],'result':caller.pin(path)})
            check(valid)
            for key,value in [('case','mimo-H03'),('scripted',False),('caller_commit','different'),('case_binding_sha256','bad'),('caller_driver',{'path':'driver','sha256':'changed'})]:
                with self.subTest(key=key),self.assertRaises(ValueError):check({**valid,key:value})
            for key in ('helpers','case_dependencies','shared_inputs','inspection_package','queue','channel','shared_chromium'):
                changed={**spec,key:({'mimo-B02':[{'path':'changed','sha256':'changed'}]} if key=='case_dependencies' else 'changed')}
                with self.subTest(spec_key=key),self.assertRaises(ValueError):check(valid,case,changed)
            for key,value in [('recipe','other'),('root','other'),('policy_model','gpt-6-luna'),('max_input_tokens',250000),('public_request','different')]:
                with self.subTest(key=key),self.assertRaises(ValueError):check(valid,{**case,key:value})

class IndependentWatchdogTests(unittest.TestCase):
    def test_parent_stops_real_child_which_ignores_its_alarm(self):
        import subprocess,sys,socket
        process=subprocess.Popen([sys.executable,'-I','-B','-c','import signal,time; signal.signal(signal.SIGALRM,signal.SIG_IGN); print("ready",flush=True); time.sleep(30)'],stdout=subprocess.PIPE,text=True)
        left,right=socket.socketpair();watchdog=None
        try:
            self.assertEqual(process.stdout.readline().strip(),'ready')
            watchdog=caller.CaseWatchdog(process,{'connection':left},startup_seconds=.2,episode_seconds=1,cleanup_grace_seconds=.1)
            self.assertNotEqual(process.wait(timeout=3),0)
            right.settimeout(1);self.assertEqual(right.recv(1),b'')
            self.assertEqual(watchdog.failure['phase'],'startup')
        finally:
            if watchdog:watchdog.close()
            left.close();right.close();process.stdout.close()
            if process.poll() is None:process.kill();process.wait()

    def test_warming_budget_pauses_and_active_budget_is_independent(self):
        from unittest.mock import Mock
        import time
        process=Mock();process.poll.return_value=None
        watchdog=caller.CaseWatchdog(process,{},startup_seconds=.2,episode_seconds=.15,cleanup_grace_seconds=.1)
        try:
            watchdog.ready();time.sleep(.3);process.terminate.assert_not_called()
            watchdog.activate();watchdog.thread.join(1)
            process.terminate.assert_called_once();self.assertEqual(watchdog.failure['phase'],'active')
        finally:watchdog.close()

    def test_repeated_signal_does_not_abort_already_running_cleanup(self):
        old={kind:signal.getsignal(kind)for kind in (signal.SIGTERM,signal.SIGINT,signal.SIGALRM)}
        try:
            signal.signal(signal.SIGTERM,caller.signal_deadline)
            with self.assertRaises(caller.EpisodeDeadline):signal.raise_signal(signal.SIGTERM)
            signal.raise_signal(signal.SIGTERM);signal.raise_signal(signal.SIGALRM)
            self.assertEqual(signal.getsignal(signal.SIGTERM),signal.SIG_IGN)
        finally:
            for kind,handler in old.items():signal.signal(kind,handler)

    def test_supervisor_signal_sets_shared_stop_before_unwind(self):
        def implementation(spec,scripted,stop):
            with self.assertRaises(caller.EpisodeDeadline):signal.raise_signal(signal.SIGTERM)
            self.assertTrue(stop.is_set());signal.raise_signal(signal.SIGTERM)
            return 'contained'
        old=signal.getsignal(signal.SIGTERM)
        with patch.object(caller,'_supervise',implementation):self.assertEqual(caller.supervise({},True),'contained')
        self.assertEqual(signal.getsignal(signal.SIGTERM),old)

class DeadlineGraceTests(unittest.TestCase):
    def test_child_alarm_can_save_failure_costs_and_cleanup_before_parent_kill(self):
        import subprocess,time
        with tempfile.TemporaryDirectory() as temp:
            receipt=Path(temp)/'cleanup.json'
            program="import signal,time,json,sys\nfrom pathlib import Path\ndef stop(*a):raise RuntimeError('deadline')\nsignal.signal(signal.SIGALRM,stop);signal.alarm(1);print('ready',flush=True)\ntry:time.sleep(30)\nexcept RuntimeError:time.sleep(.3);Path(sys.argv[1]).write_text(json.dumps({'cleanup':True,'paid_response_preserved':True}))\n"
            process=subprocess.Popen([sys.executable,'-I','-B','-c',program,str(receipt)],stdout=subprocess.PIPE,text=True);watchdog=None
            try:
                self.assertEqual(process.stdout.readline().strip(),'ready')
                watchdog=caller.CaseWatchdog(process,{},startup_seconds=1,episode_seconds=1,cleanup_grace_seconds=1)
                watchdog.activate();self.assertEqual(process.wait(timeout=4),0)
                self.assertTrue(json.loads(receipt.read_text())['cleanup']);self.assertIsNone(watchdog.failure)
            finally:
                if watchdog:watchdog.close()
                process.stdout.close()
                if process.poll() is None:process.kill();process.wait()

    def test_suite_stop_bounds_silent_child_by_cleanup_grace(self):
        import subprocess
        stop=threading.Event();process=subprocess.Popen([sys.executable,'-I','-B','-c',"import time;print('ready',flush=True);time.sleep(30)"],stdout=subprocess.PIPE,text=True);watchdog=None
        try:
            self.assertEqual(process.stdout.readline().strip(),'ready')
            watchdog=caller.CaseWatchdog(process,{},startup_seconds=20,episode_seconds=20,cleanup_grace_seconds=.15,stop_event=stop);watchdog.activate();stop.set()
            self.assertNotEqual(process.wait(timeout=3),0);self.assertEqual(watchdog.failure['phase'],'suite_stop')
        finally:
            if watchdog:watchdog.close()
            process.stdout.close()
            if process.poll() is None:process.kill();process.wait()

    def test_invalid_limits_reject_before_helper_or_case_claim(self):
        valid={'startup_timeout':15,'episode_timeout':3,'suite_timeout':60}
        for value in (None,0,True,1.5,'3'):
            with self.subTest(value=value),patch.object(caller,'helper',side_effect=AssertionError('must reject before setup')),self.assertRaisesRegex(ValueError,'Positive integer episode_timeout'):
                caller._supervise({**valid,'episode_timeout':value},scripted=True)

class QueueDeadlineIntegrationTests(unittest.TestCase):
    def test_hard_deadline_is_case_local_with_real_queue_channel_and_launcher(self):
        import textwrap,subprocess,time,os
        from types import SimpleNamespace
        source=Path(caller.__file__).read_text().splitlines()
        first=next(i for i,line in enumerate(source)if line.strip().startswith('def one(c,admission):'))
        last=next(i for i,line in enumerate(source)if line.strip().startswith("result=queue['run_ordered_suite']"))
        one=textwrap.dedent('\n'.join(source[first:last]))
        queue=caller.runpy.run_path(str(ROOT/'scripts/episode_queue.py'));channel=caller.runpy.run_path(str(ROOT/'scripts/episode_queue_channel.py'))
        child_code=r'''import json,runpy,signal,socket,sys,time,types
from pathlib import Path
_,config,ident=sys.argv[1:];s=json.loads(Path(config).read_text());out=Path(s['output'])/ident;trace=out/'live/runs/ep';trace.mkdir(parents=True)
(trace/'metadata.json').write_text(json.dumps({'model':'scripted','tags':['scripted','CPU-queue-control'],'not_native_grade':True}))
for sig in (signal.SIGTERM,signal.SIGALRM):signal.signal(sig,signal.SIG_IGN)
api=runpy.run_path(s['channel_path']);peer=socket.socket(socket.AF_UNIX);peer.connect(s['sockets'][ident]);admission=api['ChildAdmission'](peer,ident,RuntimeError)
admission.environment_admission(types.SimpleNamespace(episode_id='ep',directory=str(trace),ready_monotonic=time.monotonic()))
end=time.monotonic()+s['work'][ident]
while time.monotonic()<end:admission.before_dispatch();time.sleep(.1)
(out/'result.json').write_text(json.dumps({'status':'graded_and_projected','usage':{},'result':{'viewer_projection':{'task_completed':True}}}))
(out/'grade-viewer.json').write_text(json.dumps({'status':'verified'}));peer.close()
'''
        with tempfile.TemporaryDirectory(prefix='qd-') as temp:
            out=Path(temp)/'output';out.mkdir();child=Path(temp)/'child.py';child.write_text(child_code)
            listeners={};sockets={};stop=threading.Event();records=[]
            try:
                for ident in 'ABCDE':
                    sock=caller.socket.socket(caller.socket.AF_UNIX);path=str(Path(temp)/(ident+'.sock'));sock.bind(path);sock.listen(1);sock.settimeout(15);listeners[ident]=sock;sockets[ident]=path
                spec={'suite_id':'CPU-only','output':str(out),'sockets':sockets,'startup_timeout':15,'episode_timeout':3,'suite_timeout':60,'python':sys.executable,'driver':{'path':str(child)},'channel_path':str(ROOT/'scripts/episode_queue_channel.py'),'library_path':os.environ.get('LD_LIBRARY_PATH',''),'launcher':{'path':'/home/bjorn/code/LLM_proj_uu/scripts/run_bounded_job.py'},'work':{'A':30,'B':1,'C':2,'D':2,'E':1}}
                runtime=Path(temp)/'runtime.json';runtime.write_text(json.dumps(spec))
                namespace=dict(vars(caller));namespace.update(s=spec,scripted=False,out=out,runtime=runtime,listeners=listeners,stop=stop,grace=1,lock=threading.Lock(),clocks={},channel=channel,events=SimpleNamespace(start=lambda *a:None,finish=lambda *a:records.append(a)),delivery_lock=threading.Lock(),api={'flush':lambda _:None})
                exec(one,namespace)
                result=queue['run_ordered_suite']({i:{'id':i}for i in 'ABCDE'},namespace['one'],max_concurrent_episodes=2,prewarm_count=1,start_order=list('ABCDE'),stop_event=stop)
                self.assertFalse(result['cancelled']);self.assertEqual(result['cases']['A']['status'],'failed')
                self.assertIn('CaseDeadline',result['cases']['A']['error']['type'])
                for ident in 'BCDE':self.assertEqual(result['cases'][ident]['status'],'completed',result['cases'][ident])
                self.assertEqual(json.loads((out/'A-watchdog.json').read_text())['failure']['phase'],'active')
            finally:
                for listener in listeners.values():listener.close()

if __name__=='__main__':unittest.main()
