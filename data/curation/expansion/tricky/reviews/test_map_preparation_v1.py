"""Independent offline adversarial review; all Docker/process calls are mocks."""
import hashlib,io,json,tarfile,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from data.curation.expansion import prepare_map_volumes as m

class Sink(io.BytesIO):
 def close(self):self.saved=self.getvalue();super().close()
class Process:
 def __init__(self,command,**kw):self.command=command;self.stdin=Sink();self.returncode=0
 def __enter__(self):return self
 def __exit__(self,*a):return False
 def wait(self):return self.returncode
 def terminate(self):pass

def tarbytes(content=b'GOOD',name='db/file'):
 b=io.BytesIO()
 with tarfile.open(fileobj=b,mode='w')as t:
  for path,data in [('db',None),(name,content)]:
   i=tarfile.TarInfo(path);i.type=tarfile.DIRTYPE if data is None else tarfile.REGTYPE;i.size=len(data or b'');t.addfile(i,io.BytesIO(data)if data is not None else None)
 return b.getvalue()

class Review(unittest.TestCase):
 def fixture(self,root,strip=1,duplicate=False):
  data=tarbytes();(root/'a.tar').write_bytes(data)
  dp={'assets':[{'filename':'a.tar','bytes':len(data)}]};(root/'download.json').write_text(json.dumps(dp))
  ledger={'plan_sha256':m.sha(root/'download.json'),'assets':{'a.tar':{'status':'complete','sha256':m.sha(root/'a.tar')}}};(root/'ranges-ledger.json').write_text(json.dumps(ledger))
  v={'name':'curation-map-v2-test','source_archive':'a.tar','source_prefix':'db','strip_components':strip}
  plan={'image':'cached@sha256:abc','project':'curation-webarena-map-test','volumes':[v,v]if duplicate else[v]};(root/'plan.json').write_text(json.dumps(plan));return data
 def fake(self,root,trigger=None):
  calls=[];processes=[]
  def command(args):
   calls.append(args)
   if args[:3]==['docker','volume','ls']:return ''
   if args[:3]==['docker','image','inspect']:return '[{"Id":"cached-id"}]'
   if args[:3]==['docker','volume','create']:
    if trigger:trigger()
    return args[-1] # Docker returns an already-existing same-name volume as well.
   if args[0:2]==['docker','run']:return 'Filesystem 1024-blocks Used Available Capacity Mounted\nx 999999999 0 999999999 0% /'
   raise AssertionError(args)
  def process(*args,**kw):p=Process(*args,**kw);processes.append(p);return p
  return calls,processes,command,process
 def execute(self,root,command,process):
  with patch.object(m,'cmd',command),patch.object(m.subprocess,'Popen',process):return m.prepare(root/'plan.json',root/'download.json',root,root/'out.json',True)
 def test_existing_volume_rejected_at_initial_listing(self):
  with tempfile.TemporaryDirectory()as d:
   root=Path(d);self.fixture(root)
   with patch.object(m,'cmd',return_value='curation-map-v2-test\n'):
    with self.assertRaises(ValueError):m.prepare(root/'plan.json',root/'download.json',root,root/'out.json',True)
 def test_reproduces_volume_create_race_not_rejected(self):
  with tempfile.TemporaryDirectory()as d:
   root=Path(d);self.fixture(root);external={'existing':False};calls,ps,cmd,pop=self.fake(root,lambda:external.update(existing=True,owner='other'))
   r=self.execute(root,cmd,pop);self.assertTrue(external['existing']);self.assertEqual(r['status'],'extracted_not_launched');self.assertEqual(len(ps),1)
   self.assertFalse(any(c[:3]==['docker','volume','inspect']for c in calls))
 def test_reproduces_duplicate_volume_plan(self):
  with tempfile.TemporaryDirectory()as d:
   root=Path(d);self.fixture(root,duplicate=True);calls,ps,cmd,pop=self.fake(root)
   with self.assertRaises(FileExistsError):self.execute(root,cmd,pop)
   self.assertEqual(sum(c[:3]==['docker','volume','create']for c in calls),2);self.assertEqual(len(ps),1)
   self.assertEqual(json.loads((root/'out.json').read_text())['status'],'failed_partial_volumes_preserved')
 def test_reproduces_late_report_reservation(self):
  with tempfile.TemporaryDirectory()as d:
   root=Path(d);self.fixture(root);calls,ps,cmd,pop=self.fake(root,lambda:(root/'out.json').write_text('other writer'))
   with self.assertRaises(FileExistsError):self.execute(root,cmd,pop)
   self.assertEqual(len(ps),1);self.assertEqual((root/'out.json').read_text(),'other writer')
 def test_reproduces_source_changed_after_verification(self):
  with tempfile.TemporaryDirectory()as d:
   root=Path(d);original=self.fixture(root);calls,ps,cmd,pop=self.fake(root,lambda:(root/'a.tar').write_bytes(tarbytes(b'EVIL')))
   r=self.execute(root,cmd,pop);self.assertEqual(r['source_assets']['a.tar'],hashlib.sha256(original).hexdigest());self.assertIn(b'EVIL',ps[0].stdin.saved);self.assertEqual(r['status'],'extracted_not_launched')
 def test_reproduces_strip_all_files_not_preflight_rejected(self):
  with tempfile.TemporaryDirectory()as d:
   root=Path(d);self.fixture(root,strip=99);calls,ps,cmd,pop=self.fake(root);r=self.execute(root,cmd,pop)
   self.assertEqual(r['status'],'extracted_not_launched');self.assertIn('--strip-components=99',ps[0].command)
 def test_reject_traversal_links_and_devices(self):
  for name,typ in [('/absolute',tarfile.REGTYPE),('db/../escape',tarfile.REGTYPE),('db/link',tarfile.SYMTYPE),('db/hard',tarfile.LNKTYPE),('db/device',tarfile.CHRTYPE)]:
   with self.subTest(name=name):
    t=tarfile.TarInfo(name);t.type=typ
    with self.assertRaises(ValueError):m.member_allowed(t,'db')
 def test_exact_prefix_boundary(self):
  for name,expected in [('db/file',True),('db',True),('db-other/file',False),('other/db/file',False)]:self.assertEqual(m.member_allowed(tarfile.TarInfo(name),'db'),expected)
 def test_existing_and_dangling_output_rejected_before_commands(self):
  with tempfile.TemporaryDirectory()as d:
   root=Path(d);out=root/'out';out.symlink_to(root/'missing')
   with patch.object(m,'cmd',side_effect=AssertionError('Unexpected command')):
    with self.assertRaises(FileExistsError):m.prepare(root/'none',root/'none',root,out,True)
 def test_virtual_end_blocks_do_not_alter_members(self):
  with tempfile.TemporaryDirectory()as d:
   root=Path(d);raw=tarbytes();prefix=raw[:1536];(root/'prefix').write_bytes(prefix);(root/'terminated').write_bytes(prefix+bytes(1024))
   self.assertEqual(m.members_for(root/'prefix','db'),m.members_for(root/'terminated','db'))

if __name__=='__main__':unittest.main()
