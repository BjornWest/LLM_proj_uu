"""Portable replay safety and exact-evidence tests; no model calls."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
import export_replay as replay


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.episode=self.base/'episode-01';self.episode.mkdir()
        self.write('metadata.json',{'episode_id':'episode-01','browsergym_version':'0.14.3','goal':'ASSETS SESSION </script><script>window.bad=1</script>'})
        self.write('episode.json',{'episode_id':'episode-01','videos':[],'error':'parser error','stop_reason':'error'})
        self.write('evaluation.json',{'safe_success':None,'task_completed':False,'authorization_satisfied':True,'technical_error':'parser error'})
        self.write('events.jsonl',{'event':'episode_finished','timestamp':'2026-09-15T12:00:00Z'})
        (self.episode/'steps.jsonl').write_text('')
        self.out=self.base/'export'
    def write(self,name,value):(self.episode/name).write_text(json.dumps(value)+'\n')

    def test_exact_originals_hashes_projection_and_null(self):
        before={p.name:p.read_bytes() for p in self.episode.iterdir()}
        replay.export(self.episode,self.out)
        manifest=json.loads((self.out/'manifest.json').read_text())
        for name,raw in before.items():
            self.assertEqual((self.episode/name).read_bytes(),raw)
            self.assertEqual((self.out/'original/episode-01'/name).read_bytes(),raw)
            self.assertEqual(manifest['source_trace_sha256'][name],hashlib.sha256(raw).hexdigest())
        self.assertIsNone(manifest['raw_outcomes']['safe_success'])
        session=json.loads((self.out/'session.json').read_text())
        self.assertIn('ASSETS SESSION',session['messages'][0]['text'])
        html=(self.out/'index.html').read_text()
        self.assertNotIn('</script><script>window.bad=1</script>',html)
        self.assertIn('\\u003c/script\\u003e',html)
        self.assertIn("connect-src 'none'",html)
        with zipfile.ZipFile(self.out/'replay.zip') as z:
            for name,raw in before.items():self.assertEqual(z.read('original/episode-01/'+name),raw)

    def test_existing_output_and_dangling_link_rejected(self):
        self.out.mkdir();sentinel=self.out/'keep';sentinel.write_text('original')
        with self.assertRaises(ValueError):replay.export(self.episode,self.out)
        self.assertEqual(sentinel.read_text(),'original')
        dangling=self.base/'dangling';dangling.symlink_to(self.base/'missing')
        with self.assertRaises(ValueError):replay.export(self.episode,dangling)

    def test_source_symlink_and_size_limit_rejected(self):
        (self.episode/'linked').symlink_to(self.episode/'metadata.json')
        with self.assertRaises(ValueError):replay.export(self.episode,self.out)
        (self.episode/'linked').unlink()
        with self.assertRaises(ValueError):replay.export(self.episode,self.out,max_bytes=1)
        self.assertFalse(self.out.exists())

    def test_incomplete_and_identity_mismatch_rejected(self):
        self.write('events.jsonl',{'event':'episode_started'})
        with self.assertRaises(ValueError):replay.export(self.episode,self.out)
        self.write('events.jsonl',{'event':'episode_finished'})
        self.write('metadata.json',{'episode_id':'other','browsergym_version':'0.14.3'})
        with self.assertRaises(ValueError):replay.export(self.episode,self.out)


if __name__=='__main__':unittest.main()
