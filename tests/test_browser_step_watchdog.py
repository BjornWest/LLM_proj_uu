"""Parent containment of a whole browser step, independent of child RPC limits."""
import importlib.util
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[1]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
caller=module('browser_step_watchdog_caller','scripts/comparison_suite.py')
channel=module('browser_step_watchdog_channel','scripts/episode_queue_channel.py')

class BrowserStepWatchdogTests(unittest.TestCase):
    def test_stalled_child_is_contained_while_healthy_sibling_survives(self):
        program='import signal,time;signal.signal(signal.SIGALRM,signal.SIG_IGN);print("ready",flush=True);time.sleep(30)'
        stalled=subprocess.Popen([sys.executable,'-I','-B','-c',program],stdout=subprocess.PIPE,text=True)
        sibling=subprocess.Popen([sys.executable,'-I','-B','-c',program],stdout=subprocess.PIPE,text=True)
        watchdog=None
        try:
            self.assertEqual(stalled.stdout.readline().strip(),'ready')
            self.assertEqual(sibling.stdout.readline().strip(),'ready')
            watchdog=caller.CaseWatchdog(stalled,{},startup_seconds=2,episode_seconds=None,
                rental_deadline=time.monotonic()+30,browser_step_seconds=.05,cleanup_grace_seconds=.1)
            watchdog.ready();watchdog.activate();watchdog.step_started(1)
            self.assertNotEqual(stalled.wait(timeout=3),0)
            self.assertIsNone(sibling.poll())
            self.assertEqual(watchdog.failure['phase'],'browser_step')
            self.assertEqual(watchdog.failure['effects'],'unknown')
        finally:
            if watchdog:watchdog.close()
            for process in (stalled,sibling):
                if process.poll() is None:process.terminate();process.wait(timeout=3)
                process.stdout.close()

    def test_step_completion_restores_longer_generation_deadline(self):
        process=Mock();process.poll.return_value=None
        watchdog=caller.CaseWatchdog(process,{},startup_seconds=2,episode_seconds=5,
            browser_step_seconds=.05,cleanup_grace_seconds=.1)
        try:
            watchdog.ready();watchdog.activate();deadline=watchdog.deadline
            watchdog.step_started(1);watchdog.step_finished(1);time.sleep(.25)
            process.terminate.assert_not_called();self.assertEqual(watchdog.deadline,deadline)
            self.assertEqual(watchdog.phase,'active')
            with self.assertRaises(caller.CaseDeadline):watchdog.step_finished(1)
            watchdog.step_started(2)
            with self.assertRaises(caller.CaseDeadline):watchdog.step_started(3)
        finally:watchdog.close()

    def test_wrapper_keeps_actions_results_and_native_exception(self):
        requests=[];gate=Mock()
        def step(*args,**kwargs):requests.append((args,kwargs));return {'native':'unchanged'}
        env=SimpleNamespace(step=step)
        self.assertIs(caller.watch_browser_steps(env,gate),env)
        self.assertEqual(env.step('click("1234")',option=2),{'native':'unchanged'})
        self.assertEqual(requests,[(('click("1234")',),{'option':2})])
        gate.step_started.assert_called_once();gate.step_finished.assert_called_once()
        def interrupted(*_):raise caller.EpisodeDeadline('native termination')
        gate=Mock();gate.step_finished.side_effect=RuntimeError('channel closed')
        env=SimpleNamespace(step=interrupted);caller.watch_browser_steps(env,gate)
        with self.assertRaisesRegex(caller.EpisodeDeadline,'native termination'):env.step('original')

    def test_channel_pairs_steps_and_refuses_dispatch_during_open_step(self):
        left,right=socket.socketpair();errors=[];calls=[]
        admission=SimpleNamespace(case_id='A',environment_ready=lambda ready:None,
            check_active=lambda:None,step_started=lambda seq:calls.append(('start',seq)),
            step_finished=lambda seq:calls.append(('end',seq)))
        result=[]
        def parent():
            try:result.append(channel.serve_admission(left,admission,expected_run_root='/private/runs'))
            except BaseException as exc:errors.append(exc)
        t=threading.Thread(target=parent);t.start()
        try:
            child=channel.ChildAdmission(right,'A',RuntimeError)
            child.environment_admission(SimpleNamespace(episode_id='trace',directory='/private/runs/trace',ready_monotonic=time.monotonic()))
            child.before_dispatch();child.step_started()
            with self.assertRaises(channel.ChannelError):child.before_dispatch()
            child.step_finished()
            child.step_started();child.step_finished();child.before_dispatch()
        finally:right.close();t.join(2);left.close()
        self.assertFalse(t.is_alive());self.assertEqual(errors,[])
        self.assertEqual(calls,[('start',1),('end',1),('start',2),('end',2)])
        self.assertEqual(result[0]['browser_steps'],2)
        self.assertEqual(result[0]['guarded_dispatches'],2)

    def test_unpaired_or_nested_frames_are_rejected(self):
        for frames in ([{'type':'browser_step_end','sequence':1}],
                [{'type':'browser_step_start','sequence':True}],
                [{'type':'browser_step_start','sequence':2}],
                [{'type':'browser_step_start','sequence':1},{'type':'dispatch'}],
                [{'type':'browser_step_start','sequence':1},{'type':'browser_step_start','sequence':2}]):
            left,right=socket.socketpair();errors=[]
            admission=SimpleNamespace(case_id='A',environment_ready=lambda ready:None,
                check_active=lambda:None,step_started=lambda seq:None,step_finished=lambda seq:None)
            def parent():
                try:channel.serve_admission(left,admission,expected_run_root='/private/runs')
                except BaseException as exc:errors.append(exc)
            t=threading.Thread(target=parent);t.start()
            try:
                child=channel.ChildAdmission(right,'A',RuntimeError)
                child.environment_admission(SimpleNamespace(episode_id='trace',directory='/private/runs/trace',ready_monotonic=1))
                for i,frame in enumerate(frames):
                    channel._send(right,{'case':'A',**frame})
                    if i<len(frames)-1:channel._receive(right)
            finally:right.close();t.join(2);left.close()
            self.assertFalse(t.is_alive());self.assertEqual(len(errors),1)
            self.assertIsInstance(errors[0],channel.ChannelError)

    def test_active_deadline_cannot_be_extended_by_step_begin(self):
        now=[0.0];process=Mock();process.poll.return_value=None
        watchdog=caller.CaseWatchdog(process,{},startup_seconds=5,episode_seconds=1,
            browser_step_seconds=10,cleanup_grace_seconds=.1,clock=lambda:now[0])
        try:
            watchdog.ready();watchdog.activate();now[0]=1.11
            with self.assertRaises(caller.CaseDeadline):watchdog.step_started(1)
            self.assertIsNone(watchdog.open_step)
        finally:watchdog.close()

    def test_eof_during_step_never_proves_absent_effects_or_success(self):
        left,right=socket.socketpair();errors=[]
        admission=SimpleNamespace(case_id='A',environment_ready=lambda ready:None,
            check_active=lambda:None,step_started=lambda seq:None)
        def parent():
            try:channel.serve_admission(left,admission,expected_run_root='/private/runs')
            except BaseException as exc:errors.append(exc)
        t=threading.Thread(target=parent);t.start()
        try:
            child=channel.ChildAdmission(right,'A',RuntimeError)
            child.environment_admission(SimpleNamespace(episode_id='trace',directory='/private/runs/trace',ready_monotonic=1))
            child.step_started()
        finally:right.close();t.join(2);left.close()
        self.assertEqual(len(errors),1);self.assertRegex(str(errors[0]),'effects unknown')

    def test_disabled_or_malformed_boundaries_fail_before_browser_execution(self):
        child=channel.ChildAdmission(Mock(),'A',RuntimeError)
        with self.assertRaises(channel.ChannelError):child.step_started()
        with self.assertRaises(channel.ChannelError):child.step_finished()
        self.assertEqual(caller.browser_step_options({}),(None,None))
        for invalid in (True,0,-1,601,'120',1.5):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):caller.browser_step_options({'browser_step_watchdog_seconds':invalid})
        for invalid in (1,'true'):
            with self.assertRaises(ValueError):caller.browser_step_options({'env_step_telemetry':invalid})
        self.assertEqual(caller.browser_step_options({'browser_step_watchdog_seconds':120,'env_step_telemetry':True}),(120,True))
