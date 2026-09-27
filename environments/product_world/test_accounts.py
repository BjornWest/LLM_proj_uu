from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import pytest
from .accounts import generate_accounts,validate_accounts,AccountSession
from .scenario import generate_scenario
from .locations import quote
from .outcomes import evaluate

@pytest.fixture
def sample():
    s=generate_scenario({'family':'laptops','destination_city':'malmo','requirements':1,'hidden':'none','world_preferences':'none'},
      {'seed':42,'models_per_store':1,'store_config':{'stockout_probability':0}},
      {'config':{'home_city_probability':1,'home_country_probability':0}},
      account_options={'seed':42,'config':{'signed_in_probability':1,'coupon_probability':1,'expired_probability':0,'redeemed_probability':0}})
    return s


def test_generation_binding_dates_determinism_and_no_current_stock_mutation(sample):
    a=sample['accounts'];w=sample['bundle'];before=deepcopy(w)
    assert validate_accounts(w,a)['valid']
    assert a==generate_accounts(w,seed=42,config={'signed_in_probability':1,'coupon_probability':1,'expired_probability':0,'redeemed_probability':0})
    session=AccountSession(w,a)
    for row in a['accounts']:
        assert session.orders(row['retailer_id'])==row['orders']
    assert w==before


def controlled(sample,kind='percent',value=25):
    w=sample['bundle'];a=deepcopy(sample['accounts']);o=w['public']['offers'][0];sid=o['retailer_id']
    row=next(x for x in a['accounts'] if x['retailer_id']==sid)
    c=row['coupons'][0];c.update(kind=kind,value=value,minimum_subtotal_minor=0,families=[],valid_from='2026-09-01',valid_until='2026-10-01',redeemed=False)
    base=quote(w,sample['locations'],o['offer_id'])
    assert base['eligible']
    return a,row,c,base


def test_percent_fixed_caps_shipping_not_discounted_and_no_consumption(sample):
    a,row,c,base=controlled(sample);session=AccountSession(sample['bundle'],a);before=session.snapshot()
    q=session.quote(base,c['code']);assert q['discount_minor']==(q['subtotal_minor']*25+50)//100
    assert q['total_minor']==base['total_minor']-q['discount_minor']
    assert q['shipping_minor']==base['shipping_minor']
    assert session.snapshot()==before
    with pytest.raises(ValueError,match='undiscounted'):session.quote(q,c['code'])
    c.update(kind='fixed',value=10**9);q=AccountSession(sample['bundle'],a).quote(base,c['code'])
    assert q['total_minor']==base['shipping_minor']


@pytest.mark.parametrize('change,reason',[
 ({'valid_until':'2026-09-26'},'coupon_not_active'),({'valid_from':'2026-10-01'},'coupon_not_active'),
 ({'redeemed':True},'coupon_already_redeemed'),({'minimum_subtotal_minor':10**9},'coupon_minimum_not_met')])
def test_ineligible_coupons(sample,change,reason):
    a,row,c,base=controlled(sample);c.update(change)
    q=AccountSession(sample['bundle'],a).quote(base,c['code']);assert not q['eligible'] and q['coupon_error']==reason


def test_signed_out_and_other_retailer_order_isolation(sample):
    a,row,c,base=controlled(sample);row['signed_in']=False
    session=AccountSession(sample['bundle'],a);sid=row['retailer_id'];order=row['orders'][0]
    assert session.account(sid)=={'retailer_id':sid,'signed_in':False,'account':None}
    with pytest.raises(PermissionError):session.track(sid,order['order_id'])
    assert session.cancel(sid,order['order_id'])['error']=='sign_in_required'
    assert session.quote(base,c['code'])['coupon_error']=='coupon_sign_in_required'
    other=next(x for x in a['accounts'] if x['retailer_id']!=sid)
    assert session.cancel(other['retailer_id'],order['order_id'])['error']=='order_not_found'


def test_cancellation_processing_only_atomic_idempotent_and_does_not_touch_other_orders(sample):
    a=generate_accounts(sample['bundle'],seed=4,config={'signed_in_probability':1,
        'order_status_weights':{'processing':1,'shipped':0,'delivered':0,'cancelled':0}})
    session=AccountSession(sample['bundle'],a);row=a['accounts'][0];sid=row['retailer_id'];oid=row['orders'][0]['order_id']
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:session.cancel(sid,oid),range(4)))
    assert all(r['ok'] for r in results) and sum(r['changed'] for r in results)==1
    after=session.snapshot();assert len(after['events'])==4
    assert session.track(sid,oid)['status']=='cancelled'
    assert session.orders(sid)[1:]==row['orders'][1:]
    validate_accounts(sample['bundle'],{k:after[k] for k in ('source_world_sha256','as_of','accounts')}|{'schema_version':'shopping-accounts-v1'})
    blocked=generate_accounts(sample['bundle'],config={'signed_in_probability':1,
        'order_status_weights':{'processing':0,'shipped':1,'delivered':0,'cancelled':0}})
    other=AccountSession(sample['bundle'],blocked);r=blocked['accounts'][0]
    before=other.orders(r['retailer_id']);assert other.cancel(r['retailer_id'],r['orders'][0]['order_id'])['error']=='order_not_cancellable'
    assert other.orders(r['retailer_id'])==before


def test_best_quote_is_optional_discount_and_not_a_winner_guarantee(sample):
    a,row,c,base=controlled(sample);session=AccountSession(sample['bundle'],a)
    best=session.best_quote(base);assert best['total_minor']<=base['total_minor']
    assert session.quote(base)['coupon_code'] is None
    result=evaluate(sample)
    assert any(c.get('coupon_code') for c in result['candidates'])
    wrong=deepcopy(a);wrong['source_world_sha256']='wrong'
    with pytest.raises(ValueError):AccountSession(sample['bundle'],wrong)
