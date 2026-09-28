from copy import deepcopy
import pytest
from .runtime import ConsentUI,DESIGNS,PURPOSES,design_for


def request(state,action='save',**prefs):
    return {'csrf':state['csrf'],'revision':state['revision'],'action':action,'preferences':{p:prefs.get(p,False) for p in PURPOSES}}


def test_session_choices_and_revision_conflict():
    ui=ConsentUI('center-modal');a,cookie=ui.begin(None)
    assert a['choice'] is None and not any(a['preferences'].values())
    status,r=ui.commit(cookie,request(a,'accept'));assert status==200 and all(r['preferences'].values())
    assert ui.commit(cookie,request(a,'reject'))[0]==409
    b,new=ui.begin(cookie);assert new is None and b['revision']==1
    status,r=ui.commit(cookie,request(b,marketing=True));assert status==200 and r['preferences']=={'analytics':False,'personalisation':False,'marketing':True}
    b,_=ui.begin(cookie);status,r=ui.commit(cookie,request(b,'reject',marketing=True));assert status==200 and not any(r['preferences'].values())
    state=ui.snapshot()['sessions'][a['session_id']];assert [e['action'] for e in state['events']]==['accept','save','reject']
    assert 'csrf' not in state


def test_browser_and_runtime_isolation():
    first=ConsentUI('side-drawer');second=ConsentUI('side-drawer')
    a,cookie=first.begin(None);b,othercookie=first.begin(None)
    assert first.commit(othercookie,request(a,'accept'))[0]==403
    assert second.commit(cookie,request(a,'accept'))[0]==403
    assert first.commit(cookie,request(a,'accept'))[0]==200
    assert first.begin(othercookie)[0]['choice'] is None
    assert second.begin(cookie)[0]['choice'] is None
    snapshot=first.snapshot();snapshot['sessions'].clear();assert first.snapshot()['sessions']


@pytest.mark.parametrize('change',[{'revision':True},{'action':'other'},{'preferences':{'analytics':True}},{'preferences':dict.fromkeys(PURPOSES,1)},{'csrf':'wrong'},{'extra':'x'}])
def test_invalid_request_does_not_mutate(change):
    ui=ConsentUI('bottom-banner');state,cookie=ui.begin(None);before=ui.snapshot()
    body=request(state);body.update(change)
    assert ui.commit(cookie,body)[0] in (400,403,409)
    assert ui.snapshot()==before


def test_independent_seed_stream_and_markup():
    assert {design_for(seed,'a') for seed in range(30)}==set(DESIGNS)
    for d in DESIGNS:
        ui=ConsentUI(d);state,_=ui.begin(None);markup=ui.markup(state)
        assert 'private_provenance' not in markup and 'consent-preferences' in markup
        assert 'data-decided="false"' in markup
        assert ('role="switch"' in markup)==(d=='center-modal')
        assert ('Reject optional cookies' in markup)==(d=='side-drawer')


def test_http_boundary_and_disabled_default():
    import json
    from urllib.request import build_opener,HTTPCookieProcessor,Request,urlopen
    from urllib.error import HTTPError
    from http.cookiejar import CookieJar
    from environments.product_review_sites.runtime import Runtime
    from environments.product_world.generator import generate_catalog
    from environments.product_review_sites.generate import generate_reviews
    public=generate_reviews(generate_catalog(seed=1,model_count=1,model_families=['footwear']))['public']
    with Runtime(public) as rt:
        assert 'consent-ui' not in urlopen(rt.origin).read().decode()
        with pytest.raises(HTTPError) as exc:urlopen(rt.origin+'/_consent/ui.js')
        assert exc.value.code==404
    with Runtime(public,consent_design='bottom-banner') as rt:
        op=build_opener(HTTPCookieProcessor(CookieJar()))
        with op.open(rt.origin) as response:
            assert "script-src 'self'" in response.headers['Content-Security-Policy']
            assert 'HttpOnly' in response.headers['Set-Cookie']
            assert 'consent-ui' in response.read().decode()
        state=next(iter(rt.consent._sessions.values())) # Privileged test setup only.
        payload=request(state,'accept')
        headers={'Content-Type':'application/json','Origin':'https://unrelated.invalid'}
        with pytest.raises(HTTPError) as exc:op.open(Request(rt.origin+'/_consent/choose',data=json.dumps(payload).encode(),headers=headers))
        assert exc.value.code==403 and state['revision']==0
        headers['Origin']=rt.origin
        assert json.loads(op.open(Request(rt.origin+'/_consent/choose',data=json.dumps(payload).encode(),headers=headers)).read())['revision']==1
        assert op.open(rt.origin+'/_consent/ui.js').headers.get_content_type()=='text/javascript'
        with pytest.raises(HTTPError) as exc:op.open(rt.origin+'/_consent/state')
        assert exc.value.code==404
