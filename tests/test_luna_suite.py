"""Zero-provider contracts for parallel, once-only, graded Luna dispatch."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import importlib.util
import json
import os
import py_compile
import subprocess
from pathlib import Path
import tempfile
import threading
import unittest
from dataclasses import dataclass, replace
from types import SimpleNamespace
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]/'scripts/luna_suite.py'
specification = importlib.util.spec_from_file_location('luna_suite_test_target', SOURCE)
suite = importlib.util.module_from_spec(specification)
specification.loader.exec_module(suite)


def authorization():
    return {'id': 'LUNA34-PARALLEL-EVALUATION-20261011-01', 'model': 'gpt-6-luna',
        'reasoning_effort': 'medium', 'cases': [{'case': c} for c in suite.CASE_IDS],
        'limits': dict(suite.LIMITS), 'concurrency': {'target': 34}}


class Requests(unittest.TestCase):
    def test_exact_finite_authorization(self):
        suite.validate_request(authorization())

    def test_other_model_or_partial_suite_rejected(self):
        for key, value in [('model', 'gpt-6-sol'), ('cases', []),
                           ('reasoning_effort', 'high')]:
            with self.subTest(key=key):
                row = authorization(); row[key] = value
                with self.assertRaises(ValueError): suite.validate_request(row)

    def test_changed_limit_rejected(self):
        for name in suite.LIMITS:
            row = authorization(); row['limits'][name] += 1
            with self.subTest(name=name), self.assertRaises(ValueError):
                suite.validate_request(row)

    def test_hashed_input_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'a'; path.write_text('one')
            row = suite.pin(path); path.write_text('two')
            with self.assertRaises(ValueError): suite.checked(row)
            link = Path(directory)/'link'; link.symlink_to(path)
            with self.assertRaises(ValueError): suite.checked(suite.pin(link))


class Registry(unittest.TestCase):
    def test_parallel_root_registration_preserves_old_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); registry = root/'registry.json'
            registry.write_text(json.dumps({'roots': ['old'], 'order_address_grades': {'old': {'x': 1}}}))
            specs = [{'registry': str(registry), 'output': str(root/f'suite{i}'),
                      'cases': [{'id': 'A01'}]} for i in range(20)]
            with ThreadPoolExecutor(max_workers=20) as pool:
                list(pool.map(suite.register_roots, specs))
            result = suite.load(registry)
            self.assertEqual(len(result['roots']), 21)
            self.assertEqual(result['order_address_grades'], {'old': {'x': 1}})


class Quota(unittest.TestCase):
    def test_shared_normalizer_receives_strict_flag_and_keeps_original_response(self):
        from unittest.mock import Mock
        original={'rateLimits':{'primary':{'usedPercent':1},'secondary':None}}
        normalize=Mock(return_value={'windows':[{}]})
        self.assertIs(suite.require_quota_windows(original,normalize),original)
        normalize.assert_called_once_with(original,require_complete_windows=True)
        normalize.side_effect=ValueError('Missing window field')
        with self.assertRaisesRegex(ValueError,'Missing window'):
            suite.require_quota_windows({},normalize)

    def test_http_watchdog_covers_queue_separately_from_provider180(self):
        self.assertEqual(suite.client_timeout({'admission_wait_seconds':1770}),3680)
        for value in (None,True,0,-1,10800,1.5):
            with self.subTest(value=value),self.assertRaises(ValueError):
                suite.client_timeout({'admission_wait_seconds':value})


class Imports(unittest.TestCase):
    def test_raw_loader_ignores_valid_but_stale_bytecode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'frozen.py'
            path.write_text('value = "wrong cached code"\n')
            py_compile.compile(str(path), doraise=True)
            cached = next((Path(directory)/'__pycache__').glob('*.pyc')).read_bytes()
            path.write_text('value = "approved source"\n')
            loader = suite.RawSourceLoader('frozen', str(path))
            namespace = {}
            exec(loader.get_code('frozen'), namespace)
            self.assertEqual(namespace['value'], 'approved source')
            self.assertEqual(next((Path(directory)/'__pycache__').glob('*.pyc')).read_bytes(), cached)

    def test_namespace_package_is_restricted_to_accepted_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root/'environments').mkdir()
            finder = suite.FrozenSourceFinder({'environments': root})
            with patch.object(suite.sys, 'path', [str(root)]):
                found = finder.find_spec('environments')
            self.assertEqual(list(found.submodule_search_locations), [str(root/'environments')])

    def test_mutable_fallback_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root/'scripts.py').write_text('value=1')
            finder = suite.FrozenSourceFinder({'scripts': root/'other'})
            with patch.object(suite.sys, 'path', [str(root)]):
                with self.assertRaises(ModuleNotFoundError): finder.find_spec('scripts')


class Profiles(unittest.TestCase):
    def test_task_clarification_and_consumer_callbacks_survive_helper_removal(self):
        @dataclass(frozen=True)
        class Tools:
            navigation_origins: tuple = ()
            clarification_tools: bool = False
            site_discovery_tools: bool = False
            optional: bool = False
        @dataclass(frozen=True)
        class Profile:
            name: str = 'original'
            tools: object = Tools()
            data_config: object = None
            agent_limits: object = None
            instructions: str = 'test'
            conversation_factory: object = None
            def describe(self):
                return {'tools': ['click', 'ax_search']
                    + (['ask_user'] if self.tools.clarification_tools else [])
                    + (['discover_sites'] if self.tools.site_discovery_tools else [])
                    + (['run_python','spawn_agent'] if self.tools.optional else [])}
        def factory(**kwargs):
            self.assertFalse(kwargs['helpers']); self.assertFalse(kwargs['data_tools'])
            return Profile()
        modules = {'intent_browser.standard_profile': SimpleNamespace(standard_profile=factory),
            'intent_browser.harness': SimpleNamespace(
                with_clarification=lambda p: replace(p,tools=replace(p.tools,clarification_tools=True)),
                with_site_discovery=lambda p: replace(p,tools=replace(p.tools,site_discovery_tools=True)))}
        callback = object()
        original = Profile(tools=Tools(clarification_tools=True,site_discovery_tools=True,optional=True),
            data_config=object(),agent_limits=object(),conversation_factory=callback)
        with patch.dict(suite.sys.modules,modules):
            actual = suite.policy_profile(original,discovery=True)
        self.assertIs(actual.conversation_factory,callback)
        self.assertIsNone(actual.data_config); self.assertIsNone(actual.agent_limits)
        self.assertEqual(actual.describe()['tools'],['click','ax_search','ask_user','discover_sites'])


class Projection(unittest.TestCase):
    def test_no_grade_is_system_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory); trace = output/'live/runs/one'; trace.mkdir(parents=True)
            (trace/'evaluation.json').write_text(json.dumps({'task_completed': True}))
            (trace/'automatic-grading.json').write_text(json.dumps({'status': 'pending'}))
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                suite.project({}, output, {'id': 'B06'}, trace=trace, grade={})

    def test_foreign_trace_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'escaped'):
                suite.project({}, Path(directory), {'id': 'B06'}, trace=directory, grade={})


class Lifecycle(unittest.TestCase):
    def test_state_cart_contract_receives_no_formatter_keyword(self):
        for case in ('B17','B19','H01','H02'):
            self.assertNotIn('extraction_backend_factory',suite.case_options(
                {'id':case,'callable':{}},lambda p:None))
        self.assertIn('extraction_backend_factory',suite.case_options(
            {'id':'B06','callable':{}},lambda p:None))

    def test_thread_start_failure_does_not_wait_for_unstarted_server(self):
        from unittest.mock import Mock
        server = Mock(); raw=Mock(); backend=Mock()
        thread=threading.Thread(target=lambda:None)
        suite.close_session(raw,server,thread,backend)
        server.shutdown.assert_not_called(); server.server_close.assert_called_once()
        raw.close.assert_called_once(); backend.close.assert_called_once()

    def test_dead_child_stale_live_state_does_not_count_as_capacity(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); (root/'B06').mkdir()
            suite.save(root/'B06/capacity-state.json',{'stage':'environment_live'})
            sample=suite.resource_sample({'output':str(root),'cases':[{'id':'B06'}]})
            self.assertEqual(sample['live_environment_count'],0)

    def test_supervisor_identity_reuse_or_deadline_blocks_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            suite.save(root/'supervisor-start.json',{'pid':os.getpid(),
                'process_start':'wrong-start','deadline_monotonic':suite.time.monotonic()+100})
            with self.assertRaisesRegex(RuntimeError,'Supervisor lost'):
                suite.dispatch_authority({'output':str(root)})


class StopClassification(unittest.TestCase):
    def classify(self,**changes):
        kwargs=dict(code=137,bounded={'returncode':-9,'last_observed':{'job':{'memory.events':{'oom_kill':0}}}},
                    watchdog=None,interrupted=False,timeout=False,baseline={'oom_kill':11},current={'oom_kill':12})
        kwargs.update(changes);return suite.stop_classification(**kwargs)
    def test_removed_cgroup_zero_sample_does_not_hide_correlated_oom(self):
        row=self.classify();self.assertEqual(row['capacity_failure'],'possible_memory_oom')
        self.assertEqual(row['shared_oom_kill_delta'],1)
        self.assertIn('cannot uniquely attribute',row['attribution'])
    def test_no_shared_delta_is_unknown_not_a_model_failure(self):
        row=self.classify(current={'oom_kill':11})
        self.assertIsNone(row['capacity_failure']);self.assertEqual(row['kill_reason'],'sigkill')
    def test_watchdog_interrupt_and_timeout_are_not_counted_as_oom(self):
        for kw,reason in (({'watchdog':{'reason':'supervisor_lost'}},'supervisor_lost'),
                ({'watchdog':{'reason':'episode_lifetime'}},'episode_lifetime'),
                ({'interrupted':True},'suite_interrupt'),({'timeout':True},'episode_lifetime')):
            with self.subTest(reason=reason):
                row=self.classify(**kw);self.assertIsNone(row['capacity_failure']);self.assertEqual(row['kill_reason'],reason)
    def test_launcher_refusal_is_reported(self):
        self.assertEqual(self.classify(code=125)['capacity_failure'],'launcher_refusal')
    def test_success_is_not_relabelled_by_later_signal(self):
        self.assertEqual(self.classify(code=0,interrupted=True),
                         {'capacity_failure':None,'kill_reason':None})
    def test_unreadable_counters_are_explicit(self):
        row=self.classify(baseline={'_available':False},current={'_available':False})
        self.assertFalse(row['shared_oom_counters_available'])
        self.assertIsNone(row['capacity_failure'])


class Cleanup(unittest.TestCase):
    def test_both_kill_methods_fail_still_exits_for_launcher_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(suite,'own_scope',return_value=Path(directory)), \
                    patch.object(Path,'write_text',side_effect=OSError('primary unavailable')), \
                    patch.object(suite.subprocess,'run',side_effect=subprocess.CalledProcessError(1,'systemctl')), \
                    patch.object(suite.os,'_exit',side_effect=SystemExit(124)) as exit_process:
                with self.assertRaises(SystemExit) as error:
                    suite.kill_own_scope()
                self.assertEqual(error.exception.code,124)
                exit_process.assert_called_once_with(124)

    def test_shared_counter_availability_and_failure_are_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            parent=Path(directory);scope=parent/'llmjob-test.scope';scope.mkdir()
            (parent/'memory.events').write_text('oom 3\noom_kill 2\n')
            with patch.object(suite,'own_scope',return_value=scope):
                self.assertEqual(suite.shared_memory_events(),{'oom':3,'oom_kill':2,'_available':True})
                (parent/'memory.events').unlink()
                result=suite.shared_memory_events()
                self.assertFalse(result['_available']);self.assertIn('_error',result)


class ExecutionGate(unittest.TestCase):
    def test_native_delegation_cannot_dispatch_without_grade_or_exact_prose(self):
        for mode in ('no-grade','changed-prose'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root=Path(directory);out=root/'B06';out.mkdir()
                marker=root/'source';marker.write_text('bound')
                config={'output':str(root),'suite_id':'synthetic','transport':{'subscription_lock':str(root/'lock'),'files':[]},
                        'driver':suite.pin(marker),'authorization':suite.pin(marker),
                        'bridge_worker':suite.pin(marker),'pi':suite.pin(marker),'node':suite.pin(marker)}
                case={'id':'B06','callable':{},'argument':'recipe','public_request':'approved'}
                lease=SimpleNamespace(begin_episode=lambda _: {'subscription_lock':str(root/'lock'),'admission_wait_seconds':1770},close=lambda:closed.append(True))
                closed=[];dispatches=[]
                def native(*args,**kwargs):
                    task=SimpleNamespace(files={},public={'user_message':'wrong' if mode=='changed-prose' else 'approved'})
                    kwargs['runner'](episode_task=task,automatic_grading=object() if mode=='changed-prose' else None)
                modules={'intent_browser.backend':SimpleNamespace(ChatCompletionsBackend=lambda *a,**k:dispatches.append(1)),
                        'intent_browser.input_budget':SimpleNamespace(QwenInputCounter=object,OpaqueReasoningInputCounter=object),
                        'intent_browser.runner':SimpleNamespace(run_episode=lambda **k:dispatches.append(1))}
                with patch.dict(suite.sys.modules,modules),patch.object(suite,'configure_case',return_value=native), \
                        patch.object(suite,'interface_check'),patch.object(suite,'load_transport',return_value=(
                            lambda *a,**k:dispatches.append(1),None,lambda *a:None,lambda *a,**k:lease,lambda *a,**k:None,None,None)):
                    with self.assertRaisesRegex(ValueError,'automatic grading|authorized prose'):
                        suite.execute_case(config,case)
                self.assertEqual(dispatches,[]);self.assertEqual(closed,[True])
                self.assertEqual(suite.load(out/'failure.json')['task_verdict'],None)


class Preflight(unittest.TestCase):
    def test_failed_interface_precedes_claims_and_registry_writes(self):
        request = authorization()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); auth=root/'auth.json'; suite.save(auth,request)
            config={'authorization':suite.pin(auth),'cases':[{'id':c} for c in suite.CASE_IDS],
                    'status':'ready'}
            with patch.object(suite,'validate_cases'),patch.object(suite,'validate_review'), \
                    patch.object(suite,'own_scope'), \
                    patch.object(suite,'suite_preflight',side_effect=ValueError('bad interface')), \
                    patch.object(suite.runpy,'run_path') as events,patch.object(suite,'register_roots') as roots:
                with self.assertRaisesRegex(ValueError,'bad interface'): suite.supervise(config)
                events.assert_not_called(); roots.assert_not_called()

    def test_review_receipt_cannot_bind_a_different_execution_driver(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'other.py'; p.write_text('')
            with self.assertRaisesRegex(ValueError,'exact reviewed execution driver'):
                suite.validate_review({'driver':suite.pin(p)})

    def test_unbounded_supervisor_is_rejected_before_claims(self):
        with patch.object(suite,'own_scope',side_effect=RuntimeError('unbounded')), \
                patch.object(suite.runpy,'run_path') as events:
            with self.assertRaisesRegex(RuntimeError,'unbounded'):
                suite.supervise({})
            events.assert_not_called()

    def test_review_must_match_actual_committed_driver_blob(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'scripts').mkdir();driver=root/'scripts/luna_suite.py'
            driver.write_text('approved committed source\n')
            def git(*args):
                return subprocess.check_output(['git','-C',str(root),*args],text=True,
                                               stderr=subprocess.DEVNULL).strip()
            git('init');git('add','scripts/luna_suite.py')
            git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','Fixture')
            review=root/'review.md';review.write_text('synthetic approval')
            acceptance=root/'approval.json'
            spec={'driver':suite.pin(driver),'review':suite.pin(review),
                  'launcher_python':suite.pin(driver),'caller_commit':git('rev-parse','HEAD')}
            def approve_current_bytes():
                acceptance.unlink(missing_ok=True)
                suite.save(acceptance,{'status':'reviewed_ready',**spec,'commit':spec['caller_commit'],
                           'launch_configuration_sha256':suite.launch_configuration_sha256(spec)})
                spec['review_acceptance']=suite.pin(acceptance)
            approve_current_bytes()
            with patch.object(suite,'__file__',str(driver)):
                suite.validate_review(spec)
                spec['output']='unreviewed-destination'
                with self.assertRaisesRegex(ValueError,'launch configuration'):
                    suite.validate_review(spec)
                del spec['output']
                driver.write_text('uncommitted changed source\n')
                spec['driver']=suite.pin(driver);spec['launcher_python']=suite.pin(driver)
                approve_current_bytes()
                with self.assertRaisesRegex(ValueError,'committed blob'):
                    suite.validate_review(spec)


class ParallelSupervisor(unittest.TestCase):
    def test_all34_start_together_missing_grade_fails_and_no_retry(self):
        self.run_supervisor(stops=False)

    def test_supervisor_watchdog_timeout_and_interrupt_after_success(self):
        self.run_supervisor(stops=True)

    def run_supervisor(self, *, stops):
        # Each child blocks until all34 have reached wait(). This proves that
        # the supervisor can dispatch all independent cases rather than queue.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); output = root/'suite'; output.mkdir()
            auth = root/'authorization.json'; suite.save(auth, authorization())
            reviewer = root/'review.md'; reviewer.write_text('synthetic source clearance')
            helper = Path(os.environ.get('LUNA_EVENTS_HELPER',
                str(Path(__file__).resolve().parents[1]/'scripts/episode_events.py')))
            if not helper.is_file():
                self.skipTest('Retained event helper is supplied explicitly by acceptance environment')
            registry = root/'sources.json'; suite.save(registry, {'roots': ['preserved']})
            spec = {'suite_id': 'synthetic-luna34', 'status': 'ready',
                'authorization': suite.pin(auth), 'output': str(output), 'driver': suite.pin(SOURCE),
                'review': suite.pin(reviewer), 'events_helper': suite.pin(helper),
                'thread_id': 'synthetic-no-delivery', 'registry': str(registry),
                'viewer_url': 'http://127.0.0.1:1', 'launcher': suite.pin(SOURCE),
                'launcher_python':suite.pin(SOURCE),
                'project_root': str(root), 'python': 'synthetic', 'spec_path': str(root/'spec.json'),
                'library_path': '/synthetic',
                'cases': [{'id': c, 'recipe_manifest': {}} for c in suite.CASE_IDS]}
            suite.save(spec['spec_path'], spec)
            barrier = threading.Barrier(34, timeout=10)
            starts = []
            handlers={}
            class Child:
                def __init__(self, command, **kwargs):
                    self.case = command[-1]; starts.append(self.case); self.returncode = None
                    destination = output/self.case
                    if self.case != 'B06':
                        suite.save(destination/'result.json', {'status': 'graded_and_projected',
                            'automatic_grading': True, 'task_verdict': 'fail', 'trace': '/synthetic'})
                def wait(self, timeout):
                    if stops and getattr(self,'timed_out',False):
                        self.returncode=143;return 143
                    barrier.wait()
                    if stops and self.case=='B01':
                        handlers[suite.signal.SIGTERM](suite.signal.SIGTERM,None)
                    if stops and self.case=='B02':
                        suite.save(output/self.case/'watchdog-stop.json',{'reason':'supervisor_lost'})
                        self.returncode=137;return 137
                    if stops and self.case=='B03':
                        self.timed_out=True
                        raise subprocess.TimeoutExpired('synthetic-case',timeout)
                    if stops and self.case=='B04':
                        self.returncode=143;return 143
                    self.returncode = 0; return 0
                def poll(self): return self.returncode
                def send_signal(self, value): self.returncode = -value
            @contextmanager
            def available(*args, **kwargs):
                yield type('Response', (), {'status': 200})()
            def signal_handler(signum,handler):
                prior=handlers.get(signum);handlers[signum]=handler;return prior
            with patch.object(suite, 'urlopen', available), patch.object(suite, 'validate_cases'), \
                    patch.object(suite,'validate_review'),patch.object(suite,'suite_preflight'), \
                    patch.object(suite,'own_scope'),patch.object(suite.signal,'signal',signal_handler):
                suite.supervise(spec, popen=Child, deliver=lambda _: None)
            terminal = suite.load(output/'supervisor-terminal.json')
            self.assertCountEqual(starts, suite.CASE_IDS)
            self.assertEqual(len(starts), 34)
            rows = {r['id']: r for r in terminal['episodes']}
            self.assertEqual(rows['B06']['state'], 'interrupted' if stops else 'failed')
            self.assertIn('missing graded result', rows['B06']['payload']['error'])
            excluded={'B06'}|({'B02','B03','B04'} if stops else set())
            self.assertTrue(all(r['state'] == 'succeeded' for c, r in rows.items() if c not in excluded))
            if stops:
                for case,reason in (('B02','supervisor_lost'),('B03','episode_lifetime'),('B04','suite_interrupt')):
                    self.assertEqual(rows[case]['payload']['kill_reason'],reason)
                    self.assertIsNone(rows[case]['payload']['task_verdict'])
                self.assertIsNone(rows['B01']['payload']['kill_reason'])
            self.assertEqual(terminal['capacity_stops_total'],0)
            self.assertEqual(terminal['capacity_stop_counts'],
                             {'memory_oom':0,'possible_memory_oom':0,'launcher_refusal':0})
            api = suite.runpy.run_path(str(helper))
            events = api['Events'](output/'completion.sqlite')
            with self.assertRaisesRegex(ValueError, 'already claimed'):
                events.start(spec['suite_id'], 'B06')
            notices = events.notices()
            self.assertEqual(len(notices), 39)  #34 terminals,4 milestones,one suite final.
            self.assertEqual({n['payload'].get('milestone') for n in notices
                if n['payload']['kind'] == 'milestone'}, {10, 20, 30, 34})


if __name__ == '__main__':
    unittest.main()
