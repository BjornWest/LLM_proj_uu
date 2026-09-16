import hashlib
import json
from browser_training import provenance


def test_partial_remote_tree_finds_separately_installed_environment(tmp_path, monkeypatch):
    root = tmp_path / 'training'
    package = root / 'browser_training'
    package.mkdir(parents=True)
    source = package / 'provenance.py'
    source.write_text('# mounted source')
    environment = tmp_path / 'rl'
    environment.mkdir()
    (environment / 'pyproject.toml').write_text('[project]\nname = "remote"\n')
    lock = environment / 'uv.lock'
    lock.write_text('version = 1\n')
    monkeypatch.setattr(provenance, '__file__', str(source))
    monkeypatch.setattr(provenance.sys, 'prefix', str(environment / '.venv'))
    monkeypatch.setattr(provenance.importlib.util, 'find_spec', lambda name: None)
    manifest = provenance.capture(tmp_path / 'output', {'stage': 'CPU check'})
    data = json.loads(manifest.read_text())
    assert data['environment_file_sha256'][str(lock)] == hashlib.sha256(lock.read_bytes()).hexdigest()
    assert data['source_sha256']['browser_training/provenance.py']
    assert not (root / 'envs').exists()


def test_source_only_layout_records_missing_locks_without_crashing(tmp_path, monkeypatch):
    package = tmp_path / 'training' / 'browser_training'
    package.mkdir(parents=True)
    monkeypatch.setattr(provenance, '__file__', str(package / 'provenance.py'))
    monkeypatch.setattr(provenance.sys, 'prefix', str(tmp_path / 'no-env' / '.venv'))
    monkeypatch.setattr(provenance.importlib.util, 'find_spec', lambda name: None)
    data = json.loads(provenance.capture(tmp_path / 'output', {}).read_text())
    assert data['environment_file_sha256'] == {}
