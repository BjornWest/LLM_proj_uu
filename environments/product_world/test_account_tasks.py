from copy import deepcopy
import pytest
from .scenario import generate_scenario
from .accounts import AccountSession
from .account_tasks import sample_account_task,reference_account_task,check_account_task
from environments.shopping_intent.world import fingerprint


def fixture(disclosure='none',signed_in=1):
    return generate_scenario({'seed':7,'family':'laptops','destination_city':'malmo','hidden':'none','world_preferences':'none','coupon_disclosure':disclosure},
        {'seed':42,'models_per_store':1},{},account_options={'seed':42,'config':{'signed_in_probability':signed_in,'coupon_probability':1,'expired_probability':0,'redeemed_probability':0}})


@pytest.mark.parametrize('operation',['track','cancel'])
def test_account_tasks_bind_status_and_only_authorized_order_state(operation):
    s=fixture();w=s['bundle'];a=s['accounts'];task=sample_account_task(w,a,operation=operation,seed=7)
    ref=reference_account_task(w,a,task)
    assert check_account_task(w,a,task,ref['answer'],ref['snapshot'])['success']
    bad=deepcopy(ref['snapshot']);bad['accounts'][0]['display_name']='Changed name'
    assert not check_account_task(w,a,task,ref['answer'],bad)['success']
    wrong={**ref['answer'],'order_id':'another'}
    assert not check_account_task(w,a,task,wrong,ref['snapshot'])['success']
    mismatched=deepcopy(a);mismatched['accounts'][0]['signed_in']=False
    with pytest.raises(ValueError,match='another account'):reference_account_task(w,mismatched,task)


def test_signed_out_tracking_and_cancellation_retained_no_rejection_sampling():
    s=fixture(signed_in=0)
    for operation in ('track','cancel'):
        task=sample_account_task(s['bundle'],s['accounts'],operation=operation)
        assert reference_account_task(s['bundle'],s['accounts'],task)['answer']['status']=='sign_in_required'


@pytest.mark.parametrize('disclosure',['request','memory'])
def test_coupon_cues_change_only_task_presentation_not_world_or_optimum(disclosure):
    from .outcomes import evaluate
    hard=fixture();easy=fixture(disclosure)
    assert hard['bundle']==easy['bundle'] and hard['accounts']==easy['accounts']
    assert hard['locations']==easy['locations']
    assert evaluate(hard)==evaluate(easy)
    assert easy['task']['semantic_sha256']==fingerprint(easy['task'])
    assert 'coupon' not in hard['task']['public']['user_message'].lower()
    assert easy['task']['settings']['coupon_disclosure']==disclosure


def test_missing_account_generation_cannot_invent_coupon_memory():
    with pytest.raises(ValueError,match='requires account'):
        generate_scenario({'family':'laptops','coupon_disclosure':'memory'})
