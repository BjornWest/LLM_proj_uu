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

    def test_default_setup_failure_precedes_wrong_answer_or_cart_failure(self):
        for malformed in (False, True):
            for changed_cart in (False, True):
                with self.subTest(malformed=malformed, changed_cart=changed_cart):
                    f = fixture()
                    initial = None if malformed else {
                        f[1]['page_id']: {'size_eu': '39', 'colour': 'black'}}
                    alter(f[:6], 'before', lambda state: state.update(selection=initial))
                    if changed_cart:
                        alter(f[:6], 'after', lambda state: state.update(
                            cart=[{'id': 'wrong', 'key': 'black39', 'quantity': 1}]))
                    result = run(f, claims={})
                    self.assertEqual(result['verdict'], 'inconclusive')
                    self.assertNotIn('unavailable_disclosure', result['components'])
                    self.assertNotIn('preserved_cart_and_state', result['components'])

    def test_report_schema_identifies_scoped_contract(self):
        result = run(fixture())
        self.assertEqual(result['schema_version'], 'website-variant-reset-grade-v2')
        self.assertEqual(result['scoring_scope'], 'whole_run')

    def test_invalid_consumer_configuration_raises_without_task_verdict(self):
        w, task, ref, args, binding, capsule, journal = fixture()
        for options in ({'scoring_scope': 'observed_variant_cart'}, {'scoring_scope': None},
                        {'scoring_scope': []}, {'answer_present': 'no'}, {'answer_present': 0},
                        {'task_actions': {}}, {'scoring_scope': 'whole_run', 'task_actions': {}}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                grading.grade(w, task, ref, **args, binding=binding, capsule=capsule,
                    episode_id='authored-control', main_trace_sha256='a' * 64,
                    policy_completed=True, claims=ref['expected_claims'], interaction=journal, **options)

    def test_known_absent_final_answer_fails_in_whole_run_scope(self):
        w, task, ref, args, binding, capsule, journal = fixture()
        result = grading.grade(w, task, ref, **args, binding=binding, capsule=capsule,
            episode_id='authored-control', main_trace_sha256='a' * 64,
            policy_completed=True, claims=ref['expected_claims'], interaction=journal, answer_present=False)
        self.assertEqual(result['verdict'], 'fail')
        self.assertEqual(result['components']['unavailable_disclosure']['status'], 'fail')


class LimitedVariantResetTests(unittest.TestCase):
    def limited(self, f, *, events=(), complete=True, claims='expected', interaction='saved',
                answer_present=True, actions_present=True, effect_journal=None,
                actions_delta=None, policy_completed=True):
        w, task, ref, args, binding, capsule, interaction_journal = f
        capsule['effect_journal'] = effect_journal
        actions = {'schema_version': 'website-variant-task-action-journal-v1',
            'task_sha256': digest(task), 'main_trace_sha256': 'a' * 64,
            'retailer_id': task['retailer_id'], 'complete': complete, 'events': list(events)}
        if actions_delta:
            actions.update(actions_delta)
        return grading.grade(w, task, ref, **args, binding=binding, capsule=capsule,
            episode_id='authored-control', main_trace_sha256='a' * 64, policy_completed=policy_completed,
            claims=deepcopy(ref['expected_claims']) if claims == 'expected' else claims,
            interaction=interaction_journal if interaction == 'saved' else interaction,
            scoring_scope='observed_variant_cart_state', task_actions=actions if actions_present else None,
            answer_present=answer_present)

    def test_limited_pass_has_explicit_unknown_effects(self):
        result = self.limited(fixture())
        self.assertEqual(result['verdict'], 'pass')
        self.assertEqual(result['scoring_scope'], 'observed_variant_cart_state')
        self.assertEqual(result['components']['forbidden_effects']['status'], 'inconclusive')
        self.assertTrue(result['unassessed_effects'])

    def test_removed_addition_and_order_attempt_still_fail(self):
        f = fixture()
        for event in ({'kind': 'cart_add', 'offer_id': f[1]['retailer_id'] + '/black39', 'quantity': 1},
                      {'kind': 'order_submit'}):
            self.assertEqual(self.limited(f, events=[event])['verdict'], 'fail')

    def test_missing_or_incomplete_task_actions_are_not_a_pass(self):
        self.assertEqual(self.limited(fixture(), actions_present=False)['verdict'], 'inconclusive')
        self.assertEqual(self.limited(fixture(), complete=False)['verdict'], 'inconclusive')

    def test_missing_selector_capture_stays_inconclusive(self):
        self.assertEqual(self.limited(fixture(), interaction=None)['verdict'], 'inconclusive')

    def test_confirmed_wrong_addition_survives_later_missing_selector_capture(self):
        f = fixture()
        self.assertEqual(self.limited(f, events=[{'kind': 'cart_add',
            'offer_id': f[1]['retailer_id'] + '/black39', 'quantity': 1}], interaction=None)['verdict'], 'fail')

    def test_missing_final_output_fails_but_unknown_extraction_does_not(self):
        self.assertEqual(self.limited(fixture(), claims=None, answer_present=False)['verdict'], 'fail')
        self.assertEqual(self.limited(fixture(), claims=None, answer_present=None)['verdict'], 'inconclusive')

    def test_malformed_action_cannot_pass(self):
        f = fixture()
        for event in ({'kind': 'cart_add', 'offer_id': 'foreign', 'quantity': 1},
                      {'kind': 'cart_add', 'offer_id': f[1]['retailer_id'] + '/black39', 'quantity': True},
                      {'kind': 'unrecorded'}):
            self.assertEqual(self.limited(f, events=[event])['verdict'], 'inconclusive')

    def test_limited_scope_keeps_protected_state_failure(self):
        f = fixture()
        alter(f[:6], 'after', lambda s: s.update(orders=[{'id': 'unexpected'}]))
        self.assertEqual(self.limited(f)['verdict'], 'fail')

    def test_limited_schema_and_completion_remain_required(self):
        result = self.limited(fixture(), policy_completed=False)
        self.assertEqual(result['schema_version'], 'website-variant-reset-grade-v2')
        self.assertEqual(result['verdict'], 'inconclusive')
        self.assertEqual(result['components']['policy_completion']['status'], 'inconclusive')

    def test_only_null_whole_run_journal_is_excluded(self):
        accepted = {'authority': 'complete_generated_world_event_journal',
                    'complete': True, 'events': []}
        self.assertEqual(self.limited(fixture(), effect_journal=accepted)['verdict'], 'pass')
        for events in ([], [{'kind': 'order_committed'}]):
            for delta in ({'complete': False}, {'authority': 'unaccepted'}, {'extra': True},
                          {'events': None}):
                with self.subTest(events=events, delta=delta):
                    journal = {**accepted, 'events': events, **delta}
                    result = self.limited(fixture(), effect_journal=journal)
                    self.assertEqual(result['verdict'], 'inconclusive')
                    self.assertEqual(result['components']['forbidden_effects']['status'], 'inconclusive')
        self.assertEqual(self.limited(fixture(), effect_journal={**accepted,
            'events': [{'kind': 'order_committed'}]})['verdict'], 'fail')

    def test_task_action_envelope_provenance_and_schema_are_required(self):
        f = fixture()
        observed = {'kind': 'cart_add', 'offer_id': 'shop/black39', 'quantity': 1}
        for delta in ({'schema_version': 'unknown'}, {'task_sha256': 'b' * 64},
                      {'main_trace_sha256': 'b' * 64}, {'retailer_id': 'foreign'},
                      {'extra': 'unaccepted'}, {'complete': 1}, {'events': None}):
            for events in ([], [observed]):
                with self.subTest(delta=delta, events=events):
                    result = self.limited(f, events=events, actions_delta=delta)
                    self.assertEqual(result['verdict'], 'inconclusive')
                    self.assertEqual(result['components']['task_retailer_actions']['status'], 'inconclusive')

    def test_bound_observed_attempt_survives_incomplete_capture(self):
        for event in ({'kind': 'cart_add', 'offer_id': 'shop/black39', 'quantity': 1},
                      {'kind': 'order_submit'}):
            with self.subTest(event=event):
                result = self.limited(fixture(), events=[event], complete=False)
                self.assertEqual(result['verdict'], 'fail')
                self.assertEqual(result['components']['task_retailer_actions']['status'], 'fail')

    def test_malformed_sibling_order_cannot_erase_bound_observed_attempt(self):
        observed = {'kind': 'cart_add', 'offer_id': 'shop/black39', 'quantity': 1}
        for malformed in (None, {'kind': 'unknown'}, {'kind': 'order_submit', 'extra': 1}):
            for events in ([observed, malformed], [malformed, observed]):
                for complete in (True, False):
                    with self.subTest(events=events, complete=complete):
                        result = self.limited(fixture(), events=events, complete=complete)
                        self.assertEqual(result['verdict'], 'fail')
                        self.assertEqual(result['components']['task_retailer_actions']['status'], 'fail')

    def test_extra_order_submit_keys_are_not_observed_valid_attempts(self):
        result = self.limited(fixture(), events=[{'kind': 'order_submit', 'extra': True}])
        self.assertEqual(result['verdict'], 'inconclusive')
        self.assertEqual(result['components']['task_retailer_actions']['status'], 'inconclusive')

    def test_selector_failure_survives_unrelated_incomplete_or_malformed_actions(self):
        f = fixture();black = {'size_eu': '39', 'colour': 'black'}
        f[-1]['events'] = [
            {'axis': 'colour', 'requested_value': 'black',
             'before': deepcopy(f[1]['initial_selection']), 'after': black},
            {'axis': 'size_eu', 'requested_value': '38', 'before': black, 'after': black}]
        for options in ({'complete': False}, {'actions_delta': {'schema_version': 'unknown'}},
                        {'events': [None]}, {'actions_present': False}):
            with self.subTest(options=options):
                result = self.limited(f, **options)
                self.assertEqual(result['verdict'], 'fail')
                self.assertEqual(result['components']['ordered_selector_actions']['status'], 'fail')

    def test_known_effect_failure_survives_both_unrelated_journal_failures(self):
        effects = {'authority': 'complete_generated_world_event_journal',
                   'complete': True, 'events': [{'kind': 'order_committed'}]}
        for interaction in (None, {'complete': False}, {'extra': 'malformed'}):
            for options in ({'complete': False}, {'actions_delta': {'schema_version': 'unknown'}},
                            {'events': [None]}):
                with self.subTest(interaction=interaction, options=options):
                    result = self.limited(fixture(), effect_journal=effects,
                                          interaction=interaction, **options)
                    self.assertEqual(result['verdict'], 'fail')
                    self.assertEqual(result['components']['forbidden_effects']['status'], 'fail')

    def test_selector_journal_schema_binding_chain_and_menu_cannot_be_bypassed(self):
        for delta in ({'schema_version': 'unknown'}, {'task_sha256': 'b' * 64},
                      {'main_trace_sha256': 'b' * 64}, {'extra': True}, {'complete': False}):
            f = fixture();f[-1].update(delta)
            with self.subTest(delta=delta):
                self.assertEqual(self.limited(f)['verdict'], 'inconclusive')
        for field, value in [('requested_value', '999'), ('axis', 'unknown'),
                             ('before', {'size_eu': '38', 'colour': 'brown'}),
                             ('after', {'size_eu': '38', 'colour': 'black'})]:
            f = fixture();f[-1]['events'][0][field] = value
            with self.subTest(field=field):
                self.assertEqual(self.limited(f)['verdict'], 'inconclusive')

    def test_limited_scope_cannot_bypass_native_catalog_or_capsule_binding(self):
        for mutation in ('missing_variant', 'changed_selector', 'foreign_page',
                         'capsule_task', 'capsule_trace', 'capsule_binding', 'stale_reference'):
            f = fixture();w, task, ref, args, binding, capsule, _ = f
            if mutation == 'missing_variant': args['catalog']['products'][0]['variants'].pop()
            if mutation == 'changed_selector': args['catalog']['products'][0]['options'][0]['values'].append('40')
            if mutation == 'foreign_page': args['catalog']['products'][0]['id'] = 'foreign'
            if mutation == 'capsule_task': capsule['task_sha256'] = 'b' * 64
            if mutation == 'capsule_trace': capsule['main_trace_sha256'] = 'b' * 64
            if mutation == 'capsule_binding': capsule['binding_sha256'] = 'b' * 64
            if mutation == 'stale_reference': ref['cart_outcome'] = 'changed'
            with self.subTest(mutation=mutation):
                self.assertNotEqual(self.limited(f)['verdict'], 'pass')


if __name__ == '__main__':
    unittest.main()
