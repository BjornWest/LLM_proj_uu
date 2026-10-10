"""Focused controls for the declarative saved-answer registry; no worlds, browsers or providers."""
from copy import deepcopy
from hashlib import sha256
import inspect
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from . import saved_answer_registry as registry

KINDS = sorted(registry.CONTRACTS)
# Keyword arguments each native grader factory receives besides world, task and reference.
EXPECTED = {
    'quote_offer': ({'bindings', 'surrounding', 'basket_plan'}, {'delivery_plan'}),
    'memory_offer': ({'bindings', 'surrounding'}, set()),
    'hidden_offer': ({'bindings', 'surrounding'}, set()),
    'catalog_basket': ({'bindings', 'surrounding', 'plan', 'checkout_domain'}, {'admission_plan'}),
    'catalog_shortlist': ({'bindings', 'surrounding'}, set()),
    'catalog_relaxation': ({'bindings', 'surrounding'}, set()),
    'catalog_priority': ({'bindings', 'surrounding'}, set()),
    'catalog_comparison': ({'bindings'}, set()),
    'carrier_review': ({'site_registry', 'publication'}, set()),
    'shipping_claim': ({'bindings', 'basket_plan', 'checkout_domain'}, {'delivery_plan'}),
}


@pytest.fixture(params=KINDS)
def kind(request):return request.param


def options():
    return {'policy_session':object(),'metadata':{'tags':['scripted']},
        'runner_options':{'max_steps':1,'max_input_tokens':100},'viewer_projection':object(),'quota_guard':object()}


def setup_fixture():
    task={'task_id':'task-1','memories':[{'text':'Original memory'}]}
    start={'kind':'tool_discovery'}
    setup={'schema':registry.publication.VERSION,**deepcopy(task),'user_message':'Find this offer.','start':start}
    raw=json.dumps(setup).encode()
    manifest={'saved_answer_recipe':registry.publication.VERSION,'files':{registry.SETUP:sha256(raw).hexdigest()}}
    return task,start,setup,raw,manifest


def test_registry_covers_exactly_the_ten_legacy_families():
    assert set(registry.CONTRACTS)==set(EXPECTED)
    for name in ('recipe','task','reference','contract_id','verifier'):
        assert len({c[name] for c in registry.CONTRACTS.values()})==len(registry.CONTRACTS)


def test_unknown_contract_is_rejected():
    for bad in ('feature_offer','',None,5):
        with pytest.raises(ValueError,match='Unknown saved-answer contract'):registry.contract(bad)


def test_native_episode_declares_the_contract_recipe(kind):
    episode,_=registry.CONTRACTS[kind]['native']()
    assert repr(registry.CONTRACTS[kind]['recipe']) in inspect.getsource(episode)
    assert registry.CONTRACTS[kind]['task'] in inspect.getsource(episode)
    assert registry.CONTRACTS[kind]['reference'] in inspect.getsource(episode)


def test_declared_inputs_are_exactly_what_the_native_factory_accepts(kind):
    declared=registry.CONTRACTS[kind];required,optional=EXPECTED[kind]
    assert set(declared['inputs'])==required and set(declared['optional'])==optional
    _,factory=declared['native']()
    parameters=inspect.signature(factory).parameters
    for name in {'world','task','reference'}|required|optional:
        assert name in parameters,name
    # Anything the factory requires must be declared; undeclared parameters must have defaults.
    for name,parameter in parameters.items():
        if parameter.default is inspect.Parameter.empty and parameter.kind in (
                parameter.POSITIONAL_OR_KEYWORD,parameter.KEYWORD_ONLY):
            assert name in {'world','task','reference'}|required,name
    assert ('interaction_trace' in parameters)==declared['interaction']


def test_native_inputs_paths(kind,tmp_path):
    recipe,runtime=tmp_path/'recipe',tmp_path/'runtime'
    recipe.mkdir()
    declared=registry.CONTRACTS[kind]
    without=registry.native_inputs(kind)(recipe,runtime)
    assert without['world']==recipe/'pin/world.private.json'
    assert without['task']==recipe/declared['task'] and without['reference']==recipe/declared['reference']
    assert set(without)=={'world','task','reference'}|EXPECTED[kind][0]
    for name,path in without.items():
        assert path.is_relative_to(runtime if name in registry.RUNTIME_FILES else recipe)
    (recipe/'delivery-plan.private.json').write_text('{}')
    assert set(registry.native_inputs(kind)(recipe,runtime))=={'world','task','reference'}|EXPECTED[kind][0]|EXPECTED[kind][1]


def test_checked_setup_preserves_identity_memory_and_start():
    task,start,setup,raw,manifest=setup_fixture()
    assert registry.checked_setup(raw,manifest,task,start)==setup


@pytest.mark.parametrize('field,value',[
    ('task_id','foreign'),('memories',[]),('start',{'kind':'directory'}),
    ('user_message',' '),('user_message',None),('schema','foreign'),('allow_ungraded',True)])
def test_authentic_setup_cannot_change_other_bindings(field,value):
    task,start,setup,_,manifest=setup_fixture();setup[field]=value
    raw=json.dumps(setup).encode();manifest['files'][registry.SETUP]=sha256(raw).hexdigest()
    with pytest.raises(ValueError,match='identity, memories or start'):
        registry.checked_setup(raw,manifest,task,start)


def test_setup_hash_and_recipe_marker_are_required():
    task,start,_,raw,manifest=setup_fixture()
    with pytest.raises(ValueError,match='frozen recipe'):registry.checked_setup(raw+b' ',manifest,task,start)
    del manifest['saved_answer_recipe']
    with pytest.raises(ValueError,match='frozen recipe'):registry.checked_setup(raw,manifest,task,start)


def test_saved_episode_is_a_cached_subclass_bound_to_this_module(kind):
    saved=registry.saved_episode(kind);native,_=registry.CONTRACTS[kind]['native']()
    assert saved is registry.saved_episode(kind) and saved.__mro__[1] is native
    assert Path(inspect.getsourcefile(saved)).resolve()==Path(registry.__file__).resolve()
    assert Path(inspect.getsourcefile(registry.native_inputs(kind))).resolve()==Path(registry.__file__).resolve()


def test_run_binds_fixed_native_callbacks(kind):
    declared=registry.CONTRACTS[kind];given=options()
    if declared['interaction']:given['runner']=lambda *a,**k:None
    with patch.object(registry.lifecycle,'run',return_value='result') as run:
        assert registry.run('/recipe','/run',kind=kind,**given)=='result'
        args=run.call_args.kwargs
        assert run.call_args.args==('/recipe','/run')
        assert args['episode_factory'] is registry.saved_episode(kind)
        assert args['contract_id']==declared['contract_id'] and args['verifier']==declared['verifier']
        assert set(args['inputs_factory'](Path('/recipe'),Path('/runtime')))>={'world','task','reference'}
        for key in ('policy_session','metadata','runner_options','viewer_projection','quota_guard'):
            assert args[key] is given[key]
        if not declared['interaction']:
            assert args['grader_factory'] is declared['native']()[1] and 'runner' not in args
        assert inspect.getsourcefile(args['grader_factory']) is not None


@pytest.mark.parametrize('name',['episode_factory','inputs_factory','grader_factory','contract_id','verifier'])
def test_caller_cannot_replace_native_bindings(kind,name):
    with patch.object(registry.lifecycle,'run') as run:
        with pytest.raises(TypeError):registry.run('/recipe','/run',kind=kind,**options(),**{name:lambda:None})
        run.assert_not_called()


def test_run_requires_a_known_kind():
    with patch.object(registry.lifecycle,'run') as run:
        with pytest.raises(TypeError):registry.run('/recipe','/run',**options())
        with pytest.raises(ValueError,match='Unknown saved-answer contract'):
            registry.run('/recipe','/run',kind='feature_offer',**options())
        run.assert_not_called()


class Task:
    clarification_callback=staticmethod(lambda question:'reply');clarification_audit_id='audit-1'


def interaction_run(tmp_path,*,runner,runner_options=None):
    given=options();given['runner']=runner
    if runner_options is not None:given['runner_options']=runner_options
    with patch.object(registry.lifecycle,'run') as run:
        registry.run('/recipe',tmp_path,kind='hidden_offer',**given)
        return run.call_args.kwargs


def test_interaction_runner_forwards_the_saved_reply_contract_and_binds_the_trace(tmp_path):
    seen={}
    trace=tmp_path/'runs'/'trace-1';trace.mkdir(parents=True)
    def runner(*args,**kwargs):
        seen.update(kwargs);return str(trace),{'ok':True}
    args=interaction_run(tmp_path,runner=runner)
    with pytest.raises(ValueError,match='one actual returned main trace'):args['grader_factory'](world={})
    assert args['runner']('make_env','backend',{},episode_task=Task,output='x')==(str(trace),{'ok':True})
    assert seen['clarification_callback'] is Task.clarification_callback
    assert seen['clarification_audit_id']=='audit-1' and seen['episode_task'] is Task
    built={}
    class Grader:
        def __init__(self,**records):built.update(records)
    with patch.dict(registry.CONTRACTS['hidden_offer'],{'native':lambda:(object,Grader)}):
        args=interaction_run(tmp_path,runner=runner)
        args['runner']('make_env','backend',{},episode_task=Task)
        args['grader_factory'](world={'w':1},task={'t':1})
    assert built=={'world':{'w':1},'task':{'t':1},'interaction_trace':trace.resolve()}


def test_interaction_runner_rejects_a_trace_outside_this_execution(tmp_path):
    outside=tmp_path/'elsewhere';outside.mkdir()
    args=interaction_run(tmp_path/'run',runner=lambda *a,**k:(str(outside),{}))
    with pytest.raises(ValueError,match='outside this execution'):
        args['runner']('make_env','backend',{},episode_task=Task)


@pytest.mark.parametrize('name',['clarification_callback','clarification_audit_id'])
def test_runner_options_cannot_replace_the_saved_reply_binding(tmp_path,name):
    with patch.object(registry.lifecycle,'run') as run:
        with pytest.raises(ValueError,match='saved reply binding'):
            registry.run('/recipe',tmp_path,kind='hidden_offer',**{**options(),
                'runner_options':{'max_steps':1,'max_input_tokens':100,name:object()}})
        run.assert_not_called()


def recipe(tmp_path,recipe_id,files):
    saved=tmp_path/'saved';saved.mkdir()
    for name,value in files.items():
        (saved/name).parent.mkdir(parents=True,exist_ok=True);(saved/name).write_text(json.dumps(value))
    manifest={'recipe':recipe_id,'files':{name:sha256((saved/name).read_bytes()).hexdigest() for name in files}}
    payload=json.dumps(manifest).encode();(saved/'manifest.json').write_bytes(payload)
    return saved,sha256(payload).hexdigest()


def test_another_recipe_kind_is_rejected_before_any_output(kind,tmp_path):
    saved,digest=recipe(tmp_path,'website-feature-offer-publication-v1',{'episode.json':{}})
    with pytest.raises(ValueError,match='Wrong saved answer recipe kind'):
        registry.prepare_saved(saved,tmp_path/'fresh',kind=kind,expected_manifest_sha256=digest,user_message='Find it.')
    assert not (tmp_path/'fresh').exists()


@pytest.mark.parametrize('unbound',['carrier_review','shipping_claim'])
def test_a_recipe_without_a_native_task_is_rejected_before_any_output(unbound,tmp_path):
    declared=registry.CONTRACTS[unbound]
    saved,digest=recipe(tmp_path,declared['recipe'],{declared['task']:None,declared['reference']:None})
    with pytest.raises(ValueError,match='no bound native task'):
        registry.prepare_saved(saved,tmp_path/'fresh',kind=unbound,expected_manifest_sha256=digest,user_message='Find it.')
    assert not (tmp_path/'fresh').exists()


def test_changed_reference_is_rejected_before_any_output(tmp_path):
    declared=registry.CONTRACTS['catalog_comparison']
    task={'task_id':'t','memories':[],'concept_id':'c'}
    saved,digest=recipe(tmp_path,declared['recipe'],{declared['task']:task,declared['reference']:{'winner':'a'},
        'pin/world.private.json':{},'episode.json':{'start':{'kind':'tool_discovery'}}})
    with patch.dict(declared,{'replay':lambda world,task,records:{'winner':'b'}}):
        with pytest.raises(ValueError,match='reference changed'):
            registry.prepare_saved(saved,tmp_path/'fresh',kind='catalog_comparison',
                expected_manifest_sha256=digest,user_message='Find it.')
    assert not (tmp_path/'fresh').exists()


def test_prepare_passes_only_the_public_request_and_the_registry_as_adapter(tmp_path):
    declared=registry.CONTRACTS['quote_offer']
    task={'task_id':'t','memories':[{'text':'m'}],'concept_id':'c'};reference={'winner':'a'}
    start={'kind':'tool_discovery'}
    saved,digest=recipe(tmp_path,declared['recipe'],{declared['task']:task,declared['reference']:reference,
        'pin/world.private.json':{'w':1},'episode.json':{'start':start},'surrounding.private.json':{'s':1},
        'basket-plan.private.json':{'p':1}})
    seen={}
    def replay(world,native,records):
        seen.update(world=world,task=native,records=records);return reference
    with patch.dict(declared,{'replay':replay}), \
         patch.object(registry.publication,'prepare_saved',return_value='manifest') as prepare:
        assert registry.prepare_saved(saved,tmp_path/'fresh',kind='quote_offer',
            expected_manifest_sha256=digest,user_message='Which is cheapest delivered?')=='manifest'
    assert seen=={'world':{'w':1},'task':task,'records':{'reference':reference,'surrounding':{'s':1},'basket_plan':{'p':1}}}
    args=prepare.call_args.kwargs
    assert args['setup']=={'schema':registry.publication.VERSION,'task_id':'t',
        'user_message':'Which is cheapest delivered?','memories':[{'text':'m'}],'start':start}
    assert args['task_filename']==declared['task'] and args['adapter_file']==registry.__file__


def test_prepare_requires_each_declared_recipe_input(tmp_path):
    declared=registry.CONTRACTS['quote_offer']
    saved,digest=recipe(tmp_path,declared['recipe'],{declared['task']:{'task_id':'t','memories':[]},
        declared['reference']:{},'pin/world.private.json':{},'episode.json':{'start':{}},'surrounding.private.json':{}})
    with pytest.raises(ValueError,match='lacks a declared native input: basket_plan'):
        registry.prepare_saved(saved,tmp_path/'fresh',kind='quote_offer',expected_manifest_sha256=digest,user_message='x')
