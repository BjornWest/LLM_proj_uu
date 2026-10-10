"""Focused controls for the thin branch-stock saved-answer adapter; no worlds, browsers or providers."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from . import branch_stock_saved_answer as adapter


def setup_fixture():
    task={'task_id':'task-1','memories':[{'text':'Original memory'}]}
    start={'kind':'tool_discovery'}
    setup={'schema':adapter.publication.VERSION,**deepcopy(task),'user_message':'Find this offer.', 'start':start}
    raw=json.dumps(setup).encode()
    manifest={'saved_answer_recipe':adapter.publication.VERSION,'files':{'saved-answer-setup.private.json':sha256(raw).hexdigest()}}
    return task,start,setup,raw,manifest


def test_checked_setup_preserves_identity_memory_and_start():
    task,start,setup,raw,manifest=setup_fixture()
    assert adapter.checked_setup(raw,manifest,task,start)==setup


@pytest.mark.parametrize('field,value',[
    ('task_id','foreign'),('memories',[]),('start',{'kind':'directory'}),
    ('user_message',' '),('user_message',None),('schema','foreign'),('allow_ungraded',True)])
def test_authentic_setup_cannot_change_other_bindings(field,value):
    task,start,setup,_,manifest=setup_fixture();setup[field]=value
    raw=json.dumps(setup).encode();manifest['files']['saved-answer-setup.private.json']=sha256(raw).hexdigest()
    with pytest.raises(ValueError,match='identity, memories or start'):
        adapter.checked_setup(raw,manifest,task,start)


def test_setup_hash_is_not_rebound():
    task,start,_,raw,manifest=setup_fixture()
    with pytest.raises(ValueError,match='frozen recipe'):
        adapter.checked_setup(raw+b' ',manifest,task,start)


def test_setup_requires_the_saved_answer_recipe_marker():
    task,start,_,raw,manifest=setup_fixture();del manifest['saved_answer_recipe']
    with pytest.raises(ValueError,match='frozen recipe'):
        adapter.checked_setup(raw,manifest,task,start)


def test_native_inputs_use_this_kinds_files_and_actual_runtime_bindings():
    assert adapter.native_inputs(Path('/recipe'),Path('/runtime'))=={
        'world':Path('/recipe/pin/world.private.json'),
        'task':Path('/recipe/catalog-branch-task.private.json'),
        'reference':Path('/recipe/catalog-branch-reference.private.json'),
        'bindings':Path('/runtime/bindings.private.json'),
        'surrounding':Path('/recipe/surrounding.private.json')}


def test_saved_episode_extends_only_this_kinds_native_episode():
    assert adapter.SavedBranchStockEpisode.__mro__[1].__name__=='CatalogBranchEpisode'
    assert adapter.SavedBranchStockEpisode.__module__==adapter.__name__


def test_run_attaches_existing_lifecycle_and_fixed_native_callbacks():
    options={'policy_session':object(),'metadata':{'tags':['scripted']},'runner_options':{'max_steps':1,'max_input_tokens':100},'viewer_projection':object(),'quota_guard':object()}
    with patch.object(adapter.lifecycle,'run',return_value='result') as run:
        assert adapter.run('/recipe','/run',**options)=='result'
        args=run.call_args.kwargs
        assert args['inputs_factory'] is adapter.native_inputs
        assert args['contract_id']==adapter.VERSION
        assert args['episode_factory'] is adapter.SavedBranchStockEpisode
        assert args['grader_factory'] is adapter.CatalogBranchGrader
        assert args['verifier']=='catalog-branch-native'
        for key in options:assert args[key] is options[key]


@pytest.mark.parametrize('name',['episode_factory','inputs_factory','grader_factory','contract_id','verifier'])
def test_caller_cannot_replace_native_bindings(name):
    with patch.object(adapter.lifecycle,'run') as run:
        with pytest.raises(TypeError):adapter.run('/recipe','/run',**{name:lambda:None})
        run.assert_not_called()


@pytest.mark.parametrize('recipe',['website-feature-offer-publication-v1','website-catalog-unit-price-publication-v2'])
def test_another_recipe_kind_is_rejected_before_any_output(recipe,tmp_path):
    saved=tmp_path/'saved';saved.mkdir()
    manifest={'recipe':recipe,'files':{'episode.json':sha256(b'{}').hexdigest()}}
    payload=json.dumps(manifest).encode()
    (saved/'manifest.json').write_bytes(payload);(saved/'episode.json').write_bytes(b'{}')
    with pytest.raises(ValueError,match='Wrong saved offer recipe kind'):
        adapter.prepare_saved(saved,tmp_path/'fresh-output',
            expected_manifest_sha256=sha256(payload).hexdigest(),user_message='Find this offer.')
    assert not (tmp_path/'fresh-output').exists()
