"""Small source composition controls; browser acceptance is separately scoped."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import unittest

from environments.website_world import partial_url_navigation as nav
from environments.website_world.basket import basket_shop_source


class PartialNavigationControls(unittest.TestCase):
    def test_composed_sources_and_all_other_assets_have_exact_inverse(self):
        raw = Path(__file__).parents[1].joinpath('website_drafts/shop.js').read_text()
        for basket in (False, True):
            for reviews in (False, True):
                source = basket_shop_source(raw, canonical_domain=True) if basket else raw
                if reviews:
                    source = source.replace('function productPage(id,params) {',
                                            'function originalProductPage(id,params) {')
                    source += '\nimport {customerReviews} from "./retailer_reviews.js";\nfunction productPage(id,params){const body=originalProductPage(id,params);const p=products.find(p=>p.id===id);return body+(p?customerReviews(p,{e}):"");}\n'
                assets = {'shop.js': source.encode(), 'retailer_reviews.js': b'full attributed corpus',
                          'quote.js': b'native basket quote', 'world-data.js': b'native products'}
                before = deepcopy(assets)
                result, evidence = nav.project_assets(assets,
                    expected_source_sha256=sha256(assets['shop.js']).hexdigest())
                self.assertEqual(nav.restore_source(result['shop.js']), assets['shop.js'])
                self.assertEqual(assets, before)
                for key in assets.keys() - {'shop.js'}:
                    self.assertEqual(result[key], assets[key])
                self.assertTrue(evidence['exact_inverse'])
                self.assertEqual(sha256(result['resolve-navigation.js']).hexdigest(), nav.HELPER_SHA256)

    def test_reject_changed_ambiguous_or_preprojected_seams(self):
        source = nav.ANCHOR.encode()
        for bad in (b'', source * 2, source + b'\nresolveNavigation'):
            with self.assertRaises(ValueError):
                nav.project_assets({'shop.js': bad}, expected_source_sha256=sha256(bad).hexdigest())
        with self.assertRaises(ValueError):
            nav.project_assets({'shop.js': source}, expected_source_sha256='0' * 64)
        with self.assertRaises(ValueError):
            nav.project_assets({'shop.js': source, 'resolve-navigation.js': b'unknown'},
                               expected_source_sha256=sha256(source).hexdigest())

    def test_inverse_rejects_changes_to_projection(self):
        result, _ = nav.project_assets({'shop.js': nav.ANCHOR.encode()},
                                      expected_source_sha256=sha256(nav.ANCHOR.encode()).hexdigest())
        with self.assertRaises(ValueError):
            nav.restore_source(result['shop.js'] + b'changed')

    def test_malformed_runtime_option_is_rejected_before_pin_loading(self):
        from environments.website_world.runtime import Runtime
        for value in (None, 'yes', {}, 1):
            with self.assertRaisesRegex(ValueError, 'must be boolean'):
                Runtime('/does-not-exist', partial_url_navigation=value)


if __name__ == '__main__':
    unittest.main()
