import unittest
from types import SimpleNamespace
from data.curation.expansion.download_ranges_v3 import validate_range

class PrefixRange(unittest.TestCase):
 def test_prefix_uses_original_total(self):
  response=SimpleNamespace(status_code=206,headers={'Content-Range':'bytes 0-99/1000','Content-Length':'100','ETag':'pin'})
  validate_range(response,{'bytes':100,'source_bytes':1000,'etag':'pin'},0,99)
 def test_short_total_rejected(self):
  response=SimpleNamespace(status_code=206,headers={'Content-Range':'bytes 0-99/100','Content-Length':'100','ETag':'pin'})
  with self.assertRaises(ValueError):validate_range(response,{'bytes':100,'source_bytes':1000,'etag':'pin'},0,99)
 def test_changed_etag_rejected(self):
  response=SimpleNamespace(status_code=206,headers={'Content-Range':'bytes 0-99/1000','Content-Length':'100','ETag':'changed'})
  with self.assertRaises(ValueError):validate_range(response,{'bytes':100,'source_bytes':1000,'etag':'pin'},0,99)
if __name__=='__main__':unittest.main()
