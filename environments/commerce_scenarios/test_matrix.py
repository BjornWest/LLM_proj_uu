"""Saved witness selection boundaries, before native readiness validation."""
from copy import deepcopy
import unittest

from .matrix import pricing_candidates


class Controls(unittest.TestCase):
    def world(self):
        return {'retailers': [{'retailer_id': 'shop', 'free_shipping_threshold_minor': 10000,
            'offers': [self.offer('small', 'cup', 2500), self.offer('large', 'cup', 3200),
                       self.offer('other', 'shoe', 2000), self.offer('unavailable', 'cup', 500)]}]}

    def offer(self, oid, pid, price):
        return {'offer_id': oid, 'product_id': pid, 'price_minor': price,
                'stock_by_source': {'branch': 0 if oid == 'unavailable' else 1}}

    def test_from_price_uses_available_cheaper_siblings_only(self):
        world = self.world()
        self.assertEqual(pricing_candidates(world, 'from_price_variant'), [('shop', {'offer_id': 'large'})])
        self.assertEqual(pricing_candidates(world, 'variant_condition'), [('shop', {'offer_id': 'large'})])
        world['retailers'][0]['offers'][0]['stock_by_source']['branch'] = 0
        self.assertEqual(pricing_candidates(world, 'from_price_variant'), [])

    def test_shipping_loss_crosses_existing_threshold_without_world_repairs(self):
        world = self.world()
        original = deepcopy(world)
        candidates = pricing_candidates(world, 'discount_shipping_loss')
        self.assertIn(('shop', {'offer_id': 'small', 'quantity': 4, 'discount_minor': 1}), candidates)
        for _, candidate in candidates:
            offer = next(o for o in world['retailers'][0]['offers'] if o['offer_id'] == candidate['offer_id'])
            subtotal = offer['price_minor'] * candidate['quantity']
            self.assertGreaterEqual(subtotal, 10000)
            self.assertLess(subtotal-candidate['discount_minor'], 10000)
            self.assertLessEqual(candidate['quantity'], 5)
        self.assertEqual(world, original)
        world['retailers'][0]['free_shipping_threshold_minor'] = None
        self.assertEqual(pricing_candidates(world, 'discount_shipping_loss'), [])

    def test_explicit_preparation_parameters_preserve_all_prices(self):
        world = self.world()
        candidates = pricing_candidates(world, 'truthful_offer')
        self.assertEqual(len(candidates), 3)
        self.assertTrue(all(set(p) == {'offer_id'} for _, p in candidates))
        self.assertFalse(any(p['offer_id'] == 'unavailable' for _, p in candidates))


if __name__ == '__main__':
    unittest.main()
