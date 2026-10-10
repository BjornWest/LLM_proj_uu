"""Prospective fixture tests, not executed before native/capture release."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from environments.website_world import catalog_cart_execution as execution


def test_run_cannot_dispatch_during_preparation():
    def forbidden(*a, **kw): raise AssertionError('Held runtime dispatched')
    with pytest.raises(RuntimeError, match='Source-only'):
        execution.run(policy_session=forbidden, runner=forbidden)


def test_capture_writer_refuses_overwrite(tmp_path):
    path=tmp_path/'raw.json';execution.save_new(path, {'raw':'original'})
    with pytest.raises(FileExistsError): execution.save_new(path, {'raw':'replacement'})
    assert json.loads(path.read_text())=={'raw':'original'}


def setup_capture(tmp_path):
    path=tmp_path/'trace';path.mkdir();private=path/'manual-review-private';private.mkdir()
    (path/'metadata.json').write_text(json.dumps({'episode_id':'actual-episode'}))
    (path/'steps.jsonl').write_text('{"action":"scripted"}\n')
    task={'task_id':'task'};binding={'retailers':{}}
    c=object.__new__(execution.CartCapture);c.task=task;c.binding=binding
    c.runtime=SimpleNamespace(sources={'source.py':'abc'},asset_hashes={'shop.js':'xyz'})
    c.trace=SimpleNamespace(directory=path,episode_id='actual-episode');c.artifacts={}
    context=SimpleNamespace(storage_state=lambda:{'cookies':[],'origins':[]})
    c.snapshot(context,c.trace,'before','before_policy');c.snapshot(context,c.trace,'after','after_policy_before_context_close')
    outcome={'stop_reason':'agent_finished','error':None,'terminated':False,'truncated':False}
    execution.save_new(private/'cart-terminal-outcome.private.json',outcome)
    return c,path,outcome


def test_seal_keeps_absent_effect_authority_and_actual_phases(tmp_path):
    c,path,outcome=setup_capture(tmp_path)
    capsule,done=c.seal(path,outcome)
    assert done and capsule['effect_journal'] is None
    assert capsule['before']['phase']=='before_policy'
    assert capsule['after']['phase']=='after_policy_before_context_close'
    assert capsule['main_trace_sha256']==execution.sha256((path/'steps.jsonl').read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):c.seal(path,outcome)


@pytest.mark.parametrize('fault',['foreign_trace','tampered_capture','missing_phase','changed_outcome'])
def test_seal_rejects_unbound_evidence(tmp_path,fault):
    c,path,outcome=setup_capture(tmp_path)
    if fault=='foreign_trace': path=tmp_path/'foreign'
    if fault=='tampered_capture':Path(c.artifacts['after']['path']).write_text('{}')
    if fault=='missing_phase':c.artifacts.pop('before')
    if fault=='changed_outcome':outcome={**outcome,'stop_reason':'max_steps'}
    with pytest.raises(ValueError):c.seal(path,outcome)


def test_interrupted_actual_policy_is_not_completed(tmp_path):
    c,path,outcome=setup_capture(tmp_path);outcome.update(stop_reason='interrupted',error='KeyboardInterrupt')
    p=path/'manual-review-private/cart-terminal-outcome.private.json';p.write_text(json.dumps(outcome))
    _,completed=c.seal(path,outcome);assert not completed


def test_initialize_uses_existing_tab_and_restores_start():
    visits=[]
    class Page:
        url='https://start.test/'
        def goto(self,url): self.url=url;visits.append(url)
        def wait_for_selector(self,selector): assert selector=='#app main'
        def wait_for_function(self,expression,*,arg): assert arg=='state-v2'
    page=Page()
    def forbidden(): raise AssertionError('Baseline must respect the one-tab origin bridge')
    page.context=SimpleNamespace(pages=[page],new_page=forbidden)
    capture=object.__new__(execution.CartCapture)
    capture.installed=True;capture.initialized=False;capture.setup_requests=[]
    capture.binding={'retailers':{'one':{'origin':'https://one.test','storage_key':'state-v2'}}}
    capture.initialize(page)
    assert visits==['https://one.test/#/home','https://start.test/']
    assert capture.initialized and page.context.pages==[page]
    assert capture.setup_requests[0]['browser_storage_writes_by_capture'] is False
    with pytest.raises(ValueError,match='already initialized'): capture.initialize(page)


@pytest.mark.parametrize('wrong_recovery',[False,True])
def test_storage_capture_recovers_only_the_original_task_page(tmp_path,wrong_recovery):
    trace=SimpleNamespace(directory=tmp_path)
    (tmp_path/'manual-review-private').mkdir()
    page=SimpleNamespace();base=SimpleNamespace(page=page)
    internal=SimpleNamespace(closed=True)
    raw={'cookies':[],'origins':[{'origin':'https://one.test','localStorage':[]}]}
    def storage_state(): base.page=internal;return deepcopy(raw)
    page.context=SimpleNamespace(storage_state=storage_state)
    base._active_page_check=lambda:setattr(base,'page',internal if wrong_recovery else page)
    env=SimpleNamespace(unwrapped=base)
    capture=object.__new__(execution.CartCapture);capture.artifacts={};capture.trace=None
    if wrong_recovery:
        with pytest.raises(ValueError,match='active task page'):
            capture.snapshot_environment(env,trace,'before','before_policy')
    else:
        result=capture.snapshot_environment(env,trace,'before','before_policy')
        assert base.page is page
        assert json.loads(Path(result['path']).read_text())['storage_state']==raw
