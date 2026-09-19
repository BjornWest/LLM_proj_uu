"""Resume must preserve earlier hashes instead of silently blessing changed bytes."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from data.curation.expansion.download_ranges_v2 import verify_completed

class ResumeChecks(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.p=Path(self.temp.name)/'part';self.p.write_bytes(b'abc');self.entry={'status':'complete','sha256':hashlib.sha256(b'abc').hexdigest()}
 def test_unchanged(self):verify_completed(self.p,self.entry,3)
 def test_same_size_change(self):
  self.p.write_bytes(b'xyz')
  with self.assertRaisesRegex(ValueError,'content changed'):verify_completed(self.p,self.entry,3)
 def test_size_change(self):
  self.p.write_bytes(b'ab')
  with self.assertRaisesRegex(ValueError,'size changed'):verify_completed(self.p,self.entry,3)
 def test_symlink(self):
  q=self.p.with_name('link');q.symlink_to(self.p)
  with self.assertRaisesRegex(ValueError,'regular'):verify_completed(q,self.entry,3)
 def test_missing_digest(self):
  with self.assertRaisesRegex(ValueError,'fingerprint'):verify_completed(self.p,{'status':'complete'},3)
 def test_unfinished_not_promoted(self):
  with self.assertRaisesRegex(ValueError,'fingerprint'):verify_completed(self.p,{**self.entry,'status':'in_progress'},3)

if __name__=='__main__':unittest.main()
