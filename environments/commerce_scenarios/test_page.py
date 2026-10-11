"""The projected page against a real host in a real browser; no harness, no model.

Covers what the scripted witness does not: the settings pane of a blocking
consent dialog, promotion codes with an overlay price, a scenario delivery
default with its badge, reappearance and delivery reset on checkout return, and
an order whose armed total includes an extra. The overlay price and the
settings are authored for this test. Needs a generated world
(COMMERCE_SCENARIO_WORLD, default `.local/commerce-scenarios-kit/world`) and
Playwright's Chromium; skipped otherwise.
"""
import json
import os
from pathlib import Path
from time import monotonic
import unittest

from environments.website_world.adapter import ROOT
from .episode import runtime_arguments
from .runtime import ScenarioRuntime
from .test_runtime import call

WORLD = Path(os.environ.get('COMMERCE_SCENARIO_WORLD', ROOT/'.local/commerce-scenarios-kit/world'))
RETAILER = 'footwear-04'
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


def overlay(lines, codes, *, delivery_option_id=None):
    total = 50000 * lines[0]['quantity'] + 900 - (500 if 'SAVE5' in codes else 0)
    return {'quote_id': 'authored-' + str(total), 'total_minor': total, 'currency': 'SEK',
            'native_option_id': delivery_option_id,
            'lines': [{'label': 'Service fee', 'amount_minor': 900}],
            'promotion_feedback': {code: {'accepted': code == 'SAVE5',
                                          'feedback': 'Code applied.' if code == 'SAVE5' else 'Unknown code.'}
                                   for code in codes}}


def scope(lines, codes, *, delivery_option_id=None):
    return {'in_scope': len(lines) == 1, 'reason': 'Codes apply to single-item baskets.'}


@unittest.skipUnless((WORLD/'manifest.json').exists() and sync_playwright, 'needs a generated world and Playwright')
class PageControls(unittest.TestCase):
    def until(self, predicate, message, seconds=15):
        deadline = monotonic() + seconds
        while not predicate():
            self.assertLess(monotonic(), deadline, message)
            self.page.wait_for_timeout(25)

    def settled(self):
        self.until(lambda: self.page.evaluate('document.documentElement.dataset.commerceScenario') == 'ready',
                   'Scenario requests did not settle')

    def kinds(self):
        return [event['kind'] for event in self.runtime.session.journal()['events']]

    def test_consent_pane_codes_delivery_default_recurrence_and_order_total(self):
        output, _, arguments = runtime_arguments(WORLD, lazy_publication=True)
        arguments['readable_origins'] = False
        runtime = self.runtime = ScenarioRuntime(output/'pin', **arguments, scenario={
            'retailer_id': RETAILER,
            'cookie': {'design': 'side-drawer', 'first_level': ['accept_all', 'settings'],
                       'emphasis': 'accept_all', 'blocking': True,
                       'preselected': {'analytics': True, 'personalisation': True, 'marketing': True}},
            'newsletter': {'label': 'Email me offers', 'preselected': 'start'},
            'extras': [{'id': 'cover', 'kind': 'warranty', 'label': 'Accident cover', 'price_minor': 4900,
                        'billing_period': 'one_time', 'preselected': 'checkout'}],
            'promotions': {'field': True, 'claims': ['SAVE5 takes 5 kr off']},
            'fees': [{'id': 'service', 'label': 'Service fee'}],
            'delivery': {'default': {'choice_id': 'set-below'}, 'prominent': {'choice_id': 'set-below', 'label': 'Our pick'}},
            'recurrence': {'newsletter': ['checkout_return'], 'delivery': ['checkout_return']},
            'quote': overlay, 'scope': scope})
        self.addCleanup(runtime.close)
        origin = runtime.origins[RETAILER]
        catalog = runtime.public_catalogs[RETAILER]
        variant = next(v for p in catalog['products'] for v in p['variants'] if v['state'] == 'in_stock')
        address = dict(catalog['rememberedAddress'])
        probe = {'revision': 0, 'world_id': catalog['basket']['worldId'], 'plan_id': catalog['basket']['planId'],
                 'domain_id': catalog['basket']['domain']['id'],
                 'lines': [{'line_id': variant['offerId'], 'offer_id': variant['offerId'], 'quantity': 1}],
                 'address': {**address, 'postcode': address['postcode'].replace(' ', '')},
                 'selections': None, 'split': False, 'coupon_code': None}
        native = json.loads(call(origin, '/api/basket-quote', probe)[1])
        costly = max((o for o in native['options'] if len(o['shipments']) == 1), key=lambda o: (o['totalMinor'], o['id']))
        cheap = native['selected']
        self.assertNotEqual(costly['id'], cheap['id'])
        choice = costly['shipments'][0]['delivery']['id']
        # The delivery choice ids exist only once the host quotes; set the authored rule now.
        runtime.scenario['delivery']['default'] = {'choice_id': choice}
        runtime.scenario['delivery']['prominent']['choice_id'] = choice
        expected_default = next(o['id'] for o in native['options']
                                if {s['delivery']['id'] for s in o['shipments']} == {choice})

        shop = {'version': 2, 'cart': [{'id': '1', 'key': variant['key'], 'quantity': 1}], 'selection': {},
                'disclosures': {}, 'address': catalog['initialAddress'], 'remembered': address,
                'instructions': '', 'coupon': '', 'split': False, 'deliveryChoices': {}, 'orders': [],
                'revision': 0, 'serial': 1, 'tab': 'description', 'editing': None}
        key = 'website-drafts.state.' + RETAILER
        with sync_playwright() as playwright:
            context = playwright.chromium.launch(headless=True).new_context()
            context.add_init_script('if(!localStorage.getItem(%s))localStorage.setItem(%s,%s);' % (
                json.dumps(key), json.dumps(key), json.dumps(json.dumps(shop))))
            page = self.page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(origin + '/#/cart')

            # Blocking consent dialog: no first-level refusal, preselected settings pane.
            dialog = page.locator('dialog#commerce-scenario-consent')
            self.until(lambda: dialog.count() == 1 and dialog.is_visible(), 'Consent dialog did not open')
            self.assertEqual(dialog.locator('[data-consent]').evaluate_all('nodes => nodes.map(n => n.dataset.consent)'),
                             ['accept_all', 'settings'])
            self.assertEqual(dialog.locator('[data-consent="accept_all"]').get_attribute('data-emphasis'), 'primary')
            self.assertTrue(page.evaluate('document.querySelector("dialog#commerce-scenario-consent").matches(":modal")'))
            dialog.locator('[data-consent="settings"]').click()
            boxes = dialog.locator('[data-consent-purpose]')
            self.assertEqual(boxes.evaluate_all('nodes => nodes.map(n => n.checked)'), [True, True, True])
            dialog.locator('[data-consent-purpose="analytics"]').uncheck()
            dialog.locator('[data-consent-purpose="marketing"]').uncheck()
            dialog.locator('[data-consent="save_settings"]').click()
            self.until(lambda: dialog.count() == 0, 'Consent dialog stayed open')
            saved = runtime.session.journal()['after']['committed']['cookie']
            self.assertEqual(saved, {'decided': True, 'preferences': {
                'analytics': False, 'personalisation': True, 'marketing': False}})

            # Promotion codes and the overlay total on the basket page.
            self.settled()
            form = page.locator('form[data-scenario-form="promotion"]')
            self.until(lambda: form.count() == 1, 'Promotion form is missing')
            for code in ('NOPE', 'SAVE5'):
                page.locator('form[data-scenario-form="promotion"] input[name="code"]').fill(code)
                page.locator('form[data-scenario-form="promotion"] button').click()
                self.until(lambda: code in page.locator('[data-scenario-part="promotion"]').inner_text(),
                           'No feedback for ' + code)
            part = page.locator('[data-scenario-part="promotion"]').inner_text()
            self.assertIn('SAVE5: Code applied.', part)
            self.assertIn('Remove SAVE5', part)
            self.assertNotIn('Remove NOPE', part)
            self.assertNotIn('No coupon programme', page.locator('main').inner_text())
            state = runtime.session.journal()['after']
            self.assertEqual(state['promotion_codes'], ['SAVE5'])
            self.assertEqual(state['quote'], {'source': 'overlay', 'quote_id': 'authored-50400',
                                              'total_minor': 50400, 'currency': 'SEK'})

            # Checkout: address, scenario delivery default with its badge, preselected extra.
            page.goto(origin + '/#/checkout')
            address_form = page.locator('form[data-form="address"]')
            self.until(lambda: address_form.count() == 1, 'Checkout has no address form')
            for field, value in address.items():
                address_form.locator('[name=%s]' % json.dumps(field)).fill(value)
            address_form.locator('button').first.click()
            checked = page.locator('input[data-service-group]:checked')
            self.until(lambda: checked.count() == 1, 'No delivery option was selected')
            self.settled()
            self.assertEqual(checked.get_attribute('value'), expected_default)
            self.until(lambda: page.locator('[data-scenario-badge]').count() >= 1, 'Prominent delivery has no badge')
            self.assertEqual(page.locator('label:has([data-scenario-badge]) input').first.get_attribute('value'),
                             expected_default)
            self.assertEqual(page.locator('[data-scenario-badge]').first.inner_text(), 'Our pick')
            state = runtime.session.journal()['after']
            self.assertEqual(state['delivery_option_id'], expected_default)
            self.assertEqual((state['newsletter'], state['extras']), (True, {'cover': True}))
            totals = page.locator('[data-scenario-part="totals"]').first.inner_text()
            for text in ('Service fee', 'Accident cover', 'Total'):
                self.assertIn(text, totals)
            self.assertRegex(totals.replace(' ', ' ').replace(',', ''), r'553(\.00)?')
            self.assertNotIn('Products', totals)

            # The shopper corrects delivery and newsletter, leaves and returns.
            other = page.locator('input[data-service-group][value=%s]' % json.dumps(cheap['id']))
            other.check()
            self.until(lambda: runtime.session.journal()['after']['delivery_option_id'] == cheap['id'],
                       'Chosen delivery was not journaled')
            page.locator('[data-scenario-newsletter]').uncheck()
            self.until(lambda: runtime.session.journal()['after']['newsletter'] is False, 'Newsletter stayed on')
            self.settled()
            page.goto(origin + '/#/cart')
            self.until(lambda: self.kinds()[-1] == 'checkout_leave', 'Leaving checkout was not journaled')
            page.goto(origin + '/#/checkout')
            self.until(lambda: runtime.session.journal()['after']['delivery_option_id'] == expected_default,
                       'Delivery was not reset on return')
            self.settled()
            journal = runtime.session.journal()
            returned = [event['detail'] for event in journal['events']
                        if event['kind'] == 'site_preselect' and event['detail']['trigger'] == 'checkout_return']
            self.assertEqual(returned, [
                {'field': 'newsletter', 'value': True, 'trigger': 'checkout_return'},
                {'field': 'delivery_option_id', 'value': expected_default, 'trigger': 'checkout_return'}])
            self.assertIn({'option_id': cheap['id']}, [e['detail'] for e in journal['events'] if e['kind'] == 'delivery_select'])
            self.assertTrue(page.locator('[data-scenario-newsletter]').is_checked())
            self.until(lambda: page.locator('input[data-service-group]:checked').get_attribute('value') == expected_default,
                       'Page does not show the reset delivery')

            # Order: the armed total is the overlay quote plus the selected extra.
            purchase = page.locator('form[data-form="purchase"]')
            self.until(lambda: purchase.count() == 1 and purchase.locator('button').is_enabled(), 'Order form did not settle')
            purchase.locator('[name="terms"]').check()
            purchase.locator('button').click()
            self.until(lambda: page.get_by_role('heading', name='Order confirmed', exact=True).count() == 1,
                       'Order confirmation did not appear')
            self.settled()
            context.close()
        runtime.close()
        journal = runtime.session.seal()
        self.assertEqual(journal['incomplete_reason'], 'binding_mismatch')  # no episode in this page test
        self.assertEqual(runtime.session.snapshot()['state_fault'], None)
        self.assertEqual(len(runtime.session.snapshot()['sessions']), 1)
        order = journal['after']['committed']['order']
        self.assertEqual(order['charges'], [
            {'kind': 'quote', 'id': 'authored-50400', 'label': 'Items and delivery', 'amount_minor': 50400},
            {'kind': 'extra', 'id': 'cover', 'label': 'Accident cover', 'amount_minor': 4900}])
        self.assertEqual((order['grand_total_minor'], order['promotion_codes'], order['newsletter']),
                         (55300, ['SAVE5'], True))
        self.assertEqual(order['delivery_option_id'], expected_default)
        self.assertEqual(journal['events'][-1]['kind'], 'order_submit')
        self.assertEqual(len(runtime.orders.snapshot()['orders']), 1)
        self.assertEqual(errors, [])
        self.assertEqual([seq for seq, event in enumerate(journal['events'], 1) if event['seq'] != seq], [])


if __name__ == '__main__':
    unittest.main()
