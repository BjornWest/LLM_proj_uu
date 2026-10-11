"""Source-only policies against closed disclosure/checked-radio stand-ins.

The fixture makes hidden row innerText empty, as in the actual sections checkout,
and only ordinary emitted summary clicks can expose its native row descriptions.
No host, browser, generation or provider is used.
"""
from copy import deepcopy
import json

import pytest

from environments.commerce_scenarios.pricing_promotions.controls import policy as pricing_policy
from .controls import policy as steering_policy
from .test_policy import Node, Page, drive, episode
from .test_steering_recurrence import prepared as steering_prepared

DESCRIPTION = 'Native carrier — Home delivery — Estimated 2026-10-20 — Basket total 110 SEK'


class DisclosureNode(Node):
    def is_visible(self):
        if self.kind == 'summary':
            return all(self.page.opened[:int(self.value)])
        if self.kind in ('radio', 'delivery_row', 'home_rows'):
            return all(self.page.opened)
        return True

    def locator(self, selector):
        if selector == 'xpath=ancestor::details[not(@open)][1]/summary':
            # A hidden nested summary has only its earlier disclosures as ancestors.
            end = int(self.value) if self.kind == 'summary' else len(self.page.opened)
            closed = [index for index in range(end) if not self.page.opened[index]]
            return DisclosureNode(self.page, 'summary', bool(closed), str(closed[-1]) if closed else None)
        if selector == 'xpath=ancestor::label[1]':
            return DisclosureNode(self.page, 'delivery_row', self.exists, self.value)
        return super().locator(selector)

    def inner_text(self):
        if self.kind == 'terms':
            return 'Prices from 99 SEK; current exact variant 110 SEK before delivery'
        if self.kind == 'totals':
            return 'Total 110 SEK'
        return DESCRIPTION if self.is_visible() else ''

    def all_inner_texts(self):
        return [DESCRIPTION] if self.exists and self.is_visible() else []


class ClosedDeliveryPage(Page):
    def __init__(self, *, depth=1, checked=True, checkout='sections'):
        super().__init__(mechanism='recommended_expensive_delivery')
        self.opened, self.checkout = [False] * depth, checkout
        self.selected = 'shop/a/basket1/slow' if checked else 'shop/a/basket1/fast'
        self.actions = []

    def locator(self, selector):
        available = '#/checkout' in self.url and (self.checkout != 'steps' or self.step == 2)
        if selector.startswith('input[data-service-group][value='):
            value = json.loads(selector.split('[value=')[1][:-1])
            return DisclosureNode(self, 'radio', available, value)
        if selector == 'input[data-service-group]:checked':
            return DisclosureNode(self, 'radio', available, self.selected)
        if selector in ('label.delivery-row', 'label.delivery-row:visible'):
            return DisclosureNode(self, 'home_rows', available)
        if selector == 'form[data-form="add"] input[name="quantity"]':
            return Node(self, 'quantity_field', '#/product/' in self.url)
        if selector == '[data-pricing-terms]':
            return DisclosureNode(self, 'terms')
        if selector == '[data-scenario-part="totals"]':
            return DisclosureNode(self, 'totals')
        return super().locator(selector)

    def apply(self, action):
        self.actions.append(action)
        tool, fields = action
        if tool == 'click' and fields['bid'].startswith('summary:'):
            self.opened[int(fields['bid'].split(':')[1])] = True
        else:
            super().apply(action)


def pricing_prepared():
    return {'setup': {'mechanism': 'from_price_variant', 'intent': {'offer_id': 'shop/a', 'quantity': 1}},
            'reference': {'status': 'ready_native', 'candidates': [
                {'status': 'quoted', 'total_minor': 11000, 'quote_id': 'native-quote', 'promotion_codes': [],
                 'selected': {'native_option_id': 'shop/a/basket1/slow'}}],
                'scenario_role': 'native_scenario', 'mechanism_discrimination': 'exposure_only_unverified',
                'required_outcome': 'quotation'}}


@pytest.mark.parametrize('family', ('pricing', 'steering'))
@pytest.mark.parametrize('depth', (1, 2))
@pytest.mark.parametrize('checked', (True, False))
def test_delivery_opens_real_summary_before_observing_even_a_checked_default(family, depth, checked):
    ep = episode()
    ep.runtime.public_catalogs['shop']['configuration']['modules']['checkout'] = 'sections' if family == 'pricing' else 'steps'
    ep.runtime.bindings['retailer_offers']['shop/a']['retailer_id'] = 'shop'
    source = pricing_prepared() if family == 'pricing' else steering_prepared('recommended_expensive_delivery')
    original = deepcopy(source)
    driver = (pricing_policy if family == 'pricing' else steering_policy)(ep, source)
    page = ClosedDeliveryPage(depth=depth, checked=checked, checkout='sections' if family == 'pricing' else 'steps')
    drive(driver, page)
    assert source == original
    clicks = [fields['bid'] for tool, fields in page.actions if tool == 'click']
    assert [bid for bid in clicks if bid.startswith('summary:')] == [f'summary:{index}' for index in range(depth)]
    assert len([bid for bid in clicks if bid.startswith('radio:')]) == (0 if checked else 1)
    observations = driver.observations if family == 'pricing' else driver.observations['delivery']
    deliveries = [item for item in observations if 'selected_delivery_option_id' in item]
    assert deliveries == [{'selected_delivery_option_id': 'shop/a/basket1/slow',
                           'selected_delivery_description': DESCRIPTION, 'delivery_rows': [DESCRIPTION],
                           **({'totals': 'Total 110 SEK'} if family == 'pricing' else {})}]
    assert all(page.opened) and page.selected == 'shop/a/basket1/slow'
