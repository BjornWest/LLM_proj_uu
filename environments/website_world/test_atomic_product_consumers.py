"""Tiny consumer contract controls; synthetic capture, no browser/provider."""
from copy import deepcopy
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from .test_atomic_product_tasks import fixture
from . import atomic_product_publication as publication, atomic_product_task as native
from . import atomic_product_execution_consumer as consumer


def read_grader(kind, **kw):
    world, task, reference, args, binding, capsule = fixture(kind, **kw)
    return consumer.AtomicReadGrader(world, task, reference, **args,
        binding=binding, capsule=capsule, completion=True)


def entry(value, evidence): return {'value': value, 'evidence': evidence}


class AtomicConsumerTests(unittest.TestCase):
    def test_all_four_compile_without_changing_input_or_world(self):
        for kind in native.KINDS:
            world, task, reference, args, _, _ = fixture(kind)
            before = deepcopy((world, args))
            packet = publication.compile_packet(world, task['spec'], **args)
            self.assertEqual(packet['task'], task)
            self.assertEqual(packet['reference'], reference)
            self.assertEqual((world, args), before)

    def test_catalog_price_drift_and_foreign_url_are_not_repaired(self):
        for mismatch in ('price', 'url'):
            world, task, _, args, _, _ = fixture('read_listed_price')
            if mismatch == 'price': args['catalog']['products'][0]['variants'][0]['priceMinor'] += 1
            else: args['bindings']['retailer_pages']['shop']['page'] = 'https://wrong.test/#/product/other'
            with self.assertRaises(ValueError): publication.compile_packet(world, task['spec'], **args)

    def test_price_normalizes_only_answer_money_and_currency(self):
        grader = read_grader('read_listed_price')
        claims = {'interpretation': 'extracted', 'issues': [],
                  'total': {'amount': '125.00', 'currency': 'SEK', 'evidence': '125 SEK'}}
        report = grader.grade(claims, 'The listed price is 125 SEK.')
        self.assertTrue(report['structured_claims_correct'])
        self.assertEqual(report['native_report']['verdict'], 'pass')
        claims['total']['amount'] = '126'
        with self.assertRaises(ValueError): grader.grade(claims, 'The listed price is 125 SEK.')

    def test_missing_price_stays_missing(self):
        grader = read_grader('read_listed_price')
        report = grader.grade({'interpretation': 'extracted', 'issues': []}, 'I could not find it.')
        self.assertIsNone(report['claims']['total'])
        self.assertIsNone(report['structured_claims_correct'])

    def test_fact_qualification_is_required_and_never_refilled(self):
        grader = read_grader('read_public_fact')
        answer = 'Hand wash. Remove the insole first.'
        c = {'interpretation': 'extracted', 'issues': [], 'value': entry('Hand wash', 'Hand wash'),
             'unit': entry(None, None), 'qualifier': entry('Remove the insole first', 'Remove the insole first')}
        self.assertTrue(grader.grade(c, answer)['structured_claims_correct'])
        c.pop('qualifier')
        self.assertFalse(grader.grade(c, answer)['structured_claims_correct'])

    def test_known_false_and_zero_survive_answer_grounding(self):
        for field, value, answer in [('supplied', False, 'Spare supplied: false.'), ('count', 0, 'Spare count: 0.')]:
            grader = read_grader('read_public_fact', fact={'field': 'sku.facts.' + field})
            c = {'interpretation': 'extracted', 'issues': [], 'value': entry(value, answer),
                 'unit': entry(None, None), 'qualifier': entry(None, None)}
            self.assertTrue(grader.grade(c, answer)['structured_claims_correct'])
            self.assertIs(type(grader.grade(c, answer)['claims']['value']['value']), type(value))

    def test_fabricated_quote_and_unsupported_boolean_fail(self):
        grader = read_grader('read_public_fact', fact={'field': 'sku.facts.supplied'})
        c = {'interpretation': 'extracted', 'issues': [], 'value': entry(False, 'Not provided'),
             'unit': entry(None, None), 'qualifier': entry(None, None)}
        with self.assertRaises(ValueError): grader.grade(c, 'Not provided')
        c['value'] = entry(False, 'false')
        with self.assertRaises(ValueError): grader.grade(c, 'I did not find this information.')

    def test_negative_facts_and_arrays_are_supported_without_expected_refill(self):
        self.assertTrue(consumer._supported(-5, 'Minimum temperature -5 C'))
        self.assertTrue(consumer._supported(['Wi-Fi', 'USB-C'], 'Wi-Fi; USB-C'))
        self.assertFalse(consumer._supported(['Wi-Fi', 'GPS'], 'Wi-Fi; USB-C'))

    def test_boolean_and_array_negative_review_controls(self):
        for answer in ('Spare supplied: true. No other information.',
                       'It is not false; the spare is supplied.', 'Yes, no problem.'):
            self.assertFalse(consumer._supported(False, answer), answer)
        self.assertFalse(consumer._supported(['Wi-Fi', 'USB-C'], 'In this order: USB-C; Wi-Fi.'))
        self.assertFalse(consumer._supported(['Wi-Fi', 'Wi-Fi'], 'Wi-Fi'))
        self.assertFalse(consumer._supported([False, True], 'not false; true'))
        self.assertTrue(consumer._supported([False, True], 'false; true'))

    def test_boolean_negated_inclusion_and_literal_override_are_rejected(self):
        self.assertFalse(consumer._supported(True, "The spare isn't included."))
        self.assertFalse(consumer._supported(False, 'Spare supplied: false. Actually, yes, it is included.'))
        self.assertFalse(consumer._supported(False, 'It is false that the spare is absent: the spare is included.'))
        self.assertFalse(consumer._supported(True, 'The spare cannot be included.'))
        self.assertFalse(consumer._supported(True, 'The spare will not be supplied.'))
        self.assertFalse(consumer._supported(True, "The spare isn't included: true."))
        self.assertFalse(consumer._supported(True, 'Spare absent: true.'))
        self.assertFalse(consumer._supported(False, 'The spare is included, so supplied: false.'))
        self.assertTrue(consumer._supported(False, "The spare isn't included."))
        self.assertTrue(consumer._supported(False, 'Spare supplied: false.'))
        self.assertTrue(consumer._supported(True, 'Spare supplied: true.'))

    def test_actual_shared_extractor_accepts_read_contract_without_provider(self):
        grader = read_grader('read_listed_price')
        claims = {'interpretation': 'extracted', 'issues': [],
                  'total': {'amount': '125.00', 'currency': 'SEK', 'evidence': '125 SEK'}}
        class Backend:
            calls = 0
            def complete(self, prompt):
                self.calls += 1
                return SimpleNamespace(text=json.dumps(claims), request={'synthetic': True}, raw={
                    'model': 'synthetic-zero-provider', 'usage': {},
                    'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(claims)}}]})
        with tempfile.TemporaryDirectory() as directory:
            backend = Backend()
            report = consumer.task_answer.extract_and_grade(grader, {'user_message': 'Read the price'},
                'The listed price is 125 SEK.', Path(directory)/'extraction', backend)
            self.assertTrue(report['structured_claims_correct'])
            self.assertEqual(backend.calls, 1)
            self.assertEqual(json.loads((Path(directory)/'extraction/response-contract.json').read_text()), grader.contract)

    def test_existing_authority_accepts_capture_container_marker_not_task_marker(self):
        from .catalog_cart_authority import ReadOnlyCommitAuthority
        from .runtime import Runtime
        # Constructor guard only. Source/surface authority is patched out;
        # this fixture cannot establish actual approval or browser effects.
        runtime = object.__new__(Runtime)
        runtime.world = {};runtime.adapter = object();runtime.baskets = object()
        runtime.prepared = None;runtime.delivery_oracle = None
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path/'manifest.json').write_text(json.dumps({**publication.recipe_marker(), 'source_sha256': {}, 'files': {}}))
            with patch.object(ReadOnlyCommitAuthority, '_load_retained_sources'), patch.object(ReadOnlyCommitAuthority, '_surface', return_value={}):
                authority = ReadOnlyCommitAuthority(runtime, path)
            self.assertEqual(authority.source_hashes, {})
            self.assertEqual(publication.recipe_marker()['atomic_product_recipe'], publication.VERSION)

    def test_dispatch_rejects_missing_authority_projection_and_limits_before_load(self):
        with tempfile.TemporaryDirectory() as directory:
            base = {'policy_session': lambda **_: None, 'metadata': {},
                    'runner_options': {'max_steps': 5, 'max_input_tokens': 1000},
                    'viewer_projection': lambda **_: {'status': 'verified'}, 'authority_approval': {'path': 'x', 'sha256': 'x'}}
            for changed in ({'authority_approval': None}, {'viewer_projection': None},
                            {'runner_options': {'max_steps': True, 'max_input_tokens': 1000}}):
                with patch.object(consumer.shared, 'load', side_effect=AssertionError('Should reject before load')):
                    with self.assertRaises(ValueError): consumer.run(Path(directory)/'recipe', Path(directory)/'run', **{**base, **changed})

    def test_native_action_grade_once_after_close_and_projection_required(self):
        for projected in (True, False):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory); recipe = root/'recipe'; recipe.mkdir()
                (recipe/'execution.private.json').write_text(json.dumps({'answer_grading': {'mode': 'off'}}))
                (recipe/'atomic-product-task.private.json').write_text(json.dumps({'kind': 'add_exact_quantity'}))
                events = []
                class FakeEpisode:
                    def __init__(self, *args, **kw):
                        self.task = SimpleNamespace(files={}, make_env=lambda: None)
                        self.profile = object();self.capture = object();self.catalog = {};self.domain = {}
                        self.runtime = SimpleNamespace(world={}, bindings={})
                        self.native_task = {'kind': 'add_exact_quantity'};self.reference = {}
                        self.automatic_grading = {'native_saved_return': consumer.native_execution.grade_saved_return}
                    def __enter__(self): return self
                    def __exit__(self, *args): pass
                @contextmanager
                def session(**kw):
                    events.append('open')
                    try: yield object()
                    finally: events.append('close')
                def runner(*args, output, **kw):
                    trace = Path(output)/'actual-return';trace.mkdir(parents=True)
                    events.append('return');return trace, {}
                def grade(*args, **kw): events.append('grade');return {'verdict': 'pass'}
                def viewer(**kw): events.append('viewer');return {'status': 'verified' if projected else 'missing'}
                with patch.object(consumer.shared, 'load', return_value={}), \
                        patch.object(consumer, 'AtomicProductEpisode', FakeEpisode), \
                        patch.object(consumer.native_execution, 'grade_saved_return', side_effect=grade):
                    result = consumer.run(recipe, root/'run', policy_session=session, viewer_projection=viewer,
                        authority_approval={'path': 'synthetic-only', 'sha256': 'synthetic-only'}, metadata={},
                        runner_options={'max_steps': 1, 'max_input_tokens': 1}, runner=runner,
                        quota_guard=lambda: events.append('quota'))
                self.assertEqual(events, ['quota', 'open', 'return', 'close', 'grade', 'viewer'])
                self.assertEqual(result['status'], 'graded_and_projected' if projected else 'system_failure')
                self.assertIs(result['task_completed'], True if projected else None)


if __name__ == '__main__': unittest.main()
