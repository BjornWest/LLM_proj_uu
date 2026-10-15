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
                namespace=dict(vars(caller));namespace.update(canary_barrier=None,capacity_host=None,serving=None,s=spec,scripted=False,out=out,runtime=runtime,listeners=listeners,stop=stop,grace=1,lock=threading.Lock(),clocks={},channel=channel,events=SimpleNamespace(start=lambda *a:None,finish=lambda *a:records.append(a)),delivery_lock=threading.Lock(),api={'flush':lambda _:None},job_stop_record={},job_stop=lambda cause,**evidence:stop.set(),shared_health=lambda:[],phase_events={i:caller.phase_writer(spec,i,out/'phases',i+'.jsonl') for i in 'ABCDE'})
                exec(one,namespace)
                result=queue['run_ordered_suite']({i:{'id':i}for i in 'ABCDE'},namespace['one'],max_concurrent_episodes=2,prewarm_count=1,start_order=list('ABCDE'),stop_event=stop)
                self.assertFalse(result['cancelled']);self.assertEqual(result['cases']['A']['status'],'failed')
                self.assertIn('CaseDeadline',result['cases']['A']['error']['type'])
                for ident in 'BCDE':self.assertEqual(result['cases'][ident]['status'],'completed',result['cases'][ident])
                self.assertEqual(json.loads((out/'A-watchdog.json').read_text())['failure']['phase'],'active')
            finally:
                for listener in listeners.values():listener.close()

class QwenWatchdogTests(unittest.TestCase):
    def test_rental_deadline_replaces_active_episode_ceiling_and_bounds_warm_wait(self):
        from types import SimpleNamespace
        clock=[10.];process=SimpleNamespace(poll=lambda:None,terminate=lambda:None)
        watchdog=caller.CaseWatchdog(process,{},startup_seconds=5,episode_seconds=None,
            cleanup_grace_seconds=2,rental_deadline=40,clock=lambda:clock[0])
        try:
            watchdog.ready();self.assertEqual(watchdog.deadline,42)
            clock[0]=30;watchdog.activate();self.assertEqual(watchdog.deadline,42)
        finally:watchdog.close()
        with self.assertRaises(ValueError):caller.CaseWatchdog(process,{},startup_seconds=5,episode_seconds=None)

    def test_qwen_prepare_rejects_wrong_context_and_model_before_target_imports(self):
        valid=dict(max_steps=None,episode_timeout=None,max_input_tokens=250000,server_context_tokens=262144,
            max_tokens=16384,request_timeout=600,startup_timeout=900,shared_tokenizer=True,shared_chromium=True,
            cases=[dict(policy_model='Qwen/Qwen3.8-27B-FP8',max_input_tokens=250000,id='qwen-B01',task_id='B01',recipe_manifest={})],qwen_sources={})
        for key,value in [('max_steps',200),('episode_timeout',1080),('max_input_tokens',100000),('server_context_tokens',131072)]:
            with self.subTest(key=key),patch.object(caller,'checked',side_effect=AssertionError('no target reads')):
                with self.assertRaises(ValueError):caller.validate_qwen_limits({**valid,key:value})

class QwenCanaryBarrierTests(unittest.TestCase):
    def test_remainder_waits_for_all_canaries_and_failed_task_can_still_be_infrastructure_complete(self):
        stop=threading.Event();barrier=caller.CanaryBarrier(['a','b','c','d'],stop);released=threading.Event()
        thread=threading.Thread(target=lambda:(barrier.wait('e'),released.set()))
        thread.start()
        try:
            for ident in ['a','b','c']:barrier.complete(ident)
            self.assertFalse(released.wait(.1))
            barrier.complete('d');self.assertTrue(released.wait(1))
            with self.assertRaises(RuntimeError):barrier.complete('d')
        finally:stop.set();thread.join(1)

    def test_canary_failure_wakes_remainder_without_dispatch(self):
        stop=threading.Event();barrier=caller.CanaryBarrier(['a'],stop);errors=[]
        def wait():
            try:barrier.wait('b')
            except RuntimeError as e:errors.append(str(e))
        thread=threading.Thread(target=wait);thread.start();stop.set();thread.join(1)
        self.assertFalse(thread.is_alive());self.assertTrue(errors)

    def test_initial_startup_watchdog_cannot_outlive_rental_budget(self):
        from types import SimpleNamespace
        process=SimpleNamespace(poll=lambda:None,terminate=lambda:None)
        watchdog=caller.CaseWatchdog(process,{},startup_seconds=900,episode_seconds=None,
            cleanup_grace_seconds=30,rental_deadline=20,clock=lambda:10)
        try:self.assertEqual(watchdog.deadline,50)
        finally:watchdog.close()

if __name__=='__main__':unittest.main()

class QwenReviewRegressionTests(unittest.TestCase):
    def test_child_release_hash_ignores_only_private_chromium_transport(self):
        # Supervisor and child verify the same reviewed configuration, after
        # the supervisor has inserted private transport paths and capabilities.
        spec={'runtime_mode':'qwen-private-v1','shared_chromium':True,'caller_commit':'frozen',
              'max_concurrent_episodes':4,'canary_task_ids':['B02','B14','H03','H05']}
        runtime={**spec,'chromium_descriptor':'/tmp/unique/descriptor.json',
                 'capacity_bindings':{'qwen-B02':{'token':'private'}},'sockets':{'qwen-B02':'/tmp/control'}}
        self.assertEqual(caller.config_hash(spec),caller.config_hash(runtime))
        self.assertNotEqual(caller.config_hash(spec),caller.config_hash({**runtime,'max_concurrent_episodes':5}))

    def test_scripted_canary_failure_terminates_real_queue(self):
        import runpy
        queue=runpy.run_path(str(ROOT/'scripts/episode_queue.py'))
        stop=threading.Event();barrier=caller.CanaryBarrier(['a'],stop);result=[]
        def execute(case,admission):
            ident=case['id']
            try:
                admission.environment_ready()
                if ident=='a':raise RuntimeError('actual canary setup failure')
                barrier.wait(ident)
                raise AssertionError('remainder must not dispatch')
            except BaseException:
                barrier.fail(ident);raise
        def run():result.append(queue['run_ordered_suite']({'a':{'id':'a'},'b':{'id':'b'}},execute,
            max_concurrent_episodes=2,prewarm_count=0,start_order=['a','b'],stop_event=stop))
        thread=threading.Thread(target=run);thread.start();thread.join(3)
        try:self.assertFalse(thread.is_alive());self.assertTrue(stop.is_set());self.assertEqual(len(result),1)
        finally:stop.set();thread.join(2)

    def test_terminal_inventory_streams_and_preserves_symlink_as_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);(out/'trace.bin').write_bytes(b'x'*2000001);(out/'foreign').symlink_to('/etc/passwd')
            spec={'output':str(out),'suite_id':'cpu','driver':{'path':'source','sha256':'a'*64}}
            with patch.object(Path,'read_bytes',side_effect=AssertionError('must stream artifacts')):
                caller.terminal_inventory(spec)
            result=caller.load(out/'terminal-artifacts.json')
            self.assertEqual(result['files'][0]['bytes'],2000001)
            self.assertEqual(result['rejected_symlinks'],['foreign'])

class ExplicitSourceExportTests(unittest.TestCase):
    def setUp(self):
        import runpy
        self.api=runpy.run_path(str(ROOT/'scripts/comparison_suite_helpers.py'))
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'root';self.root.mkdir()
        self.source=self.root/'module.py';self.source.write_text('VALUE=1\n');self.source.chmod(0o644)
        self.digest=caller.pin(self.source)['sha256'];self.index=Path(self.tmp.name)/'source-index.json'
        self.row={'commit':'f'*40,'files':{'module.py':{'sha256':self.digest,'bytes':8,'mode':'100644'}}}
        self.index.write_text(json.dumps({'format':'private-frozen-source-capsule-v1','roots':{'frozen':self.row}}))
        self.descriptor={'index':caller.pin(self.index),'root_id':'frozen'}

    def verify(self):return self.api['verify_source_export'](self.root,'f'*40,self.descriptor,{'module.py':self.digest})

    def test_explicit_index_verifies_flat_root_without_git(self):
        with patch.object(caller.subprocess,'check_output',side_effect=AssertionError('no git fallback')):
            self.assertEqual(self.verify()['commit'],'f'*40)
        self.source.write_text('VALUE=2\n')
        with self.assertRaises(ValueError):self.verify()

    def test_identity_index_mode_ancestor_and_traversal_fail_closed(self):
        with self.assertRaises(ValueError):self.api['verify_source_export'](self.root,'a'*40,self.descriptor,{'module.py':self.digest})
        self.source.chmod(0o755)
        with self.assertRaises(ValueError):self.verify()
        self.source.chmod(0o644)
        with self.assertRaises(ValueError):self.api['verify_source_export'](self.root,'f'*40,self.descriptor,{'../module.py':self.digest})
        self.index.write_text('{}')
        with self.assertRaises(ValueError):self.verify()

    def test_recipe_check_uses_explicit_source_export_and_keeps_default_git_guard(self):
        recipe=Path(self.tmp.name)/'recipe';recipe.mkdir();(recipe/'episode.json').write_text(json.dumps({'manual_task':{'user_message':'natural'}}))
        manifest=recipe/'manifest.json';manifest.write_text(json.dumps({'files':{'episode.json':caller.pin(recipe/'episode.json')['sha256']},
            'source_sha256':{'module.py':self.digest},'automatic_grader_supported':True}))
        case={'id':'qwen-B01','task_id':'B01','root':str(self.root),'commit':'f'*40,'recipe':str(recipe),
            'recipe_manifest':caller.pin(manifest),'public_request':'natural','source_export':self.descriptor}
        self.api['recipe_check'](case)
        del case['source_export']
        with patch.object(caller.subprocess,'check_output',side_effect=RuntimeError('Git is mandatory')):
            with self.assertRaisesRegex(RuntimeError,'Git is mandatory'):self.api['recipe_check'](case)

class QwenChildReleaseRegressionTests(unittest.TestCase):
    def test_real_child_passes_reviewed_config_after_dynamic_pool_insertion(self):
        from types import SimpleNamespace
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);ident='qwen-B02';case={'id':ident,'task_id':'B02','policy_model':'Qwen/Qwen3.8-27B-FP8'}
            spec={'runtime_mode':'qwen-private-v1','shared_chromium':True,'cases':[case],'start_order':[ident],
                'max_concurrent_episodes':4,'prewarm_count':1,'authorization':{'path':'authorization'},'review':{'path':'review'},
                'ready':{'path':'ready'},'driver':{'path':'driver'},'caller_commit':'frozen','suite_id':'cpu','output':str(out)}
            authorized={'case_ids':[ident],'dispatch_authorized':True,'allocation_authorized':True,'max_active_combined':4,
                        'prewarm_count':1,'max_input_tokens':250000,'approved_rental_seconds':7200}
            review={'status':'approved','configuration_sha256':caller.config_hash(spec)}
            ready={'status':'passed','driver':spec['driver'],'cases':[{'case':ident}]}
            records={'authorization':authorized,'review':review,'ready':ready}
            with sqlite3.connect(out/'completion.sqlite') as db:
                db.execute('CREATE TABLE episodes(suite TEXT,id TEXT,state TEXT)');db.execute('INSERT INTO episodes VALUES(?,?,?)',('cpu',ident,'running'))
            runtime={**spec,'chromium_descriptor':'/tmp/fresh/descriptor.json','capacity_bindings':{ident:{'token':'one-shot'}}}
            live=SimpleNamespace(live={'dispatch_authorized':True},deployment={'approved_rental_seconds':7200},readiness=lambda:None)
            with patch.object(caller,'source_guard'),patch.object(caller,'validate_qwen_limits'),patch.object(caller,'verify_ready_case'),\
                 patch.object(caller,'checked',side_effect=lambda row:row['path']),patch.object(caller,'load',side_effect=lambda p:records[p]),\
                 patch.object(caller,'qwen_live',return_value=({},live)),patch.object(caller,'helper',side_effect=RuntimeError('passed release before target setup')):
                with self.assertRaisesRegex(RuntimeError,'passed release before target setup'):caller.execute(runtime,case,scripted=False)


class FiniteSuiteSubscriptionTests(unittest.TestCase):
    def test_real_events_subscription_initialization_accepts_one_and34_members(self):
        # Exercise the real non-scripted supervisor initialization through the
        # actual Events API, then stop before roots, environments or providers.
        from types import SimpleNamespace
        import runpy
        events_path=Path('/home/bjorn/code/LLM_proj_uu/.local/coordination/qwen-capability-sweep-20261010/sol-random4-v1/episode_events_frozen.py')
        api=runpy.run_path(str(events_path))
        for count in (1,34,56):
            with self.subTest(count=count),tempfile.TemporaryDirectory() as tmp:
                ids=['luna-'+str(i) for i in range(count)];authorization=Path(tmp)/'authorization.json';authorization.write_text(json.dumps({'case_ids':ids}))
                source={'startup_timeout':180,'episode_timeout':10800,'suite_timeout':36000,'shutdown_grace_seconds':30,
                    'output':str(Path(tmp)/'run'),'authorization':caller.pin(authorization),'suite_id':'cpu','thread_id':'CPU_NOT_DELIVERED',
                    'queue':{'path':'queue'},'channel':{'path':'channel'},'events_helper':caller.pin(events_path)}
                helper={'process_identity':lambda pid:'cpu-start','register_roots':lambda spec:(_ for _ in ()).throw(RuntimeError('subscription stage passed'))}
                real=caller.runpy.run_path
                def modules(path):return api if path==str(events_path) else {}
                with patch.object(caller,'check_release'),patch.object(caller,'source_guard'),patch.object(caller,'helper',return_value=helper),                     patch.object(caller,'checked',side_effect=lambda value:Path(value['path'])),patch.object(caller.runpy,'run_path',side_effect=modules):
                    with self.assertRaisesRegex(RuntimeError,'subscription stage passed'):caller._supervise(source,scripted=False)
                events=api['Events'](Path(source['output'])/'completion.sqlite')
                self.assertEqual(len(events.snapshot()['episodes']),count)
                with caller.sqlite3.connect(events.path) as db:
                    row=db.execute("SELECT milestones FROM subscriptions WHERE id='cpu-suite'").fetchone()
                    self.assertEqual(json.loads(row[0]),[n for n in (10,20,30,35,40,50) if n<count])
