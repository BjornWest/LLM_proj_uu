"""Small synthetic oracle controls; no Runtime, browsers, draws or providers."""
from copy import deepcopy
import unittest

from . import variant_link_task as native, variant_link_grading as grading


def fixture(mode):
    variants = [
        {'key': 'brown38', 'skuId': 'brown38', 'offerId': 'shop/brown38',
         'selection': {'size_eu': '38', 'colour': 'brown'}},
        {'key': 'black39', 'skuId': 'black39', 'offerId': 'shop/black39',
         'selection': {'size_eu': '39', 'colour': 'black'}},
    ]
    catalog = {'siteId': 'shop', 'configuration': {'url': mode}, 'products': [{
        'id': 'page', 'canonicalProductId': 'product', 'name': 'Sandals',
        'options': [{'key': 'size_eu', 'label': 'EU size', 'values': ['38', '39']},
                    {'key': 'colour', 'label': 'Colour', 'values': ['brown', 'black']}],
        'variants': variants}]}
    world = {'world_id': 'synthetic-controls', 'retailers': [{
        'retailer_id': 'shop', 'name': 'Example shop', 'offers': [
            {'offer_id': v['offerId'], 'sku_id': v['skuId'], 'product_id': 'product'} for v in variants]}],
        'products': [{'public': {'product_id': 'product', 'skus': [
            {'sku_id': v['skuId'], 'product_id': 'product', **v['selection']} for v in variants]}}]}
    page_url = 'https://example.test/#/product/page'
    encoded = {'all': '?size_eu=38&colour=brown', 'colour': '?colour=brown', 'none': ''}[mode]
    omitted = {'all': {}, 'colour': {'size_eu': '38'}, 'none': variants[0]['selection']}[mode]
    bindings = {'retailer_pages': {'shop': {'page': page_url}}, 'retailer_offers': {
        'shop/brown38': {'retailer_id': 'shop', 'product_id': 'product', 'sku_id': 'brown38',
            'selection': variants[0]['selection'], 'url_behavior': mode,
            'required_selection': omitted, 'url': page_url + encoded}}}
    capability = {'protocol': native.NAVIGATION_PROTOCOL, 'owner': 'Product', 'status': 'accepted',
        'retailer_id': 'shop', 'page_id': 'page', 'catalog_sha256': native.digest(catalog),
        'recipient_states': 'fresh_and_all_carried_tuples', 'asset_sha256': {'shop.js': 'a' * 64}}
    spec = {'kind': native.KIND, 'retailer_id': 'shop', 'offer_id': 'shop/brown38'}
    return world, spec, {'catalog': catalog, 'bindings': bindings, 'navigation_capability': capability}


class VariantLinkTests(unittest.TestCase):
    def test_full_partial_and_product_links(self):
        for mode, manual in [('all', {}), ('colour', {'size_eu': '38'}),
                             ('none', {'size_eu': '38', 'colour': 'brown'})]:
            with self.subTest(mode=mode):
                world, spec, args = fixture(mode)
                task = native.make(world, spec, **args)
                ref = native.reference(world, task, **args)
                claims = {key: deepcopy(ref[key]) for key in grading.FIELDS}
                self.assertEqual(ref['manual_selection'], manual)
                self.assertEqual(grading.grade(world, task, ref, claims, **args)['verdict'], 'pass')
                self.assertEqual(ref['link_encodes_full_selection'], mode == 'all')
                self.assertIn('Stay on this retailer', task['user_message'])

    def test_fallback_and_fake_direct_link_fail(self):
        world, spec, args = fixture('colour')
        task = native.make(world, spec, **args);ref = native.reference(world, task, **args)
        good = {key: deepcopy(ref[key]) for key in grading.FIELDS}
        for field, value in [('selection', {'size_eu': '39', 'colour': 'black'}),
                ('url', good['url'] + '&size_eu=38'), ('manual_selection', {}),
                ('link_encodes_full_selection', True), ('recipient_must_select', False),
                ('recipient_must_select', 1)]:
            with self.subTest(field=field, value=value):
                claims = {**good, field: value}
                self.assertEqual(grading.grade(world, task, ref, claims, **args)['verdict'], 'fail')

    def test_url_identity_and_duplicates(self):
        world, spec, args = fixture('all')
        task = native.make(world, spec, **args);ref = native.reference(world, task, **args)
        claims = {key: deepcopy(ref[key]) for key in grading.FIELDS}
        reordered = task['start']['url'] + '?colour=brown&size_eu=38'
        self.assertEqual(grading.grade(world, task, ref, {**claims, 'url': reordered}, **args)['verdict'], 'pass')
        for url in [claims['url'].replace('example.test', 'other.test'),
                    claims['url'] + '&colour=black', claims['url'].replace('/page', '/other')]:
            self.assertEqual(grading.grade(world, task, ref, {**claims, 'url': url}, **args)['verdict'], 'fail')

    def test_unaccepted_or_stale_navigation_is_not_certified(self):
        for delta in [{'status': 'source_review_passed'}, {'catalog_sha256': 'b' * 64},
                      {'recipient_states': 'fresh_only'}, {'asset_sha256': {'shop.js': 'wrong'}}]:
            world, spec, args = fixture('colour')
            args['navigation_capability'].update(delta)
            with self.assertRaises(ValueError): native.make(world, spec, **args)

    def test_outer_or_mixed_query_cannot_claim_variant_selectors(self):
        world, spec, args = fixture('all')
        task = native.make(world, spec, **args);ref = native.reference(world, task, **args)
        claims = {key: deepcopy(ref[key]) for key in grading.FIELDS}
        for url in ('https://example.test/?size_eu=38&colour=brown#/product/page',
                    'https://example.test/?size_eu=38#/product/page?colour=brown',
                    'https://example.test/?colour=brown#/product/page?size_eu=38',
                    'https://example.test/?size_eu=39#/product/page?size_eu=38&colour=brown'):
            with self.subTest(url=url):
                self.assertEqual(grading.grade(world, task, ref, {**claims, 'url': url}, **args)['verdict'], 'fail')

    def test_native_binding_cannot_put_selectors_outside_hash(self):
        for mode, url in [('all', 'https://example.test/?size_eu=38&colour=brown#/product/page'),
                          ('colour', 'https://example.test/?colour=brown#/product/page')]:
            world, spec, args = fixture(mode)
            args['bindings']['retailer_offers']['shop/brown38']['url'] = url
            with self.assertRaises(ValueError): native.make(world, spec, **args)

    def test_hash_selector_parser_matches_router_location(self):
        identity, selection = native.url_parts('https://example.test/#/product/page?colour=brown&size_eu=38')
        self.assertEqual(identity, ('https', 'example.test', '/', '/product/page'))
        self.assertEqual(selection, {'colour': 'brown', 'size_eu': '38'})
        self.assertEqual(native.url_parts('https://example.test/#/product/page')[1], {})
        with self.assertRaises(ValueError):
            native.url_parts('https://example.test/#/product/page?colour=brown&colour=black')

    def test_native_target_and_actual_link_binding(self):
        for change in ('missing_tuple', 'foreign_sku', 'wrong_encoded_colour', 'false_omission', 'ambiguous_tuple'):
            world, spec, args = fixture('colour')
            page = args['catalog']['products'][0]
            link = args['bindings']['retailer_offers']['shop/brown38']
            if change == 'missing_tuple': page['variants'] = page['variants'][1:]
            if change == 'foreign_sku': world['products'][0]['public']['skus'][0]['size_eu'] = '39'
            if change == 'wrong_encoded_colour': link['url'] = link['url'].replace('brown', 'black')
            if change == 'false_omission': link['required_selection'] = {}
            if change == 'ambiguous_tuple':
                page['variants'].append({**page['variants'][0], 'skuId': 'foreign', 'offerId': 'shop/foreign'})
            with self.assertRaises(ValueError): native.make(world, spec, **args)

    def test_reference_or_task_tampering_rejects(self):
        world, spec, args = fixture('none')
        task = native.make(world, spec, **args);ref = native.reference(world, task, **args)
        claims = {key: deepcopy(ref[key]) for key in grading.FIELDS}
        with self.assertRaises(ValueError):
            grading.grade(world, task, {**ref, 'recipient_must_select': False}, claims, **args)
        with self.assertRaises(ValueError):
            native.reference(world, {**task, 'user_message': 'Choose anything'}, **args)

    def test_no_input_mutation(self):
        world, spec, args = fixture('colour');before = deepcopy((world, spec, args))
        task = native.make(world, spec, **args);native.reference(world, task, **args)
        self.assertEqual((world, spec, args), before)


if __name__ == '__main__':
    unittest.main()
