"""Tiny consumer contract controls; synthetic capture, no browser/provider."""
from copy import deepcopy
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from jsonschema.exceptions import ValidationError

from .test_atomic_product_tasks import fixture
from . import atomic_product_publication as publication, atomic_product_task as native
from . import atomic_product_execution_consumer as consumer
from .adapter import digest


def read_grader(kind, **kw):
    world, task, reference, args, binding, capsule = fixture(kind, **kw)
    return consumer.AtomicReadGrader(world, task, reference, **args,
        binding=binding, capsule=capsule, completion=True)


def entry(value, evidence): return {'value': value, 'evidence': evidence}


def descriptive_grader(value, unit=None, qualifier=None):
    """A native authored fact with actual synthetic state, no expected refill."""
    world, original_task, _, args, binding, capsule = fixture('read_public_fact')
    args['catalog']['products'][0]['variants'][0]['details'][0]['facts'].append({
        'field': 'sku.facts.semantic', 'label': 'Descriptive fact',
        'value': value, 'unit': unit, 'qualifier': qualifier, 'status': 'known'})
    spec = {**original_task['spec'], 'fact': {'field': 'sku.facts.semantic'}}
    task = native.make(world, spec, **args)
    reference = native.reference(world, task, **args)
    capsule['task_sha256'] = digest(task)
    return consumer.AtomicReadGrader(world, task, reference, **args,
        binding=binding, capsule=capsule, completion=True)


def descriptive_claims(value, quote, unit=None, qualifier=None):
    return {'interpretation': 'extracted', 'issues': [], 'source_urls': [],
            'value': entry(value, quote),
            'unit': entry(unit, quote if unit is not None else None),
            'qualifier': entry(qualifier, quote if qualifier is not None else None)}


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
        claims = {'interpretation': 'extracted', 'issues': [], 'source_urls': [],
                  'total': {'amount': '125.00', 'currency': 'SEK', 'evidence': '125 SEK'}}
        report = grader.grade(claims, 'The listed price is 125 SEK.')
        self.assertTrue(report['structured_claims_correct'])
        self.assertEqual(report['native_report']['verdict'], 'pass')
        claims['total']['amount'] = '126'
        claims['total']['evidence'] = '126 SEK'
        self.assertFalse(grader.grade(claims, 'The listed price is 126 SEK.')['structured_claims_correct'])

    def test_missing_price_stays_missing(self):
        grader = read_grader('read_listed_price')
        report = grader.grade({'interpretation': 'extracted', 'issues': [], 'total': None, 'source_urls': []}, 'I could not find it.')
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

    def test_fabricated_quote_still_rejects(self):
        grader = read_grader('read_public_fact', fact={'field': 'sku.facts.supplied'})
        c = {'interpretation': 'extracted', 'issues': [], 'value': entry(False, 'false'),
             'unit': entry(None, None), 'qualifier': entry(None, None)}
        with self.assertRaises(ValueError): grader.grade(c, 'I did not find this information.')

    def test_scalar_paraphrases_use_extracted_values_then_native_comparison(self):
        for value, quote in [(False, 'The spare does not come in the box.'),
                             (True, 'You will find a spare in the box.'),
                             (-5, 'It works at five degrees below zero.'),
                             (0, 'There are no spare parts.'),
                             ('Hand wash', 'Wash it by hand.')]:
            with self.subTest(value=value):
                grader = descriptive_grader(value)
                claims = descriptive_claims(value, quote)
                before = deepcopy(claims)
                report = grader.grade(claims, quote)
                self.assertTrue(report['structured_claims_correct'])
                self.assertEqual(report['claims']['value'], claims['value'])
                self.assertEqual(claims, before)

    def test_wrong_scalar_meaning_fails_native_instead_of_quote_parser(self):
        grader = descriptive_grader(False)
        quote = 'A spare is included.'
        report = grader.grade(descriptive_claims(True, quote), quote)
        self.assertFalse(report['structured_claims_correct'])
        self.assertIs(report['claims']['value']['value'], True)

    def test_arrays_keep_extractor_order_duplicates_and_false_zero_values(self):
        for values, quote in [(['Wi-Fi', 'USB-C'], 'Wireless networking followed by a type C connector.'),
                              (['USB-C', 'USB-C'], 'Two type C connections.'),
                              ([False, True, -5, 0], 'Absent, present, five below zero, then nothing.')]:
            with self.subTest(values=values):
                grader = descriptive_grader(values)
                report = grader.grade(descriptive_claims(values, quote), quote)
                self.assertTrue(report['structured_claims_correct'])
                self.assertEqual(report['derivations'][0]['native_claims']['value'], values)
        grader = descriptive_grader(['Wi-Fi', 'USB-C'])
        quote = 'Type C first, wireless second.'
        result = grader.grade(descriptive_claims(['USB-C', 'Wi-Fi'], quote), quote)
        self.assertFalse(result['structured_claims_correct'])
        self.assertEqual(result['claims']['value']['value'], ['USB-C', 'Wi-Fi'])

    def test_unit_and_qualification_are_extractor_semantics(self):
        grader = descriptive_grader(-5, 'C', 'Remove the insole first')
        quote = 'Five below zero Celsius, after taking out the footbed.'
        claims = descriptive_claims(-5, quote, 'C', 'Remove the insole first')
        self.assertTrue(grader.grade(claims, quote)['structured_claims_correct'])
        claims['qualifier'] = entry(None, None)
        self.assertFalse(grader.grade(claims, quote)['structured_claims_correct'])

    def test_undeclared_qualifier_keeps_value_separate_from_authentic_label_quote(self):
        scope = 'Android / 4 GB RAM / 64 GB storage'
        grader = descriptive_grader(470, 'g', scope)
        self.assertNotIn('qualifier_declaration', grader.task['public_fact'])
        quote = 'Reference configuration: '+scope
        answer = 'Reference weight 470 g. '+quote
        claims = descriptive_claims(470, 'Reference weight 470 g', 'g', scope)
        claims['qualifier']['evidence'] = quote
        report = grader.grade(claims, answer)
        self.assertTrue(report['structured_claims_correct'])
        self.assertEqual(report['claims']['qualifier'], entry(scope, quote))
        for value in ('Other stated configuration', None):
            changed = deepcopy(claims)
            changed['qualifier'] = entry(value, quote if value is not None else None)
            self.assertFalse(grader.grade(changed, answer)['structured_claims_correct'])
        claims['qualifier']['evidence'] = 'Reference configuration: fabricated'
        with self.assertRaises(ValueError):
            grader.grade(claims, answer)
        self.assertIn('excluding presentation headings', grader.extraction_instructions)
        self.assertIn('excluding presentation headings', grader.schema['properties']['qualifier']['description'])

    def test_missing_fields_stay_null_and_ambiguity_remains_failure(self):
        grader = descriptive_grader(False)
        quote = 'I could not establish this.'
        report = grader.grade({'interpretation': 'extracted', 'issues': []}, quote)
        self.assertIsNone(report['claims']['value']['value'])
        self.assertFalse(report['structured_claims_correct'])
        claims = descriptive_claims(False, 'The spare is absent.')
        claims.update(interpretation='ambiguous', issues=['Conflicting declarations'])
        report = grader.grade(claims, 'The spare is absent.')
        self.assertFalse(report['structured_claims_correct'])
        self.assertEqual(report['claims']['issues'], claims['issues'])

    def test_typed_finite_values_exact_quotes_and_literal_urls_remain_required(self):
        quote = 'The spare is absent.'
        for value in ('false', 0):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                descriptive_grader(False).grade(descriptive_claims(value, quote), quote)
        for expected in (1.5, [1.5]):
            for value in (float('nan'), float('inf'), float('-inf')):
                supplied = [value] if type(expected) is list else value
                with self.subTest(value=value, expected=expected), self.assertRaisesRegex(ValueError, 'finite'):
                    descriptive_grader(expected).grade(descriptive_claims(supplied, quote), quote)
        grader = descriptive_grader(False)
        for evidence in ('', ' ', 'spare absent', None):
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                grader.grade(descriptive_claims(False, evidence), quote)
        claims = descriptive_claims(False, quote)
        claims['unit'] = entry(None, quote)
        with self.assertRaisesRegex(ValueError, 'Absent'):
            grader.grade(claims, quote)
        claims = descriptive_claims(False, quote)
        claims['source_urls'] = [{'value': 'https://wrong.test/', 'evidence': quote}]
        with self.assertRaisesRegex(ValueError, 'URL'):
            grader.grade(claims, quote)

    @unittest.skipUnless(hasattr(consumer, 'QUALIFIER_VERSION'), 'Frozen line has no qualifier vocabulary API')
    def test_declared_qualifier_schema_survives_semantic_numeric_admission(self):
        import pytest
        from .test_qualifier_domains import reference_fixture, read_claims, ANDROID
        with tempfile.TemporaryDirectory() as directory, pytest.MonkeyPatch.context() as monkeypatch:
            *_, grader, _ = reference_fixture(Path(directory), monkeypatch)
            quote = 'Reference: Android media 11, 4GB RAM, 64GB storage, Wi-Fi only, gray.'
            claims = read_claims(ANDROID, quote)
            claims['value'] = entry(470, 'It weighs four hundred and seventy grams.')
            self.assertTrue(grader.grade(claims, 'It weighs four hundred and seventy grams. Reference weight 470 g. '+quote)['structured_claims_correct'])
            self.assertIn('ambiguous', grader.extraction_instructions)
            self.assertEqual(grader.contract['canonical_qualifiers_version'], consumer.QUALIFIER_VERSION)

    @unittest.skipUnless(hasattr(consumer, 'QUALIFIER_VERSION'), 'Frozen line has no qualifier vocabulary API')
    def test_declared_qualifier_still_rejects_unknown_labels(self):
        import pytest
        from .test_qualifier_domains import reference_fixture, read_claims
        with tempfile.TemporaryDirectory() as directory, pytest.MonkeyPatch.context() as monkeypatch:
            *_, grader, _ = reference_fixture(Path(directory), monkeypatch)
            claims = read_claims('unregistered configuration', 'unregistered configuration')
            with self.assertRaises(ValidationError):
                grader.grade(claims, 'Reference weight 470 g. unregistered configuration')

    def test_actual_shared_extractor_accepts_read_contract_without_provider(self):
        class Backend:
            calls = 0
            def __init__(self, claims):
                self.claims = claims
            def complete(self, prompt):
                self.calls += 1
                return SimpleNamespace(text=json.dumps(self.claims), request={'synthetic': True}, raw={
                    'model': 'synthetic-zero-provider', 'usage': {},
                    'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(self.claims)}}]})
        cases = [(read_grader('read_listed_price'),
                  {'interpretation': 'extracted', 'issues': [], 'source_urls': [],
                   'total': {'amount': '125.00', 'currency': 'SEK', 'evidence': '125 SEK'}},
                  'The listed price is 125 SEK.'),
                 (descriptive_grader(False),
                  descriptive_claims(False, 'The spare does not come in the box.'),
                  'The spare does not come in the box.')]
        for grader, claims, answer in cases:
            with self.subTest(kind=grader.task['kind']), tempfile.TemporaryDirectory() as directory:
                backend = Backend(claims)
                report = consumer.task_answer.extract_and_grade(grader, {'user_message': 'Read this product detail'},
                    answer, Path(directory)/'extraction', backend)
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

    def test_dispatch_cannot_replace_attached_grader_or_allow_ungraded(self):
        with patch.object(consumer.shared, 'load') as loader:
            for key in ('automatic_grading','allow_ungraded','agent_runtime','episode_task'):
                with self.subTest(key=key), self.assertRaises(ValueError):
                    consumer.run('unused','unused',policy_session=lambda:None,
                        viewer_projection=lambda **_:None, metadata={'tags':['scripted']},
                        runner_options={'max_steps':1,'max_input_tokens':1,key:True})
            loader.assert_not_called()


if __name__ == '__main__': unittest.main()
