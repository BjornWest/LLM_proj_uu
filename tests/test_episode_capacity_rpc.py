"""Zero-provider composition controls against Training's real controller."""
from contextlib import contextmanager
import importlib.util
import multiprocessing
from pathlib import Path
import socket
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    import sys
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


rpc = module('capacity_rpc_test_subject', ROOT/'scripts/episode_capacity_rpc.py')
control = module('capacity_control_test_subject', ROOT/'training/browser_training/capacity_control.py')
# Exact unchanged Git blob2ec98d0:scripts/episode_queue.py, test-only fixture.
queue = module('capacity_queue_test_subject', ROOT/'tests/fixtures/episode_capacity_queue.py')


def healthy(controller, **kw):
    controller.observe(control.CapacitySnapshot(time.monotonic(), kw.get('waiting', 0),
        0, kw.get('running', 0), kw.get('kv', .1), 0))


def wait_for(test, predicate, seconds=3):
    deadline = time.monotonic()+seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.005)
    test.fail('Expected condition did not become true')


@contextmanager
def setup(cases=('run:a', 'run:b'), *, generation_cap=1, active_cap=2):
    controller = control.EpisodeCapacityController(control.ParkingConfig(
        max_active_episodes=active_cap, max_generation_requests=generation_cap,
        fresh_seconds=60))
    healthy(controller)
    pairs = {case: socket.socketpair() for case in cases}
    parent = rpc.CapacityParent(controller, {c:p[0] for c,p in pairs.items()},
        deadline=time.monotonic()+20).start()
    clients = {c:rpc.CapacityClient(p[1], deadline=time.monotonic()+20) for c,p in pairs.items()}
    try:
        yield controller, parent, clients
    finally:
        for client in clients.values():
            client.close()
        parent.close()
        controller.close()


class FakeBackend:
    model = 'cpu-test-not-a-model'
    def __init__(self, callback=lambda _: 'ok'):
        self.callback = callback
        self.closed = False
    def complete(self, messages):
        return self.callback(messages)
    def close(self):
        self.closed = True


def child_complete(sock, address, pipe):
    # An actual separate process makes buffered HTTP requests to a synthetic
    # local service. No browser, provider, inference, GPU or credentials.
    from urllib.request import urlopen
    client = rpc.CapacityClient(sock, deadline=time.monotonic()+15)
    def http_complete(messages):
        with urlopen(address, timeout=3) as response:
            return response.read().decode()
    try:
        for phase in ('policy', 'formatter'):
            backend = rpc.CapacityBackend(FakeBackend(http_complete), client,
                phase=phase, guard=lambda:None, freshness_guard=lambda:None,
                buffered_completion=True)
            pipe.send((phase, backend.complete([])))
    finally:
        client.close()
        pipe.close()


def child_park_or_hold(sock, pipe):
    client=rpc.CapacityClient(sock,deadline=time.monotonic()+15)
    pipe.send('acquiring')
    with client.turn('policy'):
        pipe.send('holding')
        time.sleep(15)


class CapacityRPCTests(unittest.TestCase):
    def test_warm_case_has_no_controller_row_and_cannot_dispatch(self):
        with setup() as (controller, parent, clients):
            self.assertEqual(controller.status()['episodes'], {})
            with self.assertRaises(rpc.CapacityChannelError):
                with clients['run:a'].turn('policy'):
                    self.fail('Warm dispatch allowed')
            self.assertEqual(controller.status()['episodes'], {})

    def test_blocked_acquire_does_not_block_another_release(self):
        with setup() as (controller, parent, clients):
            for case in clients: parent.activate(case)
            entered = threading.Event()
            def second():
                with clients['run:b'].turn('formatter'): entered.set()
            with clients['run:a'].turn('policy'):
                thread = threading.Thread(target=second)
                thread.start()
                wait_for(self, lambda:controller.status()['episodes']['run:b']['waiting'])
                self.assertFalse(entered.is_set())
            thread.join(3)
            self.assertFalse(thread.is_alive())
            self.assertTrue(entered.is_set())

    def test_both_phases_share_identity_and_sequence(self):
        with setup() as (controller, parent, clients):
            parent.activate('run:a')
            with clients['run:a'].turn('policy') as first: pass
            with clients['run:a'].turn('formatter') as second: pass
            self.assertEqual((first, second), ('run:a:policy:1', 'run:a:formatter:2'))
            self.assertEqual(controller.status()['episodes']['run:a']['turns'], 2)

    def test_backend_release_on_http_parse_and_timeout_errors(self):
        for error in (OSError('network'), ValueError('response parse'), TimeoutError('request')):
            with self.subTest(error=type(error).__name__), setup() as (controller, parent, clients):
                parent.activate('run:a')
                def fail(_): raise error
                backend = rpc.CapacityBackend(FakeBackend(fail), clients['run:a'],
                    phase='policy', guard=lambda:None, freshness_guard=lambda:None,
                    buffered_completion=True)
                with self.assertRaises(type(error)): backend.complete([])
                self.assertIsNone(controller.status()['episodes']['run:a']['request_id'])
                self.assertFalse(controller.status()['episodes']['run:a']['done'])

    def test_post_wait_source_and_freshness_checks_before_dispatch(self):
        with setup() as (controller, parent, clients):
            parent.activate('run:a');parent.activate('run:b')
            calls = []
            stale = threading.Event()
            failures = []
            def freshness():
                if stale.is_set(): raise ValueError('Observation changed while parked')
            backend = rpc.CapacityBackend(FakeBackend(lambda _:calls.append('dispatch')),
                clients['run:b'], phase='policy', guard=lambda:calls.append('guard'),
                freshness_guard=freshness, buffered_completion=True)
            def second():
                try:backend.complete([])
                except ValueError as e:failures.append(str(e))
            with clients['run:a'].turn('policy'):
                thread = threading.Thread(target=second);thread.start()
                wait_for(self, lambda:controller.status()['episodes']['run:b']['waiting'])
                stale.set()
            thread.join(3)
            self.assertEqual(calls, ['guard', 'guard'])
            self.assertEqual(failures, ['Observation changed while parked'])
            self.assertIsNone(controller.status()['episodes']['run:b']['request_id'])

    def test_dead_child_preserves_permit_until_verified_cleanup(self):
        with setup() as (controller, parent, clients):
            parent.activate('run:a')
            c = clients['run:a']
            c.sequence = 1
            reply = c._exchange({'type':'acquire','phase':'policy','sequence':1})
            c.close()
            wait_for(self, lambda:controller.status()['episodes']['run:a']['cancelled'])
            self.assertEqual(controller.status()['episodes']['run:a']['request_id'], reply['request_id'])
            with self.assertRaises(rpc.CapacityChannelError):
                parent.finish_after_cleanup('run:a', verify_cleanup=lambda:False, record_terminal=lambda:True)
            self.assertIsNotNone(controller.status()['episodes']['run:a']['request_id'])
            parent.finish_after_cleanup('run:a', verify_cleanup=lambda:True, record_terminal=lambda:True)
            self.assertTrue(controller.status()['episodes']['run:a']['done'])
            self.assertIsNone(controller.status()['episodes']['run:a']['request_id'])

    def test_terminal_grading_failure_can_be_recorded_but_not_omitted(self):
        with setup() as (controller, parent, clients):
            parent.activate('run:a')
            with self.assertRaises(rpc.CapacityChannelError):
                parent.finish_after_cleanup('run:a', verify_cleanup=lambda:True, record_terminal=lambda:None)
            self.assertFalse(controller.status()['episodes']['run:a']['done'])
            parent.finish_after_cleanup('run:a', verify_cleanup=lambda:True, record_terminal=lambda:True)
            with self.assertRaises(ValueError):
                parent.finish_after_cleanup('run:a', verify_cleanup=lambda:True, record_terminal=lambda:True)

    def test_cancellation_wakes_parked_request(self):
        with setup() as (controller, parent, clients):
            parent.activate('run:a');parent.activate('run:b')
            errors = []
            def second():
                try:
                    with clients['run:b'].turn('policy'): self.fail('Cancelled dispatch')
                except Exception as e: errors.append(type(e).__name__)
            with clients['run:a'].turn('policy'):
                thread=threading.Thread(target=second);thread.start()
                wait_for(self, lambda:controller.status()['episodes']['run:b']['waiting'])
                parent.cancel('run:b');thread.join(3)
                self.assertFalse(thread.is_alive())
            self.assertTrue(errors)
            self.assertIsNone(controller.status()['episodes']['run:b']['request_id'])

    def test_cancelled_but_uncleaned_case_counts_against_active_cap(self):
        with setup(('run:a','run:b','run:warm'), active_cap=2) as (controller,parent,clients):
            parent.activate('run:a');parent.activate('run:b');parent.cancel('run:a')
            with self.assertRaises(ValueError):parent.activate('run:warm')
            parent.finish_after_cleanup('run:a', verify_cleanup=lambda:True, record_terminal=lambda:True)
            parent.activate('run:warm')
            self.assertFalse(controller.status()['episodes']['run:warm']['done'])

    def test_child_cannot_release_other_case_permit(self):
        with setup() as (controller,parent,clients):
            parent.activate('run:a');parent.activate('run:b')
            with clients['run:a'].turn('policy') as ident:
                with self.assertRaises(rpc.CapacityChannelError):
                    clients['run:b']._exchange({'type':'release','request_id':ident})
                self.assertEqual(controller.status()['episodes']['run:a']['request_id'], ident)

    def test_duplicate_sequence_and_unknown_operation_rejected(self):
        for frame in ({'type':'acquire','phase':'policy','sequence':0}, {'type':'finish'}):
            with self.subTest(frame=frame), setup() as (controller,parent,clients):
                parent.activate('run:a')
                with self.assertRaises(rpc.CapacityChannelError):clients['run:a']._exchange(frame)

    def test_stale_metrics_fail_closed_no_synthetic_readiness(self):
        with setup() as (controller,parent,clients):
            parent.activate('run:a')
            controller.telemetry = None
            parent.deadline = time.monotonic()+.05
            with self.assertRaises(rpc.CapacityChannelError):
                with clients['run:a'].turn('policy'):self.fail('No telemetry dispatch')
            self.assertIsNone(controller.status()['episodes']['run:a']['request_id'])

    def test_close_retains_inflight_ownership(self):
        with setup() as (controller,parent,clients):
            parent.activate('run:a')
            clients['run:a']._exchange({'type':'acquire','phase':'policy','sequence':1})
            parent.close()
            self.assertIsNotNone(controller.status()['episodes']['run:a']['request_id'])
            self.assertFalse(controller.status()['episodes']['run:a']['done'])

    def test_real_child_killed_while_waiting_never_gets_phantom_permit(self):
        with setup(('run:a','run:b','run:c'),active_cap=3) as (controller,parent,clients):
            for c in clients:parent.activate(c)
            context=multiprocessing.get_context('spawn');receive,send=context.Pipe(duplex=False)
            process=context.Process(target=child_park_or_hold,args=(clients['run:b'].connection,send))
            try:
                with clients['run:a'].turn('policy'):
                    process.start();send.close();clients['run:b'].close()
                    self.assertTrue(receive.poll(3));self.assertEqual(receive.recv(),'acquiring')
                    wait_for(self,lambda:controller.status()['episodes']['run:b']['waiting'])
                    process.kill();process.join(3)
                    wait_for(self,lambda:controller.status()['episodes']['run:b']['cancelled'])
                with clients['run:c'].turn('policy'):pass
                row=controller.status()['episodes']['run:b']
                self.assertEqual(row['turns'],0);self.assertIsNone(row['request_id'])
                parent.finish_after_cleanup('run:b',verify_cleanup=lambda:process.exitcode is not None,
                    record_terminal=lambda:True)
            finally:
                if process.is_alive():process.kill();process.join(3)
                receive.close()

    def test_real_child_killed_after_grant_keeps_permit_for_cleanup(self):
        with setup() as (controller,parent,clients):
            parent.activate('run:b')
            context=multiprocessing.get_context('spawn');receive,send=context.Pipe(duplex=False)
            process=context.Process(target=child_park_or_hold,args=(clients['run:b'].connection,send))
            try:
                process.start();send.close();clients['run:b'].close()
                self.assertTrue(receive.poll(3));self.assertEqual(receive.recv(),'acquiring')
                self.assertTrue(receive.poll(3));self.assertEqual(receive.recv(),'holding')
                process.kill();process.join(3)
                wait_for(self,lambda:controller.status()['episodes']['run:b']['cancelled'])
                self.assertIsNotNone(controller.status()['episodes']['run:b']['request_id'])
                parent.finish_after_cleanup('run:b',verify_cleanup=lambda:process.exitcode is not None,
                    record_terminal=lambda:True)
                self.assertIsNone(controller.status()['episodes']['run:b']['request_id'])
            finally:
                if process.is_alive():process.kill();process.join(3)
                receive.close()

    def test_start_failure_is_clean_and_cannot_activate(self):
        from unittest.mock import patch
        controller=control.EpisodeCapacityController();a,b=socket.socketpair()
        parent=rpc.CapacityParent(controller,{'run:a':a},deadline=time.monotonic()+10)
        try:
            with patch.object(threading.Thread,'start',side_effect=RuntimeError('PID limit')):
                with self.assertRaises(RuntimeError):parent.start()
            parent.close()
            with self.assertRaises(ValueError):parent.activate('run:a')
            self.assertEqual(parent.threads,{})
        finally:b.close();controller.close()

    def test_dead_or_finished_unactivated_case_cannot_activate(self):
        with setup() as (_,parent,clients):
            clients['run:a'].close()
            wait_for(self,lambda:'run:a'in parent.ended)
            with self.assertRaises(ValueError):parent.activate('run:a')
            parent.finish_after_cleanup('run:b',verify_cleanup=lambda:True,record_terminal=lambda:True)
            with self.assertRaises(ValueError):parent.activate('run:b')

    def test_normal_finish_does_not_log_cancellation_or_repeat_callbacks(self):
        with setup() as (controller,parent,clients):
            parent.activate('run:a')
            with clients['run:a'].turn('policy'):pass
            clients['run:a'].close()
            wait_for(self,lambda:'run:a'in parent.ended)
            self.assertFalse(controller.status()['episodes']['run:a']['cancelled'])
            calls=[]
            parent.finish_after_cleanup('run:a',verify_cleanup=lambda:True,
                record_terminal=lambda:(calls.append('persist') or True))
            with self.assertRaises(ValueError):
                parent.finish_after_cleanup('run:a',verify_cleanup=lambda:True,
                    record_terminal=lambda:(calls.append('persist') or True))
            self.assertEqual(calls,['persist'])
            self.assertFalse(controller.status()['episodes']['run:a']['cancelled'])

    def test_high_fd_parent_socket_is_valid_when_contended(self):
        import fcntl
        controller=control.EpisodeCapacityController(control.ParkingConfig(
            max_active_episodes=2,max_generation_requests=1,fresh_seconds=60))
        healthy(controller);pairs={c:socket.socketpair()for c in ('a','b')}
        old=pairs['b'][0];fd=fcntl.fcntl(old.fileno(),fcntl.F_DUPFD_CLOEXEC,1100)
        high=socket.socket(fileno=fd);pairs['b']=(high,pairs['b'][1]);old.close()
        parent=rpc.CapacityParent(controller,{c:p[0]for c,p in pairs.items()},deadline=time.monotonic()+10).start()
        clients={c:rpc.CapacityClient(p[1],deadline=time.monotonic()+10)for c,p in pairs.items()}
        try:
            for c in pairs:parent.activate(c)
            entered=threading.Event();errors=[]
            def second():
                try:
                    with clients['b'].turn('policy'):entered.set()
                except Exception as e:errors.append(e)
            with clients['a'].turn('policy'):
                thread=threading.Thread(target=second);thread.start()
                wait_for(self,lambda:controller.status()['episodes']['b']['waiting'])
                self.assertFalse(entered.is_set())
            thread.join(3);self.assertFalse(thread.is_alive())
            self.assertEqual(errors,[]);self.assertTrue(entered.is_set())
            with clients['b'].turn('formatter'):pass  # Also uncontended fd>1023.
        finally:
            for c in clients.values():c.close()
            parent.close();controller.close()

    def test_post_grant_cancel_race_cannot_deliver_a_permit(self):
        with setup() as (controller,parent,clients):
            parent.activate('run:a');original=controller.acquire_turn
            def grant_then_cancel(*args,**kwargs):
                result=original(*args,**kwargs)
                parent.stops['run:a'].set()
                return result
            controller.acquire_turn=grant_then_cancel
            with self.assertRaises(rpc.CapacityChannelError):
                with clients['run:a'].turn('policy'):self.fail('Unsent raced grant escaped')
            self.assertIsNone(controller.status()['episodes']['run:a']['request_id'])

    def test_concurrent_finishes_invoke_terminal_callback_only_once(self):
        with setup() as (_,parent,clients):
            parent.activate('run:a');clients['run:a'].close()
            entered=threading.Event();unblock=threading.Event();calls=[];errors=[]
            def record():
                calls.append('record');entered.set();unblock.wait(3);return True
            def finish():
                try:parent.finish_after_cleanup('run:a',verify_cleanup=lambda:True,record_terminal=record)
                except Exception as e:errors.append(type(e).__name__)
            first=threading.Thread(target=finish);first.start();self.assertTrue(entered.wait(3))
            second=threading.Thread(target=finish);second.start();second.join(.2)
            try:
                self.assertFalse(second.is_alive());self.assertEqual(errors,['ValueError'])
            finally:
                unblock.set();first.join(3);second.join(3)
            self.assertEqual(calls,['record'])

    def test_real_queue_runner_callback_registers_and_translates_cancel(self):
        from types import SimpleNamespace
        with setup() as (controller,parent,clients):
            observed=[]
            def run_case(case,admission):
                wrapped=rpc.ActiveCapacityAdmission(admission,parent,'run:a')
                wrapped.runner_callback(RuntimeError)(SimpleNamespace(
                    episode_id='a',directory='/synthetic/a',ready_monotonic=time.monotonic()))
                observed.append('run:a'in controller.status()['episodes'])
                with clients['run:a'].turn('policy'):pass
                clients['run:a'].close()
                parent.finish_after_cleanup('run:a',verify_cleanup=lambda:True,record_terminal=lambda:True)
            result=queue.run_ordered_suite({'a':'a'},run_case,max_concurrent_episodes=1,prewarm_count=0)
            self.assertEqual(result['cases']['a']['status'],'completed')
            self.assertEqual(observed,[True])
        with setup() as (controller,parent,_):
            stop=threading.Event();stop.set()
            q=queue._Queue({'a':'a'},lambda *_:None,queue.QueueSettings(1),stop)
            inner=queue.EpisodeAdmission(q,'a');wrapped=rpc.ActiveCapacityAdmission(inner,parent,'run:a')
            class NativeCancelled(RuntimeError):pass
            with self.assertRaises(NativeCancelled):wrapped.runner_callback(NativeCancelled)(None)
            self.assertEqual(controller.status()['episodes'],{})

    def test_release_watchdogs_and_interrupts_propagate_with_paid_response_saved(self):
        import signal
        for error in (KeyboardInterrupt, SystemExit, TimeoutError):
            with self.subTest(error=error.__name__):
                a,b=socket.socketpair();done=threading.Event()
                def stalled_parent():
                    try:
                        rpc._receive(a)
                        rpc._send(a,{'type':'permit','request_id':'a:policy:1','acquire_wait_seconds':0})
                        rpc._receive(a);done.wait(3)
                    finally:a.close()
                thread=threading.Thread(target=stalled_parent);thread.start()
                client=rpc.CapacityClient(b,deadline=time.monotonic()+10)
                backend=rpc.CapacityBackend(FakeBackend(lambda _:'paid'),client,
                    phase='policy',guard=lambda:None,freshness_guard=lambda:None,buffered_completion=True)
                previous=signal.getsignal(signal.SIGALRM)
                def interrupt(*_):raise error('Stop now')
                try:
                    signal.signal(signal.SIGALRM,interrupt);signal.setitimer(signal.ITIMER_REAL,.1)
                    with self.assertRaises(error):backend.complete([])
                    self.assertEqual(backend.interrupted_completion,'paid')
                    self.assertTrue(client.broken)
                finally:
                    signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,previous)
                    done.set();client.close();thread.join(3)

    def test_release_after_generation_deadline_preserves_paid_response(self):
        with setup() as (controller,parent,clients):
            parent.activate('run:a');clients['run:a'].deadline=time.monotonic()+.1
            parent.deadline=clients['run:a'].deadline
            def paid(_):time.sleep(.15);return 'paid response'
            backend=rpc.CapacityBackend(FakeBackend(paid),clients['run:a'],phase='policy',
                guard=lambda:None,freshness_guard=lambda:None,buffered_completion=True)
            self.assertEqual(backend.complete([]),'paid response')
            self.assertIsNone(controller.status()['episodes']['run:a']['request_id'])
            self.assertIsNone(clients['run:a'].infrastructure_error)
            with self.assertRaises(TimeoutError):backend.complete([])

    def test_release_failure_retains_completion_and_original_provider_error(self):
        for fail in (False,True):
            with self.subTest(fail=fail),setup() as (_,parent,clients):
                parent.activate('run:a')
                def paid(_):
                    parent.cancel('run:a')
                    if fail:raise OSError('Provider503')
                    return 'paid response'
                backend=rpc.CapacityBackend(FakeBackend(paid),clients['run:a'],phase='policy',
                    guard=lambda:None,freshness_guard=lambda:None,buffered_completion=True)
                if fail:
                    with self.assertRaisesRegex(OSError,'Provider503') as caught:backend.complete([])
                    self.assertTrue(caught.exception.__notes__)
                else:self.assertEqual(backend.complete([]),'paid response')
                self.assertTrue(clients['run:a'].broken)
                self.assertEqual(clients['run:a'].infrastructure_error['kind'],'capacity_release_failed')
                with self.assertRaises(rpc.CapacityChannelError):backend.complete([])

    def test_parent_reason_and_wait_timing_reach_child(self):
        with setup() as (controller,parent,clients):
            parent.activate('run:a');controller.telemetry=None;parent.deadline=time.monotonic()+.08
            with self.assertRaisesRegex(rpc.CapacityChannelError,'TimeoutError.*Capacity wait timed out'):
                with clients['run:a'].turn('policy'):pass
            self.assertTrue(any(e.get('telemetry_fresh')is False for e in clients['run:a'].events))
        with setup() as (_,parent,clients):
            parent.activate('run:a')
            with clients['run:a'].turn('policy'):pass
            permit=[e for e in clients['run:a'].events if e['kind']=='capacity_permit'][0]
            self.assertGreaterEqual(permit['wait_seconds'],0)

    def test_wrapper_does_not_invent_native_support_or_recurse(self):
        with setup() as (_,_,clients):
            b=rpc.CapacityBackend(FakeBackend(),clients['run:a'],phase='policy',
                guard=lambda:None,freshness_guard=lambda:None,buffered_completion=True)
            self.assertFalse(b.supports_native_tools)
            self.assertFalse(type(b).__dict__.get('supports_native_tools',False))
            with self.assertRaises(AttributeError):getattr(rpc.CapacityBackend.__new__(rpc.CapacityBackend),'missing')

    def test_buffered_backend_and_guard_contract_explicit(self):
        with setup() as (_,_,clients):
            with self.assertRaises(ValueError):
                rpc.CapacityBackend(FakeBackend(), clients['run:a'], phase='policy',
                    guard=lambda:None, freshness_guard=lambda:None, buffered_completion=False)

    def test_actual_admission_returns_before_controller_registration(self):
        with setup() as (controller,parent,_):
            class Admission:
                case_id = 'a'
                def environment_ready(inner,ready):
                    self.assertNotIn('run:a',controller.status()['episodes'])
                def check_active(inner):return 'active'
            adapter=rpc.ActiveCapacityAdmission(Admission(),parent,'run:a',priority=7)
            self.assertEqual(adapter.case_id,'a')
            adapter.environment_ready(object())
            self.assertEqual(controller.status()['episodes']['run:a']['priority'],7)
            self.assertEqual(adapter.check_active(),'active')

    def test_failed_queue_admission_does_not_register(self):
        with setup() as (controller,parent,_):
            class Admission:
                def environment_ready(inner,ready):raise RuntimeError('Queue cancelled')
            adapter=rpc.ActiveCapacityAdmission(Admission(),parent,'run:a')
            with self.assertRaises(RuntimeError):adapter.environment_ready(object())
            self.assertEqual(controller.status()['episodes'],{})

    def test_sticky_park_requires_terminal_completion_and_healthy_metrics(self):
        with setup() as (controller,parent,clients):
            parent.activate('run:a',priority=0);parent.activate('run:b',priority=1)
            for c in clients:
                with clients[c].turn('policy'):pass
            healthy(controller,waiting=1,kv=.95);healthy(controller,waiting=1,kv=.95)
            self.assertTrue(controller.status()['episodes']['run:b']['parked'])
            healthy(controller)
            self.assertTrue(controller.status()['episodes']['run:b']['parked'])
            entered=threading.Event()
            def parked():
                with clients['run:b'].turn('formatter'):entered.set()
            thread=threading.Thread(target=parked);thread.start()
            wait_for(self,lambda:controller.status()['episodes']['run:b']['waiting'])
            self.assertFalse(entered.is_set())
            parent.finish_after_cleanup('run:a',verify_cleanup=lambda:True,record_terminal=lambda:True)
            thread.join(3)
            self.assertFalse(thread.is_alive());self.assertTrue(entered.is_set())
            self.assertFalse(controller.status()['episodes']['run:b']['parked'])

    def test_single_real_HTTP_metrics_poller_supplies_shared_parent(self):
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        reads=[]
        body=('vllm:num_requests_running{model_name="cpu-test",engine="0"} 0\n'
          'vllm:num_requests_waiting{model_name="cpu-test",engine="0"} 0\n'
          'vllm:num_requests_waiting_by_reason{model_name="cpu-test",engine="0",reason="capacity"} 0\n'
          'vllm:num_requests_waiting_by_reason{model_name="cpu-test",engine="0",reason="deferred"} 0\n'
          'vllm:kv_cache_usage_perc{model_name="cpu-test",engine="0"} 0.1\n'
          'vllm:num_preemptions_total{model_name="cpu-test",engine="0"} 0\n').encode()
        class Handler(BaseHTTPRequestHandler):
            protocol_version='HTTP/1.1'
            def log_message(self,*a):pass
            def do_GET(self):
                reads.append(self.path);self.send_response(200)
                self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever);thread.start()
        poller=None
        try:
            with setup() as (controller,parent,clients):
                controller.telemetry=None
                poller=control.SharedMetricsPoller(f'http://127.0.0.1:{server.server_port}/metrics',
                    model='cpu-test',interval=.05,timeout=1,on_snapshot=controller.observe).start()
                wait_for(self,lambda:controller.status()['telemetry_fresh'])
                for case in clients:
                    parent.activate(case)
                    with clients[case].turn('policy'):pass
                self.assertTrue(reads);self.assertEqual(set(reads),{'/metrics'})
                self.assertEqual(controller.status()['telemetry']['capacity_waiting'],0)
        finally:
            if poller:poller.close()
            server.shutdown();server.server_close();thread.join(3)

    def test_real_processes_policy_formatter_http_generation_cap(self):
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        active=peak=0
        lock=threading.Lock()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*a):pass
            def do_GET(self):
                nonlocal active,peak
                with lock:active+=1;peak=max(peak,active)
                try:
                    time.sleep(.05)
                    self.send_response(200);self.end_headers();self.wfile.write(b'cpu-only')
                finally:
                    with lock:active-=1
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever);thread.start()
        children=[]
        try:
            with setup(('run:a','run:b','run:c'), active_cap=3,generation_cap=2) as (controller,parent,clients):
                context=multiprocessing.get_context('spawn')
                for case,client in clients.items():
                    parent.activate(case)
                    receive,send=context.Pipe(duplex=False)
                    process=context.Process(target=child_complete,args=(client.connection,
                        f'http://127.0.0.1:{server.server_port}/synthetic',send))
                    process.start();send.close();children.append((case,process,receive))
                    # Parent MUST close its duplicate of the child's socket;
                    # otherwise a child's death cannot produce EOF upstream.
                    client.close()
                for case,process,pipe in children:
                    self.assertTrue(pipe.poll(10));self.assertEqual(pipe.recv(),('policy','cpu-only'))
                    self.assertTrue(pipe.poll(10));self.assertEqual(pipe.recv(),('formatter','cpu-only'))
                    process.join(5);self.assertEqual(process.exitcode,0);pipe.close()
                    parent.finish_after_cleanup(case,verify_cleanup=lambda p=process:p.exitcode==0,
                        record_terminal=lambda:True)
                self.assertEqual(peak,2)
                self.assertTrue(all(r['done'] for r in controller.status()['episodes'].values()))
        finally:
            for _,process,_ in children:
                if process.is_alive():process.terminate();process.join(3)
            server.shutdown();server.server_close();thread.join(3)


if __name__ == '__main__':unittest.main()
