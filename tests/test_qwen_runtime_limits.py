"""Actual threaded queue/controller/socket composition; no model or browser."""
import importlib.util
import json
import os
from pathlib import Path
import runpy
import socket
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
OBSERVER = runpy.run_path(str(ROOT/'scripts/qwen_suite_observer.py'))
CALLER = runpy.run_path(str(ROOT/'scripts/comparison_suite.py'))

def source_module(name, path):
    spec = importlib.util.spec_from_file_location(name,path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

CONTROL = source_module('_limits_test_control', Path(os.environ.get('QWEN_TEST_CONTROL_SOURCE',
    ROOT/'training/browser_training/capacity_control.py')))
QUEUE = source_module('_limits_test_queue', Path(os.environ.get('QWEN_TEST_QUEUE_SOURCE',
    ROOT/'scripts/episode_queue.py')))

class RuntimeLimitsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='limits-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stop = threading.Event()
        self.releases = {i:threading.Event() for i in 'abcd'}
        self.ready = {i:threading.Event() for i in 'abcd'}
        self.created = {i:threading.Event() for i in 'abcd'}
        self.control = CONTROL.EpisodeCapacityController(CONTROL.ParkingConfig(
            max_active_episodes=2,max_generation_requests=2),limits_ceiling={
            'max_active_episodes':3,'max_generation_requests':4})
        self.results,self.errors = [],[]
        self.bound = threading.Event()
        def bind(queue):
            self.q = queue
            self.rpc = OBSERVER['RuntimeLimitsRPC'](queue,self.control,self.root,
                self.root/'limits-events.jsonl',stop_event=self.stop,deadline=time.monotonic()+20)
            self.bound.set()
        def one(ident,admission):
            self.created[ident].set()
            admission.environment_ready()
            self.ready[ident].set()
            if not self.releases[ident].wait(8):raise RuntimeError('Test cleanup deadline')
            return ident
        def run():
            try:
                self.results.append(QUEUE.run_ordered_suite({i:i for i in 'abcd'},one,
                    max_concurrent_episodes=2,prewarm_count=1,max_concurrent_ceiling=3,
                    on_queue_ready=bind,stop_event=self.stop))
            except BaseException as e:self.errors.append(e)
        self.thread = threading.Thread(target=run)
        self.thread.start()
        self.addCleanup(self.cleanup)
        self.assertTrue(self.bound.wait(3))
        for i in 'ab':self.assertTrue(self.ready[i].wait(3))
        self.assertTrue(self.created['c'].wait(3))

    def cleanup(self):
        for event in self.releases.values():event.set()
        self.thread.join(10)
        self.rpc.close();self.control.close()
        self.assertFalse(self.thread.is_alive())
        self.assertEqual(self.errors,[])

    def read(self, request, *, raw=None):
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(3);client.connect(str(self.rpc.path))
            client.sendall(raw if raw is not None else (json.dumps(request)+'\n').encode())
            result=b''
            while not result.endswith(b'\n'):
                piece=client.recv(16384)
                if not piece:raise AssertionError('RPC closed without reply')
                result+=piece
            return json.loads(result)

    def update(self,active,permits,revision):
        return self.read({'op':'update_limits','token':self.rpc.token,
            'max_active_episodes':active,'max_generation_requests':permits,'expected_revision':revision})

    def test_authenticated_read_and_increase_admits_warm_before_cold(self):
        self.assertEqual(self.rpc.path.stat().st_mode & 0o777,0o600)
        first=self.read({'op':'limits','token':self.rpc.token})
        self.assertEqual(first['value']['revision'],0)
        raised=self.update(3,4,0)
        self.assertEqual(raised['status'],'ok')
        self.assertEqual(raised['value']['revision'],1)
        self.assertTrue(self.ready['c'].wait(3))
        self.assertTrue(self.created['d'].wait(3))
        self.assertFalse(self.ready['d'].is_set())
        self.assertEqual(self.rpc.limits()['queue']['target'],3)

    def test_lower_drains_lifecycles_without_canceling_or_admitting_warm(self):
        lower=self.update(1,1,0)
        self.assertEqual(lower['status'],'ok')
        self.assertEqual(lower['value']['queue']['active'],2)
        self.assertFalse(self.stop.is_set());self.assertFalse(self.ready['c'].is_set())
        self.releases['a'].set()
        until=time.monotonic()+3
        while self.q.snapshot()['active']!=1 and time.monotonic()<until:time.sleep(.01)
        self.assertEqual(self.q.snapshot()['active'],1)
        self.assertFalse(self.ready['c'].is_set())
        self.releases['b'].set();self.assertTrue(self.ready['c'].wait(3))
        self.assertFalse(self.ready['d'].is_set())

    def test_stale_and_invalid_updates_leave_both_targets_unchanged(self):
        before=self.rpc.limits()
        for active,permits,revision in [(3,4,1),(4,2,0),(2,5,0),(True,2,0),
                (2,True,0),(0,2,0),(2,0,0),(2,2,True),(2,2,-1)]:
            with self.subTest(active=active,permits=permits,revision=revision):
                self.assertEqual(self.update(active,permits,revision)['status'],'error')
                after=self.rpc.limits()
                self.assertEqual(after['revision'],before['revision'])
                self.assertEqual(after['max_active_episodes'],2)
                self.assertEqual(after['max_generation_requests'],2)
                self.assertEqual(after['queue']['target'],2)

    def test_lower_via_RPC_retains_actual_inflight_turns(self):
        for ident in 'ab':self.control.register_episode(ident)
        self.control.observe(CONTROL.CapacitySnapshot(time.monotonic(),0,0,0,.2,0))
        for ident in 'ab':self.control.acquire_turn(ident,'r-'+ident,timeout=1)
        before=self.control.status()['episodes']
        result=self.update(1,1,0)
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['value']['active_episodes'],2)
        self.assertEqual(result['value']['generation_requests'],2)
        self.assertEqual(self.control.status()['episodes'],before)
        self.assertFalse(self.stop.is_set())
        for ident in 'ab':
            self.control.release_turn(ident,'r-'+ident)
            self.control.finish_episode(ident)

    def test_owner_only_descriptor_client_and_partial_disconnect(self):
        path=self.root/'private.json'
        path.write_text(json.dumps(self.rpc.descriptor()));path.chmod(0o600)
        result=OBSERVER['runtime_limits_request'](path,'limits')
        self.assertEqual(result['revision'],0)
        result=OBSERVER['runtime_limits_request'](path,'update_limits',
            max_active_episodes=3,max_generation_requests=3,expected_revision=0)
        self.assertEqual(result['revision'],1)
        path.chmod(0o644)
        with self.assertRaises(ValueError):OBSERVER['runtime_limits_request'](path,'limits')
        with socket.socket(socket.AF_UNIX) as client:
            client.connect(str(self.rpc.path));client.sendall(b'{');client.shutdown(socket.SHUT_WR)
        self.assertEqual(self.read({'op':'limits','token':self.rpc.token})['status'],'ok')

    def test_two_simultaneous_CAS_updates_accept_exactly_one(self):
        barrier=threading.Barrier(3);results=[]
        def update(active):
            barrier.wait()
            try:results.append(self.rpc.update_limits(max_active_episodes=active,
                max_generation_requests=2,expected_revision=0))
            except ValueError:results.append(None)
        threads=[threading.Thread(target=update,args=(i,)) for i in (1,3)]
        for t in threads:t.start()
        barrier.wait()
        for t in threads:t.join(3);self.assertFalse(t.is_alive())
        self.assertEqual(sum(r is not None for r in results),1)
        self.assertEqual(self.rpc.limits()['revision'],1)

    def test_bad_frames_do_not_mutate_or_kill_service(self):
        for request in [{'op':'limits'}, {'op':'limits','token':'wrong'},
                {'op':'limits','token':42},{'op':'write','token':self.rpc.token},
                {'op':'limits','token':self.rpc.token,'extra':1}]:
            self.assertEqual(self.read(request)['status'],'error')
        raw=(json.dumps({'op':'limits','token':self.rpc.token})[:-1]+',"op":"limits"}\n').encode()
        self.assertEqual(self.read(None,raw=raw)['status'],'error')
        self.assertEqual(self.rpc.limits()['revision'],0)
        self.assertEqual(self.read({'op':'limits','token':self.rpc.token})['status'],'ok')

    def test_applied_update_journal_failure_stops_cohort_without_rolling_back_targets(self):
        from unittest.mock import patch
        with patch.dict(OBSERVER['RuntimeLimitsRPC'].update_limits.__globals__,
                {'append':lambda *a:(_ for _ in ()).throw(OSError('full disk'))}):
            reply=self.update(1,1,0)
        self.assertEqual(reply['status'],'error')
        self.assertIn('applied',reply['message'])
        self.assertTrue(self.stop.is_set())
        self.assertEqual(self.control.limits()['revision'],1)
        self.assertEqual(self.control.limits()['max_active_episodes'],1)
        self.assertEqual(self.q.snapshot()['target'],1)

    def test_finished_or_expired_queue_rejects_update(self):
        for event in self.releases.values():event.set()
        self.thread.join(5);self.assertFalse(self.thread.is_alive())
        self.assertEqual(self.update(3,3,0)['status'],'error')
        self.assertEqual(self.control.limits()['revision'],0)
        self.rpc.deadline=time.monotonic()-1
        self.assertEqual(self.read({'op':'limits','token':self.rpc.token})['status'],'error')

class ActivationDrainTests(unittest.TestCase):
    def test_already_admitted_setup_waits_when_target_drops_before_native_activation(self):
        controller=CONTROL.EpisodeCapacityController(CONTROL.ParkingConfig(max_active_episodes=2),
            limits_ceiling={'max_active_episodes':2,'max_generation_requests':4})
        self.addCleanup(controller.close)
        controller.register_episode('a')
        controller.update_limits(max_active_episodes=1,max_generation_requests=1,expected_revision=0)
        queue=SimpleNamespace(condition=threading.Condition())
        rpc=SimpleNamespace(queue=queue,_open=lambda:None)
        host=OBSERVER['CapacityHost'].__new__(OBSERVER['CapacityHost'])
        host.limits_rpc=rpc;host.controller=controller
        host.parent=SimpleNamespace(activate=lambda ident,priority:controller.register_episode(ident,priority=priority))
        finished=threading.Event();errors=[]
        def activate():
            try:host.activate('b',priority=1);finished.set()
            except BaseException as e:errors.append(e)
        worker=threading.Thread(target=activate);worker.start()
        try:
            self.assertFalse(finished.wait(.15))
            controller.finish_episode('a')
            self.assertTrue(finished.wait(3))
            self.assertEqual(controller.limits()['active_episodes'],1)
        finally:
            worker.join(3)
        self.assertEqual(errors,[]);self.assertFalse(worker.is_alive())

class ActualParentFixtureTests(unittest.TestCase):
    def test_real_parent_client_telemetry_and_queue_control_with_zero_providers(self):
        import types
        namespace='_limits_fixture_pkg'
        package=types.ModuleType(namespace);package.__path__=[];sys.modules[namespace]=package
        sys.modules[namespace+'.capacity_control']=CONTROL
        telemetry=source_module(namespace+'.serving_telemetry',ROOT/'training/browser_training/serving_telemetry.py')
        rpc=SimpleNamespace(**runpy.run_path(str(ROOT/'scripts/episode_capacity_rpc.py')))
        metrics=OBSERVER['ScriptedMetrics']();self.addCleanup(metrics.close)
        with tempfile.TemporaryDirectory(prefix='limits-native-fixture-') as temp:
            stop=threading.Event();directory=Path(temp)
            host=OBSERVER['CapacityHost'](rpc=rpc,control=CONTROL,telemetry=telemetry,
                source={'runtime_limits':{'max_active_ceiling':3,'max_generation_ceiling':4,
                    'initial_generation_requests':2}},output=directory,case_ids=list('abcd'),
                cap=2,deadline=time.monotonic()+15,stop_event=stop,directory=directory,
                qualification=SimpleNamespace(raw=metrics.raw,session='scripted-fixture',
                    identity={'model':'scripted','serving_revision':'offline-fixture'}))
            entered=threading.Event();release=threading.Event();bound=threading.Event();errors=[];result=[]
            def bind(queue):host.bind_limits(queue,directory);bound.set()
            def one(ident,admission):
                host.begin_relay(ident)
                binding=host.child_binding(ident)
                self.assertGreater(binding['deadline_utc'],time.time())
                client=OBSERVER['connect_client'](rpc,binding,
                    deadline=time.monotonic()+binding['deadline_utc']-time.time())
                try:
                    admission.environment_ready();host.activate(ident,priority=ord(ident))
                    with client.turn('policy'):
                        if ident=='a':entered.set();self.assertTrue(release.wait(5))
                    with client.turn('formatter'):pass
                finally:client.close()
                host.finish(ident,verify_cleanup=lambda:True,record_terminal=lambda:True)
                return ident
            def run():
                try:result.append(QUEUE.run_ordered_suite({i:i for i in 'abcd'},one,
                    max_concurrent_episodes=2,prewarm_count=1,max_concurrent_ceiling=3,
                    on_queue_ready=bind,stop_event=stop))
                except BaseException as e:errors.append(e)
            worker=threading.Thread(target=run);worker.start()
            try:
                self.assertTrue(bound.wait(3));self.assertTrue(entered.wait(3))
                descriptor=directory/'runtime-limits-private.json'
                changed=OBSERVER['runtime_limits_request'](descriptor,'update_limits',
                    max_active_episodes=1,max_generation_requests=1,expected_revision=0)
                self.assertEqual(changed['revision'],1);self.assertFalse(stop.is_set())
                release.set();worker.join(8);self.assertFalse(worker.is_alive())
                self.assertEqual(errors,[])
                self.assertEqual(host.parent.finished,set('abcd'))
                self.assertTrue(all(r['status']=='completed' for r in result[0]['cases'].values()))
                self.assertEqual(host.controller.limits()['active_episodes'],0)
                self.assertEqual(host.controller.limits()['generation_requests'],0)
            finally:
                release.set();worker.join(3)
                stop.set();host.close()

class ScriptedChildBoundaryTests(unittest.TestCase):
    def test_execute_uses_private_parent_deadline_and_reaches_native_run_without_live_proof(self):
        from unittest.mock import patch
        import types
        reached=[];client=SimpleNamespace(close=lambda:reached.append('closed'),infrastructure_error=None)
        class NativeBoundary(RuntimeError):pass
        def run(*args,**kwargs):reached.append('native');raise NativeBoundary('native boundary reached')
        def connect(rpc,binding,*,deadline,on_event):
            self.assertGreater(deadline,time.monotonic());reached.append('client');return client
        class Connection:
            def settimeout(self,*args):pass
            def connect(self,*args):pass
            def close(self):pass
        namespace={'intent_browser':types.ModuleType('intent_browser')}
        namespace['intent_browser'].__path__=[]
        for name,values in {
            'backend':{'ChatCompletionsBackend':object},'runner':{'run_episode':object},
            'episode_admission':{'EpisodeAdmissionCancelled':RuntimeError},
            'model_input_budget':{'model_matched_input_counter':object},
            'shared_tokenizer':{'SharedTokenizerConfig':object},
            'input_budget':{'OpaqueReasoningInputCounter':object,'QwenInputCounter':object}}.items():
            module=types.ModuleType('intent_browser.'+name)
            module.__dict__.update(values);namespace[module.__name__]=module
        with tempfile.TemporaryDirectory(prefix='limits-child-') as temp:
            out=Path(temp);(out/'supervisor-start.json').write_text(json.dumps({'pid':os.getpid(),'process_start':'fixture'}))
            source={'runtime_mode':'qwen-private-v1','runtime_limits':{},'shared_chromium':False,
                'output':str(out),'suite_id':'scripted-fixture','suite_timeout':60,'startup_timeout':60,
                'sockets':{'qwen-X':'fixture-admission'},'channel':{},'qwen_sources':{'rpc':{}},
                'capacity_bindings':{'qwen-X':{'path':'fixture-capacity','token':'private','deadline_utc':time.time()+60}}}
            case={'id':'qwen-X','task_id':'X','policy_model':'Qwen/Qwen3.8-27B-FP8',
                'argument':'fixture-recipe','max_input_tokens':250000}
            channel={'ChildAdmission':lambda *a:object()}
            helpers={'configure_case':lambda *a:run,'case_options':lambda *a:{}}
            globals_=CALLER['execute'].__globals__
            overrides={'helper':lambda *a:helpers,'source_guard':lambda *a:None,
                'checked':lambda *a:ROOT/'scripts/episode_capacity_rpc.py',
                'qwen_modules':lambda *a:({}, {'connect_client':connect}),
                'qwen_live':lambda *a:(_ for _ in ()).throw(AssertionError('scripted cannot read live serving')),
                'runpy':SimpleNamespace(run_path=lambda *a:channel if len(reached)==0 else {}),
                'signal':SimpleNamespace(SIGTERM=15,SIGALRM=14,signal=lambda *a:None,alarm=lambda *a:0),
                'socket':SimpleNamespace(AF_UNIX=1,SOCK_STREAM=1,socket=lambda *a:Connection())}
            # channel and RPC setup both run before connect; the RPC namespace
            # can contain unused channel fields without creating any service.
            overrides['runpy']=SimpleNamespace(run_path=lambda *a:channel)
            with patch.dict(sys.modules,namespace),patch.dict(globals_,overrides):
                with self.assertRaises(NativeBoundary):CALLER['execute'](source,case,scripted=True)
            self.assertEqual(reached,['client','native','closed'])
            failure=json.loads((out/'qwen-X/failure.json').read_text())
            self.assertEqual(failure['type'],'NativeBoundary')
            self.assertEqual(failure['usage']['policy_requests'],0)
            self.assertTrue((out/'qwen-X/cleanup.json').is_file())

class SourceSettingsTests(unittest.TestCase):
    def test_hard_pool_ceiling_and_no_defaults_changed(self):
        self.assertEqual(CALLER['runtime_limits']({'max_concurrent_episodes':4}),4)
        spec={'runtime_mode':'qwen-private-v1','max_concurrent_episodes':4,'cases':[{}]*34,
            'runtime_limits':{'max_active_ceiling':7,'max_generation_ceiling':8,'initial_generation_requests':4}}
        self.assertEqual(CALLER['runtime_limits'](spec),7)
        # A small acceptance cohort uses the full immutable deployment ceiling.
        self.assertEqual(CALLER['runtime_limits']({**spec,'cases':[{}]*4}),7)
        for value in [True,0,3]:
            bad={**spec,'runtime_limits':{**spec['runtime_limits'],'max_active_ceiling':value}}
            with self.subTest(value=value),self.assertRaises(ValueError):CALLER['runtime_limits'](bad)

if __name__=='__main__':unittest.main()
