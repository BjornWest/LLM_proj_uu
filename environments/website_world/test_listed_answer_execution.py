"""Post-policy grading uses the released native callable, without model/browser runs."""
from contextlib import contextmanager
from types import SimpleNamespace
from pathlib import Path
import json
import pytest

from environments.website_world import listed_answer_execution as stage, execution_generation
from environments.website_world.test_listed_offer_grading import fixture, answer
from environments.website_world.listed_offer_grading import ListedOfferGrader
from scripts.trace_grades import BOUND_FILES, read_grade


@pytest.fixture
def packet(tmp_path, monkeypatch):
    source=tmp_path/'generated'; source.mkdir(); (source/'pin').mkdir()
    world,task,reference,bindings=fixture(); text,claims=answer()
    def write(path,value): path.write_text(json.dumps(value))
    for path,value in [(source/'pin/world.private.json',world),
        (source/'basic-offer-task.private.json',task),(source/'basic-offer-reference.private.json',reference)]:write(path,value)
    write(source/'execution.private.json',{'answer_grading':{'mode':'subscription-post-run'}})
    events=[]; runtime_flags=[]; held={'policy':False}; grader=ListedOfferGrader(world,task,reference,bindings)
    class Episode:
        answer_grader=grader; profile='fixed-profile';site_discovery='fixed-directory'
        task=SimpleNamespace(files={},make_env='fixed-env')
        def __init__(self,*args,**kwargs):
            assert not kwargs.get('answer_extractor')
            runtime_flags.append(kwargs['lazy_publication'])
        def __enter__(self): return self
        def __exit__(self,*args):events.append('runtime_closed')
        def export_private_runtime(self,output):
            output.mkdir();write(output/'bindings.private.json',bindings)
    monkeypatch.setattr(stage,'GeneratedEpisode',Episode)
    monkeypatch.setattr(stage,'load',lambda p:{'source_sha256':{},'files':{}})
    @contextmanager
    def session():
        assert not held['policy'];held['policy']=True;events.append('policy_open')
        try: yield 'policy-backend'
        finally: held['policy']=False;events.append('policy_closed')
    def runner(env,backend,metadata,**kwargs):
        assert held['policy'] and env=='fixed-env' and backend=='policy-backend'
        assert kwargs['site_discovery']=='fixed-directory' and kwargs['harness_profile']=='fixed-profile'
        assert kwargs['max_steps']==2 and kwargs['max_input_tokens']==1000
        trace=Path(kwargs['output'])/'episode';trace.mkdir(parents=True)
        for name in BOUND_FILES:write(trace/name,{'preserved':name})
        write(trace/'policy-task.json',{'user_message':'Find shoes','memories':[], 'environment_context':{}})
        write(trace/'natural-answer.json',{'text':text,'stop_reason':'agent_finished','technical_error':None})
        events.append('policy_finished')
        return trace,{'error':None,'cleanup_errors':[],'stop_reason':'agent_finished'}
    class Backend:
        def complete(self,messages):
            assert not held['policy'];events.append('extraction_request')
            assert 'minimum_price_minor' not in json.dumps(messages)
            return SimpleNamespace(text=json.dumps(claims),request={'messages':messages},raw={
                'model':'scripted','provider':'offline','choices':[{'finish_reason':'stop','message':{'content':json.dumps(claims)}}]})
        def close(self):events.append('extraction_closed')
    def factory(path):
        assert not held['policy'];events.append('extraction_open');return Backend()
    return SimpleNamespace(source=source,events=events,runtime_flags=runtime_flags,session=session,runner=runner,factory=factory,held=held,
        options={'max_steps':2,'max_input_tokens':1000},write=write,claims=claims,Backend=Backend)


def run_case(packet,destination,**kwargs):
    return stage.run(packet.source,destination,policy_session=packet.session,metadata={},
        runner_options=packet.options,runner=kwargs.pop('runner',packet.runner),
        extraction_backend_factory=kwargs.pop('factory',packet.factory),**kwargs)


@pytest.mark.parametrize('lazy', [None, False, True])
def test_closed_policy_once_only_extraction_native_grade_and_preserved_trace(packet,tmp_path,lazy):
    if lazy is not None:
        packet.write(packet.source/'execution.private.json',{'answer_grading':{'mode':'subscription-post-run'},
            'runtime_options':{'lazy_publication':lazy}})
    destination=tmp_path/'run';result=run_case(packet,destination)
    assert result['answer_grading']['status']=='graded' and result['answer_grading']['task_completed'] is True
    assert packet.events==['policy_open','policy_finished','policy_closed','extraction_open',
                           'extraction_request','extraction_closed','runtime_closed']
    trace=Path(result['trace']);assert json.loads((trace/'evaluation.json').read_text())=={'preserved':'evaluation.json'}
    assert read_grade(trace)['structured_claims_correct'] is True
    with pytest.raises(FileExistsError):run_case(packet,destination)
    assert packet.events.count('extraction_request')==1 and packet.events.count('policy_open')==1
    assert packet.runtime_flags == [lazy is True]
    assert json.loads((destination/'execution-plan.private.json').read_text())['runtime_options']=={'lazy_publication':lazy is True}


@pytest.mark.parametrize('value', [True, [], {'extra':True}, {'lazy_publication':1}, {'lazy_publication':'true'}])
def test_invalid_runtime_recipe_rejects_before_runtime_or_backend(packet,tmp_path,value):
    packet.write(packet.source/'execution.private.json',{'runtime_options':value})
    with pytest.raises(ValueError): run_case(packet,tmp_path/'run')
    assert not packet.events and not packet.runtime_flags and not (tmp_path/'run').exists()


@pytest.mark.parametrize('failure',['interrupted','execution_error','cleanup_error'])
def test_incomplete_policy_never_starts_extraction(packet,tmp_path,failure):
    def runner(*args,**kwargs):
        trace,summary=packet.runner(*args,**kwargs)
        if failure=='interrupted':packet.write(trace/'natural-answer.json',{'text':answer()[0],'stop_reason':'interrupted'})
        elif failure=='execution_error':summary['error']='failed action'
        else:summary['cleanup_errors']=['failed teardown']
        return trace,summary
    result=run_case(packet,tmp_path/'run',runner=runner)
    assert result['answer_grading']['status']=='skipped' and result['answer_grading']['task_completed'] is None
    assert 'extraction_open' not in packet.events


def test_extraction_failure_is_unknown_without_retry_or_policy_relabel(packet,tmp_path):
    class Broken(packet.Backend):
        def complete(self,messages):packet.events.append('extraction_request');raise RuntimeError('Provider failed')
    result=run_case(packet,tmp_path/'run',factory=lambda path:Broken())
    assert result['answer_grading']['status']=='failed' and result['answer_grading']['task_completed'] is None
    assert result['policy_summary']['error'] is None and packet.events.count('extraction_request')==1
    assert (tmp_path/'run/answer-grading/extraction/error.json').exists()


def test_session_close_failure_prevents_extraction(packet,tmp_path):
    @contextmanager
    def failed_close():
        with packet.session() as backend:yield backend
        raise RuntimeError('Policy bridge failed to close')
    with pytest.raises(RuntimeError,match='bridge failed'):
        stage.run(packet.source,tmp_path/'run',policy_session=failed_close,metadata={},
            runner_options=packet.options,runner=packet.runner,extraction_backend_factory=packet.factory)
    assert 'extraction_open' not in packet.events


def test_source_drift_after_policy_blocks_extraction(packet,tmp_path,monkeypatch):
    from hashlib import sha256
    source=tmp_path/'source.py';source.write_text('original')
    original=stage.GeneratedEpisode
    class Episode(original):
        task=SimpleNamespace(files={str(source):sha256(source.read_bytes()).hexdigest()},make_env='fixed-env')
    monkeypatch.setattr(stage,'GeneratedEpisode',Episode)
    def runner(*args,**kwargs):
        result=packet.runner(*args,**kwargs);source.write_text('changed');return result
    with pytest.raises(ValueError,match='Pinned artifact changed'):
        run_case(packet,tmp_path/'run',runner=runner)
    assert 'policy_closed' in packet.events and 'extraction_open' not in packet.events


@pytest.mark.parametrize('override',[{'max_steps':0},{'max_input_tokens':True},{'site_discovery':'replacement'}])
def test_unbounded_or_rebound_policy_rejected_before_open(packet,tmp_path,override):
    packet.options.update(override)
    with pytest.raises(ValueError):run_case(packet,tmp_path/'run')
    assert not packet.events


def test_disabled_recipe_has_no_extraction_and_no_grade(packet,tmp_path):
    packet.write(packet.source/'execution.private.json',{})
    result=run_case(packet,tmp_path/'run',factory=None)
    assert result['answer_grading']['status']=='disabled' and 'extraction_open' not in packet.events


@pytest.mark.parametrize('value',[{'mode':'other'},{'mode':'off','model':'x'},True,
    {'mode':'subscription-post-run','extra':True},{'mode':'subscription-post-run','model':''}])
def test_invalid_stage_recipe_rejects(value):
    with pytest.raises(ValueError):stage.options(value)


def test_prepare_rejects_unsupported_task_before_any_world_generation(tmp_path):
    with pytest.raises(ValueError,match='cheapest_available'):
        execution_generation.prepare({'task':{'kind':'manual'}},tmp_path/'not-created',
            answer_grading={'mode':'subscription-post-run'})
    assert not (tmp_path/'not-created').exists()


@pytest.mark.parametrize('lazy,grading', [(False,{'mode':'subscription-post-run'}),
    (True,{'mode':'subscription-post-run'}),(True,None)])
def test_actual_prepare_pins_stage_without_changing_sampling_request(tmp_path,monkeypatch,lazy,grading):
    from copy import deepcopy
    from hashlib import sha256
    from environments.website_world import unified_generation, generation
    world=json.loads(Path('.local/accepted-catalog-commerce-pin-v2/world.private.json').read_text())
    request={'schema':unified_generation.VERSION,'seed':world['seed'],
        'task':{'kind':'cheapest_available','concept_id':'footwear.walking_shoes'},
        'episode':{'start':{'kind':'tool_discovery'},'readable_origins':True},
        'budget':{'max_proposals':1,'max_seconds':120}}
    before=deepcopy(request)
    monkeypatch.setattr(execution_generation.Execution,'generate',lambda *a,**kw:world)
    manifest=execution_generation.prepare(request,tmp_path/'prepared',answer_grading=grading,lazy_publication=lazy)
    assert request==before
    record=json.loads((tmp_path/'prepared/execution.private.json').read_text())
    assert record.get('answer_grading',{'mode':'off'})==stage.options(grading)
    assert record.get('runtime_options',{'lazy_publication':False})=={'lazy_publication':lazy}
    assert ('runtime_options' in record) is lazy
    assert json.loads((tmp_path/'prepared/pin/world.private.json').read_text())==world
    assert generation.load(tmp_path/'prepared')==manifest
    config=json.loads((tmp_path/'prepared/generation-config.private.json').read_text())
    assert config['request']==before
    assert config['resolved']['basic_offer_selection']['concept_id']=='footwear.walking_shoes'
    assert config['resolved']['requirements']==[]
    assert config['execution']=={'validation':'off','lazy_publication':lazy,'answer_grading':stage.options(grading)}
    assert config['world_id']==world['world_id'] and config['selected_seed']==world['seed']
    assert config['task_source']=='structured_template'
    assert 'environments/website_world/generation_configs.py' in manifest['source_sha256']
    sources=['environments/website_world/listed_answer_execution.py']
    if grading is not None:sources.extend([
        'experiments/answer_grading/listed_offer.py','experiments/external_agent/protocol.py',
        'experiments/external_agent/worker.mjs','scripts/trace_grades.py'])
    for name in sources:
        assert name in manifest['source_sha256']
        assert sha256((tmp_path/'prepared/pin/source-snapshot'/name).read_bytes()).hexdigest()==manifest['source_sha256'][name]


def test_prepare_rejects_invalid_runtime_flag_before_world_generation(tmp_path):
    with pytest.raises(ValueError,match='must be a bool'):
        execution_generation.prepare({},tmp_path/'not-created',lazy_publication=1)
    assert not (tmp_path/'not-created').exists()
