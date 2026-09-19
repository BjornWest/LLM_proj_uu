"""Independent v2 safety regression. Docker/processes mocked; no services/volumes."""
import io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from data.curation.expansion import prepare_map_volumes_v2 as m
from data.curation.expansion.tricky.reviews.test_map_preparation_v1 import tarbytes,Process

class ReviewV2(unittest.TestCase):
 def fixture(self,root):
  payload=tarbytes();(root/'a.tar').write_bytes(payload)
  (root/'download.json').write_text(json.dumps({'assets':[{'filename':'a.tar','bytes':len(payload)}]}))
  (root/'ranges-ledger.json').write_text(json.dumps({'plan_sha256':m.sha(root/'download.json'),'assets':{'a.tar':{'status':'complete','sha256':m.sha(root/'a.tar')}}}))
  (root/'plan.json').write_text(json.dumps({'image':'cached@sha256:abc','project':'curation-webarena-map-test','volumes':[{'name':'curation-map-v2-test','mount':'/data','source_archive':'a.tar','source_prefix':'db','strip_components':1}]}))
 def mocks(self,root,mode=None):
  calls=[];ps=[];volumes={};guards=[]
  def cmd(args):
   calls.append(args)
   if args[:3]==['docker','image','inspect']:return '[{"Id":"cached"}]'
   if args[:3]==['docker','volume','ls']:return '\n'.join(volumes)
   if args[:3]==['docker','volume','create']:
    # The report is already reserved durably before the first volume mutation.
    assert json.loads((root/'out.json').read_text())['status']=='extracting'
    name=args[-1];labels=dict(v.split('=',1)for i,v in enumerate(args)if i and args[i-1]=='--label')
    if mode=='foreign':labels={'intent.owner':'other'}
    volumes[name]={'Name':name,'Labels':labels,'Driver':'local','CreatedAt':'now','Mountpoint':'/mock'}
    if mode=='replace_source':(root/'a.tar').unlink();(root/'a.tar').write_bytes(tarbytes(b'EVIL'))
    return name
   if args[:3]==['docker','volume','inspect']:
    guards.append(args[-1]);return json.dumps([volumes[args[-1]]])
   if args[:2]==['docker','run']:
    assert '--pull' in args and args[args.index('--pull')+1]=='never'
    return 'Filesystem 1024-blocks Used Available Capacity Mounted\nx 999999999 0 999999999 0% /'
   raise AssertionError(args)
  def popen(command,**kw):
   assert len(guards)>=2
   p=Process(command,**kw);ps.append(p)
   if mode=='change_during_stream':
    original_write=p.stdin.write
    def write(content):(root/'a.tar').write_bytes(tarbytes(b'EVIL'));return original_write(content)
    p.stdin.write=write
   if mode=='tar_error':p.returncode=2
   return p
  return calls,ps,volumes,cmd,popen
 def run_case(self,root,cmd,pop,execute=True):
  with patch.object(m,'cmd',cmd),patch.object(m.subprocess,'Popen',pop):return m.prepare(root/'plan.json',root/'download.json',root,root/'out.json',execute)
 def test_success_reserves_report_guards_ownership_and_hashes_stream(self):
  with tempfile.TemporaryDirectory()as d:
   root=Path(d);self.fixture(root);calls,ps,vols,cmd,pop=self.mocks(root);r=self.run_case(root,cmd,pop)
   self.assertEqual(r['status'],'extracted_not_launched');self.assertTrue(r['volumes'][0]['completed']);self.assertEqual(r['volumes'][0]['streamed_source_sha256'],m.sha(root/'a.tar'));self.assertIn(r['transaction_id'][:12],next(iter(vols)));self.assertEqual(len(ps),1)
 def test_foreign_volume_race_rejected_before_mount(self):
  with tempfile.TemporaryDirectory()as d:
   root=Path(d);self.fixture(root);calls,ps,vols,cmd,pop=self.mocks(root,'foreign')
   with self.assertRaisesRegex(ValueError,'Foreign'):self.run_case(root,cmd,pop)
   self.assertFalse(ps);self.assertEqual(len(vols),1);self.assertEqual(json.loads((root/'out.json').read_text())['status'],'failed_partial_volumes_preserved');self.assertFalse(any('rm' in c for c in calls if c[:2]!=['docker','run']))
 def test_source_path_replacement_rejected_before_mount(self):
  with tempfile.TemporaryDirectory()as d:
   root=Path(d);self.fixture(root);calls,ps,vols,cmd,pop=self.mocks(root,'replace_source')
   with self.assertRaisesRegex(ValueError,'identity changed'):self.run_case(root,cmd,pop)
   self.assertFalse(ps);r=json.loads((root/'out.json').read_text());self.assertFalse(r['volumes'][0]['completed'])
 def test_same_path_mutation_during_stream_rejected_afterward(self):
  with tempfile.TemporaryDirectory()as d:
   root=Path(d);self.fixture(root);calls,ps,vols,cmd,pop=self.mocks(root,'change_during_stream')
   with self.assertRaisesRegex(ValueError,'identity changed'):self.run_case(root,cmd,pop)
   r=json.loads((root/'out.json').read_text());self.assertEqual(r['status'],'failed_partial_volumes_preserved');self.assertFalse(r['volumes'][0]['completed'])
 def test_transfer_rejects_actual_wrong_streamed_bytes(self):
  with self.assertRaisesRegex(ValueError,'hash mismatch'):m.transfer(io.BytesIO(b'changed'),io.BytesIO(),'0'*64)
 def test_existing_output_rejected_before_any_commands(self):
  with tempfile.TemporaryDirectory()as d:
   root=Path(d);self.fixture(root);(root/'out.json').write_text('existing')
   with patch.object(m,'cmd',side_effect=AssertionError('Unexpected command')):
    with self.assertRaises(FileExistsError):m.prepare(root/'plan.json',root/'download.json',root,root/'out.json',True)
   self.assertEqual((root/'out.json').read_text(),'existing')
 def test_dangling_output_rejected(self):
  with tempfile.TemporaryDirectory()as d:
   root=Path(d);(root/'out.json').symlink_to(root/'missing')
   with self.assertRaises(FileExistsError):m.prepare(root/'none',root/'none',root,root/'out.json',True)
   self.assertFalse((root/'missing').exists())
 def test_tar_error_preserves_partial_and_report(self):
  with tempfile.TemporaryDirectory()as d:
   root=Path(d);self.fixture(root);calls,ps,vols,cmd,pop=self.mocks(root,'tar_error')
   with self.assertRaisesRegex(RuntimeError,'Extraction failed'):self.run_case(root,cmd,pop)
   r=json.loads((root/'out.json').read_text());self.assertEqual(r['status'],'failed_partial_volumes_preserved');self.assertFalse(r['volumes'][0]['completed']);self.assertEqual(len(vols),1)
 def test_bad_plans_fail_before_docker(self):
  for mutation in ['duplicate','strip','traversal','basename']:
   with self.subTest(mutation=mutation),tempfile.TemporaryDirectory()as d:
    root=Path(d);self.fixture(root);p=json.loads((root/'plan.json').read_text())
    if mutation=='duplicate':p['volumes']*=2
    elif mutation=='strip':p['volumes'][0]['strip_components']=99
    elif mutation=='traversal':p['volumes'][0]['source_prefix']='db/../else'
    else:p['volumes'][0]['source_archive']='../a.tar'
    (root/'plan.json').write_text(json.dumps(p))
    with patch.object(m,'cmd',side_effect=AssertionError('Unexpected Docker command')):
     with self.assertRaises(ValueError):m.prepare(root/'plan.json',root/'download.json',root,root/'out.json',True)
 def test_held_lock_fails_before_docker(self):
  import fcntl
  with tempfile.TemporaryDirectory()as d:
   root=Path(d);self.fixture(root)
   with (root/'map-extraction.lock').open('a')as lock:
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    with patch.object(m,'cmd',side_effect=AssertionError('Unexpected Docker command')):
     with self.assertRaises(BlockingIOError):m.prepare(root/'plan.json',root/'download.json',root,root/'out.json',True)
 def test_source_symlink_rejected(self):
  with tempfile.TemporaryDirectory()as d:
   root=Path(d);self.fixture(root);(root/'a.tar').rename(root/'actual');(root/'a.tar').symlink_to(root/'actual');calls,ps,vols,cmd,pop=self.mocks(root)
   with self.assertRaises(OSError):self.run_case(root,cmd,pop)
   self.assertFalse(vols)

if __name__=='__main__':unittest.main()
