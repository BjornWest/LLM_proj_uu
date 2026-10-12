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
# Exercise the real queue when composed into a runtime root. The exact reviewed
# fixture is only for isolated controller roots that do not contain that file.
queue_path=ROOT/'scripts/episode_queue.py'
if not queue_path.is_file():queue_path=ROOT/'tests/fixtures/episode_capacity_queue.py'
queue = module('capacity_queue_test_subject', queue_path)


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
            self.assertTrue(controller.status()['episodes']['run:a']['dispatch_retired'])
            calls=[]
            parent.finish_after_cleanup('run:a',verify_cleanup=lambda:True,
                record_terminal=lambda:(calls.append('persist') or True))
            with self.assertRaises(ValueError):
                parent.finish_after_cleanup('run:a',verify_cleanup=lambda:True,
                    record_terminal=lambda:(calls.append('persist') or True))
            self.assertEqual(calls,['persist'])
            self.assertFalse(controller.status()['episodes']['run:a']['cancelled'])

    def test_high_fd_parent_socket_is_valid_when_contended(self):
        import fcntl,resource
        soft,_=resource.getrlimit(resource.RLIMIT_NOFILE)
        if soft < 1102:
            self.skipTest(f'High-fd control needs fd1100; current host soft limit={soft}')
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

    def test_post_grant_retirement_cannot_deliver_unsent_permit(self):
        with setup()as(controller,parent,clients):
            parent.activate('run:a');original=controller.acquire_turn
            def grant_then_retire(*args,**kwargs):
                result=original(*args,**kwargs)
                controller.retire_dispatch('run:a')
                return result
            controller.acquire_turn=grant_then_retire
            with self.assertRaisesRegex(rpc.CapacityChannelError,'retired before permit'):
                with clients['run:a'].turn('policy'):self.fail('Retired unsent grant escaped')
            wait_for(self,lambda:'run:a'in parent.ended)
            row=controller.status()['episodes']['run:a']
            self.assertIsNone(row['request_id']);self.assertFalse(row['cancelled'])
            self.assertFalse(row['done'])

    def test_retired_row_does_not_hide_malformed_frame_or_inflight_eof(self):
        for holding in (False,True):
            with self.subTest(holding=holding),setup()as(controller,parent,clients):
                parent.activate('run:a')
                if holding:
                    clients['run:a']._exchange({'type':'acquire','phase':'policy','sequence':1})
                controller.retire_dispatch('run:a')
                if holding:clients['run:a'].close()
                else:
                    with self.assertRaisesRegex(rpc.CapacityChannelError,'Unknown capacity operation'):
                        clients['run:a']._exchange({'type':'unknown'})
                wait_for(self,lambda:'run:a'in parent.ended)
                row=controller.status()['episodes']['run:a']
                self.assertTrue(row['cancelled']);self.assertFalse(row['done'])
                self.assertEqual(parent.errors['run:a']['reason'],
                    'inflight_disconnect' if holding else 'channel_failure')
                if holding:self.assertIsNotNone(row['request_id'])

    def test_ended_is_not_published_before_retirement(self):
        with setup()as(controller,parent,clients):
            parent.activate('run:a');entered=threading.Event();unblock=threading.Event()
            original=controller.retire_dispatch
            def slow_retire(case):
                entered.set()
                if not unblock.wait(2):raise AssertionError('Retirement not unblocked')
                return original(case)
            controller.retire_dispatch=slow_retire
            try:
                clients['run:a'].close();self.assertTrue(entered.wait(2))
                self.assertNotIn('run:a',parent.ended)
            finally:unblock.set()
            wait_for(self,lambda:'run:a'in parent.ended)
            self.assertTrue(controller.status()['episodes']['run:a']['dispatch_retired'])

    def test_warm_eof_ending_marker_prevents_late_activation(self):
        controller=control.EpisodeCapacityController(control.ParkingConfig(
            max_active_episodes=1,max_generation_requests=1,fresh_seconds=60))
        healthy(controller);a,b=socket.socketpair();closing=threading.Event();unblock=threading.Event()
        class DelayedClose:
            def __getattr__(self,name):return getattr(a,name)
            def close(self):closing.set();unblock.wait(3);a.close()
        parent=rpc.CapacityParent(controller,{'a':DelayedClose()},deadline=time.monotonic()+5).start()
        try:
            b.close();self.assertTrue(closing.wait(2))
            self.assertIn('a',parent.ending);self.assertNotIn('a',parent.ended)
            with self.assertRaises(ValueError):parent.activate('a')
            self.assertEqual(controller.status()['episodes'],{})
        finally:unblock.set();parent.close();controller.close()

    def test_supplied_stop_event_identity_and_constructor_validation(self):
        controller=control.EpisodeCapacityController(control.ParkingConfig(
            max_active_episodes=1,max_generation_requests=1,fresh_seconds=60))
        a,b=socket.socketpair();event=threading.Event()
        try:
            parent=rpc.CapacityParent(controller,{'a':a},deadline=time.monotonic()+5,suite_stop_event=event)
            self.assertIs(parent.suite_stop_event,event)
            event.set()
            with self.assertRaises(rpc.CapacitySuiteStopped):parent.activate('a')
            for value in ('x',True,object()):
                with self.subTest(value=type(value).__name__),self.assertRaises(ValueError):
                    rpc.CapacityParent(controller,{'a':a},deadline=time.monotonic()+5,suite_stop_event=value)
        finally:a.close();b.close();controller.close()

    def test_runner_callback_translates_stop_during_activation(self):
        with setup()as(controller,parent,_):
            class NativeCancelled(RuntimeError):pass
            def run_case(case,admission):
                original=admission.environment_ready
                def ready(value=None):
                    original(value);parent.suite_stop_event.set()
                admission.environment_ready=ready
                rpc.ActiveCapacityAdmission(admission,parent,'run:a').runner_callback(NativeCancelled)(None)
            result=queue.run_ordered_suite({'a':'a'},run_case,max_concurrent_episodes=1,
                prewarm_count=0,stop_event=parent.suite_stop_event)
            self.assertTrue(result['cancelled']);self.assertEqual(result['cases']['a']['status'],'cancelled')
            self.assertEqual(controller.status()['episodes'],{})

    def test_controller_namespace_wrappers_and_missing_api_fail_closed(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from functools import partial,wraps
        controller=control.EpisodeCapacityController(control.ParkingConfig(
            max_active_episodes=1,max_generation_requests=1,fresh_seconds=60))
        a,b=socket.socketpair()
        @wraps(controller.acquire_turn)
        def delegated(*args,**kwargs):return controller.acquire_turn(*args,**kwargs)
        try:
            for acquire in (None,lambda *a,**k:None,delegated,partial(controller.acquire_turn)):
                wrapper=SimpleNamespace(retire_dispatch=controller.retire_dispatch)
                if acquire is not None:wrapper.acquire_turn=acquire
                with self.subTest(acquire=type(acquire).__name__),self.assertRaises(ValueError):
                    rpc.CapacityParent(wrapper,{'a':a},deadline=time.monotonic()+5)
            with patch.dict(control.EpisodeCapacityController.acquire_turn.__globals__,{'TurnCancelled':None}):
                with self.assertRaisesRegex(ValueError,'TurnCancelled namespace'):
                    rpc.CapacityParent(controller,{'a':a},deadline=time.monotonic()+5)
            foreign={'__name__':'unqualified_controller_wrapper','controller':controller,
                'EpisodeCapacityController':control.EpisodeCapacityController}
            exec('class TurnCancelled(RuntimeError): pass\n'
                 'class Wrapper:\n'
                 ' def acquire_turn(self,*args,**kwargs): return controller.acquire_turn(*args,**kwargs)\n'
                 ' def retire_dispatch(self,*args,**kwargs): return controller.retire_dispatch(*args,**kwargs)\n',foreign)
            with self.assertRaisesRegex(ValueError,'Direct reviewed controller'):
                rpc.CapacityParent(foreign['Wrapper'](),{'a':a},deadline=time.monotonic()+5)
        finally:a.close();b.close();controller.close()

    def test_wake_conversion_requires_cancel_type_and_uncancelled_row(self):
        for cancelled in (False,True):
            with self.subTest(cancelled=cancelled),setup()as(controller,parent,clients):
                parent.activate('run:a')
                def failing_acquire(*args,**kwargs):
                    controller.retire_dispatch('run:a')
                    if cancelled:
                        controller.cancel_episode('run:a');raise control.TurnCancelled('Explicit cancellation')
                    raise RuntimeError('Actual controller defect')
                controller.acquire_turn=failing_acquire
                with self.assertRaises(rpc.CapacityParentError)as caught:
                    with clients['run:a'].turn('policy'):self.fail('Fault admitted')
                self.assertEqual(caught.exception.parent_error_type,'TurnCancelled'if cancelled else'RuntimeError')
                self.assertEqual(caught.exception.parent_reason,'explicit_cancellation'if cancelled else'channel_failure')
                wait_for(self,lambda:'run:a'in parent.ended)
                self.assertTrue(controller.status()['episodes']['run:a']['cancelled'])

    def test_direct_controller_cancel_after_grant_prevents_permit(self):
        with setup()as(controller,parent,clients):
            parent.activate('run:a');original=controller.acquire_turn
            def grant_then_cancel(*args,**kwargs):
                result=original(*args,**kwargs);controller.cancel_episode('run:a');return result
            controller.acquire_turn=grant_then_cancel
            with self.assertRaises(rpc.CapacityParentError):
                with clients['run:a'].turn('policy'):self.fail('Cancelled grant escaped')
            self.assertIsNone(controller.status()['episodes']['run:a']['request_id'])

    def test_parent_reason_reaches_client_structured_event(self):
        with setup()as(controller,parent,clients):
            parent.activate('run:a');controller.telemetry=None;parent.deadline=time.monotonic()+.06
            with self.assertRaises(rpc.CapacityParentError)as caught:
                with clients['run:a'].turn('policy'):self.fail('Stale grant escaped')
            self.assertEqual(caught.exception.parent_reason,'rental_deadline')
            self.assertEqual(caught.exception.parent_error_type,'TimeoutError')
            rows=[r for r in clients['run:a'].events if r['kind']=='capacity_parent_error']
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]['parent_reason'],'rental_deadline')

    def test_early_caller_failure_aborts_queue_without_releasing_permit(self):
        with setup(('run:a','run:b'),active_cap=1)as(controller,parent,clients):
            def run_case(case,admission):
                try:
                    rpc.ActiveCapacityAdmission(admission,parent,'run:'+case).environment_ready()
                    clients['run:'+case]._exchange({'type':'acquire','phase':'policy','sequence':1})
                    raise RuntimeError('Caller exited before final verification')
                except BaseException as exc:
                    parent.abort_after_failure('run:'+case,exc,infrastructure=True);raise
            result=queue.run_ordered_suite({'a':'a','b':'b'},run_case,max_concurrent_episodes=1,
                prewarm_count=0,stop_event=parent.suite_stop_event)
            self.assertEqual(result['cases']['b']['status'],'not_started');self.assertTrue(result['cancelled'])
            row=controller.status()['episodes']['run:a']
            self.assertTrue(row['dispatch_retired']);self.assertFalse(row['done'])
            self.assertIsNotNone(row['request_id'])
            self.assertFalse(row['cancelled'])
            self.assertEqual(parent.stop_cause['case'],'run:a')

    def test_secondary_aborts_preserve_first_infrastructure_cause_and_root(self):
        with setup()as(controller,parent,clients):
            for c in clients:parent.activate(c)
            permit=clients['run:a']._exchange({'type':'acquire','phase':'policy','sequence':1})
            first=RuntimeError('Original infrastructure failure')
            parent.abort_after_failure('run:a',first,infrastructure=True)
            parent.abort_after_failure('run:b',RuntimeError('Sibling cancelled'),infrastructure=False)
            parent.abort_after_failure('run:a',OSError('Later cleanup failure'),infrastructure=True)
            wait_for(self,lambda:'run:a'in parent.ended)
            rows=controller.status()['episodes']
            self.assertFalse(rows['run:a']['cancelled']);self.assertTrue(rows['run:b']['cancelled'])
            self.assertEqual(rows['run:a']['request_id'],permit['request_id'])
            self.assertEqual(parent.stop_cause['message'],str(first))
            self.assertEqual(parent.cleanup_failures,{}) # Abort classification is not final-verification evidence.
            self.assertEqual(len(parent.secondary_exits),2)
            self.assertEqual(parent.errors['run:a']['reason'],'infrastructure_abort')

    def test_user_cancellation_is_not_an_infrastructure_cleanup_failure(self):
        with setup()as(controller,parent,_):
            for c in ('run:a','run:b'):parent.activate(c)
            parent.abort_after_failure('run:a',RuntimeError('User stopped suite'),infrastructure=False)
            parent.abort_after_failure('run:b',RuntimeError('Secondary cancelled exit'),infrastructure=False)
            self.assertFalse(parent.stop_cause['infrastructure'])
            self.assertEqual(parent.cleanup_failures,{})
            self.assertEqual(len(parent.secondary_exits),1)
            self.assertTrue(all(r['cancelled']for r in controller.status()['episodes'].values()))

    def test_parent_shutdown_does_not_report_sibling_as_peer_disconnect(self):
        with setup(generation_cap=2)as(controller,parent,clients):
            for c in clients:parent.activate(c)
            permit=clients['run:b']._exchange({'type':'acquire','phase':'policy','sequence':1})
            parent.abort_after_failure('run:a',RuntimeError('Root failure'),infrastructure=True)
            wait_for(self,lambda:'run:b'in parent.ended)
            self.assertEqual(parent.errors['run:b']['reason'],'cohort_abort')
            self.assertIn('Parent stopped channel',parent.errors['run:b']['message'])
            self.assertEqual(controller.status()['episodes']['run:b']['request_id'],permit['request_id'])

    def test_abort_does_not_cancel_a_sibling_already_in_final_verification(self):
        with setup()as(controller,parent,_):
            for c in ('run:a','run:b'):parent.activate(c)
            entered=threading.Event();unblock=threading.Event();errors=[]
            def verify():entered.set();unblock.wait(3);return True
            def finish():
                try:parent.finish_after_cleanup('run:b',verify_cleanup=verify,record_terminal=lambda:True)
                except BaseException as exc:errors.append(exc)
            thread=threading.Thread(target=finish);thread.start()
            try:
                self.assertTrue(entered.wait(2))
                parent.abort_after_failure('run:a',RuntimeError('Root failure'),infrastructure=True)
                self.assertFalse(controller.status()['episodes']['run:b']['cancelled'])
            finally:unblock.set();thread.join(3)
            self.assertEqual(errors,[])
            self.assertTrue(controller.status()['episodes']['run:b']['done'])
            self.assertFalse(controller.status()['episodes']['run:b']['cancelled'])

    def test_parent_error_pickle_copy_and_strict_frame_validation(self):
        import pickle,copy
        reply=dict(type='error',error_type='TimeoutError',message='Capacity wait timed out',
            reason='rental_deadline',telemetry_fresh=False)
        original=rpc.CapacityParentError(reply)
        original.add_note('Paid response evidence retained')
        for restored in (pickle.loads(pickle.dumps(original)),copy.copy(original)):
            self.assertEqual(str(restored),str(original))
            self.assertEqual(restored.parent_reason,original.parent_reason)
            self.assertEqual(restored.parent_error_type,original.parent_error_type)
            self.assertEqual(restored.__notes__,original.__notes__)
        for bad in (dict(reply,telemetry_fresh='no'),dict(reply,reason='unknown'),
                    {k:v for k,v in reply.items()if k!='reason'}):
            a,b=socket.socketpair()
            try:
                rpc._send(a,bad)
                client=rpc.CapacityClient(b,deadline=time.monotonic()+5)
                with self.assertRaisesRegex(rpc.CapacityChannelError,'Malformed parent error diagnostic'):
                    client._exchange({'type':'acquire','phase':'policy','sequence':1})
            finally:a.close();b.close()

    def test_event_sink_failure_chains_original_parent_diagnostic(self):
        with setup()as(controller,parent,clients):
            parent.activate('run:a')
            def acquire(*args,**kwargs):raise RuntimeError('Original controller error')
            controller.acquire_turn=acquire
            error=OSError('Durable sink failed')
            def sink(event):
                if event['kind']=='capacity_parent_error':raise error
            clients['run:a'].on_event=sink
            with self.assertRaises(OSError)as caught:
                with clients['run:a'].turn('policy'):self.fail('Sink failure admitted')
            self.assertIs(caught.exception,error)
            self.assertIsInstance(error.__cause__,rpc.CapacityParentError)
            self.assertEqual(error.__cause__.parent_reason,'channel_failure')

    def test_abort_requires_known_case_actual_error_and_explicit_classification(self):
        with setup()as(_,parent,_):
            for case,error,classification in (('unknown',RuntimeError('x'),True),
                    ('run:a','not an exception',True),('run:a',RuntimeError('x'),'yes')):
                with self.subTest(case=case,classification=classification),self.assertRaises(ValueError):
                    parent.abort_after_failure(case,error,infrastructure=classification)
            with self.assertRaises(TypeError):parent.abort_after_failure('run:a',RuntimeError('x'))
            self.assertFalse(parent.suite_stop_event.is_set())

    def test_final_failures_are_recorded_after_user_stop_and_for_every_case(self):
        with setup(generation_cap=2)as(controller,parent,clients):
            permits={}
            for case in clients:
                parent.activate(case)
                permits[case]=clients[case]._exchange({'type':'acquire','phase':'policy','sequence':1})['request_id']
            parent.abort_after_failure('run:a',RuntimeError('User stopped suite'),infrastructure=False)
            for case in clients:
                with self.assertRaises(rpc.CapacityChannelError):
                    parent.finish_after_cleanup(case,verify_cleanup=lambda:False,record_terminal=lambda:True)
            self.assertFalse(parent.stop_cause['infrastructure'])
            self.assertEqual(set(parent.cleanup_failures),set(clients))
            for case in clients:
                failure=parent.cleanup_failures[case]
                self.assertEqual(failure['stage'],'verify_cleanup')
                self.assertEqual(failure['request_id'],permits[case])
                self.assertEqual(controller.status()['episodes'][case]['request_id'],permits[case])
                self.assertFalse(controller.status()['episodes'][case]['done'])

    def test_close_and_secondary_handlers_preserve_final_failure_without_new_cancel(self):
        with setup()as(controller,parent,_):
            for c in ('run:a','run:b'):parent.activate(c)
            # B is already verifying when A fails, so its own later genuine
            # verification failure must remain protected after its method exits.
            entered=threading.Event();unblock=threading.Event();errors=[]
            def verify():entered.set();unblock.wait(3);return False
            def finish_b():
                try:parent.finish_after_cleanup('run:b',verify_cleanup=verify,record_terminal=lambda:True)
                except BaseException as exc:
                    errors.append(exc)
                    parent.abort_after_failure('run:b',exc,infrastructure=True)
            thread=threading.Thread(target=finish_b);thread.start()
            try:
                self.assertTrue(entered.wait(2))
                with self.assertRaises(rpc.CapacityChannelError):
                    parent.finish_after_cleanup('run:a',verify_cleanup=lambda:False,record_terminal=lambda:True)
            finally:unblock.set();thread.join(3)
            self.assertEqual(len(errors),1);self.assertEqual(set(parent.cleanup_failures),{'run:a','run:b'})
            self.assertTrue(all(not r['cancelled']for r in controller.status()['episodes'].values()))
            parent.close()
            self.assertTrue(all(not r['cancelled']for r in controller.status()['episodes'].values()))

    def test_explicit_shutdown_reason_survives_unrelated_cohort_abort(self):
        with setup(generation_cap=2)as(controller,parent,clients):
            for c in clients:parent.activate(c)
            clients['run:b']._exchange({'type':'acquire','phase':'policy','sequence':1})
            parent.cancel('run:b')
            parent.abort_after_failure('run:a',RuntimeError('Unrelated infrastructure failure'),infrastructure=True)
            wait_for(self,lambda:'run:b'in parent.ended)
            self.assertEqual(parent.errors['run:b']['reason'],'explicit_cancellation')

    def test_sink_existing_cause_and_parent_diagnostic_both_survive(self):
        with setup()as(controller,parent,clients):
            parent.activate('run:a')
            def acquire(*args,**kwargs):raise RuntimeError('Original controller error')
            controller.acquire_turn=acquire
            permission=PermissionError('Event journal unwritable')
            def sink(event):
                if event['kind']=='capacity_parent_error':raise OSError('Durable sink failed')from permission
            clients['run:a'].on_event=sink
            with self.assertRaises(OSError)as caught:
                with clients['run:a'].turn('policy'):self.fail('Sink fault dispatched')
            self.assertIs(caught.exception.__cause__,permission)
            self.assertIsInstance(caught.exception.capacity_parent_error,rpc.CapacityParentError)
            self.assertEqual(caught.exception.capacity_parent_error.parent_reason,'channel_failure')

    def test_final_failure_wakes_parked_wait_without_rental_idle_time(self):
        with setup()as(controller,parent,clients):
            for c in clients:parent.activate(c)
            permit=clients['run:a']._exchange({'type':'acquire','phase':'policy','sequence':1})
            entered=threading.Event();errors=[]
            def wait():
                try:
                    with clients['run:b'].turn('policy'):entered.set()
                except Exception as exc:errors.append(exc)
            thread=threading.Thread(target=wait);thread.start()
            wait_for(self,lambda:controller.status()['episodes']['run:b']['waiting'])
            with self.assertRaises(rpc.CapacityChannelError):
                parent.finish_after_cleanup('run:a',verify_cleanup=lambda:False,record_terminal=lambda:True)
            thread.join(2);self.assertFalse(thread.is_alive());self.assertFalse(entered.is_set())
            self.assertEqual(len(errors),1);self.assertTrue(parent.suite_stop_event.is_set())
            self.assertEqual(controller.status()['episodes']['run:a']['request_id'],permit['request_id'])
            parent.finish_after_cleanup('run:a',verify_cleanup=lambda:True,record_terminal=lambda:True)
            self.assertTrue(parent.suite_stop_event.is_set()) # Cleanup never restarts an aborted cohort.

    def test_final_failure_stops_active_and_warm_real_queue(self):
        with setup(('run:a','run:b','run:c'),active_cap=2)as(controller,parent,clients):
            active=threading.Event();warm=threading.Event()
            class NativeCancelled(RuntimeError):pass
            def run_case(case,admission):
                if case=='c':warm.set()
                rpc.ActiveCapacityAdmission(admission,parent,'run:'+case).runner_callback(NativeCancelled)(None)
                if case=='b':
                    active.set();wait_for(self,parent.suite_stop_event.is_set);admission.check_active()
                if case=='a':
                    self.assertTrue(active.wait(2));self.assertTrue(warm.wait(2))
                    parent.finish_after_cleanup('run:a',verify_cleanup=lambda:False,record_terminal=lambda:True)
            result=queue.run_ordered_suite({c:c for c in('a','b','c')},run_case,max_concurrent_episodes=2,
                prewarm_count=1,stop_event=parent.suite_stop_event)
            self.assertTrue(result['cancelled'])
            self.assertEqual(result['cases']['a']['status'],'failed')
            for c in('b','c'):self.assertEqual(result['cases'][c]['status'],'cancelled')
            self.assertNotIn('run:c',controller.status()['episodes'])

    def test_real_queue_secondary_exit_handlers_do_not_cancel_primary_failure(self):
        with setup(('run:a','run:b','run:c'),active_cap=2)as(controller,parent,_):
            active=threading.Event();warm=threading.Event()
            class NativeCancelled(RuntimeError):pass
            def run_case(case,admission):
                try:
                    if case=='c':warm.set()
                    rpc.ActiveCapacityAdmission(admission,parent,'run:'+case).runner_callback(NativeCancelled)(None)
                    if case=='b':
                        active.set();wait_for(self,parent.suite_stop_event.is_set);admission.check_active()
                    if case=='a':
                        self.assertTrue(active.wait(2));self.assertTrue(warm.wait(2))
                        parent.finish_after_cleanup('run:a',verify_cleanup=lambda:False,record_terminal=lambda:True)
                except (NativeCancelled,queue.QueueCancelled)as exc:
                    parent.abort_after_failure('run:'+case,exc,infrastructure=False);raise
                except BaseException as exc:
                    parent.abort_after_failure('run:'+case,exc,infrastructure=True);raise
            result=queue.run_ordered_suite({c:c for c in('a','b','c')},run_case,max_concurrent_episodes=2,
                prewarm_count=1,stop_event=parent.suite_stop_event)
            self.assertTrue(result['cancelled']);self.assertEqual(result['cases']['a']['status'],'failed')
            self.assertFalse(controller.status()['episodes']['run:a']['cancelled'])
            self.assertEqual(set(parent.cleanup_failures),{'run:a'})
            self.assertEqual(parent.stop_cause['case'],'run:a')
            self.assertEqual(len(parent.secondary_exits),3)

    def test_final_cleanup_interrupt_stops_cohort_without_masking_interrupt(self):
        from unittest.mock import patch
        with setup()as(controller,parent,_):
            parent.activate('run:a');original=KeyboardInterrupt('Final verifier interrupted')
            with patch.object(parent.threads['run:a'],'join',side_effect=original):
                with self.assertRaises(KeyboardInterrupt)as caught:
                    parent.finish_after_cleanup('run:a',verify_cleanup=lambda:True,record_terminal=lambda:True)
            self.assertIs(caught.exception,original);self.assertTrue(parent.suite_stop_event.is_set())
            self.assertFalse(controller.status()['episodes']['run:a']['done'])

    def test_explicit_cancel_precedes_retirement_even_on_idle_channel(self):
        with setup()as(controller,parent,_):
            parent.activate('run:a');calls=[]
            original_cancel=controller.cancel_episode;original_retire=controller.retire_dispatch
            def cancel(case):calls.append('cancel');original_cancel(case)
            def retire(case):calls.append('retire');original_retire(case)
            controller.cancel_episode=cancel;controller.retire_dispatch=retire
            parent.cancel('run:a')
            self.assertEqual(calls[:2],['cancel','retire'])

    def test_transport_timeout_before_deadline_is_not_rental_expiry(self):
        from unittest.mock import patch
        controller=control.EpisodeCapacityController(control.ParkingConfig(
            max_active_episodes=1,max_generation_requests=1,fresh_seconds=60))
        a,b=socket.socketpair()
        with patch.object(rpc,'_receive',side_effect=rpc.CapacityTransportTimeout('Local IPC stall')):
            parent=rpc.CapacityParent(controller,{'a':a},deadline=time.monotonic()+10).start()
            try:
                wait_for(self,lambda:'a'in parent.ended)
                self.assertEqual(parent.errors['a']['reason'],'channel_failure')
            finally:b.close();parent.close();controller.close()

    def test_cleanup_failure_stops_real_queue_before_refill(self):
        for failure in ('verify','terminal'):
            with self.subTest(failure=failure),setup(('run:a','run:b','run:c'),active_cap=1)as(controller,parent,clients):
                started=[]
                def run_case(case,admission):
                    started.append(case)
                    wrapped=rpc.ActiveCapacityAdmission(admission,parent,'run:'+case)
                    wrapped.environment_ready()
                    with clients['run:'+case].turn('policy'):pass
                    clients['run:'+case].close()
                    parent.finish_after_cleanup('run:'+case,
                        verify_cleanup=lambda:failure!='verify',record_terminal=lambda:failure!='terminal')
                result=queue.run_ordered_suite({c:c for c in ('a','b','c')},run_case,
                    max_concurrent_episodes=1,prewarm_count=0,stop_event=parent.suite_stop_event)
                self.assertEqual(started,['a']);self.assertTrue(result['cancelled'])
                self.assertEqual(result['cases']['a']['status'],'failed')
                for c in ('b','c'):self.assertEqual(result['cases'][c]['status'],'not_started')
                self.assertIn('run:a',parent.cleanup_failures)
                self.assertFalse(controller.status()['episodes']['run:a']['done'])

    def test_unjoinable_worker_retires_before_failure_and_stops_refill(self):
        from unittest.mock import patch
        controller=control.EpisodeCapacityController(control.ParkingConfig(
            max_active_episodes=1,max_generation_requests=1,fresh_seconds=60))
        healthy(controller);a,b=socket.socketpair();entered=threading.Event();unblock=threading.Event()
        def blocked_receive(*args,**kwargs):
            entered.set();unblock.wait(3);return None
        with patch.object(rpc,'_receive',blocked_receive):
            parent=rpc.CapacityParent(controller,{'run:a':a},deadline=time.monotonic()+5).start()
            try:
                self.assertTrue(entered.wait(2));parent.activate('run:a')
                with self.assertRaisesRegex(TimeoutError,'worker not stopped'):
                    parent.finish_after_cleanup('run:a',verify_cleanup=lambda:True,
                        record_terminal=lambda:True,timeout=.02)
                row=controller.status()['episodes']['run:a']
                self.assertTrue(row['dispatch_retired']);self.assertFalse(row['done'])
                self.assertTrue(parent.suite_stop_event.is_set())
                self.assertTrue(parent.threads['run:a'].is_alive())
            finally:unblock.set();b.close();parent.close();controller.close()

    def test_old_controller_retirement_api_rejected_at_construction(self):
        from types import SimpleNamespace
        a,b=socket.socketpair()
        try:
            with self.assertRaisesRegex(ValueError,'retire_dispatch'):
                rpc.CapacityParent(SimpleNamespace(),{'a':a},deadline=time.monotonic()+5)
        finally:a.close();b.close()

    def test_cleanup_timeout_is_bounded_and_typed(self):
        a,b=socket.socketpair()
        try:
            for value in (True,False,None,'x',float('nan'),float('inf'),0,-1,5.01,1e9):
                with self.subTest(value=value),self.assertRaises(ValueError):
                    rpc.CapacityClient(a,deadline=time.monotonic()+5,cleanup_timeout=value)
            for value in (.01,5,5.0):
                rpc.CapacityClient(a,deadline=time.monotonic()+5,cleanup_timeout=value)
        finally:a.close();b.close()

    def test_blocked_send_is_transport_timeout(self):
        a,b=socket.socketpair()
        try:
            a.setsockopt(socket.SOL_SOCKET,socket.SO_SNDBUF,1024)
            a.setblocking(False)
            try:
                while True:a.send(b'x'*4096)
            except BlockingIOError:pass
            a.settimeout(.02)
            with self.assertRaises(rpc.CapacityTransportTimeout):rpc._send(a,{'type':'release'})
        finally:a.close();b.close()

    def test_error_frame_transport_timeout_does_not_escape_worker(self):
        from unittest.mock import patch
        with setup()as(controller,parent,clients):
            parent.activate('run:a');original_send=rpc._send;fault=threading.Event();escaped=[]
            previous=threading.excepthook
            def send(sock,value):
                if value['type']=='error':
                    fault.set();raise rpc.CapacityTransportTimeout('Error ack stalled')
                return original_send(sock,value)
            threading.excepthook=lambda args:escaped.append(args.exc_value)
            try:
                with patch.object(rpc,'_send',send):
                    original_send(clients['run:a'].connection,{'type':'unknown'})
                    self.assertTrue(fault.wait(2))
                    parent.threads['run:a'].join(2)
                    self.assertFalse(parent.threads['run:a'].is_alive())
                self.assertEqual(escaped,[])
                self.assertIn('run:a',parent.ended)
            finally:threading.excepthook=previous

    def test_parent_reason_distinguishes_cancel_and_rental_expiry(self):
        with setup()as(controller,parent,clients):
            parent.activate('run:a');controller.telemetry=None;errors=[]
            def waiting():
                try:
                    with clients['run:a'].turn('policy'):self.fail('Cancelled acquire granted')
                except Exception as exc:errors.append(exc)
            thread=threading.Thread(target=waiting);thread.start()
            wait_for(self,lambda:controller.status()['episodes']['run:a']['waiting'])
            parent.cancel('run:a');thread.join(2)
            wait_for(self,lambda:'run:a'in parent.ended)
            self.assertEqual(parent.errors['run:a']['reason'],'explicit_cancellation')
        controller=control.EpisodeCapacityController(control.ParkingConfig(
            max_active_episodes=1,max_generation_requests=1,fresh_seconds=60))
        healthy(controller);a,b=socket.socketpair()
        parent=rpc.CapacityParent(controller,{'run:a':a},deadline=time.monotonic()+.08).start()
        try:
            parent.activate('run:a');wait_for(self,lambda:'run:a'in parent.ended)
            self.assertEqual(parent.errors['run:a']['reason'],'rental_deadline')
        finally:b.close();parent.close();controller.close()

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

    def test_local_release_ack_timeout_preserves_paid_response_and_provider_error(self):
        for provider_error in (False,True):
            with self.subTest(provider_error=provider_error):
                a,b=socket.socketpair();done=threading.Event()
                def stalled_parent():
                    try:
                        rpc._receive(a)
                        rpc._send(a,{'type':'permit','request_id':'a:policy:1','acquire_wait_seconds':0})
                        rpc._receive(a);done.wait(2)
                    finally:a.close()
                thread=threading.Thread(target=stalled_parent);thread.start()
                client=rpc.CapacityClient(b,deadline=time.monotonic()+10,cleanup_timeout=.03)
                original=OSError('Provider503')
                def complete(_):
                    if provider_error:raise original
                    return 'paid'
                backend=rpc.CapacityBackend(FakeBackend(complete),client,phase='policy',
                    guard=lambda:None,freshness_guard=lambda:None,buffered_completion=True)
                try:
                    if provider_error:
                        with self.assertRaises(OSError)as caught:backend.complete([])
                        self.assertIs(caught.exception,original)
                        self.assertTrue(original.__notes__)
                    else:
                        self.assertEqual(backend.complete([]),'paid')
                        self.assertIsNone(backend.interrupted_completion)
                    self.assertTrue(client.broken)
                    self.assertEqual(client.infrastructure_error['type'],'CapacityTransportTimeout')
                finally:done.set();client.close();thread.join(3)

    def test_module_receive_deadline_is_transport_not_foreign_watchdog(self):
        a,b=socket.socketpair()
        try:
            with self.assertRaises(rpc.CapacityTransportTimeout):
                rpc._receive(a,deadline=time.monotonic()-.01)
        finally:a.close();b.close()

    def test_retired_eof_is_not_a_parking_victim_before_terminal(self):
        with setup(('run:a','run:b','run:z'),active_cap=3)as(controller,parent,clients):
            for i,c in enumerate(clients):
                parent.activate(c,priority=i)
                with clients[c].turn('policy'):pass
            clients['run:z'].close()
            wait_for(self,lambda:'run:z'in parent.ended)
            row=controller.status()['episodes']['run:z']
            self.assertTrue(row['dispatch_retired']);self.assertFalse(row['done'])
            healthy(controller,waiting=1,kv=.95);healthy(controller,waiting=1,kv=.95)
            rows=controller.status()['episodes']
            self.assertFalse(rows['run:z']['parked'])
            self.assertTrue(rows['run:b']['parked'])
            with self.assertRaises(ValueError):controller.register_episode('run:new')

    def test_failed_cleanup_retires_but_keeps_permit_and_active_cap(self):
        with setup()as(controller,parent,clients):
            parent.activate('run:a');parent.activate('run:b')
            reply=clients['run:a']._exchange({'type':'acquire','phase':'policy','sequence':1})
            with self.assertRaises(rpc.CapacityChannelError):
                parent.finish_after_cleanup('run:a',verify_cleanup=lambda:False,record_terminal=lambda:True)
            row=controller.status()['episodes']['run:a']
            self.assertTrue(row['dispatch_retired']);self.assertFalse(row['done'])
            self.assertFalse(row['cancelled'])
            self.assertEqual(row['request_id'],reply['request_id'])
            self.assertEqual(controller.status()['resume_credits'],0)
            with self.assertRaises(ValueError):controller.register_episode('run:new')
            parent.finish_after_cleanup('run:a',verify_cleanup=lambda:True,record_terminal=lambda:True)
            self.assertTrue(controller.status()['episodes']['run:a']['done'])

    def test_external_retirement_wakes_wait_without_episode_cancellation(self):
        with setup()as(controller,parent,clients):
            parent.activate('run:a');controller.telemetry=None
            errors=[]
            def wait():
                try:
                    with clients['run:a'].turn('policy'):self.fail('Retired dispatch granted')
                except Exception as exc:errors.append(exc)
            thread=threading.Thread(target=wait);thread.start()
            wait_for(self,lambda:controller.status()['episodes']['run:a']['waiting'])
            controller.retire_dispatch('run:a')
            thread.join(2);self.assertFalse(thread.is_alive())
            wait_for(self,lambda:'run:a'in parent.ended)
            row=controller.status()['episodes']['run:a']
            self.assertTrue(row['dispatch_retired']);self.assertFalse(row['cancelled'])
            self.assertFalse(row['done']);self.assertIsNone(row['request_id'])
            self.assertEqual(len(errors),1)
            self.assertIn('dispatch retired',str(errors[0]))
            self.assertNotIn('episode_cancelled',[e['kind'] for e in controller.status()['events']])
            # A later explicit cancellation is still a distinct caller choice.
            parent.cancel('run:a')
            self.assertTrue(controller.status()['episodes']['run:a']['cancelled'])

    def test_finish_retirement_wakes_wait_without_cancellation(self):
        with setup()as(controller,parent,clients):
            parent.activate('run:a');controller.telemetry=None
            errors=[]
            def wait():
                try:
                    with clients['run:a'].turn('policy'):self.fail('Finishing dispatch granted')
                except Exception as exc:errors.append(exc)
            thread=threading.Thread(target=wait);thread.start()
            wait_for(self,lambda:controller.status()['episodes']['run:a']['waiting'])
            parent.finish_after_cleanup('run:a',verify_cleanup=lambda:True,record_terminal=lambda:True)
            thread.join(2);self.assertFalse(thread.is_alive())
            row=controller.status()['episodes']['run:a']
            self.assertTrue(row['dispatch_retired']);self.assertTrue(row['done'])
            self.assertFalse(row['cancelled']);self.assertIsNone(row['request_id'])
            self.assertEqual(len(errors),1)

    def test_last_drainer_resumes_after_success_or_aborts_after_final_failure(self):
        for cleanup_verified in (False,True):
            with self.subTest(cleanup_verified=cleanup_verified),setup()as(controller,parent,clients):
                for i,c in enumerate(clients):
                    parent.activate(c,priority=i)
                    with clients[c].turn('policy'):pass
                healthy(controller,waiting=1,kv=.95);healthy(controller,waiting=1,kv=.95)
                self.assertTrue(controller.status()['episodes']['run:b']['parked'])
                clients['run:a'].close();wait_for(self,lambda:'run:a'in parent.ended)
                healthy(controller)
                self.assertEqual(controller.status()['resume_credits'],0)
                self.assertTrue(controller.status()['episodes']['run:b']['parked'])
                entered=threading.Event();errors=[]
                def second():
                    try:
                        with clients['run:b'].turn('formatter'):entered.set()
                    except Exception as e:errors.append(str(e))
                thread=threading.Thread(target=second);thread.start()
                wait_for(self,lambda:controller.status()['episodes']['run:b']['waiting'])
                if cleanup_verified:
                    parent.finish_after_cleanup('run:a',verify_cleanup=lambda:True,record_terminal=lambda:True)
                else:
                    with self.assertRaises(rpc.CapacityChannelError):
                        parent.finish_after_cleanup('run:a',verify_cleanup=lambda:False,record_terminal=lambda:True)
                thread.join(2);self.assertFalse(thread.is_alive())
                if cleanup_verified:
                    self.assertTrue(entered.is_set());self.assertEqual(errors,[])
                else:
                    self.assertFalse(entered.is_set())
                    self.assertTrue(errors);self.assertTrue(parent.suite_stop_event.is_set())
                    self.assertFalse(controller.status()['episodes']['run:a']['done'])

    def test_permit_timing_rejects_malformed_values_before_body(self):
        for timing in (True,-1,'bad'):
            with self.subTest(timing=timing),setup()as(_,parent,clients):
                parent.activate('run:a');client=clients['run:a']
                client._exchange=lambda _:dict(type='permit',request_id='a:policy:1',acquire_wait_seconds=timing)
                with self.assertRaises(rpc.CapacityChannelError):
                    with client.turn('policy'):self.fail('Malformed permit admitted')

    def test_failed_wait_has_duration_timestamp_and_phase(self):
        with setup()as(controller,parent,clients):
            parent.activate('run:a');controller.telemetry=None;parent.deadline=time.monotonic()+.08
            with self.assertRaises(rpc.CapacityChannelError):
                with clients['run:a'].turn('formatter'):pass
            rows=[e for e in clients['run:a'].events if e['kind']=='capacity_wait_failed']
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['phase'],'formatter')
            self.assertGreaterEqual(rows[0]['wait_seconds'],0)
            self.assertGreater(rows[0]['observed_monotonic'],0)

    def test_fast_grant_wakes_monitor_without_status_frame(self):
        from unittest.mock import patch
        with setup()as(controller,parent,clients):
            parent.activate('run:a');original_poll=rpc.select.poll;entered=threading.Event()
            class ControlledPoll:
                def __init__(self):self.real=original_poll()
                def register(self,*args):self.real.register(*args)
                def poll(self,_):
                    entered.set()
                    return self.real.poll()  # Requires wake byte; no timer fallback.
            original_acquire=controller.acquire_turn
            def acquire(*args,**kwargs):
                if not entered.wait(2):raise AssertionError('Monitor never entered poll')
                return original_acquire(*args,**kwargs)
            controller.acquire_turn=acquire
            with patch.object(rpc.select,'poll',ControlledPoll):
                with clients['run:a'].turn('policy'):pass
            self.assertFalse(any(e['kind']=='capacity_wait_status'for e in clients['run:a'].events))

    def test_local_watcher_fault_is_diagnostic_and_cannot_grant(self):
        from unittest.mock import patch
        with setup()as(controller,parent,clients):
            parent.activate('run:a');entered=threading.Event();original=controller.acquire_turn
            class BrokenPoll:
                def register(self,*args):pass
                def poll(self,_):entered.set();raise ValueError('local watcher defect')
            def acquire(*args,**kwargs):
                if not entered.wait(2):raise AssertionError('No watcher')
                wait_for(self,lambda:parent.stops['run:a'].is_set())
                return original(*args,**kwargs)
            controller.acquire_turn=acquire
            with patch.object(rpc.select,'poll',BrokenPoll):
                with self.assertRaisesRegex(rpc.CapacityChannelError,'Capacity watcher failed: local watcher defect'):
                    with clients['run:a'].turn('policy'):self.fail('Watcher fault granted')
            self.assertIsNone(controller.status()['episodes']['run:a']['request_id'])

    def test_watcher_failure_after_grant_releases_unsent_permit(self):
        from unittest.mock import patch
        with setup()as(controller,parent,clients):
            parent.activate('run:a');entered=threading.Event();fault=threading.Event()
            original=controller.acquire_turn
            class BrokenAfterGrant:
                def register(self,*args):pass
                def poll(self,_):
                    entered.set();fault.wait(2);raise ValueError('post-grant watcher defect')
            def acquire(*args,**kwargs):
                if not entered.wait(2):raise AssertionError('No watcher')
                result=original(*args,**kwargs);fault.set()
                wait_for(self,lambda:parent.stops['run:a'].is_set())
                return result
            controller.acquire_turn=acquire
            with patch.object(rpc.select,'poll',BrokenAfterGrant):
                with self.assertRaisesRegex(rpc.CapacityChannelError,'Capacity watcher failed: post-grant watcher defect'):
                    with clients['run:a'].turn('policy'):self.fail('Defective watcher granted')
            self.assertIsNone(controller.status()['episodes']['run:a']['request_id'])

    def test_watcher_that_does_not_join_cannot_send_permit(self):
        from unittest.mock import patch
        with setup()as(controller,parent,clients):
            parent.activate('run:a');entered=threading.Event();unblock=threading.Event()
            original=controller.acquire_turn
            class StuckPoll:
                def register(self,*args):pass
                def poll(self,_):entered.set();unblock.wait(3);return []
            def acquire(*args,**kwargs):
                if not entered.wait(2):raise AssertionError('No watcher')
                return original(*args,**kwargs)
            controller.acquire_turn=acquire
            try:
                with patch.object(rpc.select,'poll',StuckPoll):
                    with self.assertRaisesRegex(rpc.CapacityChannelError,'Capacity watcher failed: did not stop'):
                        with clients['run:a'].turn('policy'):self.fail('Stuck watcher granted')
                self.assertIsNone(controller.status()['episodes']['run:a']['request_id'])
            finally:unblock.set()

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
