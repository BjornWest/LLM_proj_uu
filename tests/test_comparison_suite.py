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
        old=signal.signal(signal.SIGALRM,caller.signal_deadline);operations=[]
        try:
            provider=recording.NativeSuiteProvider(enabled=True,expected_sources=pins);provider.page=Page()
            with self.assertRaises(caller.EpisodeDeadline):provider.observe(lambda:operations.append('replayed'))
            self.assertEqual(operations,[])
            self.assertFalse(issubclass(caller.EpisodeDeadline,Exception))
        finally:signal.signal(signal.SIGALRM,old);recording.release_package()

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

if __name__=='__main__':unittest.main()
