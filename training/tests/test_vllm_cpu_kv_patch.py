"""Patch integrity and installation controls; no model or GPU imports."""
from importlib.metadata import distribution
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import apply_vllm_cpu_kv_patch as p


def stock_source(data):
    """Recover a hash-checked stock fixture without changing installed vLLM."""
    digest=p.sha256(data)
    if digest==p.BASE_SHA256:return data
    if digest!=p.RESULT_SHA256:raise RuntimeError('Unknown installed scheduler source')
    if p.sha256(p.PATCH_FILE.read_bytes())!=p.PATCH_SHA256:
        raise RuntimeError('Backport artifact differs from pinned patch bytes')
    with tempfile.TemporaryDirectory(prefix='vllm-stock-test-',dir='/tmp')as folder:
        root=Path(folder);source=root/p.SOURCE_PATH
        source.parent.mkdir(parents=True);source.write_bytes(data)
        env={k:v for k,v in os.environ.items()if not k.startswith('GIT_')}
        env['GIT_CEILING_DIRECTORIES']=str(root.parent)
        result=subprocess.run(['git','apply','--reverse','--include='+p.SOURCE_PATH,str(p.PATCH_FILE)],
            cwd=root,env=env,text=True,capture_output=True,timeout=20)
        if result.returncode:raise RuntimeError('Stock fixture reverse-apply failed: '+result.stderr)
        recovered=source.read_bytes()
    if p.sha256(recovered)!=p.BASE_SHA256:raise RuntimeError('Recovered stock fixture hash mismatch')
    return recovered


class PatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        package=distribution('vllm')
        if package.version!='0.28.0':raise RuntimeError('Controls require pinned vLLM0.28.0')
        cls.installed=Path(package.locate_file(p.SOURCE_PATH)).read_bytes()
        cls.base=stock_source(cls.installed)

    @classmethod
    def tearDownClass(cls):
        if Path(distribution('vllm').locate_file(p.SOURCE_PATH)).read_bytes()!=cls.installed:
            raise AssertionError('Installed scheduler changed during tests')

    def test_installed_distribution_verify_is_read_only_in_both_states(self):
        if p.sha256(self.installed)==p.RESULT_SHA256:
            self.assertEqual(p.apply_patch(verify_only=True)['status'],'verified')
        else:
            with self.assertRaisesRegex(RuntimeError,'not installed'):
                p.apply_patch(verify_only=True)
        self.assertEqual(Path(distribution('vllm').locate_file(p.SOURCE_PATH)).read_bytes(),self.installed)

    def test_installed_distribution_wrong_version_is_rejected_before_lookup(self):
        from unittest.mock import Mock,patch
        package=Mock(version='0.28.1')
        with patch.object(p,'distribution',return_value=package):
            with self.assertRaisesRegex(RuntimeError,'exactly vLLM0.28.0'):
                p.apply_patch(verify_only=True)
        package.locate_file.assert_not_called()

    def test_fixture_accepts_both_pinned_states_and_rejects_unknown_bytes(self):
        self.assertEqual(stock_source(self.base),self.base)
        with tempfile.TemporaryDirectory()as folder:
            source=Path(folder)/'scheduler.py';source.write_bytes(self.base);p.apply_patch(source)
            self.assertEqual(stock_source(source.read_bytes()),self.base)
        with self.assertRaisesRegex(RuntimeError,'Unknown installed'):
            stock_source(self.base+b'\n# unknown\n')

    def test_real_application_idempotence_and_verify(self):
        with tempfile.TemporaryDirectory()as folder:
            source=Path(folder)/'scheduler.py';source.write_bytes(self.base);source.chmod(0o640)
            with self.assertRaisesRegex(RuntimeError,'not installed'):p.apply_patch(source,verify_only=True)
            result=p.apply_patch(source)
            self.assertEqual(result['status'],'patched')
            self.assertEqual(p.sha256(source.read_bytes()),p.RESULT_SHA256)
            self.assertEqual(source.stat().st_mode&0o777,0o640)
            self.assertEqual(p.apply_patch(source)['status'],'already_patched')
            self.assertEqual(p.apply_patch(source,verify_only=True)['status'],'verified')

    def test_unknown_base_leaves_source_intact(self):
        with tempfile.TemporaryDirectory()as folder:
            source=Path(folder)/'scheduler.py';source.write_bytes(self.base+b'\n# modified\n')
            original=source.read_bytes()
            with self.assertRaisesRegex(RuntimeError,'Unknown vLLM'):p.apply_patch(source)
            self.assertEqual(source.read_bytes(),original)

    def test_patch_tampering_leaves_source_intact(self):
        with tempfile.TemporaryDirectory()as folder:
            source=Path(folder)/'scheduler.py';source.write_bytes(self.base)
            artifact=Path(folder)/'bad.patch';artifact.write_bytes(p.PATCH_FILE.read_bytes()+b'\n')
            with self.assertRaisesRegex(RuntimeError,'artifact differs'):p.apply_patch(source,patch_file=artifact)
            self.assertEqual(source.read_bytes(),self.base)

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory()as folder:
            source=Path(folder)/'scheduler.py';source.write_bytes(self.base)
            link=Path(folder)/'link.py';link.symlink_to(source)
            with self.assertRaisesRegex(RuntimeError,'symlinked'):p.apply_patch(link)
            self.assertEqual(source.read_bytes(),self.base)

    def test_installed_package_requires_explicit_modification_opt_in(self):
        with self.assertRaisesRegex(RuntimeError,'requires --install-in-place'):p.apply_patch()
        self.assertEqual(Path(distribution('vllm').locate_file(p.SOURCE_PATH)).read_bytes(),self.installed)

    def test_native_lookup_restores_sparse_recurrent_checkpoints(self):
        """Same retained keys: original lookup misses; patched lookup restores."""
        import importlib.util
        from types import SimpleNamespace
        from unittest.mock import patch
        with patch.dict(os.environ,{'VLLM_TARGET_DEVICE':'cpu'}):
            import torch
            from vllm.v1.kv_cache_interface import KVCacheGroupSpec,FullAttentionSpec,MambaSpec
            with tempfile.TemporaryDirectory()as folder:
                original_source=Path(folder)/'stock.py';original_source.write_bytes(self.base)
                original_name='mtp_offload_stock_native_test'
                original_spec=importlib.util.spec_from_file_location(original_name,original_source)
                original=importlib.util.module_from_spec(original_spec)
                source=Path(folder)/'scheduler.py';source.write_bytes(self.base);p.apply_patch(source)
                name='mtp_offload_patch_native_test'
                spec=importlib.util.spec_from_file_location(name,source)
                updated=importlib.util.module_from_spec(spec)
                sys.modules[original_name]=original;sys.modules[name]=updated
                try:
                    original_spec.loader.exec_module(original)
                    spec.loader.exec_module(updated)
                    hits=[]
                    for module in (original,updated):
                        groups=[
                            KVCacheGroupSpec(['full'],FullAttentionSpec(block_size=1664,
                                num_kv_heads=1,head_size=16,dtype=torch.float32))]
                        groups.extend(KVCacheGroupSpec([f'recurrent-{i}'],MambaSpec(block_size=1664,
                            shapes=((1,1),),dtypes=(torch.float32,),mamba_cache_mode='align'))for i in range(3))
                        cache=SimpleNamespace(kv_cache_groups=groups)
                        spec=SimpleNamespace(tokens_per_block=[1664]*4,blocks_per_chunk=1,
                            tokens_per_hash=1664,offload_prompt_only=True)
                        config=SimpleNamespace(speculative_config=SimpleNamespace(use_eagle=lambda:True),
                            parallel_config=SimpleNamespace(world_size=1,decode_context_parallel_size=1))
                        scheduler=module.OffloadingConnectorScheduler.__new__(module.OffloadingConnectorScheduler)
                        scheduler.config=module.SchedulerOffloadConfig.from_spec(spec,config,cache)
                        keys=[[(group,i)for i in range(36)]for group in range(4)]
                        # Synthetic layout derived from0.28's MTP one-block
                        # backoff; actual Modal retained keys are not captured.
                        retained=set(keys[0])|{keys[group][i]for group in range(1,4)
                            for i in [*range(3,32,4),34]}
                        scheduler.manager=SimpleNamespace(lookup=lambda key,ctx:module.LookupResult.HIT
                            if key in retained else module.LookupResult.MISS)
                        scheduler._events_tracker=SimpleNamespace(record_lookup=lambda *args:None)
                        scheduler._lookup_groups=(0,1,2,3);scheduler._sliding_window_groups=(1,2,3)
                        scheduler._mamba_align_size=1664;scheduler._chunks_being_loaded={}
                        state=SimpleNamespace(num_locally_computed_tokens=0,req_context=None,
                            req=SimpleNamespace(num_tokens=59905,request_id='source-control'),
                            group_states=tuple(module.RequestGroupState(offload_keys=group)for group in keys))
                        cold=scheduler._lookup_complete_chunks(state)
                        state.num_locally_computed_tokens=58240
                        warm=scheduler._lookup_complete_chunks(state)
                        hits.append((cold,warm))
                    self.assertEqual(hits[0],(0,0))
                    self.assertEqual(hits[1],(58240,0))
                finally:
                    sys.modules.pop(name,None);sys.modules.pop(original_name,None)


if __name__=='__main__':unittest.main()
