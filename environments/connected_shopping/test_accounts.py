"""HTTP integration of real account rules, isolated stores/worlds and explicit forms."""
from copy import deepcopy
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from urllib.parse import urlencode
import json
import pytest
from environments.product_world.accounts import generate_accounts
from environments.product_world.scenario import generate_scenario
from .runtime import Runtime
from .conformance import Document


def account_scenario():
    s=generate_scenario({'family':'footwear','destination_city':'malmo','hidden':'none'},
        {'seed':42,'models_per_store':1,'store_config':{'stockout_probability':0}}, {})
    s['accounts']=generate_accounts(s['bundle'],config={'signed_in_probability':1,'coupon_probability':1,'expired_probability':0,'redeemed_probability':0,'orders_per_account':1,'order_status_weights':{'processing':1,'shipped':0,'delivered':0,'cancelled':0}})
    # Explicit authored UI contract cases, not a retained random generation draw.
    c=s['accounts']['accounts'][0]['coupons'][0]
    c.update(families=[],minimum_subtotal_minor=0,kind='percent',value=10)
    s['accounts']['accounts'][-1]['signed_in']=False
    return s


def get(rt,sid,path):return urlopen(rt.origins[sid]+path).read().decode()
def post(rt,sid,oid,token,**extra):
    return urlopen(Request(rt.origins[sid]+'/account/orders/'+oid+'/cancel',data=urlencode({'token':token,'confirm':'yes',**extra}).encode(),headers={'Content-Type':'application/x-www-form-urlencoded'}))


def token(rt,sid,oid):
    return Document(get(rt,sid,'/account/orders/'+oid+'/cancel')).root.one('input',name='token').attrs['value']


@pytest.fixture
def rt():
    with Runtime(account_scenario(),consent=False) as x:yield x


def test_account_navigation_tracking_and_no_index_leak(rt):
    a=rt.account_pages.session.account('store-001')['account'];order=a['orders'][0]
    assert 'My account' in get(rt,'store-001','/')
    assert a['coupons'][0]['code'] in get(rt,'store-001','/account/coupons')
    html=get(rt,'store-001','/account/orders/'+order['order_id'])
    assert order['lines'][0]['product_id'] in html and 'Tracking history' in html
    assert 'Confirm cancellation' in get(rt,'store-001','/account/orders/'+order['order_id']+'/cancel')
    assert rt.account_pages.session.track('store-001',order['order_id'])['status']=='processing'
    assert not rt.snapshot()['commerce_mutations']
    public=json.dumps(rt.public_manifest)+json.dumps(rt.documents)+get(rt,'aggregator','/')
    assert a['coupons'][0]['code'] not in public and order['order_id'] not in public


def test_signed_out_and_cross_store_access(rt):
    oid=rt.account_pages.session.orders('store-001')[0]['order_id']
    for path in ('/account','/account/coupons','/account/orders','/account/orders/'+oid):
        html=get(rt,'store-006',path)
        assert 'not signed in' in html and oid not in html
        assert 'SAVE' not in html and 'Tracking history' not in html
    with pytest.raises(HTTPError) as e:get(rt,'store-002','/account/orders/'+oid)
    assert e.value.code==404


def test_cancel_requires_form_and_is_idempotent(rt):
    oid=rt.account_pages.session.orders('store-001')[0]['order_id'];t=token(rt,'store-001',oid)
    for wrong in ('bogus',rt.account_pages.tokens['store-002']):
        with pytest.raises(HTTPError) as e:post(rt,'store-001',oid,wrong)
        assert e.value.code==403
    assert not rt.snapshot()['commerce_mutations']
    assert post(rt,'store-001',oid,t).status==200
    assert 'already cancelled' in post(rt,'store-001',oid,t).read().decode()
    snap=rt.snapshot();assert len(snap['commerce_mutations'])==1
    assert next(o for o in snap['orders'] if o['order_id']==oid)['status']=='cancelled'
    assert len(rt.account_pages.session.track('store-001',oid)['tracking_events'])==2
    with pytest.raises(HTTPError) as e:post(rt,'store-002',oid,rt.account_pages.tokens['store-002'])
    assert e.value.code==409 and len(rt.snapshot()['commerce_mutations'])==1


def test_coupon_totals_use_product_engine_and_do_not_auto_apply(rt):
    sid='store-001';o=next(o for o in rt.offers.values() if o['retailer_id']==sid)
    c=rt.account_pages.session.account(sid)['account']['coupons'][0];before=rt.account_pages.session.snapshot()
    base=rt.quote(o['offer_id']);expected=rt.account_pages.session.quote(base,c['code'])
    params={'offer_id':o['offer_id'],'coupon_code':c['code']}
    root=Document(get(rt,sid,'/quote?'+urlencode(params))).root
    assert root.one(id='delivered-total').text()==f"{expected['total_minor']/100:.2f} SEK"
    assert f"{expected['discount_minor']/100:.2f} SEK" in root.one(id='coupon-discount').text()
    assert rt.quote(o['offer_id'])==base
    invalid=Document(get(rt,sid,'/quote?'+urlencode({**params,'coupon_code':'INVALID'}))).root
    assert invalid.one(id='delivered-total').text()=='Unavailable'
    assert rt.account_pages.session.snapshot()==before


def test_fresh_runtime_isolated_and_preserves_input():
    s=account_scenario();initial=deepcopy(s)
    with Runtime(s,consent=False) as a,Runtime(s,consent=False) as b:
        oid=a.account_pages.session.orders('store-001')[0]['order_id']
        post(a,'store-001',oid,token(a,'store-001',oid))
        assert b.account_pages.session.track('store-001',oid)['status']=='processing'
        with pytest.raises(HTTPError) as e:post(b,'store-001',oid,a.account_pages.tokens['store-001'])
        assert e.value.code==403
    assert s==initial


def test_shipped_and_signed_out_posts_fail_without_state_change():
    s=account_scenario()
    s['accounts']=generate_accounts(s['bundle'],config={'signed_in_probability':1,'order_status_weights':{'processing':0,'shipped':1,'delivered':0,'cancelled':0}})
    s['accounts']['accounts'][-1]['signed_in']=False
    with Runtime(s,consent=False) as rt:
        for account in (s['accounts']['accounts'][0],s['accounts']['accounts'][-1]):
            sid=account['retailer_id'];oid=account['orders'][0]['order_id']
            with pytest.raises(HTTPError) as e:post(rt,sid,oid,rt.account_pages.tokens[sid])
            assert e.value.code==409
        snap=rt.snapshot()
        assert not snap['commerce_mutations']
        assert [e['error'] for e in snap['accounts']['events']]==['order_not_cancellable','sign_in_required']
