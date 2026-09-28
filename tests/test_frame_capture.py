from copy import deepcopy
from unittest.mock import patch
import pytest
from intent_browser.frame_capture import project_capture,target_document_error,quarantined_documents
from intent_browser.batching import DocumentScanInvalidated


def inputs():
    docs={'page_id':1,'main_frame':'main','frames':{
        'main':{'loader_id':'a','url':'http://main','parent':None},
        'child':{'loader_id':'b','url':'http://child','parent':'main'}}}
    obs={'axtree_object':{'nodes':[
        {'nodeId':'1','frameId':'main','childIds':['2'],'role':{'value':'RootWebArea'}},
        {'nodeId':'2','browsergym_id':'10','childIds':['3'],'role':{'value':'Iframe'}},
        {'nodeId':'3','frameId':'child','childIds':['4'],'role':{'value':'RootWebArea'}},
        {'nodeId':'4','browsergym_id':'11','role':{'value':'button'}}]},
        'dom_object':{'strings':['main','child'],'documents':[
            {'frameId':0,'nodes':{'contentDocumentIndex':{'index':[2],'value':[1]}}},
            {'frameId':1,'nodes':{'contentDocumentIndex':{'index':[],'value':[]}}}]},
        'focused_element_bid':'11'}
    return obs,docs


def test_excludes_changed_child_preserves_unknown_placeholder_and_original():
    obs,before=inputs();original=deepcopy(obs);after=deepcopy(before);after['frames']['child']['loader_id']='c'
    with patch('intent_browser.frame_capture.extract_dom_extra_properties',return_value={}):
        p=project_capture(obs,before,after)
    assert obs==original
    assert [n['nodeId'] for n in p['axtree_object']['nodes']]==['1','2']
    assert 'browsergym_id' not in p['axtree_object']['nodes'][1]
    assert p['dom_object']['documents'][0]['nodes']['contentDocumentIndex']=={'index':[],'value':[]}
    assert p['frame_capture']['omitted_frames']==['child'] and p['frame_capture']['partial']
    assert p['focused_element_bid']==''


def test_main_replacement_never_becomes_partial():
    obs,before=inputs();after=deepcopy(before);after['frames']['main']['loader_id']='changed'
    with pytest.raises(DocumentScanInvalidated):project_capture(obs,before,after)


def test_frames_missing_from_cdp_identity_tree_are_explicitly_unknown():
    obs,before=inputs();before['browser_frame_count']=4
    after=deepcopy(before);after['browser_frame_count']=3
    with patch('intent_browser.frame_capture.extract_dom_extra_properties',return_value={}):
        result=project_capture(obs,before,after)
    coverage=result['frame_capture']
    assert coverage['partial'] and coverage['unresolved_browser_frames']=={'before':2,'after':1}
    assert coverage['omitted_frames']==[]  # Unknown identities are not invented.
    assert coverage['included_frames']==['child','main']
    assert result['axtree_object']==obs['axtree_object']


def test_target_and_ancestor_documents_required():
    obs,before=inputs()
    with patch('intent_browser.frame_capture.extract_dom_extra_properties',return_value={}):p=project_capture(obs,before,before)
    ticket={'frame_capture':p['frame_capture']}
    assert target_document_error(ticket,before,'11') is None
    after=deepcopy(before);after['frames']['main']['loader_id']='changed'
    assert target_document_error(ticket,after,'11')=='target_frame_document_changed'
    assert target_document_error(ticket,before,'999')=='target_not_in_captured_stable_document'


@pytest.mark.parametrize('options', [{'excluded_frames':{'child'}}, {'exclude_children':True}])
def test_native_quarantine_excludes_unchanged_child(options):
    obs,docs=inputs()
    with patch('intent_browser.frame_capture.extract_dom_extra_properties',return_value={}):
        result=project_capture(obs,docs,docs,**options)
    assert result['frame_capture']['included_frames']==['main']
    assert result['frame_capture']['native_exclusions']
    assert '11' not in result['frame_capture']['bid_frames']


def test_quarantine_owner_lookup_fails_closed_when_unmapped():
    obs,_=inputs()
    obs['dom_object']['strings']+=['bid','owner']
    obs['dom_object']['documents'][0]['nodes']['attributes']=[[],[],[2,3]]
    assert quarantined_documents(obs,['owner'])==({'child'},False)
    assert quarantined_documents(obs,['owner','missing'])==({'child'},True)


def test_quarantined_ancestor_excludes_stable_grandchild():
    obs,docs=inputs()
    docs['frames']['grandchild']={'loader_id':'c','url':'http://grandchild','parent':'child'}
    obs['axtree_object']['nodes']+=[{'nodeId':'5','frameId':'grandchild','browsergym_id':'12'}]
    with patch('intent_browser.frame_capture.extract_dom_extra_properties',return_value={}):
        result=project_capture(obs,docs,docs,excluded_frames={'child'})
    assert result['frame_capture']['included_frames']==['main']
    assert result['frame_capture']['omitted_frames']==['child','grandchild']
