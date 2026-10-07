"""Detached arithmetic fixture: real native quotes/store/public projection.

These controls do not start a Runtime/server/browser or certify capture origin.
"""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from experiments.footwear_world_pilot import basket_quote as footwear_quote
from experiments.accepted_catalog_commerce import basket_quote as catalog_quote
from . import checkout_domain, catalog_checkout_domain, simulated_order_task as native
from . import simulated_order_record as records, simulated_order_runtime as presentation
from .simulated_order_publication import basket_context


class NativeBindingControls(unittest.TestCase):
    def fixture(self, catalog=False):
        world = json.loads(Path(__file__).with_name('fixtures').joinpath(
            'simulated_order_quote_world_v1.json').read_bytes())
        world['brands'] = []  # The detached arithmetic fixture has no brand renderer.
        if catalog:
            world['schema_version'] = 'accepted-catalog-commerce-world-v1'
            for product in world['products']:
                product['commerce'] = {'shipping_class': 'regular',
                    'classification_basis': 'closed_ordinary_parcel_concept_slice_v1'}
            for retailer in world['retailers']:
                retailer['catalog'] = [{'pages': [{'listings': [
                    {'sku_id': offer['sku_id']} for offer in retailer['offers']]}]}]
        quote = catalog_quote if catalog else footwear_quote
        domain = catalog_checkout_domain if catalog else checkout_domain
        baskets = basket_context(world, quote.make_plan(world), domain.make(world))
        retailer = world['retailers'][0]
        offer = retailer['offers'][0]
        spec = {'kind': native.KIND, 'retailer_id': retailer['retailer_id'],
            'offer_id': offer['offer_id'], 'quantity': 1, 'delivery_types': None,
            'coupon_code': None, 'public_request': 'Order the item in my cart with the cheapest delivery.',
            'memories': ['Use my saved current address.']}
        task = native.make(baskets, spec)
        reference = native.reference(baskets, task)
        option = reference['winners'][0]
        request = {'revision': 1, 'world_id': world['world_id'], 'plan_id': baskets.plan_id,
            'domain_id': baskets.domain_id, 'lines': deepcopy(task['setup']['lines']),
            'address': deepcopy(task['address_fields']), 'split': option['split'],
            'coupon_code': None, 'selections': deepcopy(option['selection'])}
        actual = baskets.quote(retailer['retailer_id'], request)
        submission = {'idempotency_key': 'ordinary-checkout-1', 'quote_request': request,
            'displayed_quote': {'request_id': actual['requestId'], 'quote_id': actual['quoteId'],
                'option_id': actual['selected']['id'], 'total_minor': actual['selected']['totalMinor'],
                'currency': 'SEK'}, 'delivery_instructions': 'Ring twice.', 'terms_accepted': True}
        product = next(p['public'] for p in world['products'] if p['public']['product_id'] == offer['product_id'])
        sku = next(s for s in product['skus'] if s['sku_id'] == offer['sku_id'])
        selected = {key: str(sku[key]) for key in ('colour', 'width', 'size_eu')}
        # Explicit small public fixture grounded in the native subject; no page renderer.
        public = {'products': [{'name': product['name'], 'canonicalProductId': product['product_id'],
            'options': [{'key': key, 'label': key} for key in selected],
            'variants': [{'offerId': offer['offer_id'], 'skuId': sku['sku_id'], 'selection': selected}]}]}
        runtime = SimpleNamespace(world=world, baskets=baskets,
                                  public_catalogs={retailer['retailer_id']: public})
        presentation.initialize(runtime)
        return runtime, retailer['retailer_id'], submission, reference

    def test_real_native_receipt_roundtrip_and_projection_for_both_world_types(self):
        for catalog in (False, True):
            with self.subTest(catalog=catalog):
                runtime, rid, submission, reference = self.fixture(catalog)
                original = deepcopy(runtime.world)
                response = presentation.submit(runtime, rid, submission)
                private = runtime.orders.snapshot()
                receipt = private['orders'][0]
                self.assertTrue(records.validate(runtime.baskets, rid, receipt))
                confirmation = response['confirmation']
                self.assertEqual(confirmation['id'], receipt['order_id'])
                self.assertEqual(confirmation['address'], receipt['address'])
                self.assertEqual(confirmation['instructions'], 'Ring twice.')
                self.assertEqual(confirmation['items'][0]['offerId'], receipt['items'][0]['offer_id'])
                self.assertEqual(confirmation['items'][0]['quantity'], 1)
                for public, native_key in [('subtotalMinor', 'subtotal_minor'), ('discountMinor', 'discount_minor'),
                                           ('shippingMinor', 'shipping_minor'), ('totalMinor', 'total_minor')]:
                    self.assertEqual(confirmation[public], receipt[native_key])
                self.assertEqual(receipt['shipping_minor'], reference['minimum_shipping_minor'])
                self.assertEqual(runtime.world, original)
                self.assertNotIn('submission', confirmation)
                self.assertNotIn('record_sha256', confirmation)
                # Same actual request is idempotent, never a duplicate order.
                self.assertEqual(presentation.submit(runtime, rid, deepcopy(submission)), response)
                self.assertEqual(len(runtime.orders.snapshot()['orders']), 1)
                submission['idempotency_key'] = 'ordinary-checkout-2'
                second = presentation.submit(runtime, rid, submission)
                self.assertNotEqual(second['confirmation']['id'], confirmation['id'])
                self.assertEqual(len(runtime.orders.snapshot()['orders']), 2)

    def test_stale_displayed_total_and_unrenderable_subject_never_commit(self):
        for case in ('stale_total', 'unrenderable_subject'):
            with self.subTest(case=case):
                runtime, rid, submission, _ = self.fixture()
                if case == 'stale_total':
                    submission['displayed_quote']['total_minor'] += 1
                else:
                    runtime.public_catalogs[rid]['products'][0]['canonicalProductId'] = 'foreign'
                with self.assertRaises(ValueError):
                    presentation.submit(runtime, rid, submission)
                self.assertEqual(runtime.orders.snapshot()['orders'], [])
                self.assertEqual(runtime.orders.snapshot()['events'], [])


if __name__ == '__main__':
    unittest.main()
