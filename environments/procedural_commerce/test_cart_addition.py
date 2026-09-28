from copy import deepcopy
from environments.procedural_commerce.engine import CommerceSession
from environments.procedural_commerce.cart_interaction import resolve_addition
from environments.procedural_commerce.generator import generate_world


def _world():
    # Self-contained source fixture; no dependency on ignored/deleted curation data.
    world = generate_world(0, parameters={"stockout_probability": 0})
    for offer in world["offers"]:
        offer["stock_quantity"] = 10
    return world


def test_add_delta_is_journaled_and_update_remains_absolute():
    s=CommerceSession(_world());payload={'offer_id':'offer-product-001-nordhem','quantity':2,'extra':False}
    assert s.perform('cart.add',payload)['ok']
    assert s.perform('cart.add',payload)['ok']
    state=s.snapshot();assert state['carts']['nordhem']['quantity']==4
    assert state['events'][-1]['action']=='cart.add'
    assert state['events'][-1]['payload']['quantity']==2
    assert s.perform('cart.update',{'retailer_id':'nordhem','quantity':1})['ok']
    assert s.snapshot()['carts']['nordhem']['quantity']==1
    assert s.perform('cart.set',payload)['ok']
    assert s.perform('cart.set',payload)['ok']
    assert s.snapshot()['carts']['nordhem']['quantity']==2


def test_invalid_delta_and_other_product_do_not_mutate_cart():
    s=CommerceSession(_world());s.perform('cart.add',{'offer_id':'offer-product-001-nordhem','quantity':1})
    before=deepcopy(s.snapshot()['carts'])
    for quantity in (0,-1,True,'2'):
        assert not s.perform('cart.add',{'offer_id':'offer-product-001-nordhem','quantity':quantity})['ok']
        assert s.snapshot()['carts']==before
    assert not s.perform('cart.add',{'offer_id':'offer-product-002-nordhem','quantity':1})['ok']
    assert s.snapshot()['carts']==before


def test_addition_sampling_is_order_independent_and_has_no_layout_input():
    assert resolve_addition(7,['a','b'],'sampled')==resolve_addition(7,['b','a'],'sampled')
    for mode in ('set','increment'):
        assert resolve_addition(7,['a'],{'a':mode})=={'a':mode}
