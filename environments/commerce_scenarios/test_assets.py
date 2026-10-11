"""Projection seams and exact inverse over the actual composed renderer."""
from hashlib import sha256
import unittest

from environments.website_world.adapter import ROOT
from environments.website_world.basket import basket_shop_source
from environments.website_world.simulated_order_presentation import project_assets as order_assets
from . import assets

DRAFTS, LOCAL = ROOT/'environments/website_drafts', ROOT/'environments/website_world'


def composed(canonical_domain=True):
    """The renderer and quote binding as `Runtime` composes them for an ordering shop."""
    native = {'shop.js': basket_shop_source((DRAFTS/'shop.js').read_text(),
                                            canonical_domain=canonical_domain).encode(),
              'quote.js': (LOCAL/'basket_quote.js').read_bytes()}
    return order_assets(native, expected_source_sha256=sha256(native['shop.js']).hexdigest())[0]


def pins(native):
    return {'expected_source_sha256': sha256(native['shop.js']).hexdigest(),
            'expected_quote_sha256': sha256(native['quote.js']).hexdigest()}


class Controls(unittest.TestCase):
    def test_projection_patches_unique_seams_and_inverts_exactly(self):
        for canonical in (True, False):
            native = composed(canonical)
            served, evidence = assets.project_assets(native, **pins(native), pieces={'family.js': b'export{}'})
            self.assertEqual(assets.restore_source(served['shop.js'], evidence), native['shop.js'])
            self.assertEqual(assets.restore_quote(served['quote.js'], evidence), native['quote.js'])
            text = served['shop.js'].decode()
            for old, new in assets.HOOKS.items():
                self.assertEqual(text.count(new), 1, old)
            self.assertTrue(text.endswith(assets.IMPORT))
            self.assertIn('optionId:selected.id,', served['quote.js'].decode())
            self.assertEqual(served['commerce-scenario.js'], (assets.HERE/'scenario.js').read_bytes())
            self.assertEqual(served['commerce-scenario.css'], (assets.HERE/'scenario.css').read_bytes())
            self.assertEqual(set(served) - set(native), {'commerce-scenario.js', 'commerce-scenario.css', 'family.js'})
            self.assertEqual(evidence['served_asset_sha256']['family.js'], sha256(b'export{}').hexdigest())
            self.assertEqual(evidence['pieces'], ['family.js'])
            self.assertEqual({name for name in native if native[name] != served[name]}, {'shop.js', 'quote.js'})

    def test_changed_or_already_projected_sources_are_refused(self):
        native = composed()
        served, evidence = assets.project_assets(native, **pins(native))
        with self.assertRaises(ValueError):
            assets.project_assets(served, **pins(served))
        with self.assertRaises(ValueError):
            assets.project_assets(native, **{**pins(native), 'expected_source_sha256': '0' * 64})
        with self.assertRaises(ValueError):
            assets.project_assets(native, **{**pins(native), 'expected_quote_sha256': '0' * 64})
        drifted = {**native, 'shop.js': native['shop.js'].replace(assets.REVIEW.encode(), b'<section>')}
        with self.assertRaisesRegex(ValueError, 'seam is absent or ambiguous'):
            assets.project_assets(drifted, **pins(drifted))
        doubled = {**native, 'shop.js': native['shop.js'] + assets.SAVE.encode()}
        with self.assertRaisesRegex(ValueError, 'seam is absent or ambiguous'):
            assets.project_assets(doubled, **pins(doubled))
        with self.assertRaises(ValueError):
            assets.restore_source(served['shop.js'] + b' ', evidence)
        with self.assertRaises(ValueError):
            assets.restore_source(served['shop.js'], {**evidence, 'before_sha256': '0' * 64})
        for name in ('Family.js', 'family.mjs', 'shop.js', 'commerce-scenario.js', '../x.js'):
            with self.assertRaises(ValueError, msg=name):
                assets.project_assets(native, **pins(native), pieces={name: b''})
        with self.assertRaises(ValueError):
            assets.project_assets(native, **pins(native), pieces={'family.js': 'text'})


if __name__ == '__main__':
    unittest.main()
