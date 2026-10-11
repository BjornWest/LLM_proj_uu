"""Selected-route pricing and failure provenance; authored producer stand-ins."""
from copy import deepcopy
import unittest

from .settings import options
from .store import SessionStore

SESSION = '12345678abcd'
BASKET = [{'offer_id': 'shop/a', 'quantity': 1}]


class OverlayControls(unittest.TestCase):
    def store(self, quote, **settings):
        return SessionStore(options({'retailer_id': 'shop', 'quote': quote,
            'scope': lambda lines, codes, *, delivery_option_id=None: {
                'in_scope': len(lines) == 1, 'reason': 'Single-item offer only.'},
            **settings}), offers=['shop/a', 'shop/b'], runtime_id='test')

    def send(self, store, op, **fields):
        return store.handle({'op': op, 'session': SESSION, **fields})

    def sync(self, store, option=None, basket=None):
        return self.send(store, 'sync', basket=BASKET if basket is None else basket,
            delivery={'option_id': option, 'source': 'shopper'}, location='outside', step=None)

    def offer(self, store):
        store.observe_quote({'lines': BASKET}, {'options': [
            {'id': id, 'totalMinor': total, 'selection': {'line': id},
             'shipments': [{'delivery': {'id': 'delivery/'+id}}]}
            for id, total in [('cheap', 10000), ('costly', 15000)]]})

    def test_selected_route_and_default_quote_are_distinct(self):
        calls = []
        def quote(lines, codes, *, delivery_option_id=None):
            calls.append(delivery_option_id)
            selected = delivery_option_id or 'cheap'
            total = 10900 if selected == 'cheap' else 15900
            return {'quote_id': selected+'-q', 'total_minor': total, 'currency': 'SEK',
                    'native_option_id': selected}
        store = self.store(quote)
        self.offer(store)
        for selected, total in [('cheap', 10900), ('costly', 15900), ('cheap', 10900)]:
            view = self.sync(store, selected)
            self.assertEqual((view['delivery_option_id'], view['quote']['quote_id'],
                              view['grand_total_minor']), (selected, selected+'-q', total))
        reply = {'options': [{'id': 'cheap', 'selection': {'line': 'cheap'}, 'shipments': []}]}
        self.assertEqual(store.default_selection({'lines': BASKET}, reply), {'line': 'cheap'})
        self.assertIsNone(calls[-1])

    def test_rejected_nonstacking_codes_replace_all_active_codes(self):
        def quote(lines, codes, *, delivery_option_id=None):
            active = codes if len(codes) == 1 else []
            return {'quote_id': '-'.join(active) or 'none', 'total_minor': 10000,
                    'currency': 'SEK', 'promotion_codes': active,
                    'promotion_feedback': {code: {'accepted': bool(active),
                        'feedback': 'Applied.' if active else 'Cannot combine.'} for code in codes}}
        store = self.store(quote, promotions={'field': True})
        self.sync(store)
        self.assertEqual(self.send(store, 'promotion_apply', code='SAVE')['promotion_codes'], ['SAVE'])
        rejected = self.send(store, 'promotion_apply', code='BONUS')
        self.assertEqual(rejected['promotion_codes'], [])
        self.assertFalse(rejected['promotion_feedback']['accepted'])
        self.assertEqual(store.journal()['events'][-1]['state']['promotion_codes'], [])

    def test_bad_overlay_cannot_lose_a_saved_grant_or_claim_complete_capture(self):
        mode = [False]
        def quote(lines, codes, *, delivery_option_id=None):
            return {'quote_id': 'authentic', 'total_minor': 10000, 'currency': 'SEK',
                    'lines': [{}] if mode[0] else []}
        store = self.store(quote, cookie={'design': 'bottom-banner'})
        store.bind_episode('episode', {'bound': True})
        self.send(store, 'cookie_dialog', event='load')
        self.sync(store)
        mode[0] = True
        self.send(store, 'cookie_save', action='accept_all')
        journal = store.seal(episode_id='episode')
        self.assertEqual(journal['events'][-1]['kind'], 'cookie_save')
        self.assertTrue(journal['after']['committed']['cookie']['preferences']['marketing'])
        self.assertEqual(journal['after'], journal['events'][-1]['state'])
        self.assertEqual((journal['complete'], journal['incomplete_reason']), (False, 'state_fault'))
        self.assertIn('Malformed overlay breakdown', store.snapshot()['state_fault'])

    def test_unexpected_refresh_failure_retains_actual_commit_and_faults_journal(self):
        store = self.store(lambda *args, **kwargs: {}, cookie={'design': 'bottom-banner'})
        store.bind_episode('episode', {'bound': True})
        self.send(store, 'cookie_dialog', event='load')
        def fail():
            raise KeyError('unexpected capture failure')
        store._refresh_quote = fail
        with self.assertRaises(KeyError):
            self.send(store, 'cookie_save', action='accept_all')
        journal = store.seal(episode_id='episode')
        self.assertTrue(journal['after']['committed']['cookie']['preferences']['marketing'])
        self.assertEqual((journal['complete'], journal['incomplete_reason']), (False, 'state_fault'))
        self.assertNotEqual(journal['after'], journal['events'][-1]['state'])

    def test_malformed_optional_fields_fault_preview_and_basket_capture(self):
        malformed = [{'lines': [{}]}, {'promotion_feedback': {'SAVE': {'accepted': 'yes'}}},
                     {'promotion_codes': ['SAVE', 'SAVE']}, {'options': [{}]},
                     {'total_minor': True}, {'native_option_id': {}}, {'currency': 'EUR'}]
        for extra in malformed:
            with self.subTest(extra=extra):
                def quote(lines, codes, *, delivery_option_id=None):
                    return {'quote_id': 'q', 'total_minor': 10000, 'currency': 'SEK', **deepcopy(extra)}
                store = self.store(quote)
                store.bind_episode('episode', {'bound': True})
                self.sync(store)
                journal = store.seal(episode_id='episode')
                self.assertEqual(journal['events'][-1]['kind'], 'basket_change')
                self.assertEqual(journal['after'], journal['events'][-1]['state'])
                self.assertEqual((journal['complete'], journal['incomplete_reason']), (False, 'state_fault'))

    def test_explicit_overlay_scope_refusal_does_not_publish_native_total(self):
        def quote(lines, codes, *, delivery_option_id=None):
            return {'quote_id': 'q', 'total_minor': 10000, 'currency': 'SEK'}
        store = self.store(quote, outside_scope_behavior='reject_quote')
        basket = [*BASKET, {'offer_id': 'shop/b', 'quantity': 1}]
        view = self.sync(store, basket=basket)
        self.assertIsNone(view['quote'])
        self.assertIn('Single-item offer only.', view['quote_reason'])


if __name__ == '__main__':
    unittest.main()
