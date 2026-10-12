"""Pure discrimination of native caller classification and terminal proof."""
from pathlib import Path
from types import SimpleNamespace
from contextlib import contextmanager
import importlib.util,json,sys,tempfile,unittest,socket,time
ROOT=Path(__file__).resolve().parents[1]
def module(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);sys.modules[name]=m;s.loader.exec_module(m);return m
probe=module('capacity_native_probe_subject',ROOT/'scripts/episode_capacity_native_probe.py')
rpc=module('_native_probe_rpc_fixture',ROOT/'scripts/episode_capacity_rpc.py')
control=module('_native_probe_controller_fixture',ROOT/'training/browser_training/capacity_control.py')
queue_path=ROOT/'scripts/episode_queue.py'
if not queue_path.exists():queue_path=ROOT/'tests/fixtures/episode_capacity_queue.py'
queue=module('_native_probe_queue_fixture',queue_path)
@contextmanager
def setup():
    c=control.EpisodeCapacityController(control.ParkingConfig(max_active_episodes=2,max_generation_requests=1,fresh_seconds=60))
    c.observe(control.CapacitySnapshot(time.monotonic(),0,0,0,.1,0))
    pairs={i:socket.socketpair() for i in ('run:a','run:b')}
    p=rpc.CapacityParent(c,{i:v[0] for i,v in pairs.items()},deadline=time.monotonic()+10).start()
    try:yield c,p,None
    finally:
        for a,b in pairs.values():b.close()
        p.close();c.close()
fixture=SimpleNamespace(rpc=rpc,queue=queue,setup=setup)

class NativeConsumerTests(unittest.TestCase):
    def test_direct_activation_stop_is_native_cancellation_not_infrastructure(self):
        with fixture.setup() as (_,parent,_):
            original=fixture.rpc.CapacitySuiteStopped('user stop during activation')
            channel=SimpleNamespace(serve_admission=lambda *a,**k:(_ for _ in ()).throw(original))
            with self.assertRaises(fixture.queue.QueueCancelled):
                probe.serve_native(None,None,parent,'run:a',channel,fixture.queue,ROOT)
            self.assertFalse(parent.stop_cause['infrastructure'])
            self.assertEqual(parent.stop_cause['message'],str(original))
            self.assertTrue(parent.suite_stop_event.is_set())

    def test_other_admission_failure_is_explicit_infrastructure(self):
        with fixture.setup() as (_,parent,_):
            original=OSError('broken admission socket')
            channel=SimpleNamespace(serve_admission=lambda *a,**k:(_ for _ in ()).throw(original))
            with self.assertRaises(OSError) as caught:
                probe.serve_native(None,None,parent,'run:a',channel,fixture.queue,ROOT)
            self.assertIs(caught.exception,original);self.assertTrue(parent.stop_cause['infrastructure'])

    def record(self,folder,verdict=False):
        a=folder/'automatic.json';e=folder/'evaluation.json'
        a.write_text(json.dumps({'status':'graded'}));e.write_text(json.dumps({'task_completed':verdict,'technical_error':None}))
        return {'status':'graded_and_projected','projection':{'automatic':probe.pin(a),'canonical':probe.pin(e)}}

    def test_terminal_requires_actual_process_exit_and_parent_error_join(self):
        with tempfile.TemporaryDirectory() as temp:
            r=self.record(Path(temp));parent=SimpleNamespace(errors={})
            for code in (None,1,-15):
                self.assertFalse(probe.terminal_proof(parent,'a',SimpleNamespace(poll=lambda:code),r,lambda _:True))
            parent.errors['a']={'reason':'inflight_disconnect'}
            self.assertFalse(probe.terminal_proof(parent,'a',SimpleNamespace(poll=lambda:0),r,lambda _:True))

    def test_native_failure_is_a_valid_terminal_grade_and_HTTP_must_match(self):
        with tempfile.TemporaryDirectory() as temp:
            for verdict in (True,False,None):
                with self.subTest(verdict=verdict):
                    r=self.record(Path(temp),verdict);p=SimpleNamespace(errors={});proc=SimpleNamespace(poll=lambda:0)
                    self.assertTrue(probe.terminal_proof(p,'a',proc,r,lambda _:True))
                    self.assertFalse(probe.terminal_proof(p,'a',proc,r,lambda _:False))

    def test_stale_grade_pin_is_not_terminal_proof(self):
        with tempfile.TemporaryDirectory() as temp:
            r=self.record(Path(temp));Path(r['projection']['canonical']['path']).write_text('{}')
            with self.assertRaises(ValueError):probe.terminal_proof(SimpleNamespace(errors={}), 'a',SimpleNamespace(poll=lambda:0),r,lambda _:True)

class CleanupTests(unittest.TestCase):
    def test_terminate_timeout_escalates_to_kill(self):
        from unittest.mock import Mock,patch
        process=Mock();process.poll.side_effect=[None,-9]
        process.wait.side_effect=[probe.subprocess.TimeoutExpired('owned',.01),probe.subprocess.TimeoutExpired('owned',.01),-9]
        with patch.object(probe,'remember_descendants',return_value={}),patch.object(probe,'start_ticks',return_value='owned'):
            process._owned_root_start='owned';probe.stop_process(process,timeout=.01)
        process.terminate.assert_called_once();process.kill.assert_called_once()
        self.assertEqual(process.wait.call_count,3)

    def test_cleanup_continues_after_unjoinable_child_or_service(self):
        from unittest.mock import Mock,patch
        process=Mock();process.poll.return_value=None;process.wait.side_effect=probe.subprocess.TimeoutExpired('owned',.01)
        service=Mock();service.poll.return_value=0
        poller,http,thread,sock,parent,controller,drain=(Mock() for _ in range(7));thread.is_alive.return_value=False
        with patch.object(probe,'remember_descendants',return_value={}),patch.object(probe,'start_ticks',return_value='owned'):
            process._owned_root_start='owned'
            errors=probe.cleanup_resources({'a':process},service,poller,http,thread,{'a':(None,sock)},parent,controller,drain)
        self.assertEqual([e['resource'] for e in errors],['a'])
        poller.close.assert_called_once();http.shutdown.assert_called_once();http.server_close.assert_called_once()
        sock.close.assert_called_once();parent.close.assert_called_once();controller.close.assert_called_once();drain.assert_called_once()

class TerminationTests(unittest.TestCase):
    def test_termination_is_not_swallowed_as_optional_ordinary_error(self):
        self.assertFalse(issubclass(probe.NativeProbeTermination,Exception))
        from unittest.mock import patch
        with patch.object(probe.signal,'signal') as handler:
            with self.assertRaises(probe.NativeProbeTermination):probe.terminate_probe()
            self.assertEqual(handler.call_count,2)

class EarlyResourceTests(unittest.TestCase):
    def test_one_early_close_failure_does_not_skip_other_owned_resources(self):
        from unittest.mock import Mock
        a,b,parent,controller=(Mock() for _ in range(4));a.close.side_effect=OSError('broken socket')
        errors=probe.cleanup_early_resources({'a':(a,b)},parent,controller)
        self.assertEqual(len(errors),1)
        b.close.assert_called_once();parent.close.assert_called_once();controller.close.assert_called_once()

    def test_missing_or_nonboolean_canonical_outcome_is_not_terminal(self):
        with tempfile.TemporaryDirectory() as temp:
            for value in ({'technical_error':None},{'technical_error':None,'task_completed':1}):
                a=Path(temp)/'automatic.json';e=Path(temp)/'evaluation.json'
                a.write_text(json.dumps({'status':'graded'}));e.write_text(json.dumps(value))
                r={'status':'graded_and_projected','projection':{'automatic':probe.pin(a),'canonical':probe.pin(e)}}
                self.assertFalse(probe.terminal_proof(SimpleNamespace(errors={}), 'a',SimpleNamespace(poll=lambda:0),r,lambda _:True))

class ProcessIdentityTests(unittest.TestCase):
    def test_reaped_root_never_enumerates_foreign_reused_pid(self):
        from unittest.mock import Mock,patch
        proc=Mock();proc.poll.return_value=0;proc._owned_descendants={}
        with patch('psutil.Process',side_effect=AssertionError('reaped PID must not be queried')):
            probe.stop_process(proc,timeout=.01)
        proc.terminate.assert_not_called();proc.kill.assert_not_called()

    def test_root_identity_mismatch_never_collects_descendants(self):
        from unittest.mock import Mock,patch
        proc=Mock();proc.poll.return_value=None;proc._owned_descendants={};proc._owned_root_start='old'
        with patch.object(probe,'start_ticks',return_value='new'),patch('psutil.Process',side_effect=AssertionError('foreign root')):
            self.assertEqual(probe.remember_descendants(proc),{})

    def test_native_child_already_unwinding_gets_grace_without_signal(self):
        from unittest.mock import Mock,patch
        proc=Mock();proc.poll.return_value=None
        with patch.object(probe,'remember_descendants',return_value={}):probe.stop_process(proc,timeout=.01)
        proc.wait.assert_called_once_with(timeout=.01);proc.terminate.assert_not_called();proc.kill.assert_not_called()

if __name__=='__main__':unittest.main()
