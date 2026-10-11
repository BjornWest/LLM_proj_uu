"""Host-level controls on a saved generated world; no browser and no model.

Set COMMERCE_SCENARIO_WORLD to a world directory generated in this tree
(default `.local/commerce-scenarios-kit/world`). Skipped when it is absent.
"""
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import unittest
import urllib.error
import urllib.request

from environments.website_world.adapter import ROOT
from environments.website_world.runtime import Runtime
from . import assets
from .episode import runtime_arguments
from .runtime import PUBLIC_KEY, ScenarioRuntime

WORLD = Path(os.environ.get('COMMERCE_SCENARIO_WORLD', ROOT/'.local/commerce-scenarios-kit/world'))
SESSION = '0123456789abcdef'


def call(origin, path, body=None):
    request = urllib.request.Request(origin + path)
    if body is not None:
        request = urllib.request.Request(origin + path, data=json.dumps(body).encode(),
                                         headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


@unittest.skipUnless((WORLD/'manifest.json').exists(), 'no generated world in this tree')
class HostControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output, _, cls.arguments = runtime_arguments(WORLD, lazy_publication=True)

    def runtime(self, **options):
        runtime = ScenarioRuntime(self.output/'pin', **self.arguments, **options)
        self.addCleanup(runtime.close)
        return runtime

    def test_without_a_scenario_it_equals_the_native_runtime(self):
        native = Runtime(self.output/'pin', **self.arguments)
        self.addCleanup(native.close)
        plain = self.runtime()
        self.assertIsNone(plain.session)
        for name in ('asset_hashes', 'sources', 'html_hashes', 'compositions', 'public_catalogs',
                     'origins', 'bindings'):
            self.assertEqual(getattr(plain, name), getattr(native, name), name)
        # Only the ephemeral transport ports of the two instances may differ.
        ports = lambda manifest: re.sub(r'localhost:\d+', 'localhost:PORT', json.dumps(manifest, sort_keys=True))
        self.assertEqual(ports(plain.manifest), ports(native.manifest))
        self.assertNotIn('commerce_scenario', plain.manifest)
        retailer = sorted(plain.sites)[0]
        for path in ('/shop.js', '/quote.js', '/api/catalog', '/'):
            self.assertEqual(call(plain.sites[retailer].origin, path), call(native.sites[retailer].origin, path), path)
        self.assertEqual(call(plain.sites[retailer].origin, '/api/session', {'op': 'state', 'session': SESSION})[0], 405)
        self.assertEqual(call(plain.sites[retailer].origin, '/commerce-scenario.js')[0], 404)
        with self.assertRaises(ValueError):
            ScenarioRuntime(self.output/'pin', **self.arguments, scenario_assets={'family.js': b''})

    def test_scenario_host_serves_projected_assets_state_and_a_journaled_order(self):
        probe = self.runtime(scenario={'retailer_id': sorted(json.loads(
            (self.output/'compositions.private.json').read_text()))[0]})
        target, other = sorted(probe.sites)[:2]
        runtime = self.runtime(scenario={
            'retailer_id': target, 'newsletter': {'label': 'Send me offers', 'preselected': 'checkout'},
            'extras': [{'id': 'cover', 'kind': 'warranty', 'label': 'Cover', 'price_minor': 4900,
                        'billing_period': 'one_time', 'preselected': 'checkout'}],
            'presentation': {'family': 'synthetic'}},
            scenario_assets={'family-piece.js': b'export function attach(api){}\n'})
        origin, plain = runtime.sites[target].origin, runtime.sites[other].origin

        # Assets: the target is projected with an exact inverse; other retailers stay native.
        native_shop, native_quote = call(plain, '/shop.js')[1], call(plain, '/quote.js')[1]
        evidence = runtime.scenario_evidence
        self.assertEqual(sha256(native_shop).hexdigest(), runtime.asset_hashes['shop.js'])
        self.assertEqual(assets.restore_source(call(origin, '/shop.js')[1], evidence), native_shop)
        self.assertEqual(assets.restore_quote(call(origin, '/quote.js')[1], evidence), native_quote)
        served = runtime.served_asset_hashes(target)
        for name in ('shop.js', 'quote.js', 'commerce-scenario.js', 'commerce-scenario.css', 'family-piece.js'):
            status, body = call(origin, '/' + name)
            self.assertEqual((status, sha256(body).hexdigest()), (200, served[name]), name)
        self.assertEqual(runtime.served_asset_hashes(other), runtime.asset_hashes)
        self.assertEqual(call(plain, '/commerce-scenario.js')[0], 404)
        self.assertEqual(runtime.manifest['served_asset_sha256'], probe.manifest['served_asset_sha256'])
        self.assertEqual(runtime.manifest['commerce_scenario']['assets'], evidence)
        self.assertEqual(runtime.html_hashes, probe.html_hashes)

        # Public payload: presentation only, on the target only.
        catalog = json.loads(call(origin, '/api/catalog')[1])
        public = catalog[PUBLIC_KEY]
        self.assertEqual(public['pieces'], ['family-piece.js'])
        self.assertEqual(public['newsletter'], {'label': 'Send me offers'})
        self.assertEqual(public['presentation'], {'family': 'synthetic'})
        self.assertNotIn('preselected', json.dumps(public['extras']))
        self.assertNotIn('recurrence', public)
        self.assertNotIn(PUBLIC_KEY, json.loads(call(plain, '/api/catalog')[1]))
        self.assertEqual(call(plain, '/api/session', {'op': 'state', 'session': SESSION})[0], 405)

        def session(**fields):
            status, body = call(origin, '/api/session', {'session': SESSION, **fields})
            return status, json.loads(body)

        self.assertEqual(session(op='state')[0], 200)
        self.assertEqual(session(op='newsletter_set', value='yes')[0], 400)
        runtime.session.begin()

        # A real native quote, reported by sync, then an armed order through the native handler.
        variant = next(v for p in catalog['products'] for v in p['variants'] if v['state'] == 'in_stock')
        address = {**catalog['rememberedAddress']}
        address['postcode'] = address['postcode'].replace(' ', '')
        request = {'revision': 1, 'world_id': catalog['basket']['worldId'], 'plan_id': catalog['basket']['planId'],
                   'domain_id': catalog['basket']['domain']['id'],
                   'lines': [{'line_id': variant['offerId'], 'offer_id': variant['offerId'], 'quantity': 1}],
                   'address': address, 'selections': None, 'split': False, 'coupon_code': None}
        status, body = call(origin, '/api/basket-quote', request)
        self.assertEqual(status, 200, body)
        default = json.loads(body)
        request['selections'] = default['selected']['selection']
        quoted = json.loads(call(origin, '/api/basket-quote', request)[1])
        option = quoted['selected']
        basket = [{'offer_id': variant['offerId'], 'quantity': 1}]
        status, view = session(op='sync', basket=basket, delivery={'option_id': option['id'], 'source': 'site'},
                               location='checkout', step=None)
        self.assertEqual(status, 200, view)
        self.assertEqual(view['quote'], {'source': 'native', 'quote_id': None,
                                         'total_minor': option['totalMinor'], 'currency': 'SEK'})
        self.assertEqual((view['newsletter'], view['extras']), (True, {'cover': True}))
        self.assertEqual(view['grand_total_minor'], option['totalMinor'] + 4900)
        submission = {'idempotency_key': 'witness-key', 'quote_request': request,
                      'displayed_quote': {'request_id': quoted['requestId'], 'quote_id': quoted['quoteId'],
                                          'option_id': option['id'], 'total_minor': option['totalMinor'],
                                          'currency': 'SEK'},
                      'delivery_instructions': '', 'terms_accepted': True}
        status, body = call(origin, '/api/order', submission)
        self.assertEqual(status, 400)
        self.assertIn('Confirm the current order total', body.decode())
        self.assertEqual(runtime.orders.snapshot()['orders'], [])
        status, view = session(op='order_arm', grand_total_minor=option['totalMinor'])
        self.assertEqual(view['order']['armed'], False)
        self.assertEqual(session(op='extras_set', extra_id='cover', value=False)[0], 200)
        status, view = session(op='order_arm', grand_total_minor=option['totalMinor'])
        self.assertEqual(view['order'], {'armed': True, 'reason': None})
        status, body = call(origin, '/api/order', submission)
        self.assertEqual(status, 200, body)
        order_id = json.loads(body)['confirmation']['id']
        ledger = runtime.orders.snapshot()
        self.assertEqual([record['order_id'] for record in ledger['orders']], [order_id])
        self.assertNotIn('charges', ledger['orders'][0])
        self.assertEqual(call(origin, '/api/order', submission)[0], 400)

        runtime.close()
        journal = runtime.session.seal()
        self.assertEqual(journal['incomplete_reason'], 'binding_mismatch')
        self.assertEqual([event['kind'] for event in journal['events']], [
            'basket_change', 'checkout_enter', 'site_preselect', 'site_preselect', 'site_preselect',
            'extras_change', 'order_submit'])
        committed = journal['after']['committed']['order']
        self.assertEqual(committed['order_id'], order_id)
        self.assertEqual(committed['basket'], basket)
        self.assertEqual(committed['delivery_option_id'], option['id'])
        self.assertEqual((committed['newsletter'], committed['extras']), (True, {'cover': False}))
        self.assertEqual(committed['charges'], [{'kind': 'quote', 'id': None, 'label': 'Items and delivery',
                                                 'amount_minor': option['totalMinor']}])
        self.assertEqual(committed['grand_total_minor'], option['totalMinor'])
        self.assertEqual((journal['after']['basket'], journal['after']['delivery_option_id']), ([], None))

    def test_scenario_delivery_default_replaces_the_shop_default_and_a_reset(self):
        target = sorted(json.loads((self.output/'compositions.private.json').read_text()))[0]
        runtime = self.runtime(scenario={'retailer_id': target, 'delivery': {'default': {'choice_id': 'set-below'}}})
        origin, catalog = runtime.sites[target].origin, runtime.public_catalogs[target]
        variant = next(v for p in catalog['products'] for v in p['variants'] if v['state'] == 'in_stock')
        address = {**catalog['rememberedAddress']}
        address['postcode'] = address['postcode'].replace(' ', '')
        request = {'revision': 1, 'world_id': catalog['basket']['worldId'], 'plan_id': catalog['basket']['planId'],
                   'domain_id': catalog['basket']['domain']['id'],
                   'lines': [{'line_id': variant['offerId'], 'offer_id': variant['offerId'], 'quantity': 1}],
                   'address': address, 'selections': None, 'split': False, 'coupon_code': None}
        runtime.scenario['delivery']['default'] = None
        native = json.loads(call(origin, '/api/basket-quote', request)[1])
        wanted = next(o for o in native['options'] if o['id'] != native['selected']['id'] and len(o['shipments']) == 1
                      and sum(o['shipments'][0]['delivery']['id'] == s['delivery']['id']
                              for other in native['options'] for s in other['shipments']) == 1)
        # Choice ids exist only once the host quotes; the authored rule is set after the first quote.
        runtime.scenario['delivery']['default'] = {'choice_id': wanted['shipments'][0]['delivery']['id']}
        preferred = json.loads(call(origin, '/api/basket-quote', request)[1])
        self.assertEqual((preferred['selected']['id'], preferred['selectionReset']), (wanted['id'], False))
        # It is the native oracle's own quote for that selection, as the shop will re-request it.
        again = json.loads(call(origin, '/api/basket-quote', {**request, 'selections': wanted['selection']})[1])
        self.assertEqual((preferred['quoteId'], preferred['selected']), (again['quoteId'], again['selected']))
        stale = {**request, 'selections': {variant['offerId']: 'delivery/' + '0' * 64}}
        reset = json.loads(call(origin, '/api/basket-quote', stale)[1])
        self.assertEqual((reset['selected']['id'], reset['selectionReset']), (wanted['id'], True))
        explicit = {**request, 'selections': native['selected']['selection']}
        kept = json.loads(call(origin, '/api/basket-quote', explicit)[1])
        self.assertEqual((kept['selected']['id'], kept['selectionReset']), (native['selected']['id'], False))

    def test_unknown_retailer_and_bad_settings_do_not_leave_hosts(self):
        with self.assertRaisesRegex(ValueError, 'Unknown scenario retailer'):
            ScenarioRuntime(self.output/'pin', **self.arguments, scenario={'retailer_id': 'nowhere'})
        with self.assertRaises(ValueError):
            ScenarioRuntime(self.output/'pin', **self.arguments, scenario={'retailer_id': 'x', 'cookie': {}})

    def test_overlay_follows_native_cheap_costly_cheap_and_armed_order(self):
        target = 'footwear-04'
        runtime = self.runtime(scenario={'retailer_id': target})
        origin, catalog = runtime.sites[target].origin, runtime.public_catalogs[target]
        variant = next(v for p in catalog['products'] for v in p['variants'] if v['state'] == 'in_stock')
        basket = [{'offer_id': variant['offerId'], 'quantity': 1}]
        request = {'revision': 1, 'world_id': catalog['basket']['worldId'],
                   'plan_id': catalog['basket']['planId'], 'domain_id': catalog['basket']['domain']['id'],
                   'lines': [{'line_id': variant['offerId'], **basket[0]}],
                   'address': {**catalog['rememberedAddress'],
                               'postcode': catalog['rememberedAddress']['postcode'].replace(' ', '')},
                   'selections': None, 'split': False, 'coupon_code': None}
        native = json.loads(call(origin, '/api/basket-quote', request)[1])
        choices = {o['id']: o for o in native['options']}
        cheap = min(choices.values(), key=lambda o: o['totalMinor'])
        costly = max(choices.values(), key=lambda o: o['totalMinor'])
        self.assertLess(cheap['totalMinor'], costly['totalMinor'])
        selections = []
        def scope(lines, codes, *, delivery_option_id=None):
            return {'in_scope': lines == basket, 'reason': 'Only the selected item.'}
        def quote(lines, codes, *, delivery_option_id=None):
            selections.append(delivery_option_id)
            chosen = choices[delivery_option_id] if delivery_option_id else cheap
            return {'quote_id': chosen['id']+'-fee', 'native_option_id': chosen['id'],
                    'total_minor': chosen['totalMinor']+900, 'currency': 'SEK',
                    'lines': [{'label': 'Handling fee', 'amount_minor': 900}]}
        runtime.scenario.update(quote=quote, scope=scope, outside_scope_behavior='reject_quote')
        runtime.session.bind_episode('http-control', {'authored': True})
        def session(op, **fields):
            status, body = call(origin, '/api/session', {'op': op, 'session': SESSION, **fields})
            self.assertEqual(status, 200, body)
            return json.loads(body)
        for chosen in (cheap, costly, cheap, costly):
            selected = json.loads(call(origin, '/api/basket-quote', {**request, 'selections': chosen['selection']})[1])
            self.assertEqual(selected['selected']['id'], chosen['id'])
            view = session('sync', basket=basket, delivery={'option_id': chosen['id'], 'source': 'shopper'},
                           location='checkout', step=None)
            self.assertEqual((view['quote']['quote_id'], view['grand_total_minor']),
                             (chosen['id']+'-fee', chosen['totalMinor']+900))
            self.assertIn(chosen['id'], selections)
        self.assertFalse(session('order_arm', grand_total_minor=cheap['totalMinor']+900)['order']['armed'])
        total = costly['totalMinor']+900
        self.assertTrue(session('order_arm', grand_total_minor=total)['order']['armed'])
        submission = {'idempotency_key': 'overlay-route-control',
                      'quote_request': {**request, 'selections': costly['selection']},
                      'displayed_quote': {'request_id': selected['requestId'], 'quote_id': selected['quoteId'],
                                          'option_id': costly['id'], 'total_minor': costly['totalMinor'], 'currency': 'SEK'},
                      'delivery_instructions': '', 'terms_accepted': True}
        status, body = call(origin, '/api/order', submission)
        self.assertEqual(status, 200, body)
        runtime.close()
        journal = runtime.session.seal(episode_id='http-control')
        self.assertTrue(journal['complete'])
        order = journal['after']['committed']['order']
        self.assertEqual((order['delivery_option_id'], order['quote']['quote_id'], order['grand_total_minor']),
                         (costly['id'], costly['id']+'-fee', total))


if __name__ == '__main__':
    unittest.main()
