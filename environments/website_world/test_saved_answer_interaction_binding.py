"""Synthetic lifecycle controls; no browsers, model requests or HTTP acceptance."""
from contextlib import contextmanager
from hashlib import sha256
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from . import saved_answer_lifecycle as lifecycle
from . import saved_answer_registry as registry


def test_registry_forwards_real_native_interaction_sources(tmp_path):
    trace = tmp_path/'trace';trace.mkdir()
    for name in ('steps.jsonl','policy-delivery.jsonl','clarification-000.json','policy-content-0000.json'):
        (trace/name).write_text('{}')
    assert {p.name for p in registry._interaction_sources(trace)} == {
        'steps.jsonl','policy-delivery.jsonl','clarification-000.json','policy-content-0000.json'}


@pytest.mark.parametrize('mode', ['stable','unlimited','mutated','escaped'])
def test_lifecycle_pins_interaction_bytes_through_cleanup_extraction_and_publication(tmp_path, monkeypatch, mode):
    from intent_browser import automatic_grading as auto
    from intent_browser.connected_world_task import checked_files
    from .compound_answer_delivery_v1 import SCHEMA, SOURCE
    recipe=tmp_path/'recipe';recipe.mkdir()
    native={'task_id':'hidden-1','memories':[],'user_message':'Find the offer.'}
    records={'world':{},'task':native,'reference':{}}
    files={}
    for name,row in records.items():
        p=recipe/(name+'.json');p.write_text(json.dumps(row));files[str(p)]=sha256(p.read_bytes()).hexdigest()
    events=[];control={}
    def inputs(output,runtime):return {k:recipe/(k+'.json') for k in records}
    def native_factory(**values):return SimpleNamespace(task=values['task'])
    def evidence(trace):
        if mode=='escaped':return [tmp_path/'outside.json']
        return [trace/'clarification-000.json',trace/'policy-content-0000.json',trace/'policy-delivery.jsonl']
    callback_file=Path(inspect.getsourcefile(inputs)).resolve()
    files[str(callback_file)]=sha256(callback_file.read_bytes()).hexdigest()
    class Episode:
        def __init__(self,output):
            self.public=native;self.task=SimpleNamespace(files=dict(files),make_env=lambda:None)
            self.profile=None;self.site_discovery=None
        def __enter__(self):return self
        def __exit__(self,*args):events.append('runtime_closed')
        def export_private_runtime(self,path):
            path.mkdir();(path/'manifest.json').write_text('{}');return {'files':{}}
    @contextmanager
    def policy(**kwargs):
        kwargs['before_dispatch']()
        yield object()
        events.append('policy_closed')
    terminal={'stop_reason':'agent_finished','trace_complete':True,'error':None,'execution_error':None,
              'cleanup_errors':[],'terminated':False,'truncated':False}
    def runner(env_factory, backend, metadata, **kwargs):
        assert metadata['tags']==['scripted']
        control['contract']=kwargs['automatic_grading']
        trace=kwargs['output']/'main';trace.mkdir(parents=True);control['trace']=trace
        (trace/'episode.json').write_text(json.dumps(terminal))
        natural={'schema_version':SCHEMA,'source':SOURCE,'text':'This offer.','assistant_messages':['This offer.'],
                 'stop_reason':'agent_finished','initial_chat_messages_excluded':0,'technical_error':None,'correctness':None}
        (trace/'natural-answer.json').write_text(json.dumps(natural))
        for name in ('clarification-000.json','policy-content-0000.json','policy-delivery.jsonl'):(trace/name).write_text('{}')
        return trace,terminal
    def extract(**kwargs):
        assert events==['policy_closed','runtime_closed']
        hashes={str(p):sha256(Path(p).read_bytes()).hexdigest() for p in kwargs['source_paths']}
        assert all(str(control['trace']/name) in hashes for name in
                   ('clarification-000.json','policy-content-0000.json','policy-delivery.jsonl'))
        kwargs['grader_factory'](**records)
        if mode=='mutated':(control['trace']/'clarification-000.json').write_text('{"changed":true}')
        checked_files(hashes)
        return {'grade':{'structured_claims_correct':True},'source_hashes':hashes}
    def finalize(trace,contract):
        contract.grade(None,SimpleNamespace(directory=trace),terminal)
        return {'infrastructure_completed':True}
    monkeypatch.setattr(auto.AutomaticGrading,'callable_sources',lambda self:set())
    monkeypatch.setattr(lifecycle,'check_policy_outcome',lambda *args:None)
    monkeypatch.setattr(lifecycle,'check_saved_public_task',lambda *args:None)
    monkeypatch.setattr(lifecycle,'extract_saved_deferred',extract)
    monkeypatch.setattr(lifecycle,'publish_finalized_answer',lambda *args,**kwargs:events.append('published'))
    monkeypatch.setattr(auto,'finalize_external',finalize)
    result=lifecycle.run(recipe,tmp_path/'run',episode_factory=Episode,inputs_factory=inputs,
        grader_factory=native_factory,contract_id='synthetic-hidden',verifier='synthetic',policy_session=policy,
        metadata={'tags':['scripted']},runner_options={'max_steps':None if mode=='unlimited' else 1,'max_input_tokens':100},
        viewer_projection=lambda **kwargs:{'status':'verified'},quota_guard=lambda:None,
        extraction_backend_factory=lambda p:None,runner=runner,evidence_sources=evidence)
    if mode in ('stable','unlimited'):
        assert result['status']=='graded_and_projected';assert events[-1]=='published'
    else:
        assert result['status']=='system_failure';assert 'published' not in events
        assert ('Pinned artifact changed' if mode=='mutated' else 'escaped') in result['reason']

@pytest.mark.parametrize('bounds', [
    {'max_steps':None,'max_input_tokens':0},
    {'max_steps':None,'max_input_tokens':True},
    {'max_steps':0,'max_input_tokens':100},
    {'max_steps':True,'max_input_tokens':100},
    {'max_input_tokens':100},
])
def test_explicit_unlimited_turns_never_disable_input_context_guard(tmp_path, bounds):
    with pytest.raises(ValueError, match='positive input-context'):
        lifecycle.run(tmp_path/'recipe',tmp_path/'run',episode_factory=lambda *a:None,
            inputs_factory=lambda *a:None,grader_factory=lambda **kw:None,
            contract_id='test',verifier='test',policy_session=lambda **kw:None,
            metadata={'tags':['scripted']},runner_options=bounds,
            viewer_projection=lambda **kw:None,quota_guard=lambda:None)
    assert not (tmp_path/'run').exists()
