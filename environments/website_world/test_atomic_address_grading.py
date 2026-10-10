"""Finite saved-world and synthetic component checks; no episodes or draws."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
import unittest
import tempfile

from . import address_grading as address, atomic_shop_task as task, atomic_shop_grading as grade
from . import catalog_cart_grading as capture, catalog_checkout_domain as domain
from .adapter import digest

BASE = Path(__file__).resolve().parents[2] / '.local/coordination/short-task-hindrance-tests-20261007'


@lru_cache(maxsize=1)
def original():
    w = json.loads((BASE.parent/'task-support-expansion-20261007/natural-address-world-v1/world.private.json').read_bytes())
    before = json.loads((BASE/'address-preview-v8/actual-start-state.private.json').read_bytes())
    after = json.loads((BASE/'address-preview-v8/scripted-corrected-state.private.json').read_bytes())
    return w, before, after, domain.make(w)


def fixture(note=None):
    w, initial, final, d = original()
    w, initial, final, d = deepcopy((w, initial, final, d))
    spec = {'kind': task.KIND, 'retailer_id': 'department_store-03', 'delivery_note': note}
    t = task.make(w, spec);r = task.reference(w, t)
    rows = {x['retailer_id']: {'origin': 'https://' + x['retailer_id'] + '.test',
            'storage_key': 'website-drafts.state.' + x['retailer_id'],
            'offer_keys': {o['sku_id']: o['offer_id'] for o in x['offers']}} for x in w['retailers']}
    binding = capture.storage_binding(w, rows)
    # Other retailers are explicit synthetic untouched captures, not relabelled
    # real-browser evidence. The target uses preserved actual preview snapshots.
    empty = {'version': 2, 'cart': [], 'address': {}, 'remembered': {},
             'instructions': '', 'coupon': '', 'orders': []}
    before = {rid: deepcopy(initial if rid == t['retailer_id'] else empty) for rid in rows}
    after = {rid: deepcopy(final if rid == t['retailer_id'] else empty) for rid in rows}
    def snapshot(states):
        return {'cookies': [], 'origins': [{'origin': row['origin'], 'localStorage': [
            {'name': row['storage_key'], 'value': json.dumps(states[rid])}]} for rid, row in rows.items()]}
    c = {'schema_version': capture.CAPSULE_VERSION, 'task_sha256': digest(t),
         'binding_sha256': digest(binding), 'episode_id': 'fixed-case', 'main_trace_sha256': 'a'*64,
         'before': {'phase': 'before_policy', 'storage_state': snapshot(before)},
         'after': {'phase': 'after_policy_before_context_close', 'storage_state': snapshot(after)},
         'effect_journal': {'authority': 'complete_generated_world_event_journal', 'complete': True, 'events': []}}
    return w, t, r, d, binding, c


def run(f, completed=True):
    w, t, r, d, b, c = f
    return grade.grade(w, t, r, checkout_domain=d, binding=b, capsule=c,
                       episode_id='fixed-case', main_trace_sha256='a'*64, policy_completed=completed)


def change_after(f, update, *, retailer=None):
    _, t, _, _, b, c = f;rid = retailer or t['retailer_id']
    row = next(x for x in c['after']['storage_state']['origins'] if x['origin'] == b['retailers'][rid]['origin'])
    value = json.loads(row['localStorage'][0]['value']);update(value)
    row['localStorage'][0]['value'] = json.dumps(value)


class AddressTests(unittest.TestCase):
    def test_saved_actual_target_snapshot_without_new_units_passes(self):
        f = fixture();self.assertEqual(run(f)['verdict'], 'pass')
        self.assertNotIn('autofill', f[1]['user_message'])

    def test_old_building_in_same_city_fails(self):
        f = fixture();old = original()[1]['address']
        change_after(f, lambda s: s.update(address=deepcopy(old), remembered=deepcopy(old)))
        self.assertEqual(run(f)['verdict'], 'fail')

    def test_each_address_field_is_required(self):
        for key in ('name', 'street', 'unit', 'postcode', 'city'):
            f = fixture();change_after(f, lambda s: s['address'].update({key: 'wrong'}))
            self.assertEqual(run(f)['verdict'], 'fail', key)

    def test_equivalent_formatting_and_inline_unit(self):
        f = fixture()
        def update(s):
            a = s['address'];a['name'] = '  ' + a['name'].upper() + '  '
            a['street'] += ', Apartment ' + a['unit'];a['unit'] = ''
            a['postcode'] = a['postcode'].replace(' ', '')
        change_after(f, update);self.assertEqual(run(f)['verdict'], 'pass')

    def test_conflicting_inline_and_separate_unit_fails(self):
        f = fixture();change_after(f, lambda s: s['address'].update(street=s['address']['street'] + ', Apt foreign'))
        self.assertEqual(run(f)['verdict'], 'fail')

    def test_unsaved_or_wrong_remembered_address_fails(self):
        for update in (lambda s: s.update(addressStatus='unvalidated'), lambda s: s.update(remembered=original()[1]['address'])):
            f = fixture();change_after(f, update);self.assertEqual(run(f)['verdict'], 'fail')

    def test_cart_coupon_order_or_instructions_changes_fail(self):
        updates = [lambda s: s['cart'][0].update(quantity=2), lambda s: s.update(coupon='NEW'),
                   lambda s: s.update(orders=['order']), lambda s: s.update(instructions='NEW')]
        for update in updates:
            f = fixture();change_after(f, update);self.assertEqual(run(f)['verdict'], 'fail')

    def test_other_retailer_details_must_remain_unchanged(self):
        f = fixture();change_after(f, lambda s: s.update(address={'city': 'changed'}), retailer='outdoors-03')
        self.assertEqual(run(f)['verdict'], 'fail')

    def test_optional_note_is_verbatim(self):
        f = fixture('Ring twice.');self.assertEqual(run(f)['verdict'], 'fail')
        change_after(f, lambda s: s.update(instructions='Ring twice.'))
        self.assertEqual(run(f)['verdict'], 'pass')

    def test_missing_capture_or_authority_stays_unknown(self):
        f = fixture();f[-1]['after']['storage_state']['origins'].pop()
        self.assertEqual(run(f)['verdict'], 'inconclusive')
        f = fixture();f[-1]['effect_journal'] = None
        r = run(f);self.assertEqual(r['verdict'], 'inconclusive')
        self.assertEqual(r['components']['saved_address']['status'], 'pass')

    def test_incomplete_policy_and_forbidden_event(self):
        self.assertEqual(run(fixture(), completed=False)['verdict'], 'inconclusive')
        f = fixture();f[-1]['effect_journal']['events'] = [{'kind': 'purchase'}]
        self.assertEqual(run(f)['verdict'], 'fail')

    def test_task_memory_and_trace_cannot_be_rebound(self):
        f = fixture();f[1]['memories'] = ['wrong address']
        self.assertEqual(run(f)['verdict'], 'fail')
        f = fixture();f[-1]['main_trace_sha256'] = 'b'*64
        self.assertEqual(run(f)['verdict'], 'inconclusive')

    def test_country_requires_binding_and_matches(self):
        f = fixture();expected = f[1]['expected_address'];actual = original()[2]['address']
        self.assertEqual(address.compare_address(actual, expected)['status'], 'inconclusive')
        self.assertEqual(address.compare_address(actual, expected, implicit_country='NO')['status'], 'fail')

    def test_saved_return_hook_grades_once_without_answer_extraction(self):
        from .atomic_shop_execution import grade_saved_return
        w, t, r, d, b, c = fixture()
        class SavedCapture:
            binding = b
            called = 0
            def seal(self, trace, summary):
                self.called += 1
                if self.called > 1:raise ValueError('Already sealed')
                return c, True
        saved = SavedCapture()
        with tempfile.TemporaryDirectory() as directory:
            report = grade_saved_return(saved, directory, {}, world=w, task=t, reference=r, checkout_domain=d)
            self.assertEqual(report['verdict'], 'pass')
            self.assertTrue((Path(directory)/'atomic-address-grade.private.json').is_file())
            with self.assertRaises(ValueError):grade_saved_return(saved, directory, {}, world=w, task=t, reference=r, checkout_domain=d)
        self.assertEqual(saved.called, 2)


class QuoteTests(unittest.TestCase):
    def fixture(self):
        w, t, *_ = fixture();actual = deepcopy(original()[2]['address'])
        request = {'address': actual, 'sku_ids': ['target']};response = {'address': actual, 'optionsBySku': {'target': [{'shippingMinor': 6900}]}}
        observation = {'schema_version': address.QUOTE_VERSION, 'episode_id': 'fixed-case',
            'main_trace_sha256': 'a'*64, 'world_sha256': digest(w), 'retailer_id': t['retailer_id'],
            'operation': 'item_fulfilment', 'phase': 'policy', 'request': request, 'response': response}
        kwargs = {'episode_id': 'fixed-case', 'main_trace_sha256': 'a'*64,
            'world_sha256': digest(w), 'retailer_id': t['retailer_id'], 'operation': 'item_fulfilment',
            'request_scope': {'sku_ids': ['target']}, 'replay': lambda request: deepcopy(response), 'implicit_country': 'SE'}
        return t['expected_address'], observation, kwargs

    def test_correct_captured_quote_component(self):
        expected, o, k = self.fixture();self.assertEqual(address.grade_quote_address(expected, o, **k)['status'], 'pass')

    def test_saved_correct_address_does_not_fix_wrong_quote_address(self):
        expected, o, k = self.fixture();o['request']['address'] = deepcopy(original()[1]['address'])
        self.assertEqual(address.grade_quote_address(expected, o, **k)['status'], 'fail')

    def test_missing_quote_or_native_replay_unknown(self):
        expected, o, k = self.fixture();self.assertEqual(address.grade_quote_address(expected, None, **k)['status'], 'inconclusive')
        k['replay'] = None;self.assertEqual(address.grade_quote_address(expected, o, **k)['status'], 'inconclusive')

    def test_pending_response_is_not_shipping_info(self):
        expected, o, k = self.fixture();o['response'] = {'pending': True};k['replay'] = lambda r: {'pending': True}
        self.assertEqual(address.grade_quote_address(expected, o, **k)['status'], 'inconclusive')

    def test_setup_and_foreign_trace_are_not_policy_evidence(self):
        for field, value in [('phase', 'setup'), ('main_trace_sha256', 'b'*64), ('world_sha256', 'b'*64), ('retailer_id', 'foreign')]:
            expected, o, k = self.fixture();o[field] = value
            self.assertEqual(address.grade_quote_address(expected, o, **k)['status'], 'inconclusive')

    def test_foreign_sku_and_changed_response_fail(self):
        expected, o, k = self.fixture();o['request']['sku_ids'] = ['foreign']
        self.assertEqual(address.grade_quote_address(expected, o, **k)['status'], 'fail')
        expected, o, k = self.fixture();k['replay'] = lambda r: {'foreign': True}
        self.assertEqual(address.grade_quote_address(expected, o, **k)['status'], 'fail')

    def test_boolean_amount_does_not_alias_integer(self):
        expected, o, k = self.fixture();o['response'] = {'shippingMinor': True};k['replay'] = lambda r: {'shippingMinor': 1}
        self.assertEqual(address.grade_quote_address(expected, o, **k)['status'], 'fail')


def source_controls():
    cases = [(cls, name) for cls in (AddressTests, QuoteTests)
             for name in unittest.defaultTestLoader.getTestCaseNames(cls)]
    def run_case(case):
        cls, name = case;result = unittest.TestResult();cls(name).run(result)
        return {'case': cls.__name__ + '.' + name, 'passed': result.wasSuccessful(),
                'errors': result.errors, 'failures': result.failures}
    # Warm the immutable fixture before parallel independent controls.
    original()
    with ThreadPoolExecutor(max_workers=2) as pool:return list(pool.map(run_case, cases))
