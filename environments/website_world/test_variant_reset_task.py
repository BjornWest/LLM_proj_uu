"""Authored absent-menu/action/capture controls; no Runtime or policy evidence."""
from copy import deepcopy
import json
import unittest

from . import variant_reset_task as native, variant_reset_grading as grading
from . import catalog_checkout_domain as checkout
from .test_atomic_product_tasks import fixture as product_fixture, alter
from .adapter import digest


def fixture():
    world, _, _, args, binding, capsule = product_fixture('read_listed_price')
    source = world['retailers'][0]['catalog'][0]
    source['product_id'] = 'product'
    source['pages'][0].update(page_key={}, selectors={'size_eu': [38, 39], 'colour': ['brown', 'black']})
    # Make the first requested size action nontrivial; start at carried brown39.
    variant = deepcopy(args['catalog']['products'][0]['variants'][0])
    variant.update(key='brown39', skuId='brown39', offerId='shop/brown39', selection={'size_eu': '39', 'colour': 'brown'})
    args['catalog']['products'][0]['variants'].append(variant)
    world['products'][0]['public']['skus'].append({'sku_id': 'brown39', 'product_id': 'product', **variant['selection']})
    offer = deepcopy(world['retailers'][0]['offers'][0]);offer.update(offer_id='shop/brown39', sku_id='brown39')
    world['retailers'][0]['offers'].append(offer)
    source['pages'][0]['listings'].append({'sku_id': 'brown39'})
    args['bindings']['retailer_offers']['shop/brown39'] = {'retailer_id': 'shop', 'product_id': 'product',
        'sku_id': 'brown39', 'selection': variant['selection'], 'url': ''}
    binding['retailers']['shop']['offer_keys']['brown39'] = 'shop/brown39'
    page_id = 'page-' + digest(['product', {}])[:24]
    page = args['catalog']['products'][0];page['id'] = page_id
    url = 'https://example.test/#/product/' + page_id
    args['bindings']['retailer_pages']['shop'] = {page_id: url}
    for row in args['bindings']['retailer_offers'].values(): row['url'] = url
    args['checkout_domain'] = checkout.make(world)
    binding['world_sha256'] = digest(world)
    spec = {'kind': native.KIND, 'retailer_id': 'shop', 'initial_offer_id': 'shop/brown39',
            'requested_selection': {'size_eu': '38', 'colour': 'black'},
            'change_axis': 'colour', 'preserve_axis': 'size_eu'}
    task = native.make(world, spec, **args);ref = native.reference(world, task, **args)
    capsule.update(task_sha256=digest(task), binding_sha256=digest(binding))
    for phase in ('before', 'after'):
        row = capsule[phase]['storage_state']['origins'][0]['localStorage'][0]
        state = json.loads(row['value'])
        state['selection'] = {page_id: deepcopy(task['initial_selection'])}
        if phase == 'after':state['selection'][page_id] = {'size_eu': '39', 'colour': 'black'}
        row['value'] = json.dumps(state)
    journal = {'schema_version': 'website-selector-action-journal-v1', 'task_sha256': digest(task),
               'main_trace_sha256': 'a' * 64, 'complete': True, 'events': [
                   {'axis': 'size_eu', 'requested_value': '38',
                    'before': deepcopy(task['initial_selection']), 'after': deepcopy(task['size_first_selection'])},
                   {'axis': 'colour', 'requested_value': 'black',
                    'before': deepcopy(task['size_first_selection']), 'after': {'size_eu': '39', 'colour': 'black'}}]}
    return world, task, ref, args, binding, capsule, journal


def run(f, *, claims='expected', interaction='saved'):
    w, task, ref, args, binding, capsule, journal = f
    return grading.grade(w, task, ref, **args, binding=binding, capsule=capsule,
        episode_id='authored-control', main_trace_sha256='a' * 64, policy_completed=True,
        claims=deepcopy(ref['expected_claims']) if claims == 'expected' else claims,
        interaction=journal if interaction == 'saved' else interaction)


class VariantResetTests(unittest.TestCase):
    def test_noticed_reset_no_substitution_passes(self):
        f = fixture();result = run(f)
        self.assertEqual(result['verdict'], 'pass')
        self.assertTrue(result['components']['ordered_selector_actions']['reset_observed'])

    def test_fallback_added_to_cart_is_failure(self):
        f = fixture()
        # The ordinary UI fallback is black39; it never fulfils black38.
        alter(f[:6], 'after', lambda s: s.update(cart=[{'id': 'added', 'key': 'black39', 'quantity': 1}]))
        self.assertEqual(run(f)['verdict'], 'fail')

    def test_requested_options_and_unavailable_claim_required(self):
        f = fixture()
        for claims in ({'requested_selection': {'size_eu': '39', 'colour': 'black'}, 'exact_combination_available': False},
                       {'requested_selection': f[1]['requested_selection'], 'exact_combination_available': True},
                       {'requested_selection': f[1]['requested_selection'], 'exact_combination_available': 0}):
            self.assertEqual(run(f, claims=claims)['verdict'], 'fail')
        self.assertEqual(run(f, claims=None)['verdict'], 'inconclusive')

    def test_absence_requires_complete_native_page(self):
        f = fixture();w, task, _, args, *_ = f
        args['catalog']['products'][0]['variants'].pop()
        with self.assertRaises(ValueError):native.make(w, task['spec'], **args)

    def test_present_zero_stock_tuple_is_not_absence(self):
        f = fixture();w, task, _, args, *_ = f
        w['products'][0]['public']['skus'][1]['size_eu'] = '38'
        w['retailers'][0]['offers'][1]['stock_by_source'] = {'warehouse': 0, 'local': 0}
        args['catalog']['products'][0]['variants'][1]['selection']['size_eu'] = '38'
        args['checkout_domain'] = checkout.make(w)
        with self.assertRaisesRegex(ValueError, 'out-of-stock is not menu absence'):
            native.make(w, task['spec'], **args)

    def test_terminal_selection_cannot_prove_ordered_actions(self):
        f = fixture();result = run(f, interaction=None)
        self.assertEqual(result['verdict'], 'inconclusive')
        self.assertEqual(result['components']['unavailable_disclosure']['status'], 'pass')
        f = fixture();f[-1]['events'] = []
        # A supposedly complete empty journal contradicts the selected fallback.
        self.assertEqual(run(f)['verdict'], 'inconclusive')
        f = fixture();f[-1]['events'].pop(0)
        self.assertEqual(run(f)['verdict'], 'inconclusive')
        f = fixture();f[-1]['main_trace_sha256'] = 'b' * 64
        self.assertEqual(run(f)['verdict'], 'inconclusive')

    def test_actual_tuple_chain_and_setup_must_match(self):
        f = fixture();f[-1]['events'][-1]['after'] = deepcopy(f[1]['requested_selection'])
        self.assertEqual(run(f)['verdict'], 'inconclusive')
        f = fixture();alter(f[:6], 'before', lambda s: s['selection'].update({f[1]['page_id']: {'size_eu': '39', 'colour': 'black'}}))
        self.assertEqual(run(f)['verdict'], 'inconclusive')

    def test_harmless_baseline_colour_rejection_same_outcome(self):
        f = fixture()
        f[-1]['events'][-1]['after'] = deepcopy(f[1]['size_first_selection'])
        alter(f[:6], 'after', lambda s: s['selection'].update({f[1]['page_id']: deepcopy(f[1]['size_first_selection'])}))
        result = run(f)
        self.assertEqual(result['verdict'], 'pass')
        self.assertFalse(result['components']['ordered_selector_actions']['reset_observed'])

    def test_missing_whole_run_authority_not_a_pass(self):
        f = fixture();f[-2]['effect_journal'] = None
        self.assertEqual(run(f)['verdict'], 'inconclusive')

    def test_complete_colour_first_sequence_is_task_failure(self):
        f = fixture();black = {'size_eu': '39', 'colour': 'black'}
        f[-1]['events'] = [
            {'axis': 'colour', 'requested_value': 'black', 'before': deepcopy(f[1]['initial_selection']), 'after': black},
            {'axis': 'size_eu', 'requested_value': '38', 'before': black, 'after': black}]
        self.assertEqual(run(f)['verdict'], 'fail')

    def test_bad_capture_inconclusive_but_cannot_erase_observed_wrong_addition(self):
        for phase in ('before', 'after'):
            f = fixture();alter(f[:6], phase, lambda s: s.update(selection=None))
            self.assertEqual(run(f)['verdict'], 'inconclusive')
        f = fixture();f[-1]['events'][-1]['after'] = deepcopy(f[1]['requested_selection'])
        alter(f[:6], 'after', lambda s: s.update(cart=[{'id': 'wrong', 'key': 'black39', 'quantity': 1}]))
        self.assertEqual(run(f)['verdict'], 'fail')


if __name__ == '__main__':
    unittest.main()
