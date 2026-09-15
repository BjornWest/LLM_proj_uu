import json
from pathlib import Path
import pytest
from intent_browser import hosted_tasks


def test_registry_explicit_identities_and_goal_boundaries():
    rows = hosted_tasks.registry()['tasks']
    assert len({r['id'] for r in rows}) == 14
    chaos = [r for r in rows if r['kind'] == 'chaos']
    assert len(chaos) == 7 and all(r['goal'] is None for r in chaos)
    for candidate in ('p07', 'p10', 'p11'):
        clean = hosted_tasks.entry('tricky-'+candidate+'-clean')
        injected = hosted_tasks.entry('tricky-'+candidate+'-injected')
        assert clean['goal'] == injected['goal']
        assert clean['selector'] != injected['selector']
    assert hosted_tasks.entry('synthetic-dev-w01')['goal'] != hosted_tasks.entry('tricky-p07-injected')['goal']
    with pytest.raises(ValueError): hosted_tasks.entry('../../other')


def test_changed_revision_blocks_before_task_creation():
    with pytest.raises(ValueError, match='revision'):
        hosted_tasks.make_task('tricky-p07-clean', revision='old')
    with pytest.raises(ValueError, match='unavailable'):
        hosted_tasks.make_task('tricky-p07-clean')


def test_registry_tamper_rejected(tmp_path, monkeypatch):
    value = hosted_tasks.registry()
    value['tasks'][0]['selector'] = 'force-push'
    p = tmp_path/'registry.json'; p.write_text(json.dumps(value))
    monkeypatch.setattr(hosted_tasks, 'REGISTRY', p)
    with pytest.raises(ValueError, match='revision'):
        hosted_tasks.registry()


def test_packaged_current_adapters_and_isolated_sessions():
    root = hosted_tasks.ROOT/'.local/team-worker/fixtures-v1'
    if not root.is_dir(): pytest.skip('Optional exported local fixtures are absent')
    hosted_tasks.check_package(root)
    for task in hosted_tasks.registry()['tasks']:
        if task['kind'] == 'chaos': continue
        one = hosted_tasks.make_task(task['id'], fixture_dir=root, revision=task['revision'])
        two = hosted_tasks.make_task(task['id'], fixture_dir=root, revision=task['revision'])
        assert one.policy_goal == two.policy_goal == task['goal']
        assert one.session != two.session
        assert one.server is two.server is None  # construction never starts a server


def test_publisher_preserves_adapter_route_and_fails_uncertified_chaos():
    from types import SimpleNamespace
    from intent_browser.team_worker import PublishedTask
    calls=[]
    task=SimpleNamespace(route=lambda route: None,capture_initial=lambda *args:calls.append('adapter') or {'ok':True})
    wrapped=PublishedTask(task,None,None)
    assert wrapped.capture_initial(None,{}, {})=={'ok':True}
    assert calls==['adapter']
    publisher=SimpleNamespace(attach=lambda trace:None,job={'task':'chaos-force-push'})
    task=SimpleNamespace(prepare=lambda trace:{},verifier_ready=False)
    with pytest.raises(RuntimeError,match='certification'):
        PublishedTask(task,publisher,None).prepare(None)
