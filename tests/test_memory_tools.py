from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from intent_browser.backend import Completion
from intent_browser.harness import native_tools_profile,with_memory
from intent_browser.memory import MemorySession,MemoryRejected
from tests.runner_diagnostics import run_episode
from experiments.memory_shopping.store import FileMemory
from experiments.memory_shopping.task import FIELDS,INITIAL


def store(tmp_path):return FileMemory(tmp_path/'store.json',fields=FIELDS,initial=INITIAL)
def trace(tmp_path):return SimpleNamespace(directory=tmp_path,episode_id='test-memory')
def completion(calls):
    return Completion('',{'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
        'tool_calls':[{'id':str(i),'type':'function','function':{'name':name,'arguments':json.dumps(args)}} for i,(name,args) in enumerate(calls)]}}]})


def test_defaults_and_opt_in():
    base=native_tools_profile();before=deepcopy(base.tools.request_options())
    enabled=with_memory(base)
    assert base.tools.request_options()==before
    assert not any('memory_' in t['function']['name'] for t in before['tools'])
    assert {t['function']['name'] for t in enabled.tools.definitions()} >= {'memory_read','memory_update','memory_delete'}
    with pytest.raises(ValueError):base.tools.parse_completion(completion([('memory_read',{})]))
    d,_=enabled.tools.parse_completion(completion([('memory_read',{})]));assert d.name=='memory_read'


def test_adapter_profile_mismatch_precedes_environment_and_inference(tmp_path):
    def fail(*a):pytest.fail('must reject before environment/inference')
    for p,adapter in ((native_tools_profile(),store(tmp_path)),(with_memory(native_tools_profile()),None)):
        with pytest.raises(ValueError,match='both required'):run_episode(fail,SimpleNamespace(),{},harness_profile=p,memory_adapter=adapter)
    p=with_memory(native_tools_profile());p=replace(p,tools=replace(p.tools,helper_tools=True))
    with pytest.raises(ValueError,match='delegation'):run_episode(fail,SimpleNamespace(),{},harness_profile=p,memory_adapter=store(tmp_path))


def test_replace_delete_reopen_and_rejections(tmp_path):
    s=store(tmp_path);session=MemorySession(s,trace(tmp_path));rev=s.snapshot()['revision']
    result,_=session.execute('memory_update',{'key':'delivery_preference','value':'home_delivery','expected_revision':rev},0)
    assert result['applied'] and result['snapshot']['values']['shoe_size_eu']==38
    for i,args in enumerate(({'key':'delivery_preference','value':'pickup','expected_revision':rev},
                            {'key':'delivery_preference','value':'nonsense','expected_revision':s.snapshot()['revision']}),1):
        before=s.audit();r,_=session.execute('memory_update',args,i)
        assert r['applied'] is False and r['error'] and s.audit()==before
    reopened=FileMemory(s.path,fields=FIELDS);assert reopened.snapshot()==s.snapshot()
    result,_=session.execute('memory_delete',{'key':'delivery_preference','expected_revision':s.snapshot()['revision']},3)
    assert result['applied'] and 'delivery_preference' not in s.snapshot()['values']
    e=session.finish();assert len(e['events'])==2 and e['coverage']=='complete'
    assert e['initial']==INITIAL


def test_atomic_contending_updates(tmp_path):
    s=store(tmp_path);rev=s.snapshot()['revision']
    def update(value):
        try:return FileMemory(s.path,fields=FIELDS).update('delivery_preference',value,rev)
        except MemoryRejected:return None
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(update,['pickup','home_delivery']))
    assert sum(r is not None for r in results)==1
    assert len(s.audit()['events'])==1


def test_ambiguous_postcommit_failure_is_not_replayed(tmp_path):
    s=store(tmp_path);calls=[];real=s.update
    def broken(*a):
        calls.append(a);real(*a);raise RuntimeError('lost acknowledgment')
    s.update=broken;session=MemorySession(s,trace(tmp_path))
    with pytest.raises(RuntimeError):session.execute('memory_update',{'key':'delivery_preference','value':'home_delivery','expected_revision':s.snapshot()['revision']},0)
    assert len(calls)==1 and s.snapshot()['values']['delivery_preference']=='home_delivery'
    assert session.finish()['coverage']=='unknown'
    row=json.loads((tmp_path/'memory-000.json').read_text());assert row['applied'] is None and row['dispatch_started'] is True


def test_memory_kind_does_not_relax_ledger_allowlist(tmp_path):
    from intent_browser.policy_delivery import PolicyDelivery
    ledger=PolicyDelivery(trace(tmp_path))
    assert ledger.register('memory_result','{}',step=0)
    with pytest.raises(ValueError,match='Unsupported policy evidence kind'):
        ledger.register('made_up_memory_kind','{}',step=0)
