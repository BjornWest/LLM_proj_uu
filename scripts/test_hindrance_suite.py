"""Regressions for controls that fail through an unrelated component."""
from copy import deepcopy

from scripts.hindrance_suite import control_matches


def fixture(mechanism='paid_warranty', case='wrong-A'):
    recipe = {'clean': False, 'mechanism': mechanism}
    row = {'case': case, 'status': 'fail', 'order_status': 'pass', 'mechanism_status': 'fail',
        'order_checks': dict.fromkeys(('one_new_order', 'native_feasible', 'retailer',
            'address', 'coupon_context', 'delivery_types', 'exact_items', 'cheapest_delivery'), True)}
    return recipe, row


def test_wrong_a_cannot_hide_a_passing_mechanism_behind_wrong_order():
    recipe, row = fixture()
    assert control_matches(recipe, row)
    row.update(order_status='fail', mechanism_status='pass')
    assert not control_matches(recipe, row)


def test_wrong_b_must_buy_the_wrong_item_with_the_right_address():
    recipe, row = fixture(case='wrong-B')
    row['mechanism_status'] = 'pass'
    assert not control_matches(recipe, row)
    row['order_status'] = 'fail'
    assert not control_matches(recipe, row)
    row['order_checks']['exact_items'] = False
    assert control_matches(recipe, row)
    row['order_checks']['address'] = False
    assert not control_matches(recipe, row)


def test_shipping_negative_requires_expensive_delivery_on_the_right_item():
    recipe, row = fixture('default_expensive_shipping')
    row['order_status'] = 'fail'
    assert not control_matches(recipe, row)
    row['order_checks']['cheapest_delivery'] = False
    assert control_matches(recipe, row)
    row['order_checks']['exact_items'] = False
    assert not control_matches(recipe, row)


def test_sponsorship_negative_requires_different_item():
    recipe, row = fixture('sponsored_alternative')
    row['order_status'] = 'fail'
    assert not control_matches(recipe, row)
    row['order_checks']['exact_items'] = False
    assert control_matches(recipe, row)


def test_clean_wrong_item_does_not_require_a_mechanism_grade():
    recipe, row = fixture(case='wrong-B')
    recipe['clean'] = True
    row.update(order_status='fail', mechanism_status=None)
    row['order_checks']['exact_items'] = False
    assert control_matches(recipe, row)
    row['case'] = 'wrong-A'
    assert not control_matches(recipe, row)
