"""Finite driver state-machine regressions with a small authored UI stand-in.

This is source testing, not browser acceptance or evidence of UI realization.
"""
import json
import re
from types import SimpleNamespace
import unittest

from . import case_config, policy_for, settings_for
from .mapper import MECHANISMS, COOKIE_MECHANISMS
from .test_family import prepared


class Page:
    def __init__(self, cookie=False, stepped=False, selector_kind=None, ids_ready=True):
        self.cookie, self.stepped, self.pane, self.closed = cookie, stepped, False, False
        self.route, self.confirmed, self.terms = 'home', False, False
        self.preferences = dict.fromkeys(('analytics', 'personalisation', 'marketing'), False)
        self.newsletter, self.extra = True, True
        self.saved = None
        self.address = dict.fromkeys(('name', 'street', 'postcode', 'city', 'unit'), '')
        self.state = {'cart': [], 'addressStatus': 'missing'}
        self.selector_kind, self.ids_ready = selector_kind, ids_ready
        self.selection = {'colour': 'Red', 'size': 'Small'}

    def locator(self, selector):
        return Node(self, selector)

    def get_by_role(self, *args, **kwargs):
        return Node(self, 'confirmed')

    def evaluate(self, script, *args):
        return 'ready' if 'dataset.commerceScenario' in script else json.dumps(self.state)

    def wait_for_timeout(self, value):
        raise AssertionError('Source policy unexpectedly waited for a missing control')

    def execute(self, tool, arguments):
        if tool == 'goto':
            self.route = ('product' if '/product/' in arguments['url'] else
                          'review' if '?step=3' in arguments['url'] else 'checkout')
        elif tool == 'noop':
            self.ids_ready = True  # stand-in for the runner's next observation
        elif tool == 'select_option':
            key = re.search(r'data-selection="([^"]+)"', arguments['bid'])[1]
            self.selection[key] = arguments['options'][0]
        elif tool == 'fill':
            self.address[re.search(r'\[name="([^"]+)"\]', arguments['bid'])[1]] = arguments['value']
        elif tool == 'click':
            bid = arguments['bid']
            if 'data-selection' in bid:
                key = re.search(r'data-selection(?:-button)?="([^"]+)"', bid)[1]
                value = re.search(r'(?:data-value|value)="([^"]+)"', bid)[1]
                self.selection[key] = value
            elif 'data-consent-purpose' in bid:
                purpose = re.search(r'data-consent-purpose="([^"]+)"', bid)[1]
                self.preferences[purpose] = not self.preferences[purpose]
            elif 'data-consent=' in bid:
                action = re.search(r'data-consent="([^"]+)"', bid)[1]
                if action == 'settings':
                    self.pane = True
                else:
                    if action in ('accept_all', 'reject_all'):
                        self.preferences = dict.fromkeys(self.preferences, action == 'accept_all')
                    self.saved, self.closed = dict(self.preferences), True
            elif 'data-form="add"' in bid:
                self.state['cart'] = [{'key': 'item-key', 'quantity': 1}]
            elif 'data-form="address"' in bid:
                self.state['addressStatus'] = 'valid'
            elif 'data-scenario-newsletter' in bid:
                self.newsletter = not self.newsletter
            elif 'data-scenario-extra' in bid:
                self.extra = not self.extra
            elif 'name="terms"' in bid:
                self.terms = True
            elif 'data-form="purchase"' in bid:
                self.saved = {'newsletter': self.newsletter, 'extra': self.extra}
                self.confirmed = True
            else:
                raise AssertionError(bid)
        elif tool != 'send_msg_to_user':
            raise AssertionError(tool)


class Node:
    def __init__(self, page, selector):
        self.page, self.selector = page, selector

    @property
    def first(self):
        return self

    def locator(self, selector):
        return Node(self.page, self.selector + ' ' + selector)

    def count(self):
        if self.selector == 'confirmed':
            return int(self.page.confirmed)
        if 'data-form="purchase"' in self.selector:
            return int(self.page.route == 'review' or self.page.route == 'checkout' and not self.page.stepped)
        if 'commerce-scenario-consent' in self.selector:
            return int(self.page.cookie and not self.page.closed)
        if 'data-selection' in self.selector:
            kind = ('buttons' if 'data-selection-button' in self.selector else
                    'select' if self.selector.startswith('select') else 'radio')
            return int(kind == self.page.selector_kind)
        return 1

    def get_attribute(self, key):
        if key == 'bid':
            return self.selector if self.page.ids_ready else None
        if key == 'data-key':
            return 'item-key' if not self.page.selector_kind or self.page.selection == {
                'colour': 'Blue', 'size': 'Large'} else 'other-key'
        if key == 'aria-pressed':
            return str(self._selected()).lower()
        return None

    def _selected(self):
        key = re.search(r'data-selection(?:-button)?="([^"]+)"', self.selector)[1]
        value = re.search(r'(?:data-value|value)="([^"]+)"', self.selector)[1]
        return self.page.selection[key] == value

    def is_enabled(self):
        return True

    def input_value(self):
        if self.selector.startswith('select'):
            return self.page.selection[re.search(r'data-selection="([^"]+)"', self.selector)[1]]
        return self.page.address[re.search(r'\[name="([^"]+)"\]', self.selector)[1]]

    def is_checked(self):
        if 'data-selection' in self.selector:
            return self._selected()
        if 'data-consent-purpose' in self.selector:
            return self.page.preferences[re.search(r'data-consent-purpose="([^"]+)"', self.selector)[1]]
        if 'newsletter' in self.selector:
            return self.page.newsletter
        return self.page.terms if 'terms' in self.selector else self.page.extra


class PolicyTests(unittest.TestCase):
    def test_positive_wrong_driver_finishes_via_authored_ui_sequence_for_every_kind_and_checkout_layout(self):
        for mechanism in MECHANISMS:
            for case in ('positive', 'wrong'):
                for control in ('forbidden', 'required'):
                    for stepped in (False, True):
                        with self.subTest(mechanism=mechanism, case=case, control=control, stepped=stepped):
                            value = prepared(mechanism, control=control)
                            settings = settings_for(value['setup'])
                            runtime = SimpleNamespace(scenario=settings, origins={'shop': 'http://shop.local'},
                                public_catalogs={'shop': {'products': [{'id': 'product', 'variants': [
                                    {'key': 'item-key', 'offerId': 'shop/item', 'state': 'in_stock', 'selection': {}}]}],
                                    'rememberedAddress': {'name': 'Buyer', 'street': 'Street 1', 'postcode': '75220', 'city': 'Uppsala', 'unit': ''}}},
                                bindings={'retailer_pages': {'shop': {'product': 'http://shop.local/#/product/product'}}})
                            episode = SimpleNamespace(runtime=runtime, retailer_id='shop')
                            page = Page(cookie=mechanism in COOKIE_MECHANISMS, stepped=stepped)
                            next_action = policy_for(episode, value, case)
                            actions = []
                            for step in range(40):
                                tool, arguments = next_action(page)
                                actions.append(tool)
                                page.execute(tool, arguments)
                                if tool == 'send_msg_to_user':
                                    break
                            else:
                                self.fail('Policy exceeded its finite source-control turn bound')
                            choices = case_config(value, case)['choices']
                            if mechanism in COOKIE_MECHANISMS:
                                self.assertEqual(page.saved, choices)
                                self.assertNotIn('goto', actions)
                            else:
                                key, wanted = next(iter(choices.items()))
                                self.assertEqual(page.saved['newsletter' if key == 'newsletter' else 'extra'], wanted)
                                self.assertTrue(page.confirmed)
                                self.assertEqual(page.address, runtime.public_catalogs['shop']['rememberedAddress'])

    def test_public_variant_selectors_and_missing_browser_ids_recover_before_order(self):
        value = prepared('paid_warranty')
        address = {'name': 'Buyer', 'street': 'Street 1', 'postcode': '75220', 'city': 'Uppsala', 'unit': ''}
        runtime = SimpleNamespace(scenario=settings_for(value['setup']), origins={'shop': 'http://shop.local'},
            public_catalogs={'shop': {'products': [{'id': 'product', 'variants': [
                {'key': 'item-key', 'offerId': 'shop/item', 'state': 'in_stock',
                 'selection': {'colour': 'Blue', 'size': 'Large'}}]}], 'rememberedAddress': address}},
            bindings={'retailer_pages': {'shop': {'product': 'http://shop.local/#/product/product'}}})
        episode = SimpleNamespace(runtime=runtime, retailer_id='shop')
        for selector_kind in ('select', 'radio', 'buttons'):
            with self.subTest(selector_kind=selector_kind):
                page = Page(selector_kind=selector_kind, ids_ready=False)
                policy = policy_for(episode, value)
                actions = []
                for step in range(40):
                    tool, arguments = policy(page)
                    actions.append(tool)
                    page.execute(tool, arguments)
                    if tool == 'send_msg_to_user':
                        break
                else:
                    self.fail('Variant policy did not finish')
                self.assertIn('noop', actions)
                self.assertEqual(page.selection, {'colour': 'Blue', 'size': 'Large'})
                self.assertTrue(page.confirmed)
                self.assertIn('select_option' if selector_kind == 'select' else 'click', actions)
        for missing in ('name', 'street', 'postcode', 'city'):
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                policy_for(episode, value, address={**address, missing: ''})


if __name__ == '__main__':
    unittest.main()
