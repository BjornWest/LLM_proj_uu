"""Tiny pure asset controls; no Runtime/browser/producer imports."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import unittest
from environments.website_world import review_presentation as reviews


def assets():
    original = Path(__file__).with_name('retailer_reviews.js').read_bytes()
    return {'retailer_reviews.js': original, 'shop.js': b'original shop', 'quote.js': b'original oracle'}


class PresentationTests(unittest.TestCase):
    def test_default_is_exact_asset_noop(self):
        before = assets();after, evidence = reviews.project_assets(before)
        self.assertEqual(before, after)
        self.assertEqual(evidence['changed_assets'], [])
        self.assertEqual(evidence['before_asset_sha256'], evidence['after_asset_sha256'])

    def test_paged_changes_only_copied_review_asset(self):
        before = assets();saved = dict(before)
        after, evidence = reviews.project_assets(before, {'mode': 'paged', 'initial_count': 1, 'batch_size': 3})
        self.assertEqual(before, saved)
        self.assertEqual(after['shop.js'], before['shop.js']);self.assertEqual(after['quote.js'], before['quote.js'])
        self.assertEqual(evidence['changed_assets'], ['retailer_reviews.js'])
        self.assertIn(b'export function customerReviews', after['retailer_reviews.js'])
        self.assertIn(b'"initialCount": 1', after['retailer_reviews.js'])

    def test_inline_preserves_native_corpus_source(self):
        after, _ = reviews.project_assets(assets(), {'mode': 'inline'})
        self.assertIn(b'corpus.rating_summary', after['retailer_reviews.js'])
        self.assertIn(b'"mode": "inline"', after['retailer_reviews.js'])
        self.assertNotIn(b'new Date', after['retailer_reviews.js'])

    def test_invalid_settings_fail(self):
        for value in ({'mode': 'best-comments'}, {'initial_count': 0}, {'batch_size': True},
                      {'sample_reviews': True}, {'batch_size': 101}):
            with self.assertRaises(ValueError):reviews.options(value)

    def test_absent_review_module_is_not_invented(self):
        with self.assertRaises(ValueError):reviews.project_assets({'shop.js': b'original'}, {'mode': 'paged'})


def parallel_source_controls():
    names = unittest.defaultTestLoader.getTestCaseNames(PresentationTests)
    def run(name):
        result = unittest.TestResult();PresentationTests(name).run(result)
        return {'case': name, 'passed': result.wasSuccessful(), 'errors': result.errors, 'failures': result.failures}
    with ThreadPoolExecutor(max_workers=2) as pool:return list(pool.map(run,names))
