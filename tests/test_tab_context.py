from copy import deepcopy
from dataclasses import replace
from intent_browser.tab_context import TabContext
from intent_browser.open_internet import open_profile, with_human_handover, HUMAN_VERIFICATION_TEST_POLICY
from intent_browser.harness import native_tools_profile


def snapshot():
    return {'active_tab_id':'tab-1','revision':1,'tabs':[{'tab_id':'tab-1','state':'agent_controlled',
        'title':'One','url':'https://example.test','reason':None,'handover_id':None}],
        'recent_transitions':[{'sequence':1,'event':'registered','tab_id':'tab-1'}]}


def test_render_does_not_commit_undelivered_state():
    c=TabContext();s=snapshot();c.commit(s)
    other=deepcopy(s);other['tabs'][0]['title']='Not delivered'
    assert c.project(other)['kind']=='delta'
    assert c.project(s)['kind']=='unchanged'
    assert c.project(s).get('events') is None


def test_field_deltas_cycle_and_cancellation():
    c=TabContext();s=snapshot();c.commit(s)
    s['tabs'][0].update(state='awaiting_human',reason='Very long request '*100,handover_id='handover-2')
    c.commit(s)
    s['tabs'][0]['state']='returned';s['recent_transitions'].append({'sequence':3,'event':'cancel','tab_id':'tab-1'})
    p=c.project(s)
    assert p['set']=={'tab-1':{'state':'returned'}}
    assert p['events'][0]['event']=='cancel'
    c.commit(s)
    assert c.project(s)['kind']=='unchanged'


def test_same_revision_active_change_and_removed():
    c=TabContext();s=snapshot();c.commit(s)
    s['active_tab_id']='tab-2';s['tabs']=[dict(s['tabs'][0],tab_id='tab-2')]
    p=c.project(s)
    assert p['active_tab_id']=='tab-2' and p['removed']==['tab-1']
    assert p['id']!=p['base']


def test_profile_defaults_unchanged_and_wait_consistent():
    p=open_profile(native_tools_profile())
    p=replace(p,tools=replace(p.tools,batch_size=4))
    old=with_human_handover(p)
    assert with_human_handover(p,wait_for_human=False,compact_tabs=False)==old
    new=with_human_handover(p,wait_for_human=True,compact_tabs=True)
    assert HUMAN_VERIFICATION_TEST_POLICY in old.instructions
    assert HUMAN_VERIFICATION_TEST_POLICY not in new.instructions
    assert 'then continue in another tab' not in new.instructions
    assert 'Do not open another tab' in new.instructions
    defs={x['function']['name']:x['function'] for x in new.tools.definitions()}
    assert 'Blocks until' in defs['handover_tab']['description']
    assert 'Unavailable' in defs['new_tab']['description']
    assert set(defs)=={x['function']['name'] for x in old.tools.definitions()}
    assert new.tools.definitions()==deepcopy(new.tools.definitions())


def test_wait_runtime_rejects_switch_close_and_creation():
    from intent_browser.human_browser import HumanBrowser
    from types import SimpleNamespace
    browser=object.__new__(HumanBrowser)
    browser.sync=lambda:None
    browser.wait_for_human=True;browser.active='tab-1'
    for name,args in [('new_tab',{}),('tab_close',{}),('tab_focus',{'tab_id':'tab-2'}),
                      ('handover_tab',{'tab_id':'tab-2','reason':'Help'})]:
        result=browser.execute(SimpleNamespace(name=name,arguments=args))
        assert result['execution']=='not_executed'
