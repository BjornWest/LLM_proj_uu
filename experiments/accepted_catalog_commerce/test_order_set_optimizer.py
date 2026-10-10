"""Public exhaustive quote oracle verifies the mixed-catalog search binding."""
from copy import deepcopy

import pytest

from experiments.footwear_world_pilot import order_set_optimizer as historical
from experiments.footwear_world_pilot.test_basket_quote import world
from experiments.footwear_world_pilot.test_order_set_optimizer import brute, requests, stock_usage
from . import basket_quote, order_set_optimizer as oracle
from .test_basket_quote import bridged


@pytest.mark.parametrize('quantities,overlap', [((1, 1), False), ((1, 1), True), ((2, 1), False)])
def test_matches_independent_exhaustive_public_quote(world, quantities, overlap):
    w = bridged(world)
    p = basket_quote.make_plan(w)
    req = requests(w, quantities, overlap)
    caps = {o['offer_id']: 2 for r in w['retailers'] for o in r['offers']}
    before = deepcopy(w)
    expected = brute(w, req, p, caps=caps, quote_provider=basket_quote)
    result = oracle.solve(w, req, plan=p, quantity_limits=caps,
                          allowed_destination_types=['home'], budget={'max_work': 50000, 'max_seconds': 10})
    assert result['complete'] and result['status'] == 'optimal'
    assert result['total_minor'] == expected and w == before
    assert result['schema_version'] == oracle.VERSION
    for solution in result['solutions']:
        assert sum(o['cost'] for o in solution['orders']) == solution['total_minor']
        for order in solution['orders']:
            q = order['quote']
            actual = basket_quote.quote(w, order['retailer_id'], order['lines'], plan=p,
                                       selections=q['selection'], split=q['split'])['selected']
            assert actual == q


def test_search_exhaustion_is_not_an_optimality_claim(world):
    w = bridged(world)
    result = oracle.solve(w, requests(w), plan=basket_quote.make_plan(w),
                          budget={'max_work': 1, 'max_seconds': 10})
    assert not result['complete'] and result['status'] == 'inconclusive'


def test_central_unsupported_accounts_and_foreign_envelopes_reject(world):
    w = bridged(world)
    p = basket_quote.make_plan(w)
    with pytest.raises(ValueError, match='account/coupon'):
        oracle.solve(w, requests(w), plan=p, coupon_plan={})
    with pytest.raises(ValueError, match='envelope'):
        oracle.solve(world, requests(world), plan=p)


def test_binding_leaves_old_modules_and_formulas_unchanged():
    assert historical.VERSION == 'native-order-set-optimizer-v1'
    assert historical._Checkout.dispatch.__globals__['baskets'] is not basket_quote
    assert oracle._Checkout.dispatch.__code__ is historical._Checkout.dispatch.__code__
    assert oracle._Checkout.options.__code__ is historical._Checkout.options.__code__
    assert oracle._solve.__code__ is historical.solve.__code__
