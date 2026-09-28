from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock,patch
import json

import pytest
from intent_browser.actions import Decision
from intent_browser.human_browser import HumanBrowser,ax_digest
from intent_browser.tab_changes import change_report,preview,target_identity
from intent_browser.native_tools import NativeBrowserTools
from intent_browser.open_internet import with_human_handover,open_profile
from intent_browser.harness import native_tools_profile
from intent_browser.backend import Completion
from dataclasses import replace


def node(i,role,name,children=(),**extra):
    return {'nodeId':str(i),'backendDOMNodeId':i,'browsergym_id':str(i),'ignored':False,
        'role':{'value':role},'name':{'value':name},'childIds':list(map(str,children)),**extra}


def observation():
    return {'axtree_object':{'nodes':[node(1,'RootWebArea','Store',(2,5)),
        node(2,'form','Checkout',(3,4)),node(3,'button','Buy'),node(4,'StaticText','Price 100'),
        node(5,'complementary','Cart',(6,)),node(6,'StaticText','Total 100')]},
        'human_tabs':{'active_tab_id':'tab-1'}}


def manager(tmp_path,old):
    m=HumanBrowser.__new__(HumanBrowser)
    m.stable_frames=False
    m.active='tab-1';m.env=object();m.sync=lambda:None
    m.states=lambda:{'tab-1':{'state':'agent_controlled','handover_id':None}}
    m.trace=Mock();m.trace.directory=tmp_path
    m.observations={1:deepcopy(old['axtree_object'])};m.confirmations={};m.confirmation_sequence=0
    return m


def ticket(old):
    return {'tab_id':'tab-1','handover_id':None,'document':['doc'],'ax_sha256':ax_digest(old),'capture_id':1}


def test_locations_do_not_assert_distant_total_irrelevant():
    old=observation();new=deepcopy(old)
    for i,label in [(2,'Buy now'),(3,'Price 110'),(5,'Total 110')]:new['axtree_object']['nodes'][i]['name']['value']=label
    r=change_report(old,new,Decision('click',{'bid':'3'},"click(bid='3')"))
    assert [c['relationship'] for c in r['changes']]==['target','same_section','elsewhere']
    assert r['changes'][-1]['decision_relevance']=='requires_agent_review'
    assert r['changes'][-1]['after']['location'][-1]['name']=='Cart'
    assert 'Total 110' in json.dumps(preview(r))
    assert 'backendDOMNodeId' not in json.dumps(preview(r))


def test_identity_rejects_replacement_and_disabled_but_allows_content():
    old=observation();new=deepcopy(old)
    new['axtree_object']['nodes'][2]['name']['value']='Buy now'
    assert target_identity(old,'3')==target_identity(new,'3')
    new['axtree_object']['nodes'][2]['backendDOMNodeId']=999
    assert target_identity(old,'3')!=target_identity(new,'3')
    new=deepcopy(old);new['axtree_object']['nodes'][2]['properties']=[{'name':'disabled','value':{'value':True}}]
    assert target_identity(new,'3') is None


def test_confirmation_is_exact_consumed_and_does_not_loop(tmp_path):
    old=observation();new=deepcopy(old);new['axtree_object']['nodes'][5]['name']['value']='Total 110'
    m=manager(tmp_path,old);d=Decision('click',{'bid':'3'},"click(bid='3')")
    result=m.content_review(ticket(old),new,d,step=4,call_id='original')
    cid=result['confirmation']['confirmation_id'];item=m.take_confirmation(cid)
    assert item['decision']==d and item['tool_call_id']=='original'
    assert m.take_confirmation(cid) is None
    new['axtree_object']['nodes'][5]['name']['value']='Total 120'
    with patch('intent_browser.human_browser.document_signature',return_value=['doc']):
        assert m.confirmation_guard(item,new) is None
        m.states=lambda:{'tab-1':{'state':'human_active','handover_id':None}}
        assert m.confirmation_guard(item,new)=='tab_ownership_or_target_changed'
    with patch('intent_browser.human_browser.document_signature',return_value=['different']):
        m.states=lambda:{'tab-1':{'state':'agent_controlled','handover_id':None}}
        assert m.confirmation_guard(item,new)=='tab_document_changed'


def test_invalid_target_never_gets_confirmation(tmp_path):
    old=observation();new=deepcopy(old);new['axtree_object']['nodes'][2]['backendDOMNodeId']=999
    m=manager(tmp_path,old)
    r=m.content_review(ticket(old),new,Decision('click',{'bid':'3'},"click(bid='3')"),step=0,call_id='a')
    assert r['reason']=='target_removed_replaced_or_disabled' and 'confirmation' not in r


def test_only_latest_confirmation_and_preview_bounds(tmp_path):
    old=observation();new=deepcopy(old);new['axtree_object']['nodes'][5]['name']['value']='Total 120'
    m=manager(tmp_path,old);d=Decision('click',{'bid':'3'},"click(bid='3')")
    a=m.content_review(ticket(old),new,d,step=0,call_id='a')['confirmation']['confirmation_id']
    b=m.content_review(ticket(old),new,d,step=1,call_id='b')['confirmation']['confirmation_id']
    assert m.take_confirmation(a) is None and m.take_confirmation(b) is not None
    report={'change_count':20,'changes':[{'after':{'name':'x'*1000}}]*20}
    p=preview(report);assert len(p['changes'])==6 and p['omitted_changes']==14
    assert len(p['changes'][0]['after']['name'])<240


def test_schema_fixed_opt_in_and_standalone():
    base=native_tools_profile();profile=with_human_handover(open_profile(replace(base,tools=replace(base.tools,batch_size=4))))
    tools=profile.tools
    assert 'proceed_action' in profile.describe()['tools']
    assert 'proceed_action' not in [d['function']['name'] for d in base.tools.definitions()]
    raw={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,'tool_calls':[
        {'id':'a','type':'function','function':{'name':'proceed_action','arguments':'{"confirmation_id":"proceed-1"}'}}]}}]}
    decisions,_=tools.parse_batch(Completion('',raw));assert decisions[0].name=='proceed_action'
    raw['choices'][0]['message']['tool_calls'].append({'id':'b','type':'function','function':{'name':'noop','arguments':'{}'}})
    with pytest.raises(ValueError,match='only call'):tools.parse_batch(Completion('',raw))
