"""Guard the isolation mechanism independently of browser/model calls."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class RuntimeSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        (self.root/'intent_browser').mkdir();self.module=self.root/'intent_browser/__init__.py'
        self.module.write_text('ORIGIN = "frozen-test-package"\n')
        pins={'intent_browser/__init__.py':hashlib.sha256(self.module.read_bytes()).hexdigest()}
        (self.root/'manifest.json').write_text(json.dumps({'source_sha256':pins}))

    def tearDown(self):self.tmp.cleanup()

    def run_child(self, prefix=''):
        code=prefix+'\nfrom data.curation.expansion.runtime_snapshot import activate\nactivate()\nimport intent_browser\nprint(intent_browser.ORIGIN)'
        return subprocess.run([sys.executable,'-c',code],env={**os.environ,'CURATION_FROZEN_RUNTIME':str(self.root)},capture_output=True,text=True,timeout=10)

    def test_imports_copy_even_with_checkout_on_path(self):
        result=self.run_child();self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),'frozen-test-package')

    def test_changed_copy_rejected(self):
        self.module.write_text('ORIGIN = "changed"\n');self.assertNotEqual(self.run_child().returncode,0)

    def test_extra_module_rejected(self):
        (self.root/'intent_browser/unrecorded.py').write_text('')
        self.assertNotEqual(self.run_child().returncode,0)

    def test_preloaded_other_package_rejected(self):
        result=self.run_child('import intent_browser')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Wrong package already loaded',result.stderr)


if __name__=='__main__':unittest.main()
