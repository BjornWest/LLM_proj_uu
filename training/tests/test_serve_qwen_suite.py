"""Source/CPU tests for the SSH serving composition; no CUDA/model requests."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import serve_qwen_suite as serving


def test_native_profile_retains_offload_and_uses_localhost():
    argv = serving.command('/snapshot')
    assert argv[:5] == [sys.executable, '-P', '-m', 'vllm.entrypoints.cli.main', 'serve']
    for flag, value in {'--host': '127.0.0.1', '--max-model-len': '262144',
                        '--max-num-seqs': '8', '--max-num-batched-tokens': '8192',
                        '--block-size': '1664', '--kv-cache-dtype': 'fp8_e4m3',
                        '--reasoning-parser': 'qwen3', '--tool-call-parser': 'qwen3_coder',
                        '--performance-mode': 'interactivity', '--generation-config': 'vllm',
                        '--revision': serving.REVISION,
                        '--tokenizer-revision': serving.REVISION}.items():
        assert argv.count(flag) == 1
        assert argv[argv.index(flag) + 1] == value
    spec = json.loads(argv[argv.index('--speculative-config') + 1])
    assert spec == {'method': 'mtp', 'num_speculative_tokens': 3}
    connector = json.loads(argv[argv.index('--kv-transfer-config') + 1])
    assert connector['kv_connector_extra_config'] == {
        'cpu_bytes_to_use': 20 << 30, 'eviction_policy': 'lru', 'offload_prompt_only': True}
    template = json.loads(argv[argv.index('--default-chat-template-kwargs') + 1])
    assert template == {'enable_thinking': True, 'preserve_thinking': True}
    assert '--enable-auto-tool-choice' in argv
    assert '--enable-tokenizer-info-endpoint' in argv
    assert '--enable-prompt-tokens-details' in argv
    assert '--disable-uvicorn-access-log' in argv
    assert json.loads(argv[argv.index('--limit-mm-per-prompt') + 1]) == {'image': 1562, 'video': 0}
    assert json.loads(argv[argv.index('--mm-processor-kwargs') + 1]) == {
        'min_pixels': 65536, 'max_pixels': 16777216, 'patch_size': 16,
        'merge_size': 2, 'temporal_patch_size': 2}
    assert '--enforce-eager' not in argv and '--disable-log-stats' not in argv


@pytest.mark.parametrize('kwargs', [{'port': 0}, {'max_num_seqs': 257},
                                    {'memory_fraction': .95}])
def test_unsupported_launch_values_rejected(kwargs):
    with pytest.raises(ValueError):
        serving.command('/snapshot', **kwargs)


def test_dry_run_never_checks_installed_parser_or_touches_cuda(tmp_path):
    receipt = tmp_path / 'not-created.json'
    result = subprocess.run([sys.executable, '-B', str(SCRIPTS / 'serve_qwen_suite.py'),
        '--snapshot', '/does-not-exist', '--receipt', str(receipt),
        '--cache-root', str(tmp_path / 'not-created'), '--dry-run'],
        check=True, capture_output=True, text=True, timeout=15,
        env={**os.environ, 'SPEC_BENCH_PROBE': '1'})
    data = json.loads(result.stdout)
    assert data['model_GPU_or_dispatch'] is False
    assert not receipt.exists() and not (tmp_path / 'not-created').exists()


def test_launcher_runs_under_safe_path_without_implicit_script_directory(tmp_path):
    result = subprocess.run([sys.executable, '-P', '-B', str(SCRIPTS / 'serve_qwen_suite.py'),
        '--snapshot', '/missing', '--receipt', str(tmp_path / 'unused'),
        '--cache-root', str(tmp_path / 'unused-cache'), '--dry-run'],
        check=True, capture_output=True, text=True, timeout=15,
        env={**os.environ, 'PYTHONSAFEPATH': '1'})
    assert json.loads(result.stdout)['model_GPU_or_dispatch'] is False


def test_missing_parser_patch_rejected_before_apply_or_gpu(tmp_path, monkeypatch):
    monkeypatch.delenv('PYTHONPATH', raising=False)
    monkeypatch.delenv('PYTHONHOME', raising=False)
    parser = tmp_path / 'utils.py'
    parser.write_bytes(b'unknown parser')
    with patch.object(serving, 'apply_patch', return_value={}), \
         patch.object(serving, 'version', return_value='0.28.0'), \
         patch.object(serving, 'distribution') as dist, \
         patch.object(serving.schema, 'apply_to') as apply:
        dist.return_value.locate_file.return_value = parser
        with pytest.raises(ValueError, match='Install the reviewed'):
            serving.fingerprint(['serve'])
        apply.assert_not_called()
    assert parser.read_bytes() == b'unknown parser'


def test_scheduler_failure_precedes_parser_check(monkeypatch):
    monkeypatch.delenv('PYTHONPATH', raising=False)
    monkeypatch.delenv('PYTHONHOME', raising=False)
    with patch.object(serving, 'version', return_value='0.28.0'), \
         patch.object(serving, 'apply_patch', side_effect=ValueError('scheduler')), \
         patch.object(serving, 'distribution') as dist:
        with pytest.raises(ValueError, match='scheduler'):
            serving.fingerprint(['serve'])
        dist.assert_not_called()


def test_environment_removes_secrets_and_stale_experiment_settings(tmp_path):
    inherited = {key: 'test-secret' for key in ('HF_TOKEN', 'WANDB_API_KEY',
        'VERDA_CLIENT_ID', 'VERDA_CLIENT_SECRET', 'OPENROUTER_API_KEY', 'OPENAI_API_KEY',
        'ANTHROPIC_API_KEY', 'BLOB_READ_WRITE_TOKEN', 'HARNESS_WORKER_TOKEN',
        'HF_HUB_TOKEN', 'MODAL_TOKEN_ID', 'MODAL_TOKEN_SECRET', 'MODEL_API_KEY',
        'PACKET_SSH_PASSWORD', 'PARALLEL_API_KEY', 'DAYLIGHT_OPENROUTER_API_KEY')}
    inherited.update(PATH='/usr/bin', CUDA_VISIBLE_DEVICES='0',
                     VLLM_USE_V1='0', VLLM_LOG_STATS_INTERVAL='100',
                     HF_HUB_OFFLINE='0', WANDB_MODE='online',
                     PYTHONPATH='/untrusted', SPEC_BENCH_PROBE='1',
                     HF_ENDPOINT='https://invalid.test', PYTORCH_CUDA_ALLOC_CONF='old')
    with patch.object(serving, 'compiler_environment', side_effect=lambda c, p, e: dict(e)):
        env = serving.environment(Path('/cuda'), tmp_path, inherited)
    assert 'test-secret' not in env.values()
    assert 'VLLM_USE_V1' not in env
    assert env['CUDA_VISIBLE_DEVICES'] == '0'
    assert env['VLLM_LOG_STATS_INTERVAL'] == '5'
    assert env['HF_HUB_OFFLINE'] == env['PYTHONDONTWRITEBYTECODE'] == '1'
    assert env['WANDB_MODE'] == 'disabled'
    assert env['VLLM_USE_SIMPLE_KV_OFFLOAD'] == '0'
    assert env['VLLM_SERVER_DEV_MODE'] == '0'
    assert env['OMP_NUM_THREADS'] == env['PYTHONSAFEPATH'] == '1'
    for key in ('PYTHONPATH', 'SPEC_BENCH_PROBE', 'HF_ENDPOINT', 'PYTORCH_CUDA_ALLOC_CONF'):
        assert key not in env


def cuda_files(tmp_path):
    cuda = tmp_path / 'cuda'
    (cuda / 'bin').mkdir(parents=True)
    (cuda / 'lib').mkdir()
    (cuda / 'bin/nvcc').touch()
    (cuda / 'lib/libcudart.so.13').touch()
    return cuda


def test_real_compiler_helper_and_child_cannot_import_working_directory(tmp_path):
    cuda = cuda_files(tmp_path)
    env = serving.environment(cuda, tmp_path / 'cache', {
        'PATH': ':/usr/bin:relative', 'LD_LIBRARY_PATH': ':.:/usr/lib:',
        'LIBRARY_PATH': '', 'PYTHONPATH': str(tmp_path)})
    for key in ('PATH', 'LD_LIBRARY_PATH', 'LIBRARY_PATH'):
        assert all(Path(p).is_absolute() for p in env[key].split(':'))
    assert (tmp_path / 'cache/link-libs/libcudart.so').resolve() == cuda / 'lib/libcudart.so.13'
    shadow = tmp_path / 'vllm'
    shadow.mkdir()
    marker = tmp_path / 'shadow-imported'
    (shadow / '__init__.py').write_text(f'from pathlib import Path\nPath({str(marker)!r}).touch()\n')
    subprocess.run([sys.executable, '-P', '-c', 'import vllm'], cwd=tmp_path,
                   env=env, capture_output=True, timeout=10)
    assert not marker.exists()


def launch_args(tmp_path, snapshot=None, extra=()):
    snapshot = snapshot or tmp_path / 'models--Qwen--Qwen3.8-27B-FP8/snapshots' / serving.REVISION
    snapshot.mkdir(parents=True, exist_ok=True)
    (snapshot / 'config.json').write_text('{}')
    receipt = tmp_path / 'launch.json'
    argv = ['serve_qwen_suite.py', '--snapshot', str(snapshot), '--receipt', str(receipt),
            '--cache-root', str(tmp_path / 'cache'), '--cuda-home', str(cuda_files(tmp_path)), *extra]
    return argv, receipt


def test_launch_records_actual_environment_cuda_attempt_and_knobs(tmp_path, monkeypatch):
    argv, receipt = launch_args(tmp_path, extra=('--port', '8123', '--max-num-seqs', '12'))
    monkeypatch.setattr(sys, 'argv', argv)
    monkeypatch.setattr(serving.os, 'statvfs', lambda p: SimpleNamespace(f_bavail=21 << 30, f_frsize=1))
    monkeypatch.setattr(serving, 'fingerprint', lambda a: {'command': a})
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'never-to-child')
    calls = []
    monkeypatch.setattr(serving.os, 'execve', lambda *a: calls.append(a))
    serving.main()
    first = json.loads(receipt.read_text())
    assert first['status'] == 'source_checks_passed_before_exec'
    assert first['cuda_home'] == str(tmp_path / 'cuda')
    assert first['pid'] == os.getpid()
    assert first['serving_environment']['VLLM_SERVER_DEV_MODE'] == '0'
    assert 'ANTHROPIC_API_KEY' not in first['serving_environment']
    child = calls[0]
    assert child[1][child[1].index('--port') + 1] == '8123'
    assert child[1][child[1].index('--max-num-seqs') + 1] == '12'
    assert first['command'] == child[1] and first['serving_environment'] == child[2]
    assert receipt.stat().st_mode & 0o777 == 0o600
    serving.main()
    assert json.loads(receipt.read_text())['attempt_id'] != first['attempt_id']


@pytest.mark.parametrize('failure', ['snapshot', 'shm', 'patch', 'exec'])
def test_failure_replaces_old_receipt_and_never_reports_readiness(tmp_path, monkeypatch, failure):
    argv, receipt = launch_args(tmp_path,
        snapshot=tmp_path / 'wrong' if failure == 'snapshot' else None)
    receipt.write_text(json.dumps({'status': 'ready', 'attempt_id': 'old'}))
    monkeypatch.setattr(sys, 'argv', argv)
    monkeypatch.setattr(serving.os, 'statvfs', lambda p: SimpleNamespace(
        f_bavail=(20 if failure == 'shm' else 21) << 30, f_frsize=1))
    fingerprint = lambda a: {'command': a}
    if failure == 'patch':
        def fingerprint(a):
            raise ValueError('Missing patch')
    monkeypatch.setattr(serving, 'fingerprint', fingerprint)
    exec_calls = []
    def execute(*args):
        exec_calls.append(args)
        raise OSError('Failed to execute')
    monkeypatch.setattr(serving.os, 'execve', execute)
    with pytest.raises((ValueError, RuntimeError, OSError)):
        serving.main()
    saved = json.loads(receipt.read_text())
    assert saved['status'] == 'failed' and saved['attempt_id'] != 'old'
    assert 'error_type' in saved
    assert saved['error']
    assert len(exec_calls) == (1 if failure == 'exec' else 0)


@pytest.mark.parametrize('name', ['PYTHONPATH', 'PYTHONHOME'])
def test_launcher_path_override_rejected_before_package_lookup(monkeypatch, name):
    monkeypatch.setenv(name, '/foreign/patched-install')
    with patch.object(serving, 'version') as lookup:
        with pytest.raises(ValueError, match='without PYTHONPATH/PYTHONHOME'):
            serving.fingerprint(serving.command('/snapshot'))
        lookup.assert_not_called()
