"""CPU source controls for host supervision; never qualifies real GPU serving."""
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'training/scripts'/ (name+'.py'))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
W=module('qwen_host_worker');M=module('measure_qwen_host')
LOG='''Using FLASHINFER attention backend out of potential backends: ['FLASHINFER'].
Using Triton/FLA GDN prefill kernel (requested=triton, head_k_dim=128).
GDN decode kernel: cuda
Selected CutlassFp8BlockScaledMMKernel for Fp8LinearMethod
Using backend AttentionBackendEnum.FLASH_ATTN for vit attention'''


class HostTests(unittest.TestCase):
    def test_actual_backend_log_missing_or_conflicting_decisions_fail(self):
        backends,vision=M.resolved_backends(LOG)
        self.assertEqual(backends['prefill'],'FLASHINFER');self.assertEqual(vision,'FLASH_ATTN')
        self.assertEqual(backends['linear_attention'],'prefill=Triton/FLA;decode=cuda')
        for changed in (LOG.replace('GDN decode kernel: cuda',''),LOG+'\nSelected WrongKernel for Fp8LinearMethod'):
            with self.assertRaisesRegex(ValueError,'Missing/ambiguous'):M.resolved_backends(changed)

    def test_rental_cannot_restart_expired_deadline_or_ignore_approval(self):
        now=time.time();rental={'run_id':'00000000-0000-4000-8000-000000000001',
            'instance_id':'00000000-0000-4000-8000-000000000002','allocation_utc':now,
            'approved_rental_seconds':600,'deadline_utc':now+600,'allocation_authorized':True}
        self.assertEqual(W.rental_values(rental,now+1),now+600)
        for mutation in ({'deadline_utc':now+601},{'allocation_authorized':False},{'approved_rental_seconds':True},
                         {'run_id':rental['instance_id']},{'deadline_utc':float('nan')}):
            with self.assertRaises(ValueError):W.rental_values({**rental,**mutation},now+1)
        with self.assertRaises(ValueError):W.rental_values(rental,now+601)

    def test_service_uses_cgroup_deadline_memory_and_no_inherited_key(self):
        spec={'server_memory_mib':57344,'host_root':'/opt/qwen-release','rl_python':'/runtime/rl/.venv/bin/python',
            'snapshot':'/model-cache/snapshot','cache_root':'/cache'}
        with patch.dict(os.environ,{'PACKET_API_KEY':'NEVER','WANDB_API_KEY':'NEVER','PYTHONPATH':'NEVER'}):
            argv=W.unit_argv(spec,Path('/private/qwen-runs/id'),53.5)
        self.assertIn('--property=RuntimeMaxSec=53.5',argv)
        self.assertIn('--property=KillMode=control-group',argv)
        self.assertIn('--property=MemorySwapMax=0',argv)
        self.assertIn('--property=MemoryMax='+str(57344<<20),argv)
        self.assertNotIn('NEVER',' '.join(argv));self.assertIn('-I',argv)
        with self.assertRaises(TimeoutError):W.unit_argv(spec,Path('/private/id'),.5)

    def test_artifact_return_checksums_relative_paths_and_rejects_links(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'small.json').write_text('{"status":"failed"}')
            result=W.artifacts(root);self.assertFalse(result['task_success_asserted'])
            self.assertEqual(result['files'][0]['sha256'],sha256((root/'small.json').read_bytes()).hexdigest())
            self.assertEqual(result['files'][0]['path'],'small.json')
            (root/'linked').symlink_to(root/'small.json')
            with self.assertRaises(ValueError):W.artifacts(root)

    def test_live_caller_subtree_is_excluded_and_changing_worker_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);target=root/'vllm.log';target.write_text('original')
            (root/'suite').mkdir();(root/'suite/completion.sqlite').write_text('live database')
            result=W.artifacts(root)
            self.assertEqual([r['path'] for r in result['files']],['vllm.log'])
            original=os.fstat;calls=[]
            def append_during_hash(fd):
                calls.append(fd)
                if len(calls)==2:
                    with target.open('a') as stream:stream.write(' appended')
                return original(fd)
            with patch.object(W.os,'fstat',side_effect=append_during_hash),self.assertRaisesRegex(ValueError,'changed while hashing'):
                W.artifacts(root)

    def test_cache_rejects_source_or_output_containment_and_symlink_aliases(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);host=root/'host';parent=root/'runs';cache=root/'cache'
            for directory in (host,parent,cache):directory.mkdir(mode=0o700)
            W.verify_cache({'cache_root':str(cache)},host,parent)
            (host/'cache').mkdir();(root/'alias').symlink_to(cache,target_is_directory=True)
            for bad in (host,host/'cache',parent,root,root/'alias'):
                with self.assertRaises(ValueError):W.verify_cache({'cache_root':str(bad)},host,parent)

    def test_actual_cache_write_directories_and_nested_aliases_cannot_target_frozen_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);host=root/'host';parent=root/'runs';cache=root/'cache'
            for directory in (host,parent,cache):directory.mkdir(mode=0o700)
            for name in ('link-libs','vllm','triton'):
                target=cache/name;target.symlink_to(host,target_is_directory=True)
                with self.assertRaises(ValueError):W.verify_cache({'cache_root':str(cache)},host,parent)
                target.unlink()
            nested=cache/'vllm/nested';nested.parent.mkdir();nested.symlink_to(host,target_is_directory=True)
            with self.assertRaises(ValueError):W.verify_cache({'cache_root':str(cache)},host,parent)
            nested.unlink()
            (cache/'link-libs').mkdir();lib=root/'libcudart.so.13';lib.write_text('CPU fixture')
            (cache/'link-libs/libcudart.so').symlink_to(lib)
            W.verify_cache({'cache_root':str(cache)},host,parent)
            self.assertEqual(list(host.iterdir()),[])

    def test_stop_refuses_replaced_systemd_invocation(self):
        units=W.Units()
        with patch.object(units,'state',return_value={'InvocationID':'replacement','LoadState':'loaded'}),patch.object(units,'call') as call:
            with self.assertRaises(ValueError):units.stop('qwen-test','original')
            call.assert_not_called()
        states=[{'InvocationID':'original','LoadState':'loaded'}, {'MainPID':'0','ActiveState':'inactive'}]
        with patch.object(units,'state',side_effect=states),patch.object(units,'call') as call:
            units.stop('qwen-test','original');self.assertEqual(call.call_args[0][0][-2:],['stop','qwen-test'])

    def test_ambiguous_creation_cleanup_requires_exact_run_directory(self):
        units=W.Units()
        state={'LoadState':'loaded','InvocationID':'new','WorkingDirectory':'/another-run'}
        with patch.object(units,'state',return_value=state),patch.object(units,'call') as call:
            with self.assertRaises(ValueError):units.stop('qwen-test',None,expected_directory='/expected-run')
            call.assert_not_called()
        states=[{**state,'WorkingDirectory':'/expected-run'}, {'MainPID':'0','ActiveState':'inactive'}]
        with patch.object(units,'state',side_effect=states),patch.object(units,'call') as call:
            units.stop('qwen-test',None,expected_directory='/expected-run');call.assert_called_once()

    def test_cli_cleanup_failure_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as temporary:
            spec=Path(temporary)/'spec.json';spec.write_text('{"schema":"qwen-ssh-serving-worker-v1"}')
            code='''import importlib.util,sys
spec=importlib.util.spec_from_file_location('worker',sys.argv[1])
worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
def injected(spec): raise worker.CleanupFailure('injected already-recorded cleanup failure')
worker.execute=injected
sys.argv=['worker','--spec',sys.argv[2],'--spec-sha256',sys.argv[3],'--execute']
worker.main()
'''
            result=subprocess.run([sys.executable,'-I','-B','-c',code,str(ROOT/'training/scripts/qwen_host_worker.py'),
                str(spec),sha256(spec.read_bytes()).hexdigest()],capture_output=True,text=True,timeout=5)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('CleanupFailure',result.stderr)

    def test_short_child_timeout_preserves_log_and_kills_child(self):
        with tempfile.TemporaryDirectory() as temp:
            log=Path(temp)/'log';start=time.time()
            with self.assertRaises(TimeoutError):
                W.run_command([sys.executable,'-u','-c','import time;print("received");time.sleep(60)'],log,start+.3)
            self.assertLess(time.time()-start,3)
            self.assertIn('received',log.read_text())
            self.assertEqual(log.stat().st_mode&0o777,0o600)

    def test_planner_does_not_start_processes_or_require_GPU(self):
        with tempfile.TemporaryDirectory() as temp:
            spec=Path(temp)/'spec.json';spec.write_text('{"schema":"qwen-ssh-serving-worker-v1"}')
            done=subprocess.run([sys.executable,'-I','-B',str(ROOT/'training/scripts/qwen_host_worker.py'),
                '--spec',str(spec),'--spec-sha256',sha256(spec.read_bytes()).hexdigest()],
                capture_output=True,text=True,timeout=5)
            self.assertEqual(done.returncode,0,done.stderr)
            self.assertFalse(json.loads(done.stdout)['model_or_cloud_actions'])
            self.assertEqual(sorted(p.name for p in Path(temp).iterdir()),['spec.json'])

    def test_incomplete_or_synthetic_wire_cannot_publish_capability(self):
        runtime={'CHECKS':['input_boundary_forward'],'digest':lambda value,sorted_keys:'f'*64}
        valid={'passed':True,'synthetic':False,'status':'wire_qualification_passed','wire_serialization':'json-insertion-order-v1',
            'diagnostic_generation_requests':5,'diagnostic_generation_attempts':5,'stopped_by_signal':[],
            'checks':{'input_boundary_forward':True}}
        for mutation in ({'passed':False},{'synthetic':True},{'diagnostic_generation_attempts':4},
                         {'stopped_by_signal':[15]},{'checks':{}},{'wire_serialization':'sorted'}):
            with tempfile.TemporaryDirectory() as temp,self.assertRaises(ValueError):
                M.capability(runtime,{}, {**valid,**mutation},{},{},Path(temp))

    def test_reuse_requires_all_original_typed_proofs_and_matching_measurement(self):
        runtime={'CHECKS':['input_boundary_forward'],'digest':lambda value,sorted_keys:'f'*64};compatibility={'actual':'CPU-fixture-only'}
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);proofs={}
            for kind in ('qualification','deployment','processor'):
                proofs[kind]=M.publish(root/(kind+'.json'),{'passed':True,'synthetic':False,'proof_kind':kind,'fingerprint':'f'*64})
            value={'schema':'serving-stack-capability-v1','status':'passed','synthetic':False,'compatibility':compatibility,
                'fingerprint':'f'*64,'checks':{'input_boundary_forward':True},'proofs':proofs}
            cap=M.publish(root/'cap.json',value);self.assertEqual(M.reused_capability(cap,compatibility,runtime),cap)
            with self.assertRaises(ValueError):M.reused_capability(cap,{'different':'stack'},runtime)
            Path(proofs['deployment']['path']).write_text('{}')
            with self.assertRaises(ValueError):M.reused_capability(cap,compatibility,runtime)

    def test_owned_worker_full_mock_lifecycle_keeps_two_processes_and_returns_terminal(self):
        self._mock_lifecycle('normal')

    def test_worker_notices_post_readiness_adapter_death_replacement_and_failed_cleanup(self):
        for mode in ('adapter_dies','adapter_replaced','cleanup_failure','creation_timeout'):
            with self.subTest(mode=mode):self._mock_lifecycle(mode)

    def _mock_lifecycle(self,mode):
        from uuid import uuid4
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary);parent=base/'runs';parent.mkdir(mode=0o700)
            run_id=str(uuid4());instance=str(uuid4());now=time.time();fake_now=[now]
            rental={'run_id':run_id,'instance_id':instance,'allocation_utc':now,'approved_rental_seconds':60,
                    'deadline_utc':now+60,'allocation_authorized':True,'qualification_authorized':True}
            rental_pin=W.publish(base/'rental.json',rental);run=parent/run_id
            cache=base/'cache';cache.mkdir(mode=0o700)
            spec={'rental':rental_pin,'output_parent':str(parent),'host_root':'/nonexistent/reviewed-host',
                'runtime':{'path':'/runtime','sha256':'a'*64},'request':{'path':'/request','sha256':'b'*64},
                'runtime_lock':{'path':'/uv.lock','sha256':'c'*64},'server_memory_mib':57344,
                'rl_python':'/rl/.venv/bin/python','browser_python':'/browser/.venv/bin/python',
                'snapshot':'/snapshot','cache_root':str(cache)}
            children=[];commands=[]
            class FakeUnits:
                def __init__(self):self.rows={};self.stopped=[]
                def state(self,name):return self.rows.get(name,{'LoadState':'not-found'})
                def call(self,argv,timeout=10):
                    name=next(x.split('=',1)[1] for x in argv if x.startswith('--unit='))
                    process=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],start_new_session=True)
                    children.append(process);commands.append(argv)
                    self.rows[name]={'LoadState':'loaded','MainPID':str(process.pid),'InvocationID':str(uuid4()),
                        'ActiveState':'active','WorkingDirectory':str(run)}
                    if name.endswith('-qualification'):
                        ready=run/'ready';ready.mkdir(mode=0o700)
                        W.publish(ready/'adapter-ready.json',{'process':W.process_identity(process.pid),'scope':'CPU scripted fixture'})
                        W.publish(ready/'qualified-serving-live.json',{'scope':'CPU scripted fixture, never dispatch authority'})
                        if mode in ('normal','cleanup_failure'):
                            W.publish(run/'finish.json',{'run_id':run_id,'instance_id':instance,'serving_session_id':'test-session','reason':'completed'})
                    else:
                        W.publish(run/'installed-serving.json',{'pid':process.pid,'status':'source_checks_passed_before_exec',
                            'attempt_id':'test-session','scope':'CPU scripted fixture'})
                        (run/'vllm.log').write_text(LOG)
                        if mode=='creation_timeout':raise subprocess.TimeoutExpired('systemd-run',1)
                def stop(self,name,invocation,*,expected_directory=None):
                    if invocation is not None and self.rows[name]['InvocationID']!=invocation:
                        raise ValueError('Injected replaced invocation')
                    if invocation is None and self.rows[name]['WorkingDirectory']!=str(expected_directory):
                        raise ValueError('Ambiguous service belongs to another run')
                    if mode=='cleanup_failure' and not name.endswith('-qualification'):
                        raise RuntimeError('Injected serving stop failure')
                    self.stopped.append(name);pid=int(self.rows[name]['MainPID'])
                    child=next(p for p in children if p.pid==pid)
                    if child.poll() is None:os.killpg(pid,15);child.wait(timeout=3)
                    self.rows[name].update(MainPID='0',ActiveState='inactive')
            units=FakeUnits()
            def command(argv,log,end,**kwargs):
                log.write_text('CPU scripted fixture')
                directory=Path(argv[argv.index('--output')+1]);directory.mkdir(mode=0o700)
                if 'qualify_qwen_wire.py' in ' '.join(argv):W.publish(directory/'wire-proof.json',{'scope':'CPU scripted fixture'})
                else:
                    cap=W.publish(directory/'capability.json',{'scope':'CPU scripted fixture'})
                    dep=W.publish(directory/'deployment.json',{'scope':'CPU scripted fixture'})
                    W.publish(directory/'measurement-result.json',{'capability':cap,'deployment':dep})
            def sleep(seconds):
                if mode=='adapter_dies':
                    child=children[1]
                    if child.poll() is None:os.killpg(child.pid,15);child.wait(timeout=3)
                if mode=='adapter_replaced':units.rows['qwen-'+run_id+'-qualification']['InvocationID']='replacement'
                fake_now[0]+=1
            try:
                with patch.object(W.platform,'release',return_value='cpu-fixture-linux'),patch.object(W,'verify_sources'), \
                     patch.object(W,'owned_listener'),patch.object(W,'health',return_value=True),patch.object(W,'run_command',side_effect=command):
                    if mode!='normal':
                        expected=W.CleanupFailure if mode in ('cleanup_failure','adapter_replaced') else (OSError,ValueError,subprocess.TimeoutExpired)
                        with self.assertRaises(expected):W.execute(spec,units,clock=lambda:fake_now[0],sleep=sleep)
                        terminal=json.loads((run/'worker-terminal.json').read_text())
                        self.assertNotEqual(terminal['status'],'rental_deadline')
                        if mode in ('cleanup_failure','adapter_replaced'):
                            self.assertEqual(terminal['status'],'cleanup_failed')
                            index=json.loads((run/'terminal-artifacts.json').read_text())
                            self.assertEqual(index['status'],'not_finalized');self.assertEqual(index['files'],[])
                        else:self.assertTrue(terminal['serving_stopped'])
                        return
                    result=W.execute(spec,units)
                self.assertEqual(result['status'],'caller_terminal')
                self.assertTrue(result['serving_stopped']);self.assertEqual(result['cleanup_errors'],[])
                self.assertFalse(result['provider_billing_stopped']);self.assertFalse(result['task_success_asserted'])
                self.assertEqual(len(units.stopped),2)
                self.assertTrue(all(p.poll() is not None for p in children))
                terminal=json.loads((run/'worker-terminal.json').read_text())
                self.assertEqual(terminal['serving_session_id'],'test-session')
                artifact=json.loads((run/'terminal-artifacts.json').read_text())
                self.assertIn('finish.json',[r['path'] for r in artifact['files']])
                self.assertEqual(sum('qualify_qwen_wire.py' in ' '.join(argv) for argv in commands),0)
            finally:
                for child in children:
                    if child.poll() is None:os.killpg(child.pid,9);child.wait(timeout=3)

    def test_missing_first_diagnostic_approval_never_starts_service(self):
        from uuid import uuid4
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);now=time.time()
            rental={'run_id':str(uuid4()),'instance_id':str(uuid4()),'allocation_utc':now,
                'approved_rental_seconds':60,'deadline_utc':now+60,'allocation_authorized':True}
            spec={'rental':W.publish(root/'rental.json',rental)}
            with patch.object(W.platform,'release',return_value='cpu-fixture-linux'),patch.object(W,'verify_sources'), \
                 patch.object(W.Units,'call') as call,self.assertRaises(ValueError):W.execute(spec)
            call.assert_not_called()


if __name__=='__main__':unittest.main()
