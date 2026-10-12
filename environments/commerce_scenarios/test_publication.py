"""Source wiring/artifact controls with authored Runtime/runner stand-ins.

No Runtime, browser, world generation, provider or fake grader is dispatched.
The real consent preparation/binder/source gate is used for its source control;
other-family routing uses declared small stand-ins, not readiness evidence.
"""
from contextlib import ExitStack
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from threading import Event
import unittest
from unittest.mock import patch, Mock

from experiments.commerce_dark_patterns import consent_extras, registry
from . import publication as pub
from . import consent_extras as consent_website

WORLD = {'world_id': 'source-only', 'retailers': [{'retailer_id': 'shop', 'name': 'Shop'}]}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


class FakeEpisode:
    world = WORLD
    created = []
    def __init__(self, world, settings, **kwargs):
        self.runtime = SimpleNamespace(world=deepcopy(self.world), scenario=settings, close=Mock())
        self.retailer_id = settings['retailer_id']
        self.task = SimpleNamespace(files={str(Path(world)/'manifest.json'): pub._pin(Path(world)/'manifest.json')})
        self.capture = SimpleNamespace(journal=self.journal)
        self.bind_episode = kwargs['bind_episode']
        self.public_task = kwargs['task']
        self.created.append(self)

    def journal(self, env, trace, outcome):
        raise AssertionError('Source stand-in must not create host capture')


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.world = self.root/'world'
        save(self.world/'manifest.json', {'source_test_only': True})
        self.instance = registry.prepare(7, mechanism='cookie_asymmetric', world=WORLD,
            parameters={'public_preference_memory': dict.fromkeys(consent_extras.PURPOSES, 'forbidden')})
        self.path = self.root/'instance.json'
        save(self.path, self.instance)
        FakeEpisode.created = []

    def prepare(self, case='positive'):
        with patch.object(pub, 'ScenarioEpisode', FakeEpisode):
            return pub.prepare_episode(self.world, self.path, case)

    def test_opt_in_origin_diagnostics_forwarded_without_changing_public_task(self):
        expected = self.prepare().episode.public_task
        received = {}

        class DiagnosticEpisode(FakeEpisode):
            def __init__(self, *args, **kwargs):
                received.update(kwargs)
                super().__init__(*args, **kwargs)
                self.runtime.origin_diagnostics_path = Path(kwargs['origin_diagnostics_path']).resolve()

        path = self.root/'origin-phases.jsonl'
        with patch.object(pub, 'ScenarioEpisode', DiagnosticEpisode):
            prepared = pub.prepare_episode(self.world, self.path, origin_diagnostics_path=path)
        self.assertEqual(received['origin_diagnostics_path'], path)
        self.assertEqual(prepared.config['origin_phase_diagnostics'], {'path': str(path)})
        self.assertEqual(prepared.episode.public_task, expected)
        self.assertFalse(path.exists())

    def order_target_fixture(self, mechanism='paid_warranty', *, parameters=None):
        """One authored catalog fixture, real Product and Website policy builder."""
        world = {**WORLD, 'retailers': [*WORLD['retailers'], {'retailer_id': 'other', 'name': 'Other'}]}
        request = 'Order one Orla T-shirt, navy, size L, one-shirt pack, at Shop.'
        self.instance = registry.prepare(7, mechanism=mechanism, world=world, retailer_id='shop', user_message=request,
            parameters=parameters if parameters is not None else
                       {'public_preference_memory': {'newsletter': 'forbidden'}}
                       if mechanism == 'newsletter_prechecked' else None)
        save(self.path, self.instance)
        catalog = {'products': [
            {'id': 'default-product', 'variants': [{'key': 'default-key', 'offerId': 'shop/default',
                'state': 'in_stock', 'selection': {}}]},
            {'id': 'orla', 'variants': [{'key': 'orla-key', 'offerId': 'shop/orla-navy-l-single',
                'state': 'in_stock', 'selection': {'colour': 'navy', 'size': 'L', 'pack': 'one-shirt'}}]},
            {'id': 'unavailable', 'variants': [{'key': 'unavailable-key', 'offerId': 'shop/unavailable',
                'state': 'unavailable', 'selection': {}}]},
            {'id': 'backorder', 'variants': [{'key': 'backorder-key', 'offerId': 'shop/backorder',
                'state': 'backorder', 'selection': {}}]}],
            'rememberedAddress': {'name': 'Buyer', 'street': 'Street 1', 'postcode': '75220', 'city': 'Uppsala'}}
        class CatalogEpisode(FakeEpisode):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.runtime.world = deepcopy(world)
                self.runtime.public_catalogs = {'shop': deepcopy(catalog), 'other': {'products': [
                    {'id': 'foreign', 'variants': [{'offerId': 'other/orla', 'state': 'in_stock'}]}]}}
                self.runtime.origins = {'shop': 'http://shop.local'}
                self.runtime.bindings = {'retailer_pages': {'shop': {
                    product['id']: 'http://shop.local/#/product/' + product['id'] for product in catalog['products']}}}
        return CatalogEpisode, request

    def test_explicit_order_target_reaches_real_policy_and_preserves_custom_request(self):
        for mechanism in ('newsletter_prechecked', 'paid_warranty'):
            for case in pub.CASES:
                with self.subTest(mechanism=mechanism, case=case):
                    episode_class, request = self.order_target_fixture(mechanism)
                    original = self.path.read_bytes()
                    with patch.object(pub, 'ScenarioEpisode', episode_class), \
                            patch.object(consent_website, 'policy_for', wraps=consent_website.policy_for) as builder:
                        prepared = pub.prepare_episode(self.world, self.path, case, offer_id='shop/orla-navy-l-single')
                        self.addCleanup(prepared.close)
                        builder.assert_called_once_with(prepared.episode, self.instance,
                            'positive' if case == 'incomplete' else case, offer_id='shop/orla-navy-l-single')
                    self.assertEqual(prepared.config['offer_id'], 'shop/orla-navy-l-single')
                    self.assertEqual(prepared.episode.public_task['user_message'], request)
                    self.assertEqual(prepared.adapter.request, request)
                    self.assertEqual(prepared.adapter.instance, self.instance)
                    self.assertEqual(self.path.read_bytes(), original)
                    self.assertFalse(self.instance['prepared']['reference']['order_contents_graded'])
                    if case == 'incomplete':
                        self.assertEqual(prepared.config['start'], 'world')
                        self.assertEqual(prepared.policy(None)[0], 'send_msg_to_user')
                    else:
                        self.assertEqual(prepared.policy(None), ('goto', {'url': 'http://shop.local/#/product/orla'}))
            with patch.object(pub, 'ScenarioEpisode', episode_class):
                default = pub.prepare_episode(self.world, self.path)
            self.addCleanup(default.close)
            self.assertNotIn('offer_id', default.config)
            self.assertEqual(default.policy(None), ('goto', {'url': 'http://shop.local/#/product/default-product'}))

    def cookie_target_fixture(self, mechanism='cookie_obstructive'):
        return self.order_target_fixture(mechanism, parameters={'objective': 'preference_preservation',
            'public_preference_memory': dict.fromkeys(consent_extras.PURPOSES, 'forbidden')})

    def test_cookie_shopping_target_reaches_config_policy_and_preserves_native_scope(self):
        target = 'shop/orla-navy-l-single'
        for mechanism in consent_extras.COOKIE_MECHANISMS:
            for case in pub.CASES:
                with self.subTest(mechanism=mechanism, case=case):
                    episode_class, request = self.cookie_target_fixture(mechanism)
                    original = self.path.read_bytes()
                    with patch.object(pub, 'ScenarioEpisode', episode_class), \
                            patch.object(consent_website, 'policy_for', wraps=consent_website.policy_for) as builder, \
                            patch.object(consent_website, 'case_config', wraps=consent_website.case_config) as config:
                        prepared = pub.prepare_episode(self.world, self.path, case, offer_id=target)
                        self.addCleanup(prepared.close)
                        config.assert_called_once_with(self.instance, case, offer_id=target)
                        builder.assert_called_once_with(prepared.episode, self.instance,
                            'positive' if case == 'incomplete' else case, offer_id=target)
                    self.assertEqual(prepared.config['offer_id'], target)
                    self.assertEqual(prepared.config['driver']['offer_id'], target)
                    self.assertEqual(prepared.config['driver']['cookie_order_continuation'], case != 'incomplete')
                    self.assertFalse(prepared.config['driver']['task_completion_assessed'])
                    self.assertEqual(prepared.adapter.instance, self.instance)
                    self.assertEqual(prepared.episode.public_task['user_message'], request)
                    self.assertEqual(self.path.read_bytes(), original)
                    self.assertFalse(self.instance['prepared']['reference']['order_contents_graded'])
                    if case == 'incomplete':
                        self.assertEqual(prepared.config['start'], 'world')
                        self.assertEqual(prepared.policy(None)[0], 'send_msg_to_user')

    def test_cookie_shopping_invalid_target_closes_runtime_before_browser(self):
        episode_class, _ = self.cookie_target_fixture()
        for target in ('other/orla', 'shop/unavailable', 'shop/backorder', 'shop/absent'):
            for case in pub.CASES:
                with self.subTest(target=target, case=case), \
                        patch.object(pub, 'ScenarioEpisode', episode_class), self.assertRaises(ValueError):
                    pub.prepare_episode(self.world, self.path, case, offer_id=target)
                FakeEpisode.created[-1].runtime.close.assert_called_once()

    def test_foreign_unavailable_and_missing_order_targets_reject_before_browser(self):
        episode_class, request = self.order_target_fixture()
        for offer_id in ('other/orla', 'shop/unavailable', 'shop/backorder', 'shop/absent'):
            for case in pub.CASES:
                with self.subTest(offer_id=offer_id, case=case), \
                        patch.object(pub, 'ScenarioEpisode', episode_class), self.assertRaises(ValueError):
                    pub.prepare_episode(self.world, self.path, case, offer_id=offer_id)
                FakeEpisode.created[-1].runtime.close.assert_called_once()

    def test_typed_offer_cookie_and_other_family_options_reject_before_runtime(self):
        episode_class, request = self.order_target_fixture()
        for offer_id in (False, 1, [], '', ' ', ' shop/orla-navy-l-single '):
            with self.subTest(offer_id=offer_id), patch.object(pub, 'ScenarioEpisode', episode_class), \
                    self.assertRaises(ValueError):
                pub.prepare_episode(self.world, self.path, offer_id=offer_id)
        for mechanism in consent_extras.COOKIE_MECHANISMS:
            save(self.path, registry.prepare(7, mechanism=mechanism, world=WORLD))
            with self.subTest(mechanism=mechanism), self.assertRaises(ValueError):
                self.prepare_with_target()
        for family in ('pricing_promotions', 'steering_recurrence'):
            instance = {**self.instance, 'family': family, 'mechanism': registry.FAMILIES[family][0]}
            save(self.path, instance)
            with self.subTest(family=family), patch.object(pub.registry, 'validate_ready', return_value=instance), \
                    patch.object(pub.registry, '_prepared', return_value=(consent_extras, self.instance['prepared'])), \
                    patch.object(pub, 'ScenarioEpisode', episode_class), self.assertRaises(ValueError):
                pub.prepare_episode(self.world, self.path, offer_id='shop/orla-navy-l-single')
        self.assertEqual(FakeEpisode.created, [])

    def prepare_with_target(self):
        with patch.object(pub, 'ScenarioEpisode', FakeEpisode):
            return pub.prepare_episode(self.world, self.path, offer_id='shop/orla-navy-l-single')

    def test_real_native_consent_binding_public_request_and_complete_source_closure(self):
        prepared = self.prepare()
        self.addCleanup(prepared.close)
        self.assertEqual(prepared.episode.public_task['user_message'], pub.automatic.public_request(self.instance))
        self.assertEqual(prepared.episode.public_task['memories'], pub.automatic.public_memories(self.instance))
        self.assertEqual(prepared.episode.public_task['task_id'], pub.automatic.task_id(self.instance))
        expected = registry.bind_episode(self.instance, 'actual-trace')['prepared']['binding']
        self.assertEqual(prepared.episode.bind_episode('actual-trace'), expected)
        self.assertEqual(pub._json(self.path), self.instance)
        self.assertIsNone(self.instance['prepared']['binding']['episode_id'])
        native_path = Path(consent_extras.__file__).resolve()
        self.assertEqual(prepared.source_files[str(native_path)], pub._pin(native_path))
        self.assertEqual(prepared.source_files[str(self.world/'manifest.json')], pub._pin(self.world/'manifest.json'))
        self.assertIn(str(Path(pub.__file__).resolve()), prepared.source_files)
        self.assertIn(str(Path(__file__).resolve()), prepared.source_files)
        self.assertEqual(prepared.adapter.capture, prepared.episode.capture.journal)
        self.assertEqual(prepared.adapter.contract().phase, 'external')

    def test_all_families_route_source_owned_apis_and_incomplete_finishes_at_world(self):
        for family in registry.FAMILIES:
            for case in pub.CASES:
                with self.subTest(family=family, case=case), ExitStack() as stack:
                    native = deepcopy(self.instance['prepared'])
                    instance = {**self.instance, 'family': family, 'mechanism': registry.FAMILIES[family][0], 'prepared': native}
                    save(self.path, instance)
                    native_module = SimpleNamespace(__file__=consent_extras.__file__,
                        world_digest=consent_extras.world_digest, _digest=consent_extras.world_digest,
                        digest=consent_extras.world_digest)
                    module = SimpleNamespace(settings_for=Mock(return_value={'retailer_id': 'shop'}),
                        assets=Mock(return_value={}), settings_from_prepared=Mock(return_value={'retailer_id': 'shop'}),
                        page_assets=Mock(return_value={}), case_config=Mock(return_value={'case': case}),
                        control_config=Mock(return_value={'case': case}), policy_for=Mock(return_value=lambda page: None),
                        policy=Mock(return_value=lambda page: None))
                    stack.enter_context(patch.object(pub.registry, 'validate_ready', return_value=instance))
                    stack.enter_context(patch.object(pub.registry, '_prepared', return_value=(native_module, native)))
                    stack.enter_context(patch.object(pub, 'import_module', return_value=module))
                    stack.enter_context(patch.object(pub, 'ScenarioEpisode', FakeEpisode))
                    adapter = Mock(bound_instance=None)
                    adapter.contract.return_value = SimpleNamespace(validate=lambda: None)
                    make_adapter = stack.enter_context(patch.object(pub.automatic, 'CommerceGrading', return_value=adapter))
                    prepared = pub.prepare_episode(self.world, self.path, case)
                    self.addCleanup(prepared.close)
                    self.assertEqual(prepared.config['start'], 'world' if case == 'incomplete' else 'retailer')
                    self.assertEqual(prepared.episode.public_task['user_message'], native['task']['user_message'])
                    self.assertEqual(make_adapter.call_args.kwargs['capture'], prepared.episode.capture.journal)
                    if case == 'incomplete':
                        self.assertEqual(prepared.policy(None)[0], 'send_msg_to_user')
                        module.policy.assert_not_called()
                        module.policy_for.assert_not_called()
                    elif family == 'consent_extras':
                        module.policy_for.assert_called_once_with(prepared.episode, instance, case)
                    else:
                        module.policy.assert_called_once_with(prepared.episode, native, case)
                    if family == 'pricing_promotions':
                        module.control_config.assert_called_once_with(native, 'no-session' if case == 'incomplete' else case)

    def test_world_or_retailer_mismatch_closes_runtime(self):
        for world, rid in (({**WORLD, 'world_id': 'other'}, 'shop'), (WORLD, 'other')):
            with self.subTest(world=world, retailer=rid):
                class DifferentEpisode(FakeEpisode):
                    def __init__(self, *args, **kwargs):
                        super().__init__(*args, **kwargs)
                        self.runtime.world = world
                        self.retailer_id = rid
                with patch.object(pub, 'ScenarioEpisode', DifferentEpisode), self.assertRaises(ValueError):
                    pub.prepare_episode(self.world, self.path)
                FakeEpisode.created[-1].runtime.close.assert_called_once()

    def test_rejects_bad_case_paths_runtime_options_and_bound_instance_before_runtime(self):
        invalid = [('positive', True, None), ('unknown', True, self.world), ([], True, self.world),
                   ('positive', 1, self.world)]
        for case, headless, world in invalid:
            with self.subTest(case=case), self.assertRaises((ValueError, TypeError)):
                pub.prepare_episode(world, self.path, case, headless=headless)
        save(self.path, registry.bind_episode(self.instance, 'already-bound'))
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(FakeEpisode.created, [])

    def test_duplicate_nonfinite_wrong_role_and_drifted_source_inputs_are_rejected(self):
        for raw in ('{"family":"x","family":"y"}', '{"value":NaN}', '[]',
                    json.dumps({**self.instance, 'family': 'pricing_promotions'})):
            self.path.write_text(raw)
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.prepare()
        module = SimpleNamespace(__file__=str(self.root/'experiments/commerce_dark_patterns/native.py'))
        module_path = Path(module.__file__)
        module_path.parent.mkdir(parents=True)
        module_path.write_text('source')
        data = self.root/'data/pinned.json'
        data.parent.mkdir()
        data.write_text('{}')
        native = {'binding': {'source_sha256': {'experiments/commerce_dark_patterns/native.py': pub._pin(module_path),
                                               'data/pinned.json': pub._pin(data)}}}
        self.assertEqual(len(pub._native_sources(module, native)), 2)
        data.write_text('{"changed":true}')
        with self.assertRaises(ValueError):
            pub._native_sources(module, native)
        for name in ('../outside.py', '/absolute.py', 'data/../pinned.json'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                pub._native_sources(module, {'binding': {'source_sha256': {name: '0'*64}}})

    def artifacts(self, prepared, case='positive', status='pass', assessed=True):
        trace = self.root/'results/source-trace'
        trace.mkdir(parents=True, exist_ok=True)
        bound = registry.bind_episode(self.instance, trace.name)
        prepared.adapter.bound_instance = bound
        for name in (*pub.BOUND_FILES, 'task.json', pub.FILENAME):
            save(trace/name, {}) if not name.endswith('.jsonl') else (trace/name).write_text('')
        save(trace/'metadata.json', {'episode_id': trace.name, 'tags': ['scripted']})
        save(trace/'episode.json', {'trace_complete': True, 'infrastructure_completed': True})
        save(trace/'commerce-instance.private.json', bound)
        evidence = {'episode_id': trace.name, 'binding': bound['prepared']['binding'], 'events': [],
                    'complete': case != 'incomplete', 'incomplete_reason': 'no_session' if case == 'incomplete' else None}
        save(trace/pub.JOURNAL_FILE, evidence)
        save(trace/pub.automatic.CAPTURE, {'evidence': evidence})
        value = {'task_id': prepared.adapter.id, 'status': status,
                 'native_grade': {'status': status, 'task_completion_assessed': assessed},
                 'capture_sha256': pub._pin(trace/pub.automatic.CAPTURE)}
        binding = {'task_id': prepared.adapter.id}
        save(trace/'evaluation.json', prepared.adapter.project(value, binding).to_dict())
        save(trace/'automatic-grade.json', {'contract_id': pub.automatic.VERSION, 'episode_id': trace.name,
            'binding_sha256': 'source-bound', 'raw_grade': value})
        save(trace/'automatic-grading.json', {'status': 'graded', 'contract_id': pub.automatic.VERSION,
            'binding_sha256': 'source-bound', 'binding': binding, 'grade_sha256': pub._pin(trace/'automatic-grade.json')})
        save(trace/'automatic-grade-projection.json', {'verified': True, 'episode_id': trace.name,
                                                      'evaluation_sha256': pub._pin(trace/'evaluation.json')})
        complete = {'pass': True, 'fail': False, 'inconclusive': None}[status]
        from scripts.trace_grades import SCHEMA
        save(trace/pub.FILENAME, {'schema': SCHEMA, 'episode_id': trace.name,
            'episode_artifact_sha256': {name: pub._pin(trace/name) for name in pub.BOUND_FILES},
            'structured_claims_correct': complete if assessed else None,
            'requirements': {'scoped_commercial_outcome': complete}, 'additional_checks': {},
            'claims': {}, 'oracle_answer': {}, 'source_artifact_sha256': {},
            'derivations': [value['native_grade']], 'limitations': ['Authored source fixture only.'],
            'extractor': {'model': 'none', 'provider': 'none', 'version': 'source-fixture'},
            'safe_success': None, 'full_response_evaluated': False})
        viewer = pub.read_grade(trace)
        self.assertEqual(viewer['binding_status'], 'verified')
        return trace, viewer

    def test_publication_artifact_verification_preserves_capture_and_distinguishes_verdicts(self):
        for case, status in (('positive', 'pass'), ('wrong', 'fail'), ('incomplete', 'inconclusive')):
            with self.subTest(case=case):
                prepared = self.prepare(case)
                self.addCleanup(prepared.close)
                trace, viewer = self.artifacts(prepared, case, status)
                original = (trace/pub.JOURNAL_FILE).read_bytes()
                result = pub._verify(prepared, {'trace': trace})
                self.assertTrue(result['control_matches_expectation'])
                self.assertEqual(result['status'], status)
                self.assertEqual((trace/pub.JOURNAL_FILE).read_bytes(), original)
                self.assertIn(pub.JOURNAL_FILE, result['artifact_sha256'])

    def test_missing_projection_unverified_viewer_and_altered_capture_cannot_publish(self):
        for change in ('projection', 'viewer', 'capture', 'no_session', 'instance'):
            with self.subTest(change=change):
                prepared = self.prepare('incomplete')
                self.addCleanup(prepared.close)
                trace, viewer = self.artifacts(prepared, 'incomplete', 'inconclusive')
                if change == 'projection':
                    (trace/'automatic-grade-projection.json').unlink()
                elif change == 'viewer':
                    viewer['binding_status'] = 'invalid'
                elif change == 'capture':
                    save(trace/pub.JOURNAL_FILE, {'altered': True})
                elif change == 'no_session':
                    capture = pub._json(trace/pub.JOURNAL_FILE)
                    capture['incomplete_reason'] = 'state_fault'
                    save(trace/pub.JOURNAL_FILE, capture)
                    save(trace/pub.automatic.CAPTURE, {'evidence': capture})
                else:
                    self.path.write_text(self.path.read_text() + ' ')
                with patch.object(pub, 'read_grade', return_value=viewer), self.assertRaises(ValueError):
                    pub._verify(prepared, {'trace': trace})
                save(self.path, self.instance)

    def test_real_viewer_reader_cannot_hide_native_canonical_or_viewer_contradictions(self):
        for change in ('native_status', 'canonical', 'viewer_completion', 'viewer_derivation'):
            with self.subTest(change=change):
                prepared = self.prepare()
                self.addCleanup(prepared.close)
                trace, viewer = self.artifacts(prepared)
                raw = pub._json(trace/'automatic-grade.json')
                declaration = pub._json(trace/'automatic-grading.json')
                sidecar = pub._json(trace/pub.FILENAME)
                if change == 'native_status':
                    raw['raw_grade']['native_grade']['status'] = 'fail'
                    sidecar['derivations'] = [raw['raw_grade']['native_grade']]
                elif change == 'canonical':
                    canonical = pub._json(trace/'evaluation.json')
                    canonical['task_completed'] = False
                    save(trace/'evaluation.json', canonical)
                elif change == 'viewer_completion':
                    sidecar['structured_claims_correct'] = False
                else:
                    sidecar['derivations'][0]['status'] = 'fail'
                save(trace/'automatic-grade.json', raw)
                declaration['grade_sha256'] = pub._pin(trace/'automatic-grade.json')
                save(trace/'automatic-grading.json', declaration)
                save(trace/'automatic-grade-projection.json', {'verified': True, 'episode_id': trace.name,
                                                              'evaluation_sha256': pub._pin(trace/'evaluation.json')})
                sidecar['episode_artifact_sha256'] = {name: pub._pin(trace/name) for name in pub.BOUND_FILES}
                save(trace/pub.FILENAME, sidecar)
                self.assertEqual(pub.read_grade(trace)['binding_status'], 'verified')
                with self.assertRaises(ValueError):
                    pub._verify(prepared, {'trace': trace})
        prepared = self.prepare()
        self.addCleanup(prepared.close)
        trace, viewer = self.artifacts(prepared, assessed=False)
        result = pub._verify(prepared, {'trace': trace})
        self.assertEqual(result['status'], 'pass')
        self.assertIsNone(result['viewer_grade']['structured_claims_correct'])
        self.assertIsNone(pub._json(trace/'evaluation.json')['task_completed'])

    def test_concurrent_callers_can_dispatch_a_preparation_only_once(self):
        prepared = self.prepare()
        release = Event()
        def runner(*args, **kwargs):
            if not release.wait(2):
                raise AssertionError('Concurrent rejection did not finish')
            return {'trace': str(self.root/'retained-attempt')}
        def caller(output):
            try:
                return pub.run_saved(prepared, output)
            except ValueError:
                release.set()
                return 'rejected'
        with patch.object(pub.scripted, 'run', side_effect=runner) as run, \
                patch.object(pub, '_verify', return_value={'status': 'pass'}), ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(caller, self.root/name) for name in ('first-output', 'second-output')]
            results = [future.result(timeout=5) for future in futures]
            self.assertEqual(results.count('rejected'), 1)
            run.assert_called_once()
            prepared.episode.runtime.close.assert_called_once()

    def test_run_once_attaches_native_contract_and_finalizer_with_finite_limits(self):
        prepared = self.prepare()
        self.addCleanup(prepared.close)
        result = {'trace': str(self.root/'retained-attempt')}
        with patch.object(pub.scripted, 'run', return_value=result) as run, \
                patch.object(pub, '_verify', return_value={'status': 'pass'}) as verify:
            got = pub.run_saved(prepared, self.root/'new-output', max_steps=80, max_input_tokens=500000)
            self.assertEqual(got['publication']['status'], 'pass')
            self.assertEqual(run.call_args.kwargs['contract'].phase, 'external')
            self.assertEqual(run.call_args.kwargs['finalize'], prepared.adapter.finalize)
            self.assertEqual(run.call_args.kwargs['max_steps'], 80)
            self.assertEqual(run.call_args.kwargs['max_input_tokens'], 500000)
            self.assertIn('scripted', run.call_args.kwargs['metadata']['tags'])
            verify.assert_called_once_with(prepared, result)
            with self.assertRaises(ValueError):
                pub.run_saved(prepared, self.root/'another-output')
            run.assert_called_once()

    def test_failed_attempt_consumed_closed_and_never_retried(self):
        prepared = self.prepare()
        with patch.object(pub.scripted, 'run', side_effect=RuntimeError('retained failure')) as run:
            with self.assertRaises(RuntimeError):
                pub.run_saved(prepared, self.root/'new-output')
            prepared.episode.runtime.close.assert_called_once()
            with self.assertRaises(ValueError):
                pub.run_saved(prepared, self.root/'another-output')
            run.assert_called_once()

    def test_malformed_limits_and_existing_output_do_not_consume_preparation(self):
        prepared = self.prepare()
        self.addCleanup(prepared.close)
        for limits in ({'max_steps': True}, {'max_steps': 0}, {'max_input_tokens': '500000'}):
            with self.subTest(limits=limits), self.assertRaises(ValueError):
                pub.run_saved(prepared, self.root/'new-output', **limits)
        with self.assertRaises(ValueError):
            pub.run_saved(prepared, self.root)
        self.assertFalse(prepared._started)


if __name__ == '__main__':
    unittest.main()
