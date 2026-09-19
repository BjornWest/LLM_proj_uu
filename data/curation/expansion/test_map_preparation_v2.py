import copy, hashlib, io, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from data.curation.expansion import prepare_map_volumes_v2 as m

class MapPreparationTests(unittest.TestCase):
    def setUp(self):
        self.plan=json.loads(Path('data/curation/expansion/map-setup-plan-v2.json').read_text())
        self.assets={a['filename']:a for a in json.loads(Path('data/curation/expansion/download-plan-v2.json').read_text())['assets']}
    def test_current_plan(self):m.validate_plan(self.plan,self.assets)
    def test_bad_plans_before_mutation(self):
        for mutate in [lambda p:p['volumes'].append(p['volumes'][0]),lambda p:p['volumes'][0].update(strip_components=999),lambda p:p['volumes'][0].update(source_archive='../x')]:
            p=copy.deepcopy(self.plan);mutate(p)
            with self.assertRaises(ValueError):m.validate_plan(p,self.assets)
    def test_output_reserved_before_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);out=d/'report.json';out.write_text('original')
            with patch.object(m,'cmd') as command:
                with self.assertRaises(FileExistsError):m.prepare(d/'missing',d/'missing',d,out,True)
                command.assert_not_called();self.assertEqual(out.read_text(),'original')
    def test_failure_durable_before_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);out=d/'report.json'
            with patch.object(m,'cmd') as command:
                with self.assertRaises(FileNotFoundError):m.prepare(d/'missing',d/'missing',d,out,True)
                command.assert_not_called();self.assertEqual(json.loads(out.read_text())['status'],'failed_partial_volumes_preserved')
    def test_foreign_volume_rejected(self):
        for labels in [{},{'intent.owner':'curation-expansion','intent.extraction-token':'other'}]:
            with patch.object(m,'cmd',return_value=json.dumps([{'Name':'test','Labels':labels}])):
                with self.assertRaises(ValueError):m.volume_guard('test','ours')
    def test_streamed_content_checked(self):
        sink=io.BytesIO()
        with self.assertRaises(ValueError):m.transfer(io.BytesIO(b'changed'),sink,hashlib.sha256(b'original').hexdigest())
        self.assertEqual(sink.getvalue(),b'changed') # a mismatch must leave an explicitly untrusted partial volume
    def test_held_descriptor_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'archive';p.write_bytes(b'original')
            with p.open('rb') as stream:
                ident=m.identity(stream);q=Path(tmp)/'new';q.write_bytes(b'replaced');q.replace(p)
                with self.assertRaises(ValueError):m.verify_identity(p,stream,ident)
                self.assertEqual(stream.read(),b'original')

if __name__=='__main__':unittest.main()
