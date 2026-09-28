from copy import deepcopy
import pytest
from intent_browser.targeted_guard import _chain
from intent_browser.observation_pipeline import ObservationPipelineConfig

def test_opt_in_and_screenshot_contract():
    assert not ObservationPipelineConfig((),full_capture_only=True).targeted_actions
    for kw in ({'targeted_actions':1},{'targeted_actions':True},
               {'targeted_actions':True,'dynamic_preview':True}):
        with pytest.raises(ValueError):ObservationPipelineConfig((),full_capture_only=True,**kw)
    value=ObservationPipelineConfig((),full_capture_only=True,dynamic_preview=True,targeted_actions=True,trace_screenshots=False)
    assert value.describe()['targeted_actions']

def test_target_ancestry_is_identity_and_state_not_whole_page():
    nodes=[{'nodeId':'1','backendDOMNodeId':1,'role':{'value':'RootWebArea'},'childIds':['2','4']},
           {'nodeId':'2','backendDOMNodeId':2,'role':{'value':'group'},'name':{'value':'Product A'},'childIds':['3']},
           {'nodeId':'3','backendDOMNodeId':3,'role':{'value':'button'},'name':{'value':'Buy'}},
           {'nodeId':'4','backendDOMNodeId':4,'role':{'value':'heading'},'name':{'value':'News'}}]
    old=_chain(nodes,nodes[2]);changed=deepcopy(nodes);changed[3]['name']['value']='Updated news'
    assert _chain(changed,changed[2])==old
    for mutation in ('label','identity','state','parent'):
        changed=deepcopy(nodes)
        if mutation=='label':changed[2]['name']['value']='Subscribe'
        elif mutation=='identity':changed[2]['backendDOMNodeId']=999
        elif mutation=='state':changed[2]['properties']=[{'name':'disabled','value':{'value':True}}]
        else:changed[1]['name']['value']='Product B'
        assert _chain(changed,changed[2])!=old

def test_cycle_cannot_authorize_target():
    node={'nodeId':'1','backendDOMNodeId':1,'role':{'value':'button'},'childIds':['1']}
    with pytest.raises(ValueError):_chain([node],node)

def test_structural_marker_churn_preserves_identity_but_not_meaningful_ancestry():
    target={'nodeId':'3','backendDOMNodeId':3,'role':{'value':'button'},'name':{'value':'Buy'}}
    parent={'nodeId':'2','backendDOMNodeId':2,'role':{'value':'generic'},'name':{'value':''},'childIds':['3']}
    native=[parent,target];live=deepcopy(native)
    live[0].update(ignored=True,role={'value':'none'});live[0].pop('name')
    assert _chain(native,target)==_chain(live,live[1])
    live[0]['name']={'value':'New context'}
    assert _chain(native,target)!=_chain(live,live[1])
    live[0].pop('name')
    live[0]['backendDOMNodeId']=99
    assert _chain(native,target)!=_chain(live,live[1])
    live[0].update(backendDOMNodeId=2,ignored=False,role={'value':'region'},name={'value':'Different product'})
    assert _chain(native,target)!=_chain(live,live[1])

def test_deferred_observation_never_claims_empty_page_or_erases_ax_ledger():
    from intent_browser.observation_pipeline import PartialFeedback
    from intent_browser.harness import SemanticFeedback
    from intent_browser.runner import observation_text
    from intent_browser.ax_context import AXContext
    from intent_browser.ax_explorer import AXConfig
    from intent_browser.standard_profile import tokenizer_path
    from tests.test_observation_pipeline import obs
    original=obs();deferred=deepcopy(original)
    deferred['axtree_object']={'nodes':[]}
    deferred['observation_capture']={'coverage':'partial','deferred':True}
    feedback=PartialFeedback(SemanticFeedback())
    result=feedback.after_action(None,feedback.before_action(None,original),deferred)
    assert 'removed_or_changed' not in result
    assert 'contents are unknown' in observation_text(deferred)
    ax=AXContext(AXConfig(tokenizer_path(),incremental=True))
    ax.prepare_observation(original);ax.acknowledge();seen=deepcopy(ax.seen)
    ax.prepare_observation(deferred);ax.acknowledge()
    assert ax.seen==seen
