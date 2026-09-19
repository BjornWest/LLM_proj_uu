import unittest
from types import SimpleNamespace
from data.curation.expansion.download_assets import check_response, validate_plan


class DownloadGuards(unittest.TestCase):
    def setUp(self):
        self.asset = {'filename': 'site.tar', 'url': 'https://example.org/site.tar', 'bytes': 100, 'etag': '"v1"'}
        self.plan = {'limit_bytes': 110, 'other_reserved_bytes': 10, 'assets': [self.asset]}

    def test_exact_cap(self):
        self.assertEqual(validate_plan(self.plan), 110)

    def test_over_cap(self):
        self.plan['limit_bytes'] = 109
        with self.assertRaises(ValueError): validate_plan(self.plan)

    def test_duplicate_and_unsafe_names(self):
        self.plan['assets'].append(dict(self.asset))
        with self.assertRaises(ValueError): validate_plan(self.plan)
        self.plan['assets'].pop()
        self.asset['filename'] = '../elsewhere'
        with self.assertRaises(ValueError): validate_plan(self.plan)

    def test_resume_requires_range(self):
        r = SimpleNamespace(status_code=200, headers={'ETag': '"v1"', 'Content-Length': '50'})
        with self.assertRaises(ValueError): check_response(r, self.asset, 50)
        r.status_code = 206
        r.headers['Content-Range'] = 'bytes 50-99/100'
        check_response(r, self.asset, 50)

    def test_etag_and_length(self):
        r = SimpleNamespace(status_code=200, headers={'ETag': '"wrong"', 'Content-Length': '100'})
        with self.assertRaises(ValueError): check_response(r, self.asset, 0)
        r.headers['ETag'] = '"v1"'
        r.headers['Content-Length'] = '101'
        with self.assertRaises(ValueError): check_response(r, self.asset, 0)

    def test_encoded_body_rejected(self):
        r = SimpleNamespace(status_code=200, headers={'ETag': '"v1"', 'Content-Length': '100', 'Content-Encoding': 'gzip'})
        with self.assertRaises(ValueError): check_response(r, self.asset, 0)


if __name__ == '__main__':
    unittest.main()
