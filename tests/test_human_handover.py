import json,re
from concurrent.futures import ThreadPoolExecutor
import pytest,httpx
from intent_browser.human_handover import HumanHandoverController,HandoverConflict
from intent_browser.human_handover_ui import HumanHandoverUI


def registered(**kwargs):
    c=HumanHandoverController(**kwargs);c.register('tab-a',title='Shop',url='https://shop.example/');return c


def test_ordered_lifecycle_requires_explicit_fresh_resume(tmp_path):
    c=registered(journal_path=tmp_path/'human.jsonl');c.handover('tab-a','Please complete verification')
    c.signal('tab-a','start');c.signal('tab-a','complete')
    assert c.snapshot()['tabs'][0]['state']=='returned'
    c.resume('tab-a');c.close('tab-a')
    events=c.drain();assert [e['sequence'] for e in events]==list(range(1,7))
    assert [e['actor'] for e in events]==['browser','agent','human','human','browser','browser']
    assert [json.loads(l) for l in (tmp_path/'human.jsonl').read_text().splitlines()]==events
    assert c.drain()==[]
    assert not any('success' in e or 'verified' in e for e in events)
    with pytest.raises(HandoverConflict):c.register('tab-a',title='Another',url='https://other.example/')


@pytest.mark.parametrize('state,event',[('agent_controlled','start'),('awaiting_human','complete'),('human_active','start'),('returned','complete'),('closed','cancel')])
def test_invalid_transition_does_not_mutate(state,event):
    c=registered()
    if state!='agent_controlled':c.handover('tab-a','Help')
    if state in ('human_active','returned'):c.signal('tab-a','start')
    if state=='returned':c.signal('tab-a','complete')
    if state=='closed':c.close('tab-a')
    before=c.snapshot()
    with pytest.raises(HandoverConflict):c.signal('tab-a',event)
    assert c.snapshot()==before


def test_cancel_is_a_return_not_verification_and_stale_cycle_is_rejected():
    c=registered();first=c.handover('tab-a','Help')['handover_id']
    c.signal('tab-a','cancel',handover_id=first);c.resume('tab-a')
    second=c.handover('tab-a','Help again')['handover_id'];assert first!=second
    with pytest.raises(HandoverConflict):c.signal('tab-a','start',handover_id=first)
    c.signal('tab-a','start',handover_id=second)
    assert c.snapshot()['tabs'][0]['state']=='human_active'


def test_concurrent_duplicate_signals_accept_once():
    c=registered();c.handover('tab-a','Help')
    def attempt(_):
        try:c.signal('tab-a','start');return True
        except HandoverConflict:return False
    with ThreadPoolExecutor(max_workers=8) as pool:assert sum(pool.map(attempt,range(24)))==1
    assert c.snapshot()['revision']==3


def test_other_tabs_remain_independent_and_snapshots_detached():
    c=registered();c.register('tab-b',title='Other',url='https://other.example/');c.handover('tab-a','Help')
    snap=c.snapshot();snap['tabs'][1]['state']='closed'
    c.signal('tab-a','start');c.register('tab-b',title='Other results',url='https://other.example/search?q=headphones')
    assert c.snapshot()['tabs'][1]['state']=='agent_controlled'
    c.close('tab-a')
    with pytest.raises(HandoverConflict):c.signal('tab-a','complete')


def test_display_redacts_auth_and_never_overwrites_journal(tmp_path):
    path=tmp_path/'events.jsonl';c=registered(journal_path=path)
    c.register('tab-a',title='Shop',url='https://shop.example/?q=shoes&access_token=secret#token')
    assert 'secret' not in json.dumps(c.snapshot()) and 'secret' not in path.read_text()
    assert 'q=shoes' in c.snapshot()['tabs'][0]['url']
    with pytest.raises(ValueError):c.register('tab-b',title='Bad',url='https://name:password@example.com/')
    before=path.read_bytes()
    with pytest.raises(FileExistsError):HumanHandoverController(journal_path=path)
    assert path.read_bytes()==before


def test_journal_failure_is_closed_without_state_acceptance(tmp_path):
    path=tmp_path/'events.jsonl';c=registered(journal_path=path);path.unlink();path.mkdir()
    with pytest.raises(OSError):c.handover('tab-a','Help')
    assert not c.snapshot()['available'] and c.snapshot()['tabs'][0]['state']=='agent_controlled'
    with pytest.raises(RuntimeError):c.handover('tab-a','Again')


def test_local_http_signal_auth_origin_fence_and_ui_escaping():
    c=registered();c.register('tab-a',title='<img src=x onerror=alert(1)>',url='https://shop.example/')
    current=c.handover('tab-a','Help')['handover_id']
    with HumanHandoverUI(c) as ui,httpx.Client(base_url=ui.origin,trust_env=False) as client:
        page=client.get('/');assert page.status_code==200
        assert '<img src=x' not in page.text and 'textContent=value' in page.text
        token=re.search("const token='([^']+)'",page.text).group(1)
        headers={'Origin':ui.origin,'X-Handover-Token':token}
        body={'tab_id':'tab-a','event':'start','handover_id':current}
        assert client.post('/signal',json=body).status_code==403
        assert client.post('/signal',headers={**headers,'Origin':'https://foreign.example'},json=body).status_code==403
        assert client.get('/state',headers={'Host':'foreign.example'}).status_code==403
        assert client.post('/signal',headers=headers,json={**body,'handover_id':'old'}).status_code==409
        assert client.post('/signal',headers=headers,json=body).status_code==200
        assert client.post('/signal',headers=headers,json=body).status_code==409
        assert client.post('/signal',headers=headers,json={**body,'event':'complete'}).status_code==200
        assert client.get('/state').json()['tabs'][0]['state']=='returned'
        assert token not in json.dumps(c.drain())


def test_embedded_endpoint_requires_capability_not_just_opaque_origin():
    c=registered();hid=c.handover('tab-a','Help')['handover_id']
    with HumanHandoverUI(c) as ui,httpx.Client(base_url=ui.origin,trust_env=False) as client:
        auth={'Origin':'null','X-Handover-Token':ui._embed_token}
        assert client.get('/_embedded/state',headers={'Origin':'null'}).status_code==403
        assert client.get('/_embedded/state',headers={**auth,'Origin':'https://retailer.example'}).status_code==403
        assert client.get('/_embedded/state',headers={**auth,'X-Handover-Token':ui._token}).status_code==403
        state=client.get('/_embedded/state',headers=auth)
        assert state.status_code==200 and state.headers['access-control-allow-origin']=='null'
        assert ui._embed_token not in state.text
        response=client.post('/_embedded/signal',headers=auth,json={'tab_id':'tab-a','event':'start','handover_id':hid})
        assert response.status_code==200 and response.headers['access-control-allow-origin']=='null'
        assert client.post('/signal',headers=auth,json={}).status_code==403
        assert 'access-control-allow-origin' not in client.get('/state',headers=auth).headers
        preflight={'Origin':'null','Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'content-type,x-handover-token'}
        assert client.options('/_embedded/signal',headers=preflight).status_code==204
        assert client.options('/signal',headers=preflight).status_code==403
        assert client.options('/_embedded/signal',headers={**preflight,'Origin':'https://retailer.example'}).status_code==403
        assert client.options('/_embedded/signal',headers={**preflight,'Access-Control-Request-Headers':'x-extra'}).status_code==403
