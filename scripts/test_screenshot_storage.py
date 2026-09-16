import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
import zipfile
from unittest.mock import patch
from screenshot_storage import scan, replace_reference, PNG

class ScreenshotStorageTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.base=Path(self.temp.name);self.root=self.base/'runs';self.root.mkdir();self.pool=self.base/'objects'
 def episode(self,name,closed=True):
  p=self.root/name;p.mkdir()
  if closed:(p/'episode.json').write_text(json.dumps({'episode_id':name,'stop_reason':'done'}))
  return p
 def image(self,episode,name='observation-000.png',data=PNG+b'example'):
  p=episode/name;p.write_bytes(data);return p
 def run_scan(self,**kw):return scan(self.root,self.pool,min_age=0,**kw)
 def test_identical_bytes_share_inode_and_different_bytes_never_do(self):
  a=self.image(self.episode('a'));b=self.image(self.episode('b'));c=self.image(self.episode('c'),data=PNG+b'different')
  r=self.run_scan(apply=True);self.assertTrue(r['ok']);self.assertEqual(r['linked_files'],3)
  self.assertEqual(a.stat().st_ino,b.stat().st_ino);self.assertNotEqual(a.stat().st_ino,c.stat().st_ino)
  self.assertEqual(r['references'][0]['references'],2);self.assertEqual(r['unique_images'],2)
  self.assertEqual(a.read_bytes(),PNG+b'example');self.assertFalse(a.is_symlink())
  self.assertEqual(self.run_scan(apply=True)['linked_files'],0)
 def test_dry_run_and_unfinished_recent_files_not_modified(self):
  a=self.image(self.episode('a'));b=self.image(self.episode('b',closed=False));before=[a.stat().st_ino,b.stat().st_ino]
  self.assertTrue(self.run_scan()['ok']);self.assertFalse(self.pool.exists())
  r=scan(self.root,self.pool,apply=True,min_age=60);self.assertEqual(r['linked_files'],0)
  r=self.run_scan(apply=True);self.assertEqual(r['linked_files'],1);self.assertEqual(b.stat().st_ino,before[1])
 def test_exact_zip_exports_and_existing_archives_preserved(self):
  a=self.image(self.episode('a'));self.image(a.parent,'decision-observation-000.png')
  before={p.name:p.read_bytes() for p in a.parent.iterdir()}
  old=self.root/'old.zip'
  with zipfile.ZipFile(old,'w',zipfile.ZIP_DEFLATED) as z:
   for n,v in before.items():z.writestr(n,v)
  archive_bytes=old.read_bytes();r=self.run_scan(apply=True)
  self.assertEqual(r['archive_png_entries'],2);self.assertEqual(old.read_bytes(),archive_bytes)
  new=self.root/'new.zip'
  with zipfile.ZipFile(new,'w',zipfile.ZIP_DEFLATED) as z:
   for p in a.parent.iterdir():z.write(p,p.name)
  with zipfile.ZipFile(new) as z:self.assertEqual({n:z.read(n) for n in z.namelist()},before)
 def test_corrupt_object_fails_without_replacing_source(self):
  a=self.image(self.episode('a'));self.run_scan(apply=True)
  obj=next(self.pool.rglob('*.png'));obj.chmod(0o644);obj.write_bytes(PNG+b'corrupt')
  b=self.image(self.episode('b'));inode=b.stat().st_ino
  r=self.run_scan(apply=True);self.assertFalse(r['ok']);self.assertEqual(b.read_bytes(),PNG+b'example');self.assertEqual(b.stat().st_ino,inode)
 def test_symlinks_not_followed_and_pool_cannot_be_in_episode(self):
  a=self.image(self.episode('a'));self.image(self.episode('b'))
  (a.parent/'linked.png').symlink_to(a)
  r=self.run_scan(apply=True);self.assertEqual(r['png_files'],2)
  with self.assertRaises(ValueError):scan(self.root,a.parent/'objects',apply=True)
  linked=self.base/'linked-root';linked.symlink_to(self.root,target_is_directory=True)
  with self.assertRaises(ValueError):scan(linked,self.pool)
 def test_changed_source_detected_before_replace(self):
  a=self.image(self.episode('a'));expected=a.stat();destination=self.base/'saved';destination.write_bytes(a.read_bytes());a.write_bytes(PNG+b'changed')
  with self.assertRaises(ValueError):replace_reference(a,destination,expected,PNG+b'example')
  self.assertEqual(a.read_bytes(),PNG+b'changed')
 def test_reference_removal_does_not_remove_shared_bytes_and_threshold_only_reports(self):
  a=self.image(self.episode('a'));b=self.image(self.episode('b'));r=scan(self.root,self.pool,apply=True,min_age=0,threshold=1)
  self.assertTrue(r['threshold_reached']);self.assertFalse(r['retention_deletion']);a.unlink()
  self.assertEqual(b.read_bytes(),PNG+b'example');r=self.run_scan(apply=True)
  self.assertEqual(r['references'][0]['references'],1);self.assertEqual(r['unique_images'],1)


 def test_private_permissions_not_widened(self):
  a=self.image(self.episode('a'));a.chmod(0o600)
  b=self.image(self.episode('b'));b.chmod(0o644)
  self.run_scan(apply=True)
  self.assertEqual(a.stat().st_mode & 0o777,0o400)
  self.assertEqual(b.stat().st_mode & 0o777,0o444)
  self.assertNotEqual(a.stat().st_ino,b.stat().st_ino)
 def test_cross_root_reference_counts_and_no_garbage_collection(self):
  a=self.image(self.episode('a'));self.run_scan(apply=True)
  outside=self.base/'external.png';os.link(a,outside);a.unlink()
  r=self.run_scan();self.assertEqual(r['pool_objects'][0]['hardlink_references'],1)
  self.assertEqual(r['unreferenced_pool_bytes'],0)
  self.assertGreater(r['pool_bytes_outside_scan'],0)
  outside.unlink();r=self.run_scan()
  self.assertGreater(r['unreferenced_pool_bytes'],0)
  self.assertEqual(len(list(self.pool.rglob('*.png'))),1)
 def test_error_is_not_reported_as_below_threshold(self):
  a=self.image(self.episode('a'))
  with patch('screenshot_storage.install_object',side_effect=ValueError('test failure')):
   r=self.run_scan(apply=True)
  self.assertFalse(r['ok']);self.assertIsNone(r['threshold_reached'])
  self.assertEqual(r['physical_png_bytes_after_including_pool'],a.stat().st_blocks*512)

if __name__=='__main__':unittest.main()
