"""Small independent native-menu semantic controls; no generation or browser."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import unittest
from environments.website_world import variant_menu_condition as menu


def world():
    skus = [{'sku_id': 'navy42', 'colour': 'navy', 'size_eu': 42, 'width': 'standard'},
            {'sku_id': 'black41', 'colour': 'black', 'size_eu': 41, 'width': 'standard'}]
    return {'products': [{'public': {'product_id': 'model', 'concept_id': 'shoe', 'skus': skus}}],
            'retailers': [{'retailer_id': 'shop',
                'source_locations': [{'source_id': 'warehouse', 'shipping_enabled': True},
                                     {'source_id': 'branch', 'shipping_enabled': False}],
                'offers': [{'sku_id': s['sku_id'], 'product_id': 'model',
                            'offer_id': 'shop/' + s['sku_id'],
                            'stock_by_source': {'warehouse': 2, 'branch': 3}} for s in skus],
                'catalog': [{'product_id': 'model', 'pages': [{'page_key': {},
                    'selectors': {'size_eu': [41, 42], 'colour': ['black', 'navy'], 'width': ['standard']},
                    'listings': [{'sku_id': s['sku_id'], 'stock': 2} for s in skus]}]}]}]}


class MenuTests(unittest.TestCase):
    def evaluate(self, w=None, **options):
        return menu.completion(w or world(), {'schema': menu.VERSION, **options})

    def test_existing_gap_is_unavailable_target_and_input_unchanged(self):
        w = world(); saved = deepcopy(w); r = self.evaluate(w)
        self.assertTrue(r['eligible']);self.assertEqual(w, saved)
        self.assertEqual(r['witnesses'][0]['requested_selection']['size_eu'], '42')
        self.assertEqual(r['witnesses'][0]['existing_fallbacks'][0]['selection']['size_eu'], '41')
        self.assertFalse(r['witnesses'][0]['requested_tuple_present'])

    def test_zero_stock_target_still_counts_as_present(self):
        w = world();r = w['retailers'][0]
        w['products'][0]['public']['skus'].append({'sku_id': 'black42', 'colour': 'black', 'size_eu': 42, 'width': 'standard'})
        r['offers'].append({'sku_id': 'black42', 'product_id': 'model', 'offer_id': 'shop/black42', 'stock_by_source': {'warehouse': 0, 'branch': 0}})
        r['catalog'][0]['pages'][0]['listings'].append({'sku_id': 'black42', 'stock': 0})
        self.assertFalse(self.evaluate(w)['eligible'])

    def test_other_page_cannot_supply_black(self):
        w = world();p = w['retailers'][0]['catalog'][0]['pages'][0]
        other = deepcopy(p);other['page_key'] = {'colour': 'black'}
        p['listings'] = p['listings'][:1];other['listings'] = other['listings'][1:]
        w['retailers'][0]['catalog'][0]['pages'].append(other)
        self.assertFalse(self.evaluate(w)['eligible'])

    def test_colour_must_be_a_selector(self):
        w = world();del w['retailers'][0]['catalog'][0]['pages'][0]['selectors']['colour']
        self.assertFalse(self.evaluate(w)['eligible'])

    def test_other_axes_cannot_change_in_isolated_fallback(self):
        w = world();w['products'][0]['public']['skus'][1]['width'] = 'wide'
        self.assertFalse(self.evaluate(w)['eligible'])

    def test_stock_requirement_separate_from_menu(self):
        w = world();w['retailers'][0]['offers'][1]['stock_by_source']['warehouse'] = 0
        self.assertTrue(self.evaluate(w)['eligible'])
        self.assertFalse(self.evaluate(w, require_dispatch_stock=True)['eligible'])

    def test_explicit_scope(self):
        for key in ('retailer_id', 'product_id', 'concept_id'):
            self.assertFalse(self.evaluate(**{key: 'foreign'})['eligible'])

    def test_nonboolean_stock_flag_and_unknown_fields_reject(self):
        for options in ({'require_dispatch_stock': 1}, {'stock_override': True}, {'size_key': 'colour'}):
            with self.assertRaises(ValueError):self.evaluate(**options)


def source_controls():
    names = unittest.defaultTestLoader.getTestCaseNames(MenuTests)
    def run(name):
        result = unittest.TestResult();MenuTests(name).run(result)
        return {'case': name, 'passed': result.wasSuccessful(), 'errors': result.errors, 'failures': result.failures}
    with ThreadPoolExecutor(max_workers=2) as pool:return list(pool.map(run, names))
