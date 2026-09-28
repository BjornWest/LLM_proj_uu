import concurrent.futures
import http.cookiejar
import urllib.request
import urllib.error
import pytest
from environments.site_verification import sample,validate,Gate
from environments.connected_shopping.http import Site


def spec(**changes):
    row=sample(['comparison-general-a'],probability=1)['sites'][0]
    return {**row,'trigger':'entry',**changes}


def cookie_for(header):
    return header.split(';')[0]


def pending(gate):
    state=gate.snapshot()['sessions']
    sid=next(reversed(state))
    return sid,state[sid]['challenge_id']


def test_sampling_order_isolation_and_comparator_binding():
    a=sample(['a','b'],seed=12)
    assert a==sample(['b','a'],seed=12)
    assert a['sites'][0]==sample(['a'],seed=12)['sites'][0]
    assert not any(r['enabled'] for r in sample(['a','b'],probability=0)['sites'])
    assert all(r['enabled'] for r in sample(['a','b'],probability=1)['sites'])
    validate(a,['a','b'])
    with pytest.raises(ValueError):validate(a,['retailer'])
    with pytest.raises(ValueError):sample(['a'],probability=float('nan'))
    patterns={(r['style'],r['trigger']) for seed in range(40) for r in sample(['a'],seed=seed)['sites']}
    assert len(patterns)==4


def test_gate_requires_private_clearance_and_isolates_sessions():
    g=Gate(spec())
    body,cookie=g.begin(None,'/products/secret')
    assert 'Verify you are human' in body and 'secret' not in body.replace('/products/secret','')
    sid,cid=pending(g)
    assert not g.resolve(sid,'wrong')
    assert not g.resolve('wrong',cid)
    assert g.begin(cookie_for(cookie),'/other')[0]
    assert g.resolve(sid,cid)
    assert g.resolve(sid,cid) # idempotent, exactly one event
    assert len([e for e in g.events if e['event']=='user_completed'])==1
    assert g.begin(cookie_for(cookie),'/other')[0] is None
    assert g.begin(None,'/other')[0]
    other=Gate(spec())
    assert not other.resolve(sid,cid)
    assert other.begin(cookie_for(cookie),'/other')[0]


def test_expiry_cancel_reset_and_stale_completion():
    now=[0.]
    g=Gate(spec(challenge_ttl_seconds=5,clearance_ttl_seconds=10),clock=lambda:now[0])
    _,cookie=g.begin(None,'/')
    sid,cid=pending(g)
    now[0]=5
    assert not g.resolve(sid,cid)
    assert g.begin(cookie_for(cookie),'/')[0]
    _,new=pending(g)
    assert cid!=new and not g.resolve(sid,cid)
    assert g.resolve(sid,new,decision='cancel')
    assert not g.resolve(sid,new)
    g.begin(cookie_for(cookie),'/');_,new=pending(g)
    assert g.resolve(sid,new)
    now[0]=15
    assert g.begin(cookie_for(cookie),'/')[0]
    g.reset()
    assert not g.resolve(sid,new)
    assert g.begin(cookie_for(cookie),'/')[0]


def test_discovery_and_disabled():
    g=Gate(spec(trigger='discovery'))
    body,cookie=g.begin(None,'/')
    assert body is None
    assert g.begin(cookie_for(cookie),'/search')[0]
    assert g.begin(cookie_for(cookie),'/')[0] # active gate covers home, too
    g=Gate(spec(enabled=False))
    assert g.begin(None,'/search')==(None,None)
    assert not g.snapshot()['sessions']


def test_concurrent_completion_only_once():
    g=Gate(spec());g.begin(None,'/');sid,cid=pending(g)
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        assert all(pool.map(lambda _:g.resolve(sid,cid),range(30)))
    assert sum(e['event']=='user_completed' for e in g.events)==1


def fetch(opener,url,data=None):
    try:r=opener.open(url,data=data)
    except urllib.error.HTTPError as e:r=e
    return r.status,r.read().decode()


@pytest.mark.parametrize('style',['interstitial','embedded'])
def test_http_no_hidden_catalog_or_public_completion(style):
    calls=[];g=Gate(spec(style=style))
    def renderer(path,q,raw):
        calls.append(path)
        return 200,'<html><body><h1>Private offer 987</h1></body></html>'
    jar=http.cookiejar.CookieJar();client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    with Site(renderer,verification=g) as site:
        status,body=fetch(client,site.origin+'/products/x?colour=red')
        assert status==403 and 'Private offer' not in body and not calls
        assert '/products/x?colour=red' in body
        assert fetch(client,site.origin+'/complete',b'complete')[0]==403
        assert fetch(client,site.origin+'/')[0]==403 and not calls
        assert g.resolve(*pending(g))
        assert fetch(client,site.origin+'/products/x?colour=red')==(200,'<html><body><h1>Private offer 987</h1></body></html>')
        assert calls==['/products/x']
        assert fetch(urllib.request.build_opener(),site.origin+'/products/x')[0]==403


def test_default_site_unchanged():
    with Site(lambda *args:(200,'ordinary')) as site:
        assert fetch(urllib.request.build_opener(),site.origin+'/')==(200,'ordinary')


def test_gate_and_consent_keep_separate_cookies():
    from environments.site_consent.runtime import design_for
    g=Gate(spec(trigger='discovery'))
    jar=http.cookiejar.CookieJar();client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    with Site(lambda *args:(200,'<html><body>Offers</body></html>'),verification=g,consent_design=design_for(42,'comparison-general-a')) as site:
        assert fetch(client,site.origin+'/')[0]==200
        assert len(list(jar))==2
        assert fetch(client,site.origin+'/search')[0]==403
        assert fetch(client,site.origin+'/_consent/choose',b'{}')[0]==403
        assert g.resolve(*pending(g))
        assert fetch(client,site.origin+'/search')[0]==200
        assert len(list(jar))==2
