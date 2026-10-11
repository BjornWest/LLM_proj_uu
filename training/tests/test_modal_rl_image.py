"""Offline checks for image extraction and a legacy-free controller closure."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock

TRAINING = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


builder = load('image_factory_test', TRAINING/'scripts/modal_rl_image.py')
compiler = load('compiler_environment_test', TRAINING/'browser_training/compiler_environment.py')


class ImageFactoryTests(unittest.TestCase):
    def test_builder_uses_copied_locked_inputs_before_any_source_mount(self):
        calls = []
        class Image:
            @classmethod
            def debian_slim(cls, **kwargs):
                calls.append(('debian_slim', kwargs))
                return cls()
            def __getattr__(self, name):
                def record(*args, **kwargs):
                    calls.append((name, args, kwargs))
                    return self
                return record
        # This fake exposes no App/Volume/client: the factory cannot create them.
        fake = SimpleNamespace(Image=Image, is_local=lambda: True)
        with patch.dict(sys.modules, {'modal': fake}):
            builder.build_image(TRAINING)
        copies = [c for c in calls if c[0]=='add_local_file']
        self.assertEqual(len(copies), 2)
        self.assertTrue(all(c[2]=={'copy': True} for c in copies))
        commands = next(c[1] for c in calls if c[0]=='run_commands')
        self.assertIn('--locked --python 3.12.12', commands[1])
        self.assertIn('uv pip check', commands[2])
        self.assertEqual([c[0] for c in calls],
            ['debian_slim','apt_install','uv_pip_install','add_local_file','add_local_file','run_commands','env'])

    def test_missing_lock_and_remote_build_fail_before_image_definition(self):
        fake = SimpleNamespace(is_local=lambda: True)
        with tempfile.TemporaryDirectory() as d, patch.dict(sys.modules, {'modal': fake}):
            with self.assertRaises(FileNotFoundError):builder.build_image(d)
        with patch.dict(sys.modules, {'modal': SimpleNamespace(is_local=lambda: False)}):
            with self.assertRaisesRegex(RuntimeError, 'locally'):builder.build_image(TRAINING)


class CompilerTests(unittest.TestCase):
    def test_private_linker_is_idempotent_and_environment_is_not_mutated(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);cuda=root/'wheel';(cuda/'bin').mkdir(parents=True);(cuda/'lib').mkdir()
            (cuda/'bin/nvcc').write_text('compiler');(cuda/'lib/libcudart.so.13').write_text('runtime')
            before={'PATH':'/usr/bin','LIBRARY_PATH':'oldlib','LD_LIBRARY_PATH':'oldruntime'}
            first=compiler.compiler_environment(cuda,root/'private',before)
            second=compiler.compiler_environment(cuda,root/'private',before)
            self.assertEqual(first,second);self.assertEqual(before['PATH'],'/usr/bin')
            self.assertEqual((root/'private/libcudart.so').resolve(),cuda/'lib/libcudart.so.13')
            self.assertFalse((cuda/'lib/libcudart.so').exists())
            self.assertEqual(first['PATH'],str(cuda/'bin')+':/usr/bin')
            self.assertEqual(first['CUDA_HOME'],str(cuda))
            (root/'private/libcudart.so').unlink();(root/'private/libcudart.so').write_text('unexpected')
            with self.assertRaisesRegex(ValueError,'unexpected target'):
                compiler.compiler_environment(cuda,root/'private',before)

    def test_missing_toolkit_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'missing'):
                compiler.compiler_environment(Path(d)/'missing',Path(d)/'private',{})
            self.assertFalse((Path(d)/'private').exists())


class ControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:import modal
        except ImportError:raise unittest.SkipTest('Install training[modal] for SDK offline qualification')
        cls.modal=modal

    def closure(self, root):
        paths=['scripts/modal_spec_decode.py','scripts/modal_rl_image.py','scripts/spec_decode_benchmark.py',
               'scripts/spec_cache_preflight.py','browser_training/browser_benchmark_prompts.py',
               'browser_training/compiler_environment.py','browser_training/__init__.py',
               'envs/rl/pyproject.toml','envs/rl/uv.lock']
        for name in paths:
            target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(TRAINING/name,target)
        self.assertFalse((root/'scripts/modal_b06').exists())

    def test_actual_sdk_import_and_dry_run_without_legacy_files_or_network(self):
        original_path=list(sys.path)
        try:
            with tempfile.TemporaryDirectory() as d, patch('socket.socket.connect',side_effect=AssertionError('Offline only')):
                root=Path(d)/'training';self.closure(root)
                module=load('legacy_free_benchmark_test',root/'scripts/modal_spec_decode.py')
                self.assertFalse(module.image.is_hydrated)
                hashes=module.source_hashes(root)
                self.assertEqual(len(hashes),9)
                self.assertIn('envs/rl/uv.lock',hashes)
                # Verify copied inputs at their actual mapping; corruption must fail.
                mapped={name:str(root/name) for name in hashes}
                with patch.object(module,'SOURCE_DESTINATIONS',mapped):
                    module.verify_sources(hashes)
                    with self.assertRaisesRegex(ValueError,'Incomplete'):
                        module.verify_sources(dict(list(hashes.items())[:-1]))
                    (root/'envs/rl/uv.lock').write_text('changed lock')
                    with self.assertRaisesRegex(ValueError,'fingerprint differs: envs/rl/uv.lock'):
                        module.verify_sources(hashes)
                (root/'envs/rl/uv.lock').write_bytes((TRAINING/'envs/rl/uv.lock').read_bytes())
                output=root/'must-not-be-created'
                argv=['modal_spec_decode','--env-file',str(root/'absent.env'),'--output',str(output),'--dry-run']
                with patch.object(sys,'argv',argv),patch.object(module.subprocess,'check_output',side_effect=['','offline-test-commit']),contextlib.redirect_stdout(io.StringIO()) as out:
                    module.main()
                plan=json.loads(out.getvalue())
                self.assertEqual(plan['source_sha256'],hashes)
                self.assertEqual(plan['measured_cohorts'],6);self.assertEqual(plan['job_cap_seconds'],2700)
                self.assertFalse(output.exists())
                # Actual controller CLI must bind larger per-arm cohorts, not
                # accidentally keep the historical common-batch GPU arguments.
                argv += ['--arm-batch','dflash=10','--arm-batch','mtp3=17',
                         '--arm-batch','baseline=23','--job-cap-seconds','2100']
                with patch.object(sys,'argv',argv),patch.object(module.subprocess,'check_output',side_effect=['','offline-test-commit']),contextlib.redirect_stdout(io.StringIO()) as out:
                    module.main()
                plan=json.loads(out.getvalue())
                self.assertEqual(plan['arm_batches'],{'dflash':[10],'mtp3':[17],'baseline':[23]})
                self.assertEqual(plan['measured_cohorts'],3)
                self.assertEqual(plan['measured_requests_upper_bound'],50)
                self.assertEqual(plan['warmup_requests_upper_bound'],50)
                self.assertEqual(plan['job_cap_seconds'],2100)
                self.assertFalse(output.exists())
                # Execute the real non-dry-run controller with cloud calls mocked.
                # Two independent local parents may use the SAME basename; their
                # shared-volume run IDs must differ and match persisted plans.
                archive=io.BytesIO()
                with module.tarfile.open(fileobj=archive,mode='w:gz'):pass
                prepared={'snapshot':'base','draft':'draft','prompts':'prompts'}
                call=Mock(object_id='mock-call')
                call.get.return_value=({'status':'COMPLETE'},archive.getvalue())
                runs=[]
                for parent in ('one','two'):
                    destination=root/parent/'same-basename'
                    run_argv=argv[:]
                    run_argv.remove('--dry-run')
                    run_argv[run_argv.index('--output')+1]=str(destination)
                    queue=Mock()
                    with patch.object(sys,'argv',run_argv),patch.object(module.subprocess,'check_output',side_effect=['','offline-test-commit']), \
                         patch.object(module.app,'run',return_value=contextlib.nullcontext()), \
                         patch.object(module.app,'get_dashboard_url',return_value='mock-url'), \
                         patch.object(module.modal,'enable_output',return_value=contextlib.nullcontext()), \
                         patch.object(module.modal.Queue,'ephemeral',return_value=contextlib.nullcontext(queue)), \
                         patch.object(module.prepare,'remote',return_value=prepared) as prepare_call, \
                         patch.object(module.benchmark,'spawn',return_value=call) as spawn, \
                         patch.dict(sys.modules,{'dotenv':SimpleNamespace(dotenv_values=lambda _: {})}), \
                         contextlib.redirect_stdout(io.StringIO()):
                        module.main()
                    actual=json.loads((destination/'plan.json').read_text())
                    run_id=actual['run_id'];runs.append(run_id)
                    self.assertTrue(run_id.startswith('same-basename-'))
                    prepare_call.assert_called_once_with(hashes,23)
                    self.assertEqual(spawn.call_args.args[0],run_id)
                    self.assertEqual(spawn.call_args.args[4],['dflash=10','mtp3=17','baseline=23'])
                    self.assertEqual(spawn.call_args.args[3],queue)
                    call.cancel.assert_called_with(terminate_containers=True)
                self.assertNotEqual(*runs)
        finally:sys.path[:]=original_path

    def test_remote_import_does_not_assemble_image(self):
        original_path=list(sys.path)
        try:
            with tempfile.TemporaryDirectory() as d,patch('socket.socket.connect',side_effect=AssertionError('Offline only')):
                root=Path(d)/'training';self.closure(root)
                with patch.object(self.modal,'is_local',return_value=False),patch.dict(sys.modules,{'modal_rl_image': None}):
                    module=load('remote_benchmark_test',root/'scripts/modal_spec_decode.py')
                self.assertIsNone(module.image)
                self.assertEqual(len(module.source_hashes(root)),9)
        finally:sys.path[:]=original_path


if __name__=='__main__':unittest.main()
