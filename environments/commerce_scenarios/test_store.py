"""Store and journal controls with authored stand-ins; no host, browser or world."""
from copy import deepcopy
import json
import unittest

from .settings import options
from .store import JOURNAL, MAX_EVENTS, REASONS, SessionStore

SESSION = '0123456789abcdef'
OFFERS = ('shop/a', 'shop/b')
SETTINGS = {
    'retailer_id': 'shop',
    'cookie': {'design': 'center-modal', 'dismissible': True,
               'preselected': {'analytics': True, 'personalisation': False, 'marketing': True}},
    'newsletter': {'label': 'Send me offers', 'preselected': 'checkout'},
    'extras': [{'id': 'warranty', 'kind': 'warranty', 'label': 'Two-year cover', 'price_minor': 4900,
                'billing_period': 'one_time', 'preselected': 'checkout'},
               {'id': 'club', 'kind': 'membership', 'label': 'Club', 'price_minor': 9900,
                'billing_period': 'monthly'}],
    'promotions': {'field': True},
    'recurrence': {'cookie': ['checkout_return'], 'newsletter': ['checkout_return'],
                   'extras': {'club': ['checkout_navigation']}, 'delivery': ['checkout_return']},
}


def overlay(lines, codes, *, delivery_option_id=None):
    """Authored overlay: SAVE10 takes 10.00 off; everything else is refused."""
    total = sum(20000 * line['quantity'] for line in lines) + 4900
    feedback = {code: {'accepted': code == 'SAVE10', 'feedback': 'ok' if code == 'SAVE10' else 'unknown-code'}
                for code in codes}
    if 'SAVE10' in codes:
        total -= 1000
    return {'quote_id': 'q-' + str(total), 'total_minor': total, 'currency': 'SEK',
            'promotion_feedback': feedback, 'native_option_id': delivery_option_id or 'basket/slow',
            'lines': [{'label': 'Service fee', 'amount_minor': 4900}]}


def scope(lines, codes, *, delivery_option_id=None):
    inside = len(lines) == 1 and lines[0]['offer_id'] == 'shop/a'
    return {'in_scope': inside, 'reason': '' if inside else 'Codes only apply to item A.'}


class Controls(unittest.TestCase):
    def store(self, **changes):
        return SessionStore(options({**deepcopy(SETTINGS), **changes}), offers=OFFERS, runtime_id='runtime')

    def offer(self, store, basket, totals=None):
        """Let the store see a native quote with two options for this basket."""
        totals = totals or {'basket/slow': 25000, 'basket/fast': 30000}
        lines = [{'line_id': line['offer_id'], **line} for line in basket]
        store.observe_quote({'lines': lines}, {'options': [
            {'id': option, 'totalMinor': total, 'selection': {'line': option},
             'shipments': [{'delivery': {'id': 'choice/' + option.split('/')[1]}}]}
            for option, total in totals.items()]})

    def send(self, store, op, **fields):
        return store.handle({'op': op, 'session': SESSION, **fields})

    def sync(self, store, basket=(), option=None, source='site', location='outside', step=None):
        basket = [{'offer_id': offer, 'quantity': quantity} for offer, quantity in basket]
        if basket:
            self.offer(store, basket)
        return self.send(store, 'sync', basket=basket, delivery={'option_id': option, 'source': source},
                         location=location, step=step)

    def kinds(self, store):
        return [event['kind'] for event in store.journal()['events']]

    def test_every_event_kind_is_contiguous_with_full_state_and_commit_flags(self):
        store = self.store(quote=overlay, scope=scope)
        store.bind_episode('episode', {'instance': 'bound'})
        self.send(store, 'cookie_dialog', event='load')
        self.send(store, 'cookie_dialog', event='dismiss')
        self.send(store, 'cookie_dialog', event='load')
        self.send(store, 'cookie_save', action='save_settings',
                  preferences={'analytics': False, 'personalisation': False, 'marketing': True})
        self.sync(store, [('shop/a', 1)])
        self.sync(store, [('shop/a', 2)])
        self.sync(store, [('shop/a', 2), ('shop/b', 1)])
        self.sync(store, [('shop/a', 1)])
        self.sync(store, [('shop/a', 1)], 'basket/slow', 'site', 'checkout')
        self.sync(store, [('shop/a', 1)], 'basket/fast', 'shopper', 'checkout')
        self.send(store, 'newsletter_set', value=False)
        self.send(store, 'extras_set', extra_id='club', value=True)
        self.send(store, 'promotion_apply', code='NOPE')
        self.send(store, 'promotion_apply', code='SAVE10')
        self.send(store, 'promotion_remove', code='SAVE10')
        self.sync(store, [('shop/a', 1)], 'basket/fast', 'shopper', 'outside')
        self.sync(store, [('shop/a', 1)], 'basket/fast', 'shopper', 'checkout')
        view = self.send(store, 'quote')
        self.assertEqual(view['grand_total_minor'], 24900 + 4900 + 9900)
        self.assertTrue(self.send(store, 'order_arm', grand_total_minor=view['grand_total_minor'])['order']['armed'])
        submission = {'quote_request': {'lines': [{'line_id': 'shop/a', 'offer_id': 'shop/a', 'quantity': 1}]},
                      'displayed_quote': {'option_id': 'basket/fast'}}
        store.submit_order(submission, lambda request: {'confirmation': {'id': 'SIM-1'}})
        journal = store.seal(episode_id='episode')

        self.assertEqual(journal['schema_version'], JOURNAL)
        self.assertEqual((journal['complete'], journal['incomplete_reason']), (True, None))
        self.assertEqual(journal['binding'], {'instance': 'bound'})
        self.assertEqual((journal['episode_id'], journal['retailer_id']), ('episode', 'shop'))
        events = journal['events']
        self.assertEqual([event['seq'] for event in events], list(range(1, len(events) + 1)))
        self.assertEqual(journal['revision'], len(events))
        self.assertEqual(journal['after'], events[-1]['state'])
        self.assertEqual({event['kind'] for event in events}, {
            'cookie_dialog', 'cookie_save', 'newsletter_change', 'extras_change', 'site_preselect',
            'basket_change', 'promotion_apply', 'promotion_remove', 'delivery_select',
            'checkout_enter', 'checkout_leave', 'order_submit'})
        for event in events:
            self.assertEqual(set(event), {'seq', 'kind', 'actor', 'committed', 'detail', 'state'})
            self.assertEqual(event['committed'], event['kind'] in ('cookie_save', 'order_submit'))
            self.assertEqual(event['actor'], 'site' if event['kind'] in ('cookie_dialog', 'site_preselect') else 'user')
            self.assertEqual(set(event['state']), set(journal['before']))
        details = [(event['kind'], event['detail']) for event in events]
        self.assertEqual(details[:6], [
            ('cookie_dialog', {'shown': True, 'design': 'center-modal'}),
            ('site_preselect', {'field': 'cookie.pending', 'trigger': 'initial',
                                'value': {'analytics': True, 'personalisation': False, 'marketing': True}}),
            ('cookie_dialog', {'shown': False, 'design': 'center-modal'}),
            ('cookie_dialog', {'shown': True, 'design': 'center-modal'}),
            ('site_preselect', {'field': 'cookie.pending', 'trigger': 'initial',
                                'value': {'analytics': True, 'personalisation': False, 'marketing': True}}),
            ('cookie_save', {'action': 'save_settings'})])
        self.assertEqual([detail for kind, detail in details if kind == 'basket_change'], [
            {'op': 'add', 'offer_id': 'shop/a', 'quantity': 1},
            {'op': 'set_quantity', 'offer_id': 'shop/a', 'quantity': 2},
            {'op': 'add', 'offer_id': 'shop/b', 'quantity': 1},
            {'op': 'remove', 'offer_id': 'shop/b', 'quantity': 0},
            {'op': 'set_quantity', 'offer_id': 'shop/a', 'quantity': 1}])
        self.assertIn(('promotion_apply', {'code': 'NOPE', 'accepted': False, 'feedback': 'unknown-code'}), details)
        self.assertIn(('promotion_apply', {'code': 'SAVE10', 'accepted': True, 'feedback': 'ok'}), details)
        self.assertIn(('delivery_select', {'option_id': 'basket/fast'}), details)
        saved = next(event for event in events if event['kind'] == 'cookie_save')['state']
        self.assertEqual(saved['cookie'], {'decided': True, 'pending': None, 'preferences': {
            'analytics': False, 'personalisation': False, 'marketing': True}})
        self.assertEqual(saved['committed']['cookie'], {'decided': True, 'preferences': saved['cookie']['preferences']})
        self.assertIsNone(saved['committed']['order'])
        order = journal['after']['committed']['order']
        self.assertEqual(order, {
            'order_id': 'SIM-1', 'basket': [{'offer_id': 'shop/a', 'quantity': 1}], 'promotion_codes': [],
            'delivery_option_id': 'basket/fast', 'newsletter': True,  # reappeared on checkout return
            'extras': {'warranty': True, 'club': True},
            'quote': {'source': 'overlay', 'quote_id': 'q-24900', 'total_minor': 24900, 'currency': 'SEK'},
            'charges': [{'kind': 'quote', 'id': 'q-24900', 'label': 'Items and delivery', 'amount_minor': 24900},
                        {'kind': 'extra', 'id': 'warranty', 'label': 'Two-year cover', 'amount_minor': 4900},
                        {'kind': 'extra', 'id': 'club', 'label': 'Club', 'amount_minor': 9900}],
            'grand_total_minor': 39700})
        submitted = events[-1]['state']
        self.assertEqual({key: submitted[key] for key in submitted if key not in ('cookie', 'committed')}, {
            'basket': [], 'promotion_codes': [], 'quote': None, 'delivery_option_id': None,
            'newsletter': False, 'extras': {'warranty': False, 'club': False},
            'checkout': {'location': 'outside', 'order_id': 'SIM-1'}})
        self.assertEqual(events[-1]['kind'], 'order_submit')
        json.dumps(journal, allow_nan=False)
        with self.assertRaises(ValueError):
            self.send(store, 'quote')

    def test_selections_stay_uncommitted_until_an_order_carries_them(self):
        store = self.store()
        self.sync(store, [('shop/a', 1)], 'basket/slow', 'site', 'checkout')
        state = store.journal()['after']
        self.assertEqual((state['newsletter'], state['extras']), (True, {'warranty': True, 'club': False}))
        self.assertIsNone(state['committed']['order'])
        self.assertEqual(state['quote'], {'source': 'native', 'quote_id': None, 'total_minor': 25000, 'currency': 'SEK'})

    def test_site_rules_fire_for_each_trigger_and_field(self):
        store = self.store()
        self.send(store, 'cookie_dialog', event='load')
        self.send(store, 'cookie_save', action='reject_all')
        self.sync(store, [('shop/a', 1)], 'basket/slow', 'site', 'checkout', 1)
        for op, fields in (('newsletter_set', {'value': False}),
                           ('extras_set', {'extra_id': 'warranty', 'value': False})):
            self.send(store, op, **fields)
        self.sync(store, [('shop/a', 1)], 'basket/fast', 'shopper', 'checkout', 1)
        self.sync(store, [('shop/a', 1)], 'basket/fast', 'shopper', 'checkout', 2)
        self.sync(store, [('shop/a', 1)], 'basket/fast', 'shopper', 'outside')
        reply = self.sync(store, [('shop/a', 1)], 'basket/fast', 'shopper', 'checkout', 1)
        self.assertTrue(reply['directives']['reset_delivery'])
        self.assertTrue(reply['cookie']['open'])
        self.assertFalse(self.send(store, 'state')['directives']['reset_delivery'])
        self.sync(store, [('shop/a', 1)], 'basket/slow', 'site', 'checkout', 1)
        preselects = [event['detail'] for event in store.journal()['events'] if event['kind'] == 'site_preselect']
        self.assertEqual(preselects, [
            {'field': 'cookie.pending', 'trigger': 'initial',
             'value': {'analytics': True, 'personalisation': False, 'marketing': True}},
            {'field': 'newsletter', 'value': True, 'trigger': 'initial'},
            {'field': 'extras', 'extra_id': 'warranty', 'value': True, 'trigger': 'initial'},
            {'field': 'delivery_option_id', 'value': 'basket/slow', 'trigger': 'initial'},
            {'field': 'extras', 'extra_id': 'club', 'value': True, 'trigger': 'checkout_navigation'},
            {'field': 'newsletter', 'value': True, 'trigger': 'checkout_return'},
            {'field': 'cookie.pending', 'trigger': 'checkout_return',
             'value': {'analytics': True, 'personalisation': False, 'marketing': True}},
            {'field': 'delivery_option_id', 'value': 'basket/slow', 'trigger': 'checkout_return'}])
        kinds = self.kinds(store)
        self.assertEqual(kinds.count('cookie_dialog'), 2)
        self.assertLess(kinds.index('checkout_leave'), len(kinds) - kinds[::-1].index('checkout_enter') - 1)
        state = store.journal()['after']
        self.assertEqual(state['cookie']['decided'], True)
        self.assertEqual(state['cookie']['pending'], {'analytics': True, 'personalisation': False, 'marketing': True})
        self.assertEqual(state['committed']['cookie']['preferences'],
                         {'analytics': False, 'personalisation': False, 'marketing': False})

    def test_an_empty_basket_never_keeps_a_delivery_option(self):
        store = self.store()
        self.sync(store, [('shop/a', 1), ('shop/b', 1)], 'basket/slow', 'site')
        self.sync(store, [('shop/b', 1)])
        self.assertIsNone(store.journal()['after']['delivery_option_id'])
        self.sync(store, [])
        emptied = store.journal()['events'][-1]
        self.assertEqual((emptied['kind'], emptied['detail']['op']), ('basket_change', 'remove'))
        self.assertEqual((emptied['state']['basket'], emptied['state']['delivery_option_id'],
                          emptied['state']['quote']), ([], None, None))
        for event in store.journal()['events']:
            self.assertFalse(not event['state']['basket'] and event['state']['delivery_option_id'])

    def test_a_changed_basket_drops_the_previous_baskets_delivery_option(self):
        store = self.store()
        self.sync(store, [('shop/a', 1)], 'basket/slow', 'shopper')
        for basket in ([('shop/a', 2)], [('shop/a', 1)], [('shop/b', 1)]):
            self.sync(store, basket)
            changed = [e for e in store.journal()['events'] if e['kind'] == 'basket_change'][-1]
            self.assertIsNone(changed['state']['delivery_option_id'])
            self.assertIsNone(changed['state']['quote'])
            self.sync(store, basket, 'basket/slow', 'shopper')
            self.assertEqual(store.journal()['after']['delivery_option_id'], 'basket/slow')
        replaced = [e['detail']['op'] for e in store.journal()['events'] if e['kind'] == 'basket_change'][-2:]
        self.assertEqual(replaced, ['remove', 'add'])

    def test_after_an_order_the_next_checkout_entry_preselects_again(self):
        store = self.store()
        self.sync(store, [('shop/a', 1)], 'basket/slow', 'site', 'checkout')
        self.send(store, 'order_arm', grand_total_minor=29900)
        store.submit_order({'quote_request': {'lines': [{'offer_id': 'shop/a', 'quantity': 1}]},
                            'displayed_quote': {'option_id': 'basket/slow'}},
                           lambda request: {'confirmation': {'id': 'SIM-9'}})
        count = store.journal()['revision']
        self.sync(store, [])
        self.assertEqual(store.journal()['revision'], count)
        self.sync(store, [('shop/b', 1)], 'basket/fast', 'site', 'checkout')
        later = [(event['kind'], event['detail'].get('field'), event['detail'].get('trigger'))
                 for event in store.journal()['events'][count:]]
        self.assertEqual(later, [('basket_change', None, None), ('checkout_enter', None, None),
                                 ('site_preselect', 'newsletter', 'initial'),
                                 ('site_preselect', 'extras', 'initial'),
                                 ('site_preselect', 'delivery_option_id', 'initial')])
        self.assertEqual(store.journal()['after']['committed']['order']['order_id'], 'SIM-9')

    def test_start_preselection_is_part_of_before_without_an_event(self):
        store = self.store(newsletter={'label': 'Offers', 'preselected': 'start'})
        self.sync(store, [('shop/a', 1)], 'basket/slow', 'site', 'checkout')
        journal = store.journal()
        self.assertTrue(journal['before']['newsletter'])
        self.assertNotIn('newsletter', [event['detail'].get('field') for event in journal['events']])

    def test_refused_operations_change_nothing(self):
        store = self.store()
        self.send(store, 'cookie_dialog', event='load')
        self.sync(store, [('shop/a', 1)], 'basket/slow', 'site', 'checkout')
        expected = store.journal()
        refused = [
            {'op': 'unknown'}, {'op': 'cookie_save', 'action': 'accept_all', 'preferences': {}},
            {'op': 'cookie_save', 'action': 'save_settings', 'preferences': {'analytics': True}},
            {'op': 'cookie_save', 'action': 'maybe'}, {'op': 'cookie_dialog', 'event': 'reopen'},
            {'op': 'newsletter_set', 'value': 'yes'}, {'op': 'extras_set', 'extra_id': 'gift', 'value': True},
            {'op': 'extras_set', 'extra_id': 'club', 'value': 1}, {'op': 'promotion_apply', 'code': ' '},
            {'op': 'promotion_remove', 'code': 'SAVE10'}, {'op': 'order_arm', 'grand_total_minor': '1'},
            {'op': 'quote', 'extra': 1}, {'op': 'newsletter_set', 'value': True, 'session': 'short'},
        ]
        for request in refused:
            with self.assertRaises(ValueError, msg=request):
                store.handle({'session': SESSION, **request})
        self.assertEqual(store.journal(), expected)
        self.send(store, 'cookie_save', action='accept_all')
        with self.assertRaisesRegex(ValueError, 'not open'):
            self.send(store, 'cookie_save', action='reject_all')
        without = self.store(cookie=None, newsletter=None, extras=[], promotions=None, recurrence=None)
        for op, fields in (('cookie_dialog', {'event': 'load'}), ('cookie_save', {'action': 'accept_all'}),
                           ('newsletter_set', {'value': True}), ('promotion_apply', {'code': 'X'})):
            with self.assertRaises(ValueError):
                self.send(without, op, **fields)
        self.assertEqual(without.journal()['events'], [])

    def test_unchanged_values_and_repeated_syncs_add_no_event(self):
        store = self.store()
        self.sync(store, [('shop/a', 1)], 'basket/slow', 'site', 'checkout')
        count = store.journal()['revision']
        self.sync(store, [('shop/a', 1)], 'basket/slow', 'site', 'checkout')
        self.send(store, 'newsletter_set', value=True)
        self.send(store, 'extras_set', extra_id='club', value=False)
        self.send(store, 'quote')
        self.send(store, 'state')
        self.assertEqual(store.journal()['revision'], count)

    def test_sync_validates_offers_options_and_shape_and_faults_the_journal(self):
        bad = [
            dict(basket=[{'offer_id': 'other/x', 'quantity': 1}], delivery={'option_id': None, 'source': 'site'}),
            dict(basket=[{'offer_id': 'shop/a', 'quantity': 0}], delivery={'option_id': None, 'source': 'site'}),
            dict(basket=[{'offer_id': 'shop/a', 'quantity': 1}, {'offer_id': 'shop/a', 'quantity': 1}],
                 delivery={'option_id': None, 'source': 'site'}),
            dict(basket=[{'offer_id': 'shop/a', 'quantity': 1, 'price': 1}], delivery={'option_id': None, 'source': 'site'}),
            dict(basket=[{'offer_id': 'shop/a', 'quantity': 1}], delivery={'option_id': 'basket/unknown', 'source': 'site'}),
            dict(basket=[{'offer_id': 'shop/b', 'quantity': 1}], delivery={'option_id': 'basket/slow', 'source': 'site'}),
            dict(basket=[{'offer_id': 'shop/a', 'quantity': 1}], delivery={'option_id': None, 'source': 'robot'}),
            dict(basket=[], delivery={'option_id': None, 'source': 'site'}, location='checkout'),
            dict(basket=[], delivery={'option_id': None, 'source': 'site'}, step=0),
        ]
        for fields in bad:
            store = self.store()
            store.bind_episode('episode', {'b': 1})
            self.offer(store, [{'offer_id': 'shop/a', 'quantity': 1}])
            before = store.journal()
            with self.assertRaises(ValueError, msg=fields):
                self.send(store, 'sync', **{'location': 'outside', 'step': None, **fields})
            journal = store.seal()
            self.assertEqual((journal['complete'], journal['incomplete_reason']), (False, 'state_fault'))
            self.assertEqual((journal['events'], journal['after']), (before['events'], before['after']))

    def test_every_incomplete_reason(self):
        def fresh(bound=True):
            store = self.store()
            if bound:
                store.bind_episode('episode', {'b': 1})
            return store
        seen = {}
        store = fresh()
        self.send(store, 'state')
        seen['not_sealed'] = store.journal()
        store = fresh(bound=False)
        self.send(store, 'state')
        seen['binding_mismatch'] = store.seal()
        store = fresh()
        self.send(store, 'state')
        self.assertEqual(store.seal(episode_id='another')['incomplete_reason'], 'binding_mismatch')
        store = fresh()
        with self.assertRaises(ValueError):
            store.bind_episode('episode', {'b': 2})
        self.send(store, 'state')
        self.assertEqual(store.seal()['incomplete_reason'], 'binding_mismatch')
        seen['no_session'] = fresh().seal()
        store = fresh()
        self.send(store, 'state')
        store.handle({'op': 'state', 'session': 'fedcba9876543210'})
        seen['multiple_sessions'] = store.seal()
        store = fresh()
        for index in range(MAX_EVENTS // 2 + 1):
            self.send(store, 'newsletter_set', value=True)
            self.send(store, 'newsletter_set', value=False)
        seen['journal_overflow'] = store.seal()
        self.assertEqual(len(seen['journal_overflow']['events']), MAX_EVENTS)
        store = fresh()
        with self.assertRaises(ValueError):
            self.send(store, 'sync', basket=[{'offer_id': 'nowhere', 'quantity': 1}],
                      delivery={'option_id': None, 'source': 'site'}, location='outside', step=None)
        seen['state_fault'] = store.seal()
        self.assertEqual(set(seen), set(REASONS))
        for reason, journal in seen.items():
            self.assertEqual((journal['complete'], journal['incomplete_reason']), (False, reason))
        store = fresh()
        self.send(store, 'state')
        self.assertEqual(store.seal(episode_id='episode')['complete'], True)

    def test_binding_must_precede_requests_and_begin_separates_setup(self):
        store = self.store()
        self.send(store, 'cookie_dialog', event='load')
        with self.assertRaises(ValueError):
            store.bind_episode('episode', {'b': 1})
        store = self.store()
        store.bind_episode('episode', {'b': 1})
        store.bind_episode('episode', {'b': 1})
        self.send(store, 'cookie_dialog', event='load')
        before = store.begin()
        self.assertEqual(before['cookie']['pending'], {'analytics': True, 'personalisation': False, 'marketing': True})
        with self.assertRaises(ValueError):
            store.begin()
        self.send(store, 'cookie_save', action='reject_all')
        journal = store.seal(episode_id='episode')
        self.assertEqual(journal['before'], before)
        self.assertEqual([(event['seq'], event['kind']) for event in journal['events']], [(1, 'cookie_save')])
        self.assertEqual([event['kind'] for event in store.snapshot()['setup_events']],
                         ['cookie_dialog', 'site_preselect'])
        self.assertTrue(journal['complete'])
        with self.assertRaises(ValueError):
            store.seal()

    def test_callback_binding_runs_once_before_publishing_session_identity(self):
        calls = []
        def bind(episode_id):
            self.assertIsNone(store.journal()['episode_id'])
            calls.append(episode_id)
        def quote(*args, **kwargs):
            return overlay(*args, **kwargs)
        def inside(*args, **kwargs):
            return scope(*args, **kwargs)
        quote.bind_episode = inside.bind_episode = bind
        store = self.store(quote=quote, scope=inside)
        store.bind_episode('actual', {'bound': 1})
        store.bind_episode('actual', {'bound': 1})
        with self.assertRaisesRegex(ValueError, 'immutable'):
            store.bind_episode('foreign', {'bound': 2})
        self.assertEqual(calls, ['actual'])

    def test_failed_callback_binding_cannot_be_retried_or_sealed_complete(self):
        calls = []
        def bind(episode_id):
            calls.append(episode_id)
            raise ValueError('Native binding refused')
        def quote(*args, **kwargs):
            return overlay(*args, **kwargs)
        quote.bind_episode = bind
        store = self.store(quote=quote, scope=scope)
        with self.assertRaisesRegex(ValueError, 'Native binding refused'):
            store.bind_episode('actual', {'bound': 1})
        with self.assertRaisesRegex(ValueError, 'prior state fault'):
            store.bind_episode('foreign', {'bound': 2})
        self.assertEqual(calls, ['actual'])
        journal = store.seal()
        self.assertIsNone(journal['episode_id'])
        self.assertFalse(journal['complete'])
        self.assertEqual(store.snapshot()['state_fault'], 'Episode callback binding failed')

    def test_order_needs_a_matching_armed_total_and_a_known_basket(self):
        calls = []
        def native(request):
            calls.append(request)
            if request.get('fail'):
                raise ValueError('Displayed quote differs')
            return {'confirmation': {'id': 'SIM-' + str(len(calls))}}
        submission = {'quote_request': {'lines': [{'line_id': 'shop/a', 'offer_id': 'shop/a', 'quantity': 1}]},
                      'displayed_quote': {'option_id': 'basket/slow'}}
        store = self.store()
        store.bind_episode('episode', {'b': 1})
        self.sync(store, [('shop/a', 1)], 'basket/slow', 'site', 'checkout')
        count = store.journal()['revision']
        with self.assertRaisesRegex(ValueError, 'Confirm the current order total'):
            store.submit_order(submission, native)
        reply = self.send(store, 'order_arm', grand_total_minor=25000)
        self.assertEqual(reply['order'], {'armed': False, 'reason': 'The order total has changed. Review the updated total.'})
        self.assertEqual(reply['grand_total_minor'], 29900)
        with self.assertRaises(ValueError):
            store.submit_order(submission, native)
        self.assertTrue(self.send(store, 'order_arm', grand_total_minor=29900)['order']['armed'])
        self.send(store, 'extras_set', extra_id='warranty', value=False)
        with self.assertRaisesRegex(ValueError, 'Confirm the current order total'):
            store.submit_order(submission, native)
        self.assertEqual(calls, [])
        self.assertTrue(self.send(store, 'order_arm', grand_total_minor=25000)['order']['armed'])
        with self.assertRaisesRegex(ValueError, 'Displayed quote differs'):
            store.submit_order({**submission, 'fail': True}, native)
        self.assertEqual(store.journal()['revision'], count + 1)
        self.assertIsNone(store.journal()['after']['committed']['order'])
        value = store.submit_order(submission, native)
        self.assertEqual(value, {'confirmation': {'id': 'SIM-2'}})
        journal = store.journal()
        self.assertEqual(journal['events'][-1]['kind'], 'order_submit')
        self.assertEqual(journal['events'][-1]['detail'], {'order_id': 'SIM-2'})
        order = journal['after']['committed']['order']
        self.assertEqual(order['charges'], [{'kind': 'quote', 'id': None, 'label': 'Items and delivery', 'amount_minor': 25000}])
        self.assertEqual((order['grand_total_minor'], order['newsletter'], order['extras']),
                         (25000, True, {'warranty': False, 'club': False}))
        self.assertTrue(store.seal(episode_id='episode')['complete'])

        store = self.store()
        store.bind_episode('episode', {'b': 1})
        self.sync(store, [('shop/a', 1)], 'basket/slow', 'site', 'checkout')
        self.send(store, 'order_arm', grand_total_minor=29900)
        other = deepcopy(submission)
        other['quote_request']['lines'][0]['quantity'] = 2
        with self.assertRaisesRegex(ValueError, 'Review the current basket'):
            store.submit_order(other, native)
        with self.assertRaises(ValueError):
            store.submit_order({'quote_request': None}, native)
        self.assertEqual(len(calls), 2)
        self.assertEqual(store.seal(episode_id='episode')['incomplete_reason'], 'state_fault')

    def test_overlay_quote_scope_codes_and_default_delivery(self):
        store = self.store(quote=overlay, scope=scope, delivery={'default': {'choice_id': 'choice/fast'},
                                                                 'prominent': {'choice_id': 'choice/fast'}})
        reply = self.sync(store, [('shop/a', 1)])
        self.assertEqual(reply['quote'], {'source': 'overlay', 'quote_id': 'q-24900', 'total_minor': 24900, 'currency': 'SEK'})
        self.assertEqual(reply['quote_lines'], [{'label': 'Service fee', 'amount_minor': 4900}])
        self.assertEqual(reply['prominent_option_ids'], ['basket/fast'])
        options_reply = {'options': [
            {'id': 'basket/slow', 'selection': {'l': 'slow'}, 'shipments': [{'delivery': {'id': 'choice/slow'}}]},
            {'id': 'basket/fast', 'selection': {'l': 'fast'}, 'shipments': [{'delivery': {'id': 'choice/fast'}}]}]}
        request = {'lines': [{'line_id': 'shop/a', 'offer_id': 'shop/a', 'quantity': 1}]}
        self.assertEqual(store.default_selection(request, options_reply), {'l': 'slow'})
        self.send(store, 'promotion_apply', code='SAVE10')
        reply = self.sync(store, [('shop/a', 1), ('shop/b', 1)])
        self.assertIsNone(reply['quote'])
        self.assertIn('Codes only apply to item A.', reply['quote_reason'])
        self.assertIsNone(reply['grand_total_minor'])
        self.assertFalse(self.send(store, 'order_arm', grand_total_minor=0)['order']['armed'])
        reply = self.send(store, 'promotion_apply', code='OTHER')
        self.assertEqual(reply['promotion_feedback'],
                         {'code': 'OTHER', 'accepted': False, 'feedback': 'Codes only apply to item A.'})
        self.send(store, 'promotion_remove', code='SAVE10')
        self.assertIsNone(self.send(store, 'quote')['quote'])
        request = {'lines': [{'line_id': 'shop/b', 'offer_id': 'shop/b', 'quantity': 1}]}
        self.assertEqual(store.default_selection(request, options_reply), {'l': 'fast'})
        reply = self.sync(store, [('shop/a', 1), ('shop/b', 1)], 'basket/fast', 'site')
        self.assertEqual(reply['quote'], {'source': 'native', 'quote_id': None, 'total_minor': 30000, 'currency': 'SEK'})

        def broken(lines, codes, *, delivery_option_id=None):
            raise RuntimeError('producer failed')
        store = self.store(quote=broken, scope=scope)
        reply = self.sync(store, [('shop/a', 1)])
        self.assertIsNone(reply['quote'])
        self.assertEqual(store.snapshot()['overlay_errors'], ['RuntimeError: producer failed'])

    def test_view_and_snapshot_keep_private_values_apart(self):
        store = self.store()
        store.bind_episode('episode-zz', {'secret': 'hidden-answer'})
        view = self.send(store, 'cookie_dialog', event='load')
        self.assertNotIn('hidden-answer', json.dumps(view))
        self.assertNotIn('episode-zz', json.dumps(view))
        self.assertEqual(view['cookie']['open'], True)
        snapshot = store.snapshot()
        self.assertEqual(snapshot['journal']['binding'], {'secret': 'hidden-answer'})
        self.assertEqual(snapshot['sessions'], [SESSION])


class RateRefresh(Controls):
    def test_first_confirmed_total_is_refused_and_site_reselects_the_default(self):
        store = SessionStore(options({'retailer_id': 'shop', 'delivery': {'default': {'choice_id': 'choice/fast'}},
            'presentation': {'execution': 'rate_refresh_at_commit_light', 'refresh_notice': 'Delivery options were updated.'}}),
            offers=OFFERS, runtime_id='runtime')
        basket = [{'offer_id': 'shop/a', 'quantity': 1}]
        request = {'lines': [{'line_id': 'shop/a', 'offer_id': 'shop/a', 'quantity': 1}]}
        reply = {'options': [{'id': f'basket/{n}', 'totalMinor': t, 'selection': {'line': n},
                              'shipments': [{'delivery': {'id': f'choice/{n}'}}]} for n, t in (('slow', 25000), ('fast', 30000))]}
        self.offer(store, basket)
        self.assertIsNone(store.default_selection(request, reply))
        self.send(store, 'sync', basket=basket, delivery={'option_id': 'basket/slow', 'source': 'shopper'},
                  location='checkout', step=None)
        view = self.send(store, 'order_arm', grand_total_minor=25000)
        self.assertEqual(view['order'], {'armed': False, 'reason': 'Delivery options were updated.'})
        self.assertTrue(view['directives']['reset_delivery'])
        self.assertEqual(store.default_selection(request, reply), {'line': 'fast'})
        self.send(store, 'sync', basket=basket, delivery={'option_id': 'basket/fast', 'source': 'site'},
                  location='checkout', step=None)
        event = store.journal()['events'][-1]
        self.assertEqual((event['kind'], event['detail']['trigger']), ('site_preselect', 'order_arm'))
        self.assertTrue(self.send(store, 'order_arm', grand_total_minor=30000)['order']['armed'])


if __name__ == '__main__':
    unittest.main()
