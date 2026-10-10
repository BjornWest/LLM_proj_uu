"""Small pure projection controls, no fixtures, browser or native imports."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import unittest
from environments.website_world import variant_axis_order as axis


def catalog():
    product = {'id': 'page', 'canonicalProductId': 'model', 'introduction': '',
        'options': [{'key': 'size_eu', 'label': 'EU size', 'values': ['41', '42']},
                    {'key': 'width', 'label': 'Width', 'values': ['standard']},
                    {'key': 'colour', 'label': 'Colour', 'values': ['navy', 'black']}],
        'variants': [{'key': 'navy42', 'skuId': 'native-navy42', 'offerId': 'shop/navy42',
            'selection': {'size_eu': '42', 'width': 'standard', 'colour': 'navy'},
            'state': 'unavailable', 'priceMinor': 17000, 'stock': 0, 'details': []},
            {'key': 'black41', 'skuId': 'native-black41', 'offerId': 'shop/black41',
             'selection': {'size_eu': '41', 'width': 'standard', 'colour': 'black'},
             'state': 'in_stock', 'priceMinor': 17000, 'stock': 3, 'details': []}]}
    return {'siteId': 'shop', 'configuration': {'url': 'none'},
            'products': [product, {**deepcopy(product), 'id': 'other-page'}]}


class ProjectionTests(unittest.TestCase):
    def project(self, data=None):
        return axis.project(data or catalog(), retailer_id='shop', page_id='page')

    def test_exact_inverse_and_original_unmodified(self):
        before = catalog();saved = deepcopy(before)
        after, evidence = self.project(before)
        self.assertEqual(before, saved)
        self.assertEqual(axis.restore(after, evidence), before)
        self.assertEqual(evidence['after_axis_order'], ['colour', 'size_eu', 'width'])
        self.assertEqual(after['products'][1], before['products'][1])
        self.assertEqual(after['products'][0]['variants'], before['products'][0]['variants'])

    def test_other_axes_keep_relative_order(self):
        data = catalog();options = data['products'][0]['options']
        options.insert(0, {'key': 'configuration', 'values': ['standard']})
        for variant in data['products'][0]['variants']:variant['selection']['configuration'] = 'standard'
        _, evidence = self.project(data)
        self.assertEqual(evidence['after_axis_order'], ['configuration', 'colour', 'size_eu', 'width'])

    def test_already_ordered_is_noop(self):
        projected, _ = self.project()
        again, evidence = self.project(projected)
        self.assertFalse(evidence['changed']);self.assertEqual(again, projected)

    def test_scope_must_name_existing_page_and_retailer(self):
        for kwargs in ({'retailer_id': 'wrong', 'page_id': 'page'},
                       {'retailer_id': 'shop', 'page_id': 'absent'}):
            with self.assertRaises(ValueError):axis.project(catalog(), **kwargs)

    def test_missing_control_is_not_synthesized(self):
        data = catalog();data['products'][0]['options'].pop()
        with self.assertRaises(ValueError):self.project(data)

    def test_unbound_tuple_is_not_repaired(self):
        data = catalog();data['products'][0]['variants'][0]['selection']['size_eu'] = '43'
        with self.assertRaises(ValueError):self.project(data)

    def test_duplicate_tuple_is_not_removed(self):
        data = catalog();data['products'][0]['variants'].append(deepcopy(data['products'][0]['variants'][0]))
        with self.assertRaises(ValueError):self.project(data)

    def test_identity_alias_is_not_accepted(self):
        data = catalog();data['products'][0]['variants'][1]['key'] = 'navy42'
        with self.assertRaises(ValueError):self.project(data)

    def test_tampered_price_cannot_restore(self):
        after, evidence = self.project();after['products'][0]['variants'][0]['priceMinor'] += 1
        with self.assertRaises(ValueError):axis.restore(after, evidence)


def parallel_source_controls():
    """Two threads for tiny pure controls, no heavy resource launch."""
    names = unittest.defaultTestLoader.getTestCaseNames(ProjectionTests)
    def run(name):
        result = unittest.TestResult();ProjectionTests(name).run(result)
        return {'case': name, 'passed': result.wasSuccessful(),
                'errors': result.errors, 'failures': result.failures}
    with ThreadPoolExecutor(max_workers=2) as pool:return list(pool.map(run, names))
