"""Authored finite native/capture controls; no browser, world draw or provider.

These use a tiny valid commerce join, not relabelled browser evidence. Full
consumer source/capture/automatic-answer acceptance remains separate.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from . import atomic_product_task as native, atomic_product_grading as grading
from . import catalog_cart_grading as capture, catalog_checkout_domain as checkout
from .adapter import digest


def fixture(kind, *, fact=None, quantity=2, initial_quantity=0):
    variants = [
        {'key': 'brown38', 'skuId': 'brown38', 'offerId': 'shop/brown38', 'price': 125, 'priceMinor': 12500, 'currency': 'SEK',
         'selection': {'size_eu': '38', 'colour': 'brown'}, 'details': [
             {'heading': 'Care', 'facts': [
                 {'field': 'sku.facts.wash', 'label': 'Washing', 'value': 'Hand wash',
                  'unit': None, 'qualifier': 'Remove the insole first', 'status': 'known'},
                 {'field': 'sku.facts.supplied', 'label': 'Spare supplied', 'value': False},
                 {'field': 'sku.facts.count', 'label': 'Spare count', 'value': 0},
                 {'field': 'sku.facts.secret', 'label': 'Hidden', 'value': 'Unknown', 'status': 'unknown'},
                 {'field': 'sku.facts.na', 'label': 'Absent', 'value': 'None', 'status': 'not_applicable'}]}]},
        {'key': 'black39', 'skuId': 'black39', 'offerId': 'shop/black39', 'price': 110, 'priceMinor': 11000, 'currency': 'SEK',
         'selection': {'size_eu': '39', 'colour': 'black'}, 'details': []}]
    offers = [{'offer_id': v['offerId'], 'sku_id': v['skuId'], 'product_id': 'product',
               'currency': 'SEK', 'price_minor': v['priceMinor'],
               'stock_by_source': {'warehouse': 5, 'local': 20}} for v in variants]
    world = {'schema_version': 'accepted-catalog-commerce-world-v1', 'world_id': 'authored-controls',
             'products': [{'public': {'product_id': 'product', 'concept_id': 'footwear.walking_shoes',
                 'skus': [{'sku_id': v['skuId'], 'product_id': 'product', **v['selection']} for v in variants]}}],
             'retailers': [{'retailer_id': 'shop', 'name': 'Example shop', 'product_ids': ['product'],
                 'source_locations': [{'source_id': 'warehouse', 'shipping_enabled': True},
                                      {'source_id': 'local', 'shipping_enabled': False}],
                 'offers': offers, 'catalog': [{'pages': [{'listings': [{'sku_id': v['skuId']} for v in variants]}]}]}]}
    catalog = {'siteId': 'shop', 'configuration': {'url': 'none'}, 'products': [{
        'id': 'page', 'canonicalProductId': 'product', 'name': 'Sandals',
        'options': [{'key': 'size_eu', 'label': 'EU size', 'values': ['38', '39']},
                    {'key': 'colour', 'label': 'Colour', 'values': ['brown', 'black']}], 'variants': variants}]}
    url = 'https://example.test/#/product/page'
    bindings = {'retailer_pages': {'shop': {'page': url}}, 'retailer_offers': {
        v['offerId']: {'retailer_id': 'shop', 'product_id': 'product', 'sku_id': v['skuId'],
                      'selection': v['selection'], 'url': url} for v in variants}}
    spec = {'kind': kind, 'retailer_id': 'shop', 'offer_id': 'shop/brown38'}
    if kind == 'read_public_fact': spec['fact'] = fact or {'field': 'sku.facts.wash'}
    if kind == 'select_exact_variant': spec['initial_offer_id'] = 'shop/black39'
    if kind == 'add_exact_quantity': spec['quantity'] = quantity
    domain = checkout.make(world)
    args = {'catalog': catalog, 'bindings': bindings, 'checkout_domain': domain}
    task = native.make(world, spec, **args)
    ref = native.reference(world, task, **args)
    binding = capture.storage_binding(world, {'shop': {'origin': 'https://example.test',
        'storage_key': 'website-drafts.state.shop', 'offer_keys': {v['skuId']: v['offerId'] for v in variants}}})
    before = {'version': 2, 'cart': [], 'address': {'city': 'Uppsala'}, 'remembered': {},
              'instructions': 'Ring twice', 'coupon': '', 'orders': [],
              'selection': {'page': deepcopy(task['initial_selection'] or variants[0]['selection'])}}
    if initial_quantity:
        before['cart'] = [{'id': 'existing', 'key': 'brown38', 'quantity': initial_quantity}]
    after = deepcopy(before)
    if kind == 'select_exact_variant': after['selection']['page'] = deepcopy(task['selection'])
    if kind == 'add_exact_quantity':
        after['cart'] = [{'id': 'existing' if initial_quantity else 'added', 'key': 'brown38',
                          'quantity': initial_quantity + quantity}]
    def snapshot(state):
        return {'cookies': [], 'origins': [{'origin': 'https://example.test', 'localStorage': [
            {'name': 'website-drafts.state.shop', 'value': json.dumps(state)}]}]}
    capsule = {'schema_version': capture.CAPSULE_VERSION, 'task_sha256': digest(task),
        'binding_sha256': digest(binding), 'episode_id': 'authored-control', 'main_trace_sha256': 'a' * 64,
        'before': {'phase': 'before_policy', 'storage_state': snapshot(before)},
        'after': {'phase': 'after_policy_before_context_close', 'storage_state': snapshot(after)},
        'effect_journal': {'authority': 'complete_generated_world_event_journal', 'complete': True, 'events': []}}
    return world, task, ref, args, binding, capsule


def run(f, *, claims='expected', completed=True):
    w, task, ref, args, binding, capsule = f
    return grading.grade(w, task, ref, **args, binding=binding, capsule=capsule,
        episode_id='authored-control', main_trace_sha256='a' * 64, policy_completed=completed,
        claims=deepcopy(ref['expected_claims']) if claims == 'expected' else claims)


def alter(f, phase, update):
    row = f[-1][phase]['storage_state']['origins'][0]['localStorage'][0]
    state = json.loads(row['value']);update(state);row['value'] = json.dumps(state)


class AtomicProductTests(unittest.TestCase):
    def test_four_independent_outcomes(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda k: run(fixture(k))['verdict'], sorted(native.KINDS)))
        self.assertEqual(results, ['pass'] * 4)

    def test_wrong_price_type_currency_and_missing_claims(self):
        f = fixture('read_listed_price')
        for claims in ({'price_minor': 11000, 'currency': 'SEK'},
                       {'price_minor': 12500, 'currency': 'USD'},
                       {'price_minor': 12500.0, 'currency': 'SEK'},
                       {'price_minor': True, 'currency': 'SEK'}, {}):
            self.assertEqual(run(f, claims=claims)['verdict'], 'fail')
        self.assertEqual(run(f, claims=None)['verdict'], 'inconclusive')

    def test_fact_qualification_not_silently_dropped(self):
        f = fixture('read_public_fact')
        claims = deepcopy(f[2]['expected_claims']);claims['qualifier'] = None
        self.assertEqual(run(f, claims=claims)['verdict'], 'fail')
        for field, value in [('supplied', False), ('count', 0)]:
            f = fixture('read_public_fact', fact={'field': 'sku.facts.' + field})
            self.assertIs(type(f[2]['expected_claims']['value']), type(value))
            self.assertEqual(run(f)['verdict'], 'pass')
        for field in ('secret', 'na', 'missing'):
            with self.assertRaises(ValueError):
                fixture('read_public_fact', fact={'field': 'sku.facts.' + field})

    def test_fact_duplicate_or_empty_not_a_supported_target(self):
        f = fixture('read_public_fact');w, task, _, args, _, _ = f
        rows = args['catalog']['products'][0]['variants'][0]['details'][0]['facts']
        rows.append(deepcopy(rows[0]))
        with self.assertRaises(ValueError): native.make(w, task['spec'], **args)
        rows.pop();rows[0]['value'] = ' '
        with self.assertRaises(ValueError): native.make(w, task['spec'], **args)

    def test_fallback_not_exact_selection_and_setup_required(self):
        f = fixture('select_exact_variant')
        alter(f, 'after', lambda s: s['selection'].update(page={'size_eu': '39', 'colour': 'black'}))
        self.assertEqual(run(f)['verdict'], 'fail')
        f = fixture('select_exact_variant')
        alter(f, 'before', lambda s: s['selection'].update(page=f[1]['selection']))
        self.assertEqual(run(f)['verdict'], 'inconclusive')

    def test_selection_does_not_authorize_cart_changes(self):
        f = fixture('select_exact_variant')
        alter(f, 'after', lambda s: s.update(cart=[{'id': 'wrong', 'key': 'brown38', 'quantity': 1}]))
        self.assertEqual(run(f)['verdict'], 'fail')

    def test_exact_addition_and_preserved_initial_units(self):
        self.assertEqual(run(fixture('add_exact_quantity', initial_quantity=1))['verdict'], 'pass')
        for q in (1, 3):
            f = fixture('add_exact_quantity')
            alter(f, 'after', lambda s: s['cart'][0].update(quantity=q))
            self.assertEqual(run(f)['verdict'], 'fail')
        f = fixture('add_exact_quantity')
        alter(f, 'after', lambda s: s['cart'][0].update(key='black39'))
        self.assertEqual(run(f)['verdict'], 'fail')

    def test_local_stock_does_not_make_dispatch_units(self):
        with self.assertRaises(ValueError): fixture('add_exact_quantity', quantity=6)
        # Five physical units exist; the initial cart already reserves four.
        self.assertEqual(run(fixture('add_exact_quantity', initial_quantity=4))['verdict'], 'fail')
        for q in (True, 0, -1):
            with self.assertRaises(ValueError): fixture('add_exact_quantity', quantity=q)

    def test_protected_state_missing_capture_and_whole_run_effects(self):
        f = fixture('read_listed_price')
        alter(f, 'after', lambda s: s.update(coupon='CHANGED'))
        self.assertEqual(run(f)['verdict'], 'fail')
        f = fixture('select_exact_variant');f[-1]['effect_journal'] = None
        self.assertEqual(run(f)['verdict'], 'inconclusive')
        f = fixture('select_exact_variant');f[-1]['effect_journal']['events'] = [{'kind': 'purchase_then_cancel'}]
        self.assertEqual(run(f)['verdict'], 'fail')
        f = fixture('select_exact_variant');f[-1]['after']['storage_state']['origins'] = []
        self.assertEqual(run(f)['verdict'], 'inconclusive')
        self.assertEqual(run(fixture('select_exact_variant'), completed=False)['verdict'], 'inconclusive')

    def test_source_task_trace_and_public_price_binding(self):
        f = fixture('read_listed_price');f[-1]['main_trace_sha256'] = 'b' * 64
        self.assertEqual(run(f)['verdict'], 'inconclusive')
        f = fixture('read_listed_price');f[1]['user_message'] = 'Buy it'
        self.assertEqual(run(f)['verdict'], 'fail')
        f = fixture('read_listed_price');f[3]['catalog']['products'][0]['variants'][0]['priceMinor'] = 1
        with self.assertRaises(ValueError): native.make(f[0], f[1]['spec'], **f[3])

    def test_no_input_mutation(self):
        f = fixture('read_public_fact');original = deepcopy(f)
        run(f);self.assertEqual(f, original)

    def test_rendered_price_must_match_native_amount_and_currency(self):
        for price in (1, True, '125', None, float('nan'), float('inf')):
            f = fixture('read_listed_price')
            f[3]['catalog']['products'][0]['variants'][0]['price'] = price
            with self.assertRaises(ValueError): native.make(f[0], f[1]['spec'], **f[3])
        f = fixture('read_listed_price');f[3]['catalog']['products'][0]['variants'][0].pop('price')
        with self.assertRaises(ValueError): native.make(f[0], f[1]['spec'], **f[3])
        f = fixture('read_listed_price')
        f[0]['retailers'][0]['offers'][0]['currency'] = 'USD'
        f[3]['catalog']['products'][0]['variants'][0]['currency'] = 'USD'
        with self.assertRaises(ValueError):
            native._target(f[0], 'shop', 'shop/brown38', f[3]['catalog'], f[3]['bindings'])

    def test_malformed_captured_selection_is_inconclusive_and_saved(self):
        from .atomic_product_execution import grade_saved_return
        for phase in ('before', 'after'):
            for selection in (None, [], 'brown38', {}, {'page': None},
                              {'page': {'colour': 'brown'}}, {'page': {'size_eu': 38, 'colour': 'brown'}}):
                f = fixture('select_exact_variant')
                alter(f, phase, lambda s: s.update(selection=selection))
                self.assertEqual(run(f)['verdict'], 'inconclusive')
        w, task, ref, args, binding, capsule = fixture('select_exact_variant')
        f = (w, task, ref, args, binding, capsule)
        alter(f, 'after', lambda s: s.update(selection=None))
        class SealedCapture:
            def seal(self, trace, summary): return capsule, True
        c = SealedCapture();c.binding = binding
        with tempfile.TemporaryDirectory() as directory:
            report = grade_saved_return(c, directory, {}, world=w, task=task, reference=ref, **args)
            self.assertEqual(report['verdict'], 'inconclusive')
            self.assertEqual(json.loads((Path(directory)/'atomic-product-grade.private.json').read_text()), report)

    def test_once_only_saved_hook_does_not_repair_answer(self):
        from .atomic_product_execution import grade_saved_return
        w, task, ref, args, binding, capsule = fixture('read_listed_price')
        class SealedCapture:
            calls = 0
            def seal(self, trace, summary):
                self.calls += 1
                if self.calls > 1: raise ValueError('already sealed')
                return capsule, True
        c = SealedCapture();c.binding = binding
        with tempfile.TemporaryDirectory() as directory:
            report = grade_saved_return(c, directory, {}, world=w, task=task, reference=ref, **args)
            self.assertEqual(report['verdict'], 'inconclusive')
            self.assertTrue((Path(directory)/'atomic-product-grade.private.json').is_file())
            with self.assertRaises(ValueError):
                grade_saved_return(c, directory, {}, world=w, task=task, reference=ref, **args)


if __name__ == '__main__':
    unittest.main()
