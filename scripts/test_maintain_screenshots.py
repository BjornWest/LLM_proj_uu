import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from maintain_screenshots import summarize, render, atomic_write, docker_command, LIMIT

class MonitorTests(unittest.TestCase):
 def scope(self, size=1024):
  return {'ok':True,'physical_png_bytes_after_including_pool':size,'archive_png_compressed_bytes':100,
          'png_files':3,'unique_images':1,'logical_png_bytes':3072,'linked_files':3}
 def test_threshold_uses_physical_plus_archives_and_db_upper_bound(self):
  r=summarize({'local':self.scope()},0,[])
  self.assertEqual(r['monitored_budget_bytes'],1124);self.assertEqual(r['status'],'below_threshold')
  r=summarize({'local':self.scope()},LIMIT-1124,[])
  self.assertTrue(r['review_required']);self.assertFalse(r['retention_deletion'])
  self.assertIn('nothing is automatically deleted',render(r))
 def test_incomplete_never_means_under_budget(self):
  for r in [summarize({},None,[]),summarize({},0,[{'scope':'manual','error':'offline'}]),
            summarize({'local':{**self.scope(),'ok':False}},0,[])]:
   self.assertFalse(r['complete']);self.assertIsNone(r['review_required']);self.assertEqual(r['status'],'incomplete')
 def test_html_escape_errors_and_no_raw_paths_or_reference_data(self):
  r=summarize({'local':self.scope()},0,[{'error':'<script>evil</script>'}])
  self.assertNotIn('<script>',render(r));self.assertIn('&lt;script&gt;',render(r))
 def test_atomic_report_replacement(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'report.json';atomic_write(p,'{"a":1}');atomic_write(p,'{"a":2}')
   self.assertEqual(json.loads(p.read_text()),{'a':2});self.assertEqual(list(Path(d).iterdir()),[p])
 def test_missing_volume_does_not_create_empty_replacement(self):
  with patch('maintain_screenshots.subprocess.run',side_effect=RuntimeError('missing')):
   with self.assertRaises(RuntimeError):docker_command('missing')
 def test_helpers_no_network_downloads_or_credentials(self):
  with patch('maintain_screenshots.subprocess.run'):
   cmd=docker_command('existing');self.assertIn('none',cmd);self.assertIn('never',cmd)
   self.assertNotIn('--env-file',cmd);self.assertIn('type=volume,source=existing,target=/scan,readonly',cmd)

if __name__=='__main__':unittest.main()
