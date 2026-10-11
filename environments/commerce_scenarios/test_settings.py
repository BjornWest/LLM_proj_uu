"""Settings validation and public projection; authored values only."""
from copy import deepcopy
import json
import unittest

from .settings import options, plain, public_settings, validate_catalog

FULL = {
    'retailer_id': 'shop',
    'cookie': {'design': 'side-drawer', 'first_level': ['accept_all', 'settings'], 'emphasis': 'accept_all',
               'blocking': True, 'preselected': {'analytics': True, 'personalisation': True, 'marketing': True}},
    'newsletter': {'label': 'Offers by email', 'preselected': 'start'},
    'extras': [{'id': 'cover', 'kind': 'warranty', 'label': 'Cover', 'price_minor': 4900,
                'billing_period': 'one_time', 'preselected': 'checkout'}],
    'promotions': {'field': True, 'label': 'Code', 'claims': ['10% off with SAVE10']},
    'fees': [{'id': 'service', 'label': 'Service fee', 'reveal': 'checkout'}],
    'delivery': {'default': {'choice_id': 'delivery/express'},
                 'prominent': {'option_id': 'basket/abc', 'label': 'Our pick'}},
    'sponsored': [{'offer_id': 'shop/a', 'label': 'Sponsored', 'placement': 'results'}],
    'recurrence': {'cookie': ['checkout_return'], 'newsletter': ['checkout_navigation'],
                   'extras': {'cover': ['checkout_return', 'checkout_navigation']}, 'delivery': ['checkout_return']},
    'presentation': {'family': 'authored'},
}
CATALOG = {'siteId': 'shop', 'products': [{'variants': [{'offerId': 'shop/a'}, {'offerId': 'shop/b'}]}]}


class Controls(unittest.TestCase):
    def test_absent_settings_mean_no_scenario_and_defaults_are_completed(self):
        self.assertIsNone(options(None))
        minimal = options({'retailer_id': 'shop'})
        self.assertEqual({key: minimal[key] for key in ('cookie', 'newsletter', 'extras', 'fees', 'sponsored')},
                         {'cookie': None, 'newsletter': None, 'extras': [], 'fees': [], 'sponsored': []})
        self.assertEqual(minimal['promotions'], {'field': False, 'label': 'Promotion code', 'claims': []})
        self.assertEqual(minimal['delivery'], {'default': None, 'prominent': None})
        self.assertEqual(minimal['recurrence'], {'cookie': [], 'newsletter': [], 'extras': {}, 'delivery': []})
        self.assertEqual(options({'retailer_id': 'shop', 'cookie': {'design': 'bottom-banner'}})['cookie'], {
            'design': 'bottom-banner', 'first_level': ['accept_all', 'reject_all', 'settings'], 'emphasis': None,
            'blocking': False, 'dismissible': False,
            'preselected': {'analytics': False, 'personalisation': False, 'marketing': False}})

    def test_full_settings_round_trip_detached_and_are_json(self):
        source = deepcopy(FULL)
        checked = options(source)
        self.assertEqual(source, FULL)
        checked['extras'][0]['label'] = 'changed'
        self.assertEqual(source['extras'][0]['label'], 'Cover')
        json.dumps(plain(options(FULL)), allow_nan=False)
        self.assertEqual(validate_catalog(options(FULL), CATALOG), {'shop/a', 'shop/b'})

    def test_overlay_callables_stay_in_process(self):
        quote, scope = (lambda lines, codes: {}), (lambda lines, codes: {})
        checked = options({'retailer_id': 'shop', 'quote': quote, 'scope': scope})
        self.assertIs(checked['quote'], quote)
        self.assertTrue(plain(checked)['overlay_quote'])
        self.assertNotIn('quote', plain(checked))
        self.assertNotIn('quote', public_settings(checked))
        for bad in ({'quote': quote}, {'scope': scope}, {'quote': 'q', 'scope': 's'}):
            with self.assertRaises(ValueError):
                options({'retailer_id': 'shop', **bad})

    def test_public_projection_hides_site_rules(self):
        public = public_settings(options(FULL), ['family.js', 'family.css'])
        self.assertEqual(set(public), {'schema', 'cookie', 'newsletter', 'extras', 'promotions', 'fees',
                                       'sponsored', 'presentation', 'delivery', 'pieces'})
        self.assertEqual(public['newsletter'], {'label': 'Offers by email'})
        self.assertEqual(public['extras'], [{'id': 'cover', 'kind': 'warranty', 'label': 'Cover',
                                             'price_minor': 4900, 'billing_period': 'one_time'}])
        self.assertEqual(public['delivery'], {'prominent_label': 'Our pick'})
        self.assertEqual(public['pieces'], ['family.css', 'family.js'])
        text = json.dumps(public)
        for private in ('recurrence', 'checkout_return', 'delivery/express', 'basket/abc', 'retailer_id'):
            self.assertNotIn(private, text)

    def test_invalid_settings_are_refused(self):
        def changed(path, value):
            settings = deepcopy(FULL)
            node = settings
            for key in path[:-1]:
                node = node[key]
            node[path[-1]] = value
            return settings
        cases = [
            {}, {'retailer_id': ''}, {'retailer_id': 'shop', 'binding': {}}, {'retailer_id': 'shop', 'episode_id': 'e'},
            {'retailer_id': 'shop', 'schema': 'other'}, 'shop',
            changed(['cookie', 'design'], 'popup'), changed(['cookie', 'first_level'], ['accept_all']),
            changed(['cookie', 'first_level'], ['accept_all', 'accept_all', 'settings']),
            changed(['cookie', 'emphasis'], 'reject_all'), changed(['cookie', 'dismissible'], True),
            changed(['cookie', 'preselected'], {'analytics': True}), changed(['cookie', 'blocking'], 'yes'),
            changed(['newsletter', 'preselected'], True), changed(['newsletter', 'preselected'], 0),
            changed(['newsletter', 'label'], ''), changed(['newsletter', 'colour'], 'red'),
            changed(['extras', 0, 'id'], 'Not An Id'), changed(['extras', 0, 'kind'], 'gift'),
            changed(['extras', 0, 'price_minor'], -1), changed(['extras', 0, 'price_minor'], 49.0),
            changed(['extras', 0, 'billing_period'], 'yearly'), changed(['extras', 0, 'preselected'], 'always'),
            changed(['extras'], [FULL['extras'][0], FULL['extras'][0]]),
            changed(['promotions', 'field'], 'yes'), changed(['promotions', 'claims'], [3]),
            changed(['fees', 0, 'amount_minor'], 100), changed(['fees', 0, 'reveal'], 'never'),
            changed(['delivery', 'default'], {}), changed(['delivery', 'default'], {'option_id': 'a', 'choice_id': 'b'}),
            changed(['delivery', 'prominent'], {'label': 'Pick'}), changed(['delivery', 'reset_on'], []),
            changed(['sponsored', 0, 'placement'], 'popup'),
            changed(['recurrence', 'cookie'], ['initial']), changed(['recurrence', 'extras'], {'other': []}),
            changed(['recurrence', 'delivery'], ['checkout_return', 'checkout_return']),
            changed(['presentation'], ['list']), changed(['extras', 0, 'label'], float('nan')),
            {'retailer_id': 'shop', 'recurrence': {'cookie': ['checkout_return']}},
            {'retailer_id': 'shop', 'recurrence': {'newsletter': ['checkout_return']}},
        ]
        for case in cases:
            with self.assertRaises(ValueError, msg=case):
                options(case)
        with self.assertRaisesRegex(ValueError, 'not sold by this retailer'):
            validate_catalog(options(changed(['sponsored', 0, 'offer_id'], 'other/x')), CATALOG)
        with self.assertRaisesRegex(ValueError, 'another retailer'):
            validate_catalog(options(FULL), {**CATALOG, 'siteId': 'elsewhere'})


if __name__ == '__main__':
    unittest.main()
