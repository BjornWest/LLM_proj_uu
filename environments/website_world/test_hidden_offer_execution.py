from contextlib import contextmanager
import json
from types import SimpleNamespace
import pytest
from environments.website_world import hidden_offer_execution as execution


def setup_run(tmp_path,monkeypatch):
    output=tmp_path/'world';output.mkdir()
    (output/'execution.private.json').write_text(json.dumps({'validation':'off',
        'runtime_options':{'lazy_publication':True},'answer_grading':{'mode':'subscription-post-run'}}))
    events=[];callback=object();discovery=object()
    class Episode:
        def __init__(self,*args,**kwargs):
            self.task=SimpleNamespace(files={},make_env=lambda:None,site_discovery_callback=discovery,
                clarification_callback=callback,clarification_audit_id='private-audit')
            self.profile=SimpleNamespace(name='hidden+clarification+site-discovery')
        def __enter__(self):return self
        def __exit__(self,*args):events.append('runtime-close')
        def export_private_runtime(self,path):path.mkdir()
    monkeypatch.setattr(execution,'HiddenOfferEpisode',Episode)
    monkeypatch.setattr(execution.lifecycle.shared,'load',lambda p:{'source_sha256':{}})
    monkeypatch.setattr(execution.lifecycle,'provenance',lambda p:{'fixture':True})
    @contextmanager
    def policy(*,before_dispatch):
        before_dispatch();events.append('policy-open')
        try:yield object()
        finally:events.append('policy-close')
    def runner(*args,**kwargs):
        assert kwargs['clarification_callback'] is callback and kwargs['clarification_audit_id']=='private-audit'
        assert kwargs['site_discovery'] is discovery
        trace=kwargs['output']/'actual';trace.mkdir(parents=True)
        for name in ('steps.jsonl','natural-answer.json','policy-delivery.jsonl','clarification-000.json','policy-content-0000.json'):(trace/name).write_text('{}')
        events.append('policy-result');return trace,{'stop_reason':'agent_finished'}
    def grade(**kwargs):
        assert 'policy-close' in events
        assert kwargs['inputs']['task'].name=='hidden-offer-task.private.json'
        assert 'site_registry' not in kwargs['inputs']
        assert {p.name for p in kwargs['source_paths']}=={'steps.jsonl','natural-answer.json','policy-delivery.jsonl','clarification-000.json','policy-content-0000.json'}
        def native(**records):
            assert records['interaction_trace']==kwargs['trace'];events.append('actual-trace-bound');return object()
        monkeypatch.setattr(execution,'HiddenOfferGrader',native)
        kwargs['grader_factory'](world={})
        events.append('hidden-extraction');return {'structured_claims_correct':True}
    monkeypatch.setattr(execution.task_answer,'grade_saved_once',grade)
    return output,events,policy,runner


def test_callback_actual_trace_and_every_interaction_file_use_once_lifecycle(tmp_path,monkeypatch):
    output,events,policy,runner=setup_run(tmp_path,monkeypatch)
    result=execution.run(output,tmp_path/'run',policy_session=policy,metadata={},runner_options={'max_steps':5,'max_input_tokens':100000},quota_guard=lambda:None,extraction_backend_factory=lambda p:object(),runner=runner)
    assert result['answer_grading']['task_completed'] is True
    assert events==['policy-open','policy-result','policy-close','actual-trace-bound','hidden-extraction','runtime-close']
    with pytest.raises(FileExistsError):execution.run(output,tmp_path/'run',policy_session=policy,metadata={},runner_options={'max_steps':5,'max_input_tokens':100000},quota_guard=lambda:None,runner=runner)


def test_callback_binding_cannot_be_replaced(tmp_path):
    with pytest.raises(ValueError,match='reply binding'):
        execution.run(tmp_path,tmp_path/'run',policy_session=None,metadata={},runner_options={'clarification_audit_id':'replacement'})


def test_no_effect_binding_rejects_before_runtime(tmp_path,monkeypatch):
    monkeypatch.setattr(execution.shared,'load',lambda p:{'recipe':'website-hidden-offer-publication-v1'})
    for name,value in {'episode.json':{},'hidden-offer-task.private.json':{'task_id':'fixture'},
        'hidden-offer-reference.private.json':{'clarification_affects_eligibility':False},
        'hidden-offer-binding.private.json':{'task_id':'fixture','world_repaired':False,'status':'unsupported_no_effectful_clarification'}}.items():
        (tmp_path/name).write_text(json.dumps(value))
    import environments.website_world.runtime as runtime
    def forbidden(*a,**kw):raise AssertionError('Runtime must not start')
    monkeypatch.setattr(runtime,'Runtime',forbidden)
    with pytest.raises(ValueError,match='no-effect'):execution.HiddenOfferEpisode(tmp_path)


def test_interaction_symlink_cannot_escape_trace(tmp_path):
    outside=tmp_path/'outside.json';outside.write_text('{}');trace=tmp_path/'trace';trace.mkdir()
    (trace/'policy-content-0000.json').symlink_to(outside)
    with pytest.raises(ValueError,match='escapes'):execution.interaction_sources(trace)
