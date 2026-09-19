import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from data.curation.expansion.prepare_map_volumes import member_allowed,members_for

class ArchiveSelection(unittest.TestCase):
 def test_exact_prefix_not_similarly_named(self):
  for name,expected in [('db',True),('db/base/1',True),('db-other/1',False)]:self.assertIs(member_allowed(tarfile.TarInfo(name),'db'),expected)
 def test_traversal(self):
  for name in ['/db/1','db/../outside']:
   with self.assertRaises(ValueError):member_allowed(tarfile.TarInfo(name),'db')
 def test_links_rejected(self):
  for kind in [tarfile.SYMTYPE,tarfile.LNKTYPE,tarfile.CHRTYPE]:
   m=tarfile.TarInfo('db/link');m.type=kind
   with self.assertRaises(ValueError):member_allowed(m,'db')
 def test_exact_prefix_eof(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'prefix';m=tarfile.TarInfo('db/base/1');m.size=3
   p.write_bytes(m.tobuf()+b'abc'+bytes(509))
   self.assertEqual(members_for(p,'db'),[{'name':'db/base/1','bytes':3,'directory':False}])
   with self.assertRaises(ValueError):members_for(p,'absent')

if __name__=='__main__':unittest.main()
