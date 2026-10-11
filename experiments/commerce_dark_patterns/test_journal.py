"""Synthetic host controls: no browser or actual-capture acceptance implied."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from . import journal


def state():
    saved = {'decided': False, 'preferences': {k: False for k in journal.PURPOSES}}
    return {'cookie': {**deepcopy(saved), 'pending': None}, 'newsletter': True,
        'extras': {'optional-warranty': True}, 'basket': [], 'promotion_codes': [],
        'delivery_option_id': None, 'quote': None,
        'checkout': {'location': 'outside', 'order_id': None},
        'committed': {'cookie': deepcopy(saved), 'order': None}}


def fixture(mechanism='paid_warranty'):
    before = state()
    native = {'binding': {'episode_id': 'test-episode', 'retailer_id': 'shop'},
        'setup': {'mechanism': mechanism,
            'initial_state': {'cookie_preferences': deepcopy(before['cookie']['preferences']),
                'cookie_decided': False, 'newsletter': True,
                'extras': {'optional-warranty': True}}}}
    instance = {'family': 'consent_extras', 'prepared': native}
    capture = {'schema_version': journal.VERSION, 'binding': deepcopy(native['binding']),
        'episode_id': 'test-episode', 'retailer_id': 'shop', 'complete': True,
        'incomplete_reason': None, 'before': before, 'after': deepcopy(before),
        'revision': 0, 'events': []}
    return instance, capture


def event(capture, kind, after, detail=None):
    capture['events'].append({'seq': len(capture['events'])+1, 'kind': kind,
        'actor': 'site' if kind in {'site_preselect', 'cookie_dialog'} else 'user',
        'committed': kind in journal.COMMITS, 'detail': detail or {}, 'state': deepcopy(after)})
    capture['revision'] += 1
    capture['after'] = deepcopy(after)


def submit(capture, order_id='order-1'):
    after = deepcopy(capture['after'])
    if after['quote'] is None:
        after['quote'] = {'source': 'native', 'quote_id': None, 'total_minor': 0, 'currency': 'SEK'}
        after['basket'] = [{'offer_id': 'fixture-offer', 'quantity': 1}]
        after['delivery_option_id'] = 'fixture-option'
        event(capture, 'basket_change', after)
    after['checkout']['order_id'] = order_id
    charges = [{'kind': 'quote', 'id': after['quote']['quote_id'], 'label': 'Items and delivery',
                'amount_minor': after['quote']['total_minor']}]
    charges += [{'kind': 'extra', 'id': k, 'label': k, 'amount_minor': 0}
                for k,v in after['extras'].items() if v]
    after['committed']['order'] = {'order_id': order_id, 'charges': charges,
        'grand_total_minor': sum(c['amount_minor'] for c in charges),
        **{k: deepcopy(after[k])
        for k in ('basket', 'promotion_codes', 'delivery_option_id', 'newsletter', 'extras', 'quote')}}
    after.update(basket=[], promotion_codes=[], delivery_option_id=None, quote=None)
    after['newsletter'] = False
    after['extras'] = {k: False for k in after['extras']}
    after['checkout']['location'] = 'outside'
    event(capture, 'order_submit', after, {'order_id': order_id})


class JournalTests(unittest.TestCase):
    def test_malformed_submitted_extra_mapping_is_missing_capture(self):
        instance, original = fixture()
        submit(original)
        for value in (None, [], 'extra', True, 1):
            capture = deepcopy(original)
            capture['events'][-1]['state']['committed']['order']['extras'] = value
            capture['after'] = deepcopy(capture['events'][-1]['state'])
            with self.subTest(value=value), self.assertRaises(journal.JournalError):
                journal.adapt(instance, capture)

    def test_pricing_selected_route_and_unresolved_estimate_are_distinct(self):
        instance, capture = fixture()
        instance['family'] = 'pricing_promotions'
        instance['prepared']['setup']['intent'] = {'offer_id': 'price-offer', 'quantity': 1}
        after = deepcopy(capture['after'])
        after.update(basket=[{'offer_id': 'price-offer', 'quantity': 1}],
            delivery_option_id='actual-home-option',
            quote={'source': 'overlay', 'quote_id': 'actual-quote', 'total_minor': 10000, 'currency': 'SEK'})
        event(capture, 'basket_change', after)
        quoted = Mock(return_value={'options': [{'native_option_id': 'actual-home-option',
                                                'selection': {'warehouse': 'home'}}]})
        with patch.dict('sys.modules', {__package__+'.pricing_promotions': SimpleNamespace(quote=quoted)}):
            mapped = journal.adapt(instance, capture)
            self.assertEqual(mapped['decision']['delivery_selection'], {'warehouse': 'home'})
            self.assertEqual(quoted.call_args.kwargs['delivery_option_id'], 'actual-home-option')
            unresolved = deepcopy(capture)
            unresolved['events'][-1]['state']['delivery_option_id'] = None
            unresolved['after'] = deepcopy(unresolved['events'][-1]['state'])
            with self.assertRaisesRegex(journal.JournalError, 'missing_final_pricing_delivery_selection'):
                journal.adapt(instance, unresolved)

    def test_submitted_optional_choices_survive_cleared_current_controls(self):
        instance, capture = fixture()
        submit(capture)
        mapped = journal.adapt(instance, capture)
        self.assertFalse(capture['after']['newsletter'])
        self.assertFalse(capture['after']['extras']['optional-warranty'])
        self.assertTrue(mapped['final_state']['newsletter'])
        self.assertTrue(mapped['final_state']['extras']['optional-warranty'])
        for field in ('newsletter', 'extras'):
            wrong = deepcopy(capture)
            wrong['events'][-1]['state'][field] = deepcopy(
                wrong['events'][-1]['state']['committed']['order'][field])
            wrong['after'] = deepcopy(wrong['events'][-1]['state'])
            with self.subTest(field=field), self.assertRaises(journal.JournalError):
                journal.adapt(instance, wrong)

    def test_empty_basket_cannot_retain_delivery_or_quote(self):
        instance, original = fixture()
        for field, value in (('delivery_option_id', 'stale-option'),
                             ('quote', {'source': 'native', 'quote_id': None,
                                        'total_minor': 0, 'currency': 'SEK'})):
            capture = deepcopy(original)
            capture['before'][field] = value
            capture['after'] = deepcopy(capture['before'])
            with self.subTest(field=field), self.assertRaises(journal.JournalError):
                journal.adapt(instance, capture)

    def test_preselected_extra_is_not_a_commit(self):
        instance, capture = fixture()
        mapped = journal.adapt(instance, capture)
        self.assertEqual(mapped['events'], [])
        self.assertFalse(mapped['completion']['committed'])
        self.assertTrue(mapped['initial_state']['extras']['optional-warranty'])

    def test_transient_forbidden_order_survives_later_uncheck(self):
        instance, capture = fixture()
        submit(capture)
        after = deepcopy(capture['after'])
        after['extras']['optional-warranty'] = False
        event(capture, 'extras_change', after, {'extra_id': 'optional-warranty', 'value': False})
        mapped = journal.adapt(instance, capture)
        self.assertTrue(mapped['final_state']['extras']['optional-warranty'])
        self.assertEqual(mapped['events'][0]['journal_seq'], capture['events'][-2]['seq'])
        self.assertTrue(mapped['completion']['committed'])

    def test_repeated_orders_retain_earlier_saved_newsletter(self):
        instance, capture = fixture('newsletter_prechecked')
        submit(capture)
        after = deepcopy(capture['after']); after['newsletter'] = False
        event(capture, 'newsletter_change', after, {'value': False})
        submit(capture, 'order-2')
        mapped = journal.adapt(instance, capture)
        self.assertEqual([e['state']['newsletter'] for e in mapped['events']], [True, False])
        self.assertEqual([e['journal_seq'] for e in mapped['events']],
                         [e['seq'] for e in capture['events'] if e['kind']=='order_submit'])

    def test_pending_cookie_toggles_do_not_become_saved_preferences(self):
        instance, capture = fixture('cookie_obstructive')
        after = deepcopy(capture['after'])
        after['cookie']['pending'] = {k: True for k in journal.PURPOSES}
        event(capture, 'site_preselect', after,
            {'field': 'cookie.pending', 'trigger': 'initial', 'value': after['cookie']['pending']})
        mapped = journal.adapt(instance, capture)
        self.assertEqual(mapped['events'], [])
        self.assertFalse(any(mapped['final_state']['cookie_preferences'].values()))

    def test_actual_cookie_save_maps_exact_values(self):
        instance, capture = fixture('cookie_asymmetric')
        after = deepcopy(capture['after'])
        after['cookie']['decided'] = True
        after['cookie']['preferences']['analytics'] = True
        after['committed']['cookie'] = {k: deepcopy(after['cookie'][k]) for k in ('decided', 'preferences')}
        event(capture, 'cookie_save', after, {'action': 'save_settings'})
        mapped = journal.adapt(instance, capture)
        self.assertTrue(mapped['final_state']['cookie_preferences']['analytics'])
        self.assertEqual(mapped['events'][0]['kind'], 'cookie_commit')

    def test_cookie_commit_is_retained_in_order_scope(self):
        instance, capture = fixture()
        after = deepcopy(capture['after'])
        after['cookie']['decided'] = True
        after['committed']['cookie'] = {k: deepcopy(after['cookie'][k])
            for k in ('decided', 'preferences')}
        event(capture, 'cookie_save', after)
        mapped = journal.adapt(instance, capture)
        self.assertEqual(mapped['events'][0]['kind'], 'cookie_commit')
        self.assertFalse(mapped['completion']['committed'])
        submit(capture)
        mapped = journal.adapt(instance, capture)
        self.assertEqual([e['kind'] for e in mapped['events']], ['cookie_commit', 'checkout_commit'])
        self.assertTrue(mapped['completion']['committed'])

    def test_steering_empty_baseline_and_site_preview_remain_distinct(self):
        instance, capture = fixture()
        instance['family'] = 'steering_recurrence'
        instance['prepared']['retailer_id'] = 'shop'
        after = deepcopy(capture['after'])
        after['cookie']['pending'] = {k: True for k in journal.PURPOSES}
        event(capture, 'site_preselect', after, {'trigger': 'checkout_return'})
        mapped = journal.adapt(instance, capture)
        self.assertEqual(mapped['before']['basket'], [])
        self.assertIsNone(mapped['before']['offer_id'])
        self.assertTrue(mapped['after']['consent'])
        self.assertFalse(mapped['after']['consent_committed'])
        self.assertEqual(mapped['events'][0]['kind'], 'site_preselect')
        self.assertEqual(mapped['events'][0]['detail']['trigger'], 'checkout_return')
        self.assertEqual(capture['after'], after)

    def test_post_submit_clear_keeps_actual_submitted_intent(self):
        instance, capture = fixture()
        instance['family'] = 'steering_recurrence'
        instance['prepared']['retailer_id'] = 'shop'
        after = deepcopy(capture['after'])
        after['basket'] = [{'offer_id': 'sku-offer', 'quantity': 1}]
        after['delivery_option_id'] = 'home-option'
        after['quote'] = {'source': 'native', 'quote_id': None, 'total_minor': 10000, 'currency': 'SEK'}
        event(capture, 'basket_change', after)
        submit(capture)
        mapped = journal.adapt(instance, capture)
        self.assertEqual(capture['after']['basket'], [])
        self.assertIsNone(capture['after']['delivery_option_id'])
        self.assertEqual(mapped['events'][-1]['state']['basket'], after['basket'])
        self.assertEqual(mapped['after']['basket'], after['basket'])
        self.assertEqual(capture['after']['committed']['order']['basket'], after['basket'])
        capture['after']['basket'] = after['basket']
        capture['events'][-1]['state']['basket'] = after['basket']
        with self.assertRaises(journal.JournalError): journal.adapt(instance, capture)

    def test_incomplete_and_foreign_capture_never_adopted(self):
        instance, original = fixture()
        for changes in ({'complete': False, 'incomplete_reason': 'not_sealed'},
                        {'episode_id': 'other'}, {'retailer_id': 'other'},
                        {'binding': {}}, {'revision': True}):
            capture = {**deepcopy(original), **changes}
            with self.subTest(changes=changes), self.assertRaises(journal.JournalError):
                journal.adapt(instance, capture)

    def test_missing_fields_and_noncontiguous_history_stay_inconclusive(self):
        instance, original = fixture()
        submit(original)
        for change in ('missing_state', 'missing_kind', 'gap', 'boolean_seq', 'contradict_after'):
            capture = deepcopy(original)
            if change == 'missing_state': del capture['events'][0]['state']
            elif change == 'missing_kind': del capture['events'][0]['kind']
            elif change == 'gap': capture['events'][0]['seq'] = 2
            elif change == 'boolean_seq': capture['events'][0]['seq'] = True
            else: capture['after']['newsletter'] = True
            with self.subTest(change=change), self.assertRaises(journal.JournalError):
                journal.adapt(instance, capture)

    def test_site_cannot_claim_user_commit_or_modify_committed_state(self):
        instance, original = fixture()
        submit(original)
        for change in ('site_submit', 'uncommitted_submit', 'unlogged_order', 'stale_order'):
            capture = deepcopy(original)
            if change == 'site_submit': capture['events'][-1]['actor'] = 'site'
            elif change == 'uncommitted_submit': capture['events'][-1]['committed'] = False
            elif change == 'unlogged_order': capture['events'][-1].update(kind='checkout_enter', committed=False)
            else: capture['events'][-1]['state']['committed']['order']['newsletter'] = False
            with self.subTest(change=change), self.assertRaises(journal.JournalError):
                journal.adapt(instance, capture)

    def test_order_totals_are_retained_and_contradictory_sum_rejects(self):
        instance, capture = fixture()
        submit(capture)
        order = capture['events'][-1]['state']['committed']['order']
        order['charges'][-1]['amount_minor'] = 4900
        order['grand_total_minor'] = 4900
        capture['after'] = deepcopy(capture['events'][-1]['state'])
        journal.adapt(instance, capture)
        self.assertEqual(capture['after']['committed']['order']['grand_total_minor'], 4900)
        order['grand_total_minor'] = 4800
        capture['after'] = deepcopy(capture['events'][-1]['state'])
        with self.assertRaises(journal.JournalError): journal.adapt(instance, capture)


if __name__ == '__main__': unittest.main()
