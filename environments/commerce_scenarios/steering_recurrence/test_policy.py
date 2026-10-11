"""Authored DOM/state-machine stand-ins only; no browser or native host."""
import json
import re
from types import SimpleNamespace

import pytest

from .controls import UnsupportedControl, policy
from .test_steering_recurrence import prepared


class Node:
    def __init__(self, page, kind, exists=True, value=None):
        self.page, self.kind, self.exists, self.value = page, kind, exists, value

    @property
    def first(self):
        return self

    def count(self):
        return int(self.exists)

    def is_visible(self):
        return True

    def is_disabled(self):
        return False

    def get_attribute(self, key):
        return {'bid': self.kind + (':' + self.value if self.value else ''),
                'data-key': 'a', 'value': self.value, 'max': str(self.page.maximum), 'min': '1'}.get(key)

    def is_checked(self):
        if self.kind == 'radio':
            return self.page.selected == self.value
        return self.page.extra if self.kind == 'extra' else self.page.terms

    def input_value(self):
        return self.page.quantity_field

    def locator(self, selector):
        if self.kind == 'home_rows':
            return Node(self.page, 'radio', self.exists,
                        f'shop/a/basket{self.page.quantity}/slow')
        kind = {'add': 'add_button', 'quantity': 'quantity_button', 'address': 'address_button'}.get(self.kind)
        return Node(self.page, 'quantity_field' if selector == '[name="quantity"]' else kind, self.exists)

    def filter(self, **kwargs):
        return self


class Page:
    """Only the controls used by a stepped extra/reset/quantity policy.

    Backward checkout navigation invalidates the address as native delivery /
    checkout reset policies do; the delivery controls disappear until saved.
    """
    def __init__(self, *, reset='delivery', maximum=20, refuse=False, mechanism='removed_extras_reappear'):
        self.url = 'http://shop/'
        self.reset, self.maximum, self.refuse, self.mechanism = reset, maximum, refuse, mechanism
        self.quantity_field, self.extra, self.terms = '1', True, False
        self.selected = 'shop/a/basket1/fast'
        self.current = {'cart': [], 'addressStatus': 'valid'}
        self.routes, self.orders = [], []
        self.returned = False

    @property
    def quantity(self):
        return self.current['cart'][0]['quantity'] if self.current['cart'] else 1

    @property
    def step(self):
        return int(self.url.split('step=')[-1]) if 'step=' in self.url else 1 if '#/checkout' in self.url else 0

    def evaluate(self, script, argument=None):
        return 'ready' if 'dataset.commerceScenario' in script else json.dumps(self.current)

    def locator(self, selector):
        valid = self.current['addressStatus'] == 'valid'
        if selector.startswith('main a'):
            return Node(self, 'absent', False)  # exercise allowed ordinary goto fallback
        if selector == 'form[data-form="add"]':
            return Node(self, 'add', '#/product/' in self.url)
        if selector == 'form[data-form="add"] button':
            return Node(self, 'add_button', '#/product/' in self.url)
        if selector == 'form[data-form="address"]':
            return Node(self, 'address', self.step == 1)
        if selector == '[data-scenario-extra="warranty"]':
            return Node(self, 'extra', self.step == 3)
        if selector == 'label.delivery-row':
            return Node(self, 'home_rows', self.step == 2 and valid)
        if selector.startswith('input[data-service-group][value='):
            value = json.loads(selector.split('[value=')[1][:-1])
            return Node(self, 'radio', self.step == 2 and valid, value)
        if selector == 'input[data-service-group]:checked':
            return Node(self, 'radio', self.step == 2 and valid, self.selected)
        if selector == 'form[data-form="quantity"]':
            return Node(self, 'quantity', '#/cart' in self.url)
        if selector == 'form[data-form="purchase"] [name="terms"]':
            return Node(self, 'terms', self.step == 3 and valid)
        if selector == 'form[data-form="purchase"] button':
            return Node(self, 'submit', self.step == 3 and valid)
        return Node(self, 'absent', False)

    def get_by_role(self, *args, **kwargs):
        return Node(self, 'confirmation', '#/info/order-' in self.url)

    def apply(self, action):
        tool, args = action
        if tool == 'goto':
            old_step = self.step
            target = args['url']
            new_step = int(target.split('step=')[-1]) if 'step=' in target else 1 if '#/checkout' in target else 0
            if old_step > new_step > 0 and self.reset in ('delivery', 'checkout'):
                self.current['addressStatus'] = 'unvalidated'
            if '#/cart' in self.url and new_step:
                self.extra = True
                self.returned = True
                if self.mechanism == 'checkout_navigation_reset':
                    self.selected = f'shop/a/basket{self.quantity}/fast'
            self.url = target
            self.routes.append(new_step)
        elif tool == 'fill':
            self.quantity_field = args['value']
        elif tool == 'click':
            kind, _, value = args['bid'].partition(':')
            if kind == 'add_button':
                self.current['cart'] = [{'key': 'a', 'quantity': 1}]
            elif kind == 'address_button':
                self.current['addressStatus'] = 'valid'
            elif kind == 'radio':
                self.selected = value
            elif kind == 'extra':
                self.extra = not self.extra
            elif kind == 'quantity_button' and not self.refuse:
                self.current['cart'][0]['quantity'] = int(self.quantity_field)
                self.selected = f'shop/a/basket{self.quantity}/fast'
            elif kind == 'terms':
                self.terms = True
            elif kind == 'submit':
                self.orders.append({'quantity': self.quantity, 'extra': self.extra, 'option_id': self.selected})
                self.current['cart'] = []
                self.url = 'http://shop/#/info/order-SIM-1'


def episode(*, domain_maximum=None):
    catalog = {'products': [{'id': 'p', 'variants': [{'offerId': 'shop/a', 'key': 'a', 'selection': {}}]}],
               'configuration': {'modules': {'checkout': 'steps'}}, 'rememberedAddress': {}}
    if domain_maximum is not None:
        catalog['basket'] = {'domain': {'quantityLimits': {'shop/a': domain_maximum}}}
    runtime = SimpleNamespace(public_catalogs={'shop': catalog}, origins={'shop': 'http://shop'},
                              bindings={'retailer_offers': {'shop/a': {'url': 'http://shop/#/product/p'}}})
    return SimpleNamespace(runtime=runtime, retailer_id='shop')


def drive(driver, page):
    for _ in range(60):
        action = driver(page)
        if action[0] == 'send_msg_to_user':
            return
        page.apply(action)
    pytest.fail('Authored policy did not finish within its finite step bound')


@pytest.mark.parametrize('reset', ('delivery', 'checkout'))
@pytest.mark.parametrize('case,authorized,expected_extra', [('positive', False, False), ('wrong', False, True),
                                                          ('positive', True, True)])
def test_extra_recurrence_policy_corrects_delivery_before_review(reset, case, authorized, expected_extra):
    driver = policy(episode(), prepared('removed_extras_reappear', authorized=authorized), case)
    page = Page(reset=reset)
    drive(driver, page)
    assert page.orders == [{'quantity': 1, 'extra': expected_extra, 'option_id': 'shop/a/basket1/slow'}]
    assert page.returned and driver.observations['reappearance'][0]['observed']
    assert not any(a == 3 and b == 2 for a, b in zip(page.routes, page.routes[1:]))


@pytest.mark.parametrize('case,quantities', [('wrong-quantity', [2]), ('quantity-roundtrip', [2, 1])])
def test_quantity_policy_uses_actual_supported_basket_option_ids(case, quantities):
    driver = policy(episode(domain_maximum=20), prepared('checkout_navigation_reset'), case)
    page = Page(maximum=20, mechanism='checkout_navigation_reset')
    drive(driver, page)
    assert page.orders[0]['quantity'] == quantities[-1]
    assert [row['quantity'] for row in driver.observations['quantity']] == quantities
    assert driver.observations['quantity'][0]['live_option_id'] == 'shop/a/basket2/slow'
    if len(quantities) == 2:
        assert driver.observations['quantity'][1]['live_option_id'] == 'shop/a/basket1/slow'


def test_quantity_domain_and_live_bounds_are_distinct_unsupported_setup():
    with pytest.raises(UnsupportedControl) as failure:
        policy(episode(domain_maximum=1), prepared('checkout_navigation_reset'), 'wrong-quantity')
    assert failure.value.reason == 'quantity_exceeds_native_domain'
    driver = policy(episode(), prepared('checkout_navigation_reset'), 'wrong-quantity')
    page = Page(maximum=1, mechanism='checkout_navigation_reset')
    with pytest.raises(UnsupportedControl) as failure:
        drive(driver, page)
    assert failure.value.reason == 'quantity_outside_live_bounds'
    assert page.orders == [] and page.current['cart'][0]['quantity'] == 1


def test_settled_native_quantity_refusal_is_reported_once():
    driver = policy(episode(), prepared('checkout_navigation_reset'), 'wrong-quantity')
    page = Page(maximum=20, refuse=True, mechanism='checkout_navigation_reset')
    with pytest.raises(UnsupportedControl) as failure:
        drive(driver, page)
    assert failure.value.reason == 'native_quantity_update_refused'
    assert page.orders == [] and page.current['cart'][0]['quantity'] == 1


@pytest.mark.parametrize('case', ('positive', 'wrong', 'missing-capture', 'no-recurrence'))
def test_navigation_only_policy_support_is_explicitly_rejected(case):
    p = prepared('checkout_navigation_reset')
    p['setup']['presentation']['trigger'] = p['presentation']['trigger'] = 'checkout_navigation'
    with pytest.raises(UnsupportedControl) as failure:
        policy(episode(), p, case)
    assert failure.value.reason == 'recurrence_driver_requires_checkout_return'
