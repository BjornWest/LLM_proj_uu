"""Focused controls for thin adapters, without worlds, browsers or providers."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from . import comparison_stock_saved_answer as stock, feature_saved_answer as feature


@pytest.fixture(params=[stock,feature])
def adapter(request):return request.param


def setup_fixture():
    task={'task_id':'task-1','memories':[{'text':'Original memory'}]}
    start={'kind':'comparison_home','comparison_site_id':'comparison-00'}
    setup={'schema':stock.publication.VERSION,**deepcopy(task),'user_message':'Find this offer.', 'start':start}
    raw=json.dumps(setup).encode()
    manifest={'saved_answer_recipe':stock.publication.VERSION,'files':{'saved-answer-setup.private.json':sha256(raw).hexdigest()}}
    return task,start,setup,raw,manifest


def test_checked_setup_preserves_identity_memory_and_start(adapter):
    task,start,setup,raw,manifest=setup_fixture()
    assert adapter.checked_setup(raw,manifest,task,start)==setup


@pytest.mark.parametrize('field,value',[
    ('task_id','foreign'),('memories',[]),('start',{'kind':'directory'}),
    ('user_message',' '),('user_message',None),('schema','foreign')])
def test_authentic_setup_cannot_change_other_bindings(adapter,field,value):
    task,start,setup,_,manifest=setup_fixture();setup[field]=value
    raw=json.dumps(setup).encode();manifest['files']['saved-answer-setup.private.json']=sha256(raw).hexdigest()
    with pytest.raises(ValueError,match='identity, memories or start'):
        adapter.checked_setup(raw,manifest,task,start)


def test_setup_hash_is_not_rebound(adapter):
    task,start,_,raw,manifest=setup_fixture()
    with pytest.raises(ValueError,match='frozen recipe'):
        adapter.checked_setup(raw+b' ',manifest,task,start)


def test_native_inputs_keep_actual_unfiltered_runtime_bindings(adapter):
    data=adapter.native_inputs(Path('/recipe'),Path('/runtime'))
    assert data['bindings']==Path('/runtime/bindings.private.json')
    assert data['world']==Path('/recipe/pin/world.private.json')
    assert data['surrounding']==Path('/recipe/surrounding.private.json')
    assert ('site_registry' in data)==(adapter is stock)


def test_run_attaches_existing_lifecycle_and_fixed_native_callbacks(adapter):
    options={'policy_session':object(),'metadata':{'tags':['scripted']},'runner_options':{'max_steps':1,'max_input_tokens':100},'viewer_projection':object(),'quota_guard':object()}
    with patch.object(adapter.lifecycle,'run',return_value='result') as run:
        assert adapter.run('/recipe','/run',**options)=='result'
        args=run.call_args.kwargs
        assert args['inputs_factory'] is adapter.native_inputs
        assert args['contract_id']==adapter.VERSION
        assert args['episode_factory'] is (stock.SavedComparisonStockEpisode if adapter is stock else feature.SavedFeatureOfferEpisode)
        for key in options:assert args[key] is options[key]


def test_caller_cannot_replace_native_grader_or_episode_factory(adapter):
    with patch.object(adapter.lifecycle,'run') as run:
        with pytest.raises(TypeError):adapter.run('/recipe','/run',episode_factory=lambda:None)
        run.assert_not_called()
