import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from intent_browser.expanded_tasks import ExpandedTaskSession


def test_expanded_session_uses_exact_shared_factory_and_profile(tmp_path, monkeypatch):
    from data.curation.worker_integration import bindings, tasks
    from intent_browser import expanded_tasks
    path = tmp_path / 'registry.json'; path.write_text('{}')
    row = {'id': 'webarena:1', 'revision': 'r', 'family': 'webarena.posts', 'site': 'reddit', 'site_id': 'webarena-forum',
           'grading_phase': 'after_browser_close', 'profile': {'name': 'core-tools-v3', 'max_steps': 24, 'observation_text_limit': 48000},
           'policy_input': {'goal': 'Exact goal', 'terminal_response_instruction': 'Exact response instruction'}}
    monkeypatch.setattr(bindings, 'load_registry', lambda path: {'tasks': [row]})
    lease = SimpleNamespace(origin='http://worker-environment.test', browser_proxy={'server': 'private', 'password': 'private'},
                            attest=Mock(return_value={'instance_id': 'i', 'reset_id': 'r'}), state_read=Mock(), close=Mock())
    service = SimpleNamespace(acquire=Mock(return_value=lease), close=Mock())
    monkeypatch.setattr(expanded_tasks, 'WorkerSites', lambda *args: service)
    task = SimpleNamespace(close=Mock())
    seen = []
    def make_task(task_id, **kwargs): seen.append((task_id, kwargs)); return task
    monkeypatch.setattr(tasks, 'make_task', make_task)
    env = {'HARNESS_EXPANDED_REGISTRY': str(path), 'HARNESS_EXPANDED_REGISTRY_SHA256': hashlib.sha256(path.read_bytes()).hexdigest(),
           'HARNESS_SITE_SERVICE_URL': 'private', 'HARNESS_SITE_SERVICE_TOKEN': 'private',
           'HARNESS_NATIVE_EVALUATOR_PYTHON': str(tmp_path / 'venv/bin/python')}
    session = ExpandedTaskSession('webarena:1', 'r', 'session', env, require_certificate=False)
    options = session.runner_options()
    assert options['max_steps'] == 24 and options['observation_text_limit'] == 48000
    assert options['harness_profile'].name == 'core-tools-v3'
    assert options['terminal_response_instruction'] == 'Exact response instruction'
    context = seen[0][1]['runtime_context']
    assert context.state_read == lease.state_read and context.attest == lease.attest
    assert context.origins == {'reddit': lease.origin}
    assert 'password' not in repr(context)
    # A venv executable can be a symlink to base Python; preserve its lexical path.
    interpreter = tmp_path / 'venv/bin/python'; interpreter.parent.mkdir(parents=True)
    base = tmp_path / 'base-python'; base.write_text('placeholder'); interpreter.symlink_to(base)
    launched = []
    def launch(command, **kwargs):
        launched.append(command)
        from pathlib import Path
        Path(command[command.index('--output') + 1]).write_text('{}')
    monkeypatch.setattr(expanded_tasks.subprocess, 'run', launch)
    context.native_grade('1', {}, tmp_path / 'trace.har', {'reddit': 'http://site'})
    assert launched[0][0] == str(interpreter)
    session.checkpoint(); lease.attest.assert_called_once()
    session.close(); task.close.assert_called_once(); lease.close.assert_called_once(); service.close.assert_called_once()
    session.close(); service.close.assert_called_once()
    env['HARNESS_EXPANDED_REGISTRY_SHA256'] = 'bad'
    with pytest.raises(ValueError, match='snapshot'): ExpandedTaskSession('webarena:1', 'r', 'session', env, require_certificate=False)
    assert service.acquire.call_count == 1


def test_cleanup_revokes_even_if_adapter_close_raises():
    session = ExpandedTaskSession.__new__(ExpandedTaskSession)
    session.task = SimpleNamespace(close=Mock(side_effect=RuntimeError('adapter failure')))
    lease = session.lease = SimpleNamespace(close=Mock())
    service = session.service = SimpleNamespace(close=Mock())
    with pytest.raises(RuntimeError): session.close()
    lease.close.assert_called_once(); service.close.assert_called_once()
    session.close()


def test_certificate_requires_exact_sources_registry_fixture_and_revision(tmp_path, monkeypatch):
    from data.curation.worker_integration import bindings
    from intent_browser.expanded_tasks import certified_tasks
    registry = tmp_path / 'registry.json'; registry.write_text('{}')
    rows = [{'id': 'tricky:test', 'revision': 'r1'}]
    monkeypatch.setattr(bindings, 'load_registry', lambda path: {'tasks': rows})
    sources = {}
    for name in ('intent_browser/runner.py', 'intent_browser/team_worker.py', 'intent_browser/expanded_tasks.py',
                 'intent_browser/task_finalization.py', 'data/curation/worker_integration/tasks.py'):
        path = tmp_path / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('frozen')
        sources[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    fixture = tmp_path / 'fixture'; fixture.mkdir()
    fixture_hashes = {}
    for name in ('build.json', 'catalog.json'):
        path = fixture / name; path.write_text('{}')
        fixture_hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    certificate = {'schema': 'expanded-worker-certification-v1', 'registry_sha256': hashlib.sha256(registry.read_bytes()).hexdigest(),
                   'source_sha256': sources, 'fixture_sha256': fixture_hashes, 'tasks': {'tricky:test': 'r1'}}
    target = tmp_path / 'certificate.json'
    env = {'HARNESS_PROJECT_ROOT': str(tmp_path), 'HARNESS_EXPANDED_REGISTRY': str(registry),
           'HARNESS_EXPANDED_REGISTRY_SHA256': certificate['registry_sha256'], 'HARNESS_FULL_FIXTURES_DIR': str(fixture)}
    assert certified_tasks(env) == ([], None)
    env['HARNESS_EXPANDED_CERTIFICATE'] = str(target)
    target.write_text(json.dumps(certificate))
    assert certified_tasks(env)[0] == rows
    for change, reason in (({'registry_sha256': 'changed'}, 'mismatch'),
                           ({'source_sha256': {}}, 'Incomplete'),
                           ({'fixture_sha256': {}}, 'fixture'),
                           ({'tasks': {'tricky:test': 'other'}}, 'revision')):
        target.write_text(json.dumps({**certificate, **change}))
        with pytest.raises(ValueError, match=reason): certified_tasks(env)
    target.write_text(json.dumps(certificate))
    (tmp_path / 'intent_browser/runner.py').write_text('changed')
    with pytest.raises(ValueError, match='source changed'): certified_tasks(env)


def test_timeout_amendment_is_explicit_and_validated():
    from intent_browser.expanded_tasks import runner_options
    row = {'profile': {'name': 'core-tools-v3', 'max_steps': 20, 'observation_text_limit': 48000},
           'policy_input': {'terminal_response_instruction': 'Return answer'}}
    assert 'action_timeout_ms' not in runner_options(row)
    assert runner_options(row, action_timeout_ms=30000)['action_timeout_ms'] == 30000
    for value in (True, 0, -1, '30000'):
        with pytest.raises((ValueError, TypeError)): runner_options(row, action_timeout_ms=value)


def test_certificate_writer_rejects_unpassed_evidence_and_changed_package(tmp_path):
    from scripts.certify_expanded_worker import certify
    package = tmp_path / 'package'; package.mkdir()
    registry = package / 'registry.json'; registry.write_text(json.dumps({'tasks': [{'id': 'tricky:t', 'revision': 'r'}]}))
    manifest = {'files': {'registry.json': hashlib.sha256(registry.read_bytes()).hexdigest()}}
    (package / 'manifest.json').write_text(json.dumps(manifest))
    fixtures = tmp_path / 'fixtures'; fixtures.mkdir()
    for name in ('build.json', 'catalog.json'): (fixtures / name).write_text('{}')
    report = tmp_path / 'report.json'; report.write_text('{"passed":false,"model_calls":0}')
    output = tmp_path / 'certificate.json'
    with pytest.raises(ValueError, match='passing'): certify(package, fixtures, [report], ['tricky:t'], output)
    assert not output.exists()
    report.write_text('{"passed":true,"model_calls":0}')
    with pytest.raises(ValueError, match='distinct'): certify(package, fixtures, [report], ['unknown'], output)
    result = certify(package, fixtures, [report], ['tricky:t'], output)
    assert result['tasks'] == {'tricky:t': 'r'}
    with pytest.raises(FileExistsError): certify(package, fixtures, [report], ['tricky:t'], output)
    registry.write_text('{}')
    with pytest.raises(ValueError, match='manifest'): certify(package, fixtures, [report], ['tricky:t'], tmp_path / 'other.json')
