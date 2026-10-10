"""Authored finite state controls; no world generation or live effect claims."""
from copy import deepcopy
import json

import pytest
from experiments.footwear_world_pilot.test_basket_quote import world
from .test_catalog_cart_task import fixture as cart_fixture,state,capsule
from . import catalog_checkout_details_task as task,catalog_checkout_details_grading as grading
from . import catalog_checkout_details_generation as generation
from .adapter import digest


def fixture(world,*,initial_cart='preserve'):
    w,cart,d,oldref,b=cart_fixture(world,initial_cart=initial_cart)
    spec={'kind':task.KIND,'requirements':cart['requirements'],'initial_cart':initial_cart,
          'delivery_note':'Please ring the doorbell twice.'}
    t=task.make(w,spec,checkout_domain=d);r=task.reference(w,t,checkout_domain=d)
    return w,t,d,r,b


def address(t):
    a=t['delivery_address']
    return {'name':a['recipient'],'street':a['street']+' '+a['house_number'],
            'unit':a['unit'],'postcode':a['postcode'],'city':a['city']}


def prepared(values,*,initial=None,quantity=2):
    w,t,d,r,b=values;oid=w['retailers'][0]['offers'][-1]['offer_id']
    before=state(w,initial or {});after=state(w,{**(initial or {}),oid:(initial or {}).get(oid,0)+quantity})
    after.update(address=address(t),remembered=address(t),instructions=t['delivery_note'],addressStatus='valid')
    return before,after


def grade(values,before,after,*,completed=True,journal=None):
    w,t,d,r,b=values;c=capsule(w,t,b,before,after,journal=journal)
    return grading.grade(w,t,r,checkout_domain=d,binding=b,capsule=c,
        episode_id='authored-episode',main_trace_sha256='a'*64,policy_completed=completed)


def test_actual_saved_details_and_two_new_units_pass(world):
    values=fixture(world);before,after=prepared(values)
    assert grade(values,before,after)['verdict']=='pass'
    t=values[1]
    assert t['delivery_note'] not in t['user_message'] and len(t['memories'])==2
    assert 'These items are for me' in t['user_message']
    assert t['memories'][1].endswith(t['delivery_note'])


@pytest.mark.parametrize('case',['note_missing','note_changed','address_unsaved','wrong_recipient','wrong_postcode','wrong_house','wrong_unit','remembered_wrong'])
def test_wrong_or_unsaved_details_fail_despite_matching_cart(world,case):
    values=fixture(world);before,after=prepared(values)
    if case=='note_missing':after['instructions']=''
    elif case=='note_changed':after['instructions']='Something different'
    elif case=='address_unsaved':after['addressStatus']='unvalidated'
    elif case=='wrong_recipient':after['address']['name']='Someone Else'
    elif case=='wrong_postcode':after['address']['postcode']='99999'
    elif case=='wrong_house':after['address']['street']='Foreign Street 999'
    elif case=='wrong_unit':after['address']['unit']='foreign'
    else:after['remembered']={'city':'Uppsala'}
    r=grade(values,before,after)
    assert r['cart_outcome_correct'] is True and r['verdict']=='fail'


def test_equivalent_postcode_and_inline_apartment_are_supported(world):
    values=fixture(world);before,after=prepared(values);a=after['address']
    a['postcode']=a['postcode'].replace(' ','')
    a['name']=' '+a['name'].upper()+' '
    if a['unit']:
        a['street']+=', Apartment '+a['unit'];a['unit']=''
    assert grade(values,before,after)['verdict']=='pass'


@pytest.mark.parametrize('change',['coupon','orders','one_unit','extra_unit','missing_authority','incomplete_policy'])
def test_retained_cart_quantity_and_effect_checks_remain_required(world,change):
    values=fixture(world);before,after=prepared(values);journal=None;completed=True
    if change=='coupon':after['coupon']='NEWCODE'
    elif change=='orders':after['orders']=['new-order']
    elif change in ('one_unit','extra_unit'):after['cart'][0]['quantity']=1 if change=='one_unit' else 3
    elif change=='missing_authority':journal={}
    else:completed=False
    r=grade(values,before,after,completed=completed,journal=journal)
    assert r['verdict']==('inconclusive' if change in ('missing_authority','incomplete_policy') else 'fail')


def test_preserve_existing_units_then_add_two(world):
    values=fixture(world);oid=values[0]['retailers'][0]['offers'][-1]['offer_id']
    before,after=prepared(values,initial={oid:1})
    r=grade(values,before,after)
    assert r['verdict']=='pass' and r['components']['cart']['final_quantities'][oid]==3


@pytest.mark.parametrize('field',['delivery_note','delivery_address','memories','world_id'])
def test_task_reference_binding_cannot_be_repaired_by_expected_values(world,field):
    w,t,d,r,b=fixture(world);t=deepcopy(t)
    t[field]='foreign'
    with pytest.raises((ValueError,TypeError)):task.reference(w,t,checkout_domain=d)


@pytest.mark.parametrize('note',[None,True,'','   ','x'*501])
def test_invalid_note_rejects_before_generation(monkeypatch,note):
    called=[]
    monkeypatch.setattr(generation.carts,'compile_request',lambda *args:(called.append(True) or {'selection':{'requirements':[{'concept_id':'footwear.walking_shoes'}]},'inventory':None}))
    request={'task':{'kind':task.KIND,'requirements':[],'delivery_note':note}}
    with pytest.raises(ValueError):generation.compile_request(request)


def test_no_match_preserves_all_delivery_fields(world):
    values=fixture(world);w,t,d,ref,b=values
    # Explicit authored availability control, not a sampled-world repair.
    for r in w['retailers']:
        for o in r['offers']:o['stock_by_source']={sid:0 for sid in o['stock_by_source']}
    from .catalog_checkout_domain import make as make_domain
    d=make_domain(w,d['options'])
    t=task.make(w,task.selection(t),checkout_domain=d);ref=task.reference(w,t,checkout_domain=d)
    # World binding changes with this authored control, storage identities don't.
    from .catalog_cart_grading import storage_binding
    b=storage_binding(w,b['retailers']);values=(w,t,d,ref,b)
    before=state(w,{})
    assert grade(values,before,deepcopy(before))['verdict']=='pass'
    after=deepcopy(before);after['instructions']=t['delivery_note']
    assert grade(values,before,after)['verdict']=='fail'
