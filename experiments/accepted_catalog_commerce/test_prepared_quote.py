from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import json
import pytest
from . import basket_quote, delivery_admission, prepared_quote


@pytest.fixture(scope='module')
def world():
    return json.loads(Path('.local/generation-scaling-20261005-v1/scale1-unconditioned/pin/world.private.json').read_text())


@pytest.fixture(scope='module', params=[False, True])
def bound(request, world):
    plan=basket_quote.make_plan(world)
    admission=delivery_admission.make_plan(world,plan,seed=13) if request.param else None
    public=delivery_admission.Oracle(world,plan,admission) if admission else basket_quote
    return plan,admission,public,prepared_quote.prepare(world,plan=plan,admission_plan=admission)


def line(world):
    r=world['retailers'][0];o=r['offers'][0]
    return r['retailer_id'],[{'line_id':'one','offer_id':o['offer_id'],'quantity':1}]


def test_every_saved_offer_exact_quote_and_selected_identity(world,bound):
    plan,admission,public,prepared=bound
    for r in world['retailers']:
        assert prepared.public_policy(r['retailer_id'])==public.public_policy(plan,r['retailer_id'])
        for o in r['offers']:
            lines=[{'line_id':o['offer_id'],'offer_id':o['offer_id'],'quantity':1}]
            expected=public.quote(world,r['retailer_id'],lines,plan=plan)
            assert prepared.quote(r['retailer_id'],lines)==expected
            if expected['options']:
                selection=expected['options'][0]['selection']
                assert prepared.quote(r['retailer_id'],lines,selections=selection)==public.quote(
                    world,r['retailer_id'],lines,plan=plan,selections=selection)


@pytest.mark.parametrize('changes',[
    {'quantity':0},{'quantity':True},{'quantity':2}, {'quantity':10000},
    {'offer_id':'foreign'}, {'line_id':''}, {'split':True}, {'split':'yes'},
    {'signed_in':'yes'},{'coupon_code':'SAVE'}, {'coupon_code':''},{'coupon_plan':{}},
    {'selections':{}},{'expected_quote_id':'stale'},
    {'destination':'invalid'},
])
def test_request_outcomes_and_errors_equal_public(world,bound,changes):
    plan,admission,public,prepared=bound;rid,lines=line(world);kwargs={}
    for k,v in changes.items():
        if k in lines[0]:lines[0][k]=v
        else:kwargs[k]=v
    try:expected=public.quote(world,rid,lines,plan=plan,**kwargs)
    except Exception as error:
        with pytest.raises(type(error)) as actual:prepared.quote(rid,lines,**kwargs)
        assert str(actual.value)==str(error)
    else:assert prepared.quote(rid,lines,**kwargs)==expected


def test_snapshot_and_results_are_detached(world,bound):
    plan,admission,public,unused=bound
    original=deepcopy(world);p=deepcopy(plan);a=deepcopy(admission)
    prepared=prepared_quote.prepare(original,plan=p,admission_plan=a);rid,lines=line(world)
    expected=prepared.quote(rid,lines)
    original['retailers'][0]['offers'][0]['price_minor']+=999
    p['retailer_policies'][0]['membership_active']=True
    if a:a['retailers'][0]['admitted_route_keys'].clear()
    result=prepared.quote(rid,lines);result['policy'].clear();result['lines'].clear()
    policy=prepared.public_policy(rid);policy.clear()
    metadata=prepared.binding;metadata.clear()
    assert prepared.quote(rid,lines)==expected and prepared.public_policy(rid)
    with pytest.raises(ValueError):basket_quote.validate_plan(original,plan)


def test_parallel_requests_and_separate_contexts(world,bound):
    plan,admission,public,prepared=bound;rid,lines=line(world)
    separate=prepared_quote.prepare(world,plan=plan,admission_plan=admission)
    inputs=[{**lines[0],'line_id':str(i)} for i in range(8)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        actual=list(pool.map(lambda l:prepared.quote(rid,[l]),inputs))
    assert actual==[separate.quote(rid,[l]) for l in inputs]


def test_bad_construction_rejects(world,bound):
    plan,admission,public,prepared=bound
    invalid=deepcopy(plan);invalid['world_sha256']='stale'
    with pytest.raises(ValueError):prepared_quote.prepare(world,plan=invalid,admission_plan=admission)
    invalid=deepcopy(plan);invalid['retailer_policies'][0]['optional_split']='yes'
    with pytest.raises(ValueError):prepared_quote.prepare(world,plan=invalid)
    if admission:
        bad=deepcopy(admission);bad['retailers'][0]['admitted_route_keys'].append('foreign')
        with pytest.raises(ValueError):prepared_quote.prepare(world,plan=plan,admission_plan=bad)


def test_calls_do_not_repeat_world_preparation(world,monkeypatch):
    plan=basket_quote.make_plan(world);prepared=prepared_quote.prepare(world,plan=plan)
    rid,lines=line(world)
    def fail(*args,**kwargs):raise AssertionError('Whole-world preparation repeated')
    monkeypatch.setattr(basket_quote,'_world',fail)
    monkeypatch.setattr(basket_quote,'validate_plan',fail)
    prepared.quote(rid,lines);prepared.public_policy(rid)


def test_destination_scope_and_missing_duplicate_lines(world,bound):
    plan,admission,public,prepared=bound;rid,lines=line(world)
    destination=deepcopy(world['user_location']);destination['local_east_km']+=10000
    assert prepared.quote(rid,lines,destination=destination)==public.quote(world,rid,lines,plan=plan,destination=destination)
    for bad in ([],None,[{'line_id':'x','quantity':1}],[lines[0],lines[0]]):
        try:expected=public.quote(world,rid,bad,plan=plan)
        except Exception as error:
            with pytest.raises(type(error)) as actual:prepared.quote(rid,bad)
            assert str(actual.value)==str(error)
        else:assert prepared.quote(rid,bad)==expected


def test_retailer_menu_is_reused_across_skus_and_scoped_to_destination(world,monkeypatch):
    plan=basket_quote.make_plan(world);calls=[];original=basket_quote._choices
    def count(*args):calls.append(args[-1]);return original(*args)
    monkeypatch.setattr(basket_quote,'_choices',count)
    prepared=prepared_quote.prepare(world,plan=plan);r=world['retailers'][0]
    for offer in r['offers'][:3]:
        prepared.quote(r['retailer_id'],[{'line_id':'one','offer_id':offer['offer_id'],'quantity':1}])
    assert len(calls)==1
    destination=deepcopy(world['user_location']);destination['local_east_km']+=0.1
    prepared.quote(r['retailer_id'],[{'line_id':'one','offer_id':r['offers'][0]['offer_id'],'quantity':1}],destination=destination)
    assert len(calls)==2
