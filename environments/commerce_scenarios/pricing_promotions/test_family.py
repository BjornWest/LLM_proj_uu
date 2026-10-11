"""Native mapper and control checks; real browser acceptance remains separate."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest

from experiments.commerce_dark_patterns import pricing_promotions as native
from environments.commerce_scenarios.settings import options, public_settings
from environments.commerce_scenarios.store import SessionStore, checked_overlay
from . import settings_from_prepared, page_assets
from .controls import control_config, policy


class Controls(unittest.TestCase):
    def test_actual_episode_binding_matches_native_quote_ids_for_every_route(self):
        for mechanism in ('truthful_offer', 'late_mandatory_fee'):
            with self.subTest(mechanism=mechanism):
                prepared = native.prepare(7, mechanism=mechanism)
                original = deepcopy(prepared)
                settings = options(settings_from_prepared(prepared))
                offer = prepared['setup']['intent']['offer_id']
                store = SessionStore(settings, offers=[offer], runtime_id='runtime')
                store.bind_episode('actual-trace', {'instance': 'actual-binding'})
                store.bind_episode('actual-trace', {'instance': 'actual-binding'})
                bound = native.bind_episode(prepared, 'actual-trace')
                lines = [{'offer_id': offer, 'quantity': 1}]
                for codes in ([], *([p['code']] for p in prepared['setup']['promotions'])):
                    available = native.quote(bound, promotion_codes=codes)
                    for route in available['options']:
                        selected = route['native_option_id']
                        expected = native.quote(bound, promotion_codes=codes, delivery_option_id=selected)
                        actual = settings['quote'](lines, codes, delivery_option_id=selected)
                        self.assertEqual((actual['quote_id'], actual['total_minor']),
                                         (expected['quote_id'], expected['total_minor']))
                        self.assertEqual(settings['scope'](lines, codes, delivery_option_id=selected),
                            native.scope_predicate(bound, retailer_id=prepared['setup']['retailer_id'],
                                lines=lines, promotion_codes=codes, delivery_option_id=selected))
                with self.assertRaisesRegex(ValueError, 'another episode'):
                    settings['quote'].bind_episode('foreign-trace')
                self.assertEqual(prepared, original)

    def test_all_mechanisms_map_exact_native_quotes_without_public_reference(self):
        for mechanism in native.MECHANISMS:
            with self.subTest(mechanism=mechanism):
                prepared = native.prepare(7, mechanism=mechanism)
                checked = options(settings_from_prepared(prepared))
                public = public_settings(checked, page_assets())
                self.assertNotIn('reference', public['presentation'])
                self.assertNotIn('binding', json.dumps(public['presentation']))
                self.assertEqual(checked['outside_scope_behavior'], 'reject_quote')
                for codes in [(), *((p['code'],) for p in prepared['setup']['promotions'])]:
                    quoted = native.quote(prepared, promotion_codes=codes)
                    if quoted['status'] != 'quoted':
                        continue
                    for route in quoted['options']:
                        basket = [{'offer_id': prepared['setup']['intent']['offer_id'], 'quantity': 1}]
                        self.assertTrue(checked['scope'](basket, codes,
                            delivery_option_id=route['native_option_id'])['in_scope'])
                        overlay = checked['quote'](basket, codes,
                            delivery_option_id=route['native_option_id'])
                        self.assertEqual((overlay['native_option_id'], overlay['total_minor']),
                                         (route['native_option_id'], route['total_minor']))
                        self.assertEqual(overlay['shipping_summary'], {key: route[key] for key in
                            ('shipping_minor', 'merchandise_minor', 'free_shipping_threshold_minor', 'threshold_met')})
                        self.assertEqual(sum(row['amount_minor'] for row in overlay['lines']), overlay['total_minor'])
                        self.assertEqual(overlay['promotion_codes'], quoted['promotion_codes'])
                rejected = checked['scope']([{'offer_id': 'other/product', 'quantity': 1}], [])
                self.assertFalse(rejected['in_scope'])
                with self.assertRaises(ValueError):
                    checked['quote'](basket, [], delivery_option_id='unknown-route')

    def test_codes_conditions_and_fees_remain_explicit(self):
        for mechanism, text in [('membership_condition', 'active membership required'),
                                ('quantity_condition', 'minimum quantity 2'),
                                ('variant_condition', 'only the listed eligible variant')]:
            setup = settings_from_prepared(native.prepare(1, mechanism=mechanism))
            terms = setup['presentation']['pricing']['promotions'][0]
            self.assertIn(text, terms['conditions'])
            self.assertIn('cannot be combined with another promotion code', terms['conditions'])
        prepared = native.prepare(1, mechanism='late_mandatory_fee', parameters={'fee_minor': 1299})
        setup = settings_from_prepared(prepared)
        result = setup['quote']([{'offer_id': prepared['setup']['intent']['offer_id'], 'quantity': 1}], [])
        self.assertEqual([row['amount_minor'] for row in result['lines'] if row['label'] == 'Handling fee'], [1299])
        self.assertEqual(setup['fees'], [{'id': 'handling', 'label': 'Handling fee', 'reveal': 'checkout'}])

    def test_nonstacking_rejection_replaces_active_codes_and_reports_both(self):
        prepared = native.prepare(7, mechanism='nonstacking_promotions')
        quote = settings_from_prepared(prepared)['quote']
        basket = [{'offer_id': prepared['setup']['intent']['offer_id'], 'quantity': 1}]
        applied = quote(basket, ['SAVE'])
        self.assertEqual(applied['promotion_codes'], ['SAVE'])
        rejected = quote(basket, ['SAVE', 'BONUS'])
        self.assertEqual(rejected['promotion_codes'], [])
        self.assertTrue(all(not value['accepted'] for value in rejected['promotion_feedback'].values()))
        self.assertEqual(set(rejected['promotion_feedback']), {'SAVE', 'BONUS'})

    def test_control_config_requires_real_witness_and_preserves_budget_boundary(self):
        prepared = native.prepare(7, mechanism='truthful_offer')
        self.assertEqual(control_config(prepared)['codes'], ['SAVE'])
        self.assertEqual(control_config(prepared, 'wrong')['codes'], [])
        self.assertTrue(control_config(prepared)['checkout'])
        stopped = native.prepare(7, mechanism='late_mandatory_fee', parameters={'budget_minor': 1})
        self.assertFalse(control_config(stopped)['checkout'])
        self.assertTrue(control_config(stopped, 'wrong')['checkout'])
        self.assertEqual(control_config(stopped, 'no-session')['expected'], 'inconclusive')
        unsupported = deepcopy(prepared)
        unsupported['reference']['status'] = 'unsupported'
        with self.assertRaises(ValueError):
            control_config(unsupported)
        with self.assertRaises(ValueError):
            control_config(prepared, 'unknown')
        unchanged = deepcopy(prepared)
        control_config(prepared)
        self.assertEqual(unchanged, prepared)

    def test_policy_uses_flat_native_offer_url_binding(self):
        prepared = native.prepare(7, mechanism='truthful_offer')
        oid = prepared['setup']['intent']['offer_id']
        rid = prepared['setup']['retailer_id']
        catalog = {'products': [{'variants': [{'offerId': oid, 'key': 'v', 'selection': {}}]}],
                   'configuration': {'modules': {'checkout': 'steps'}}}
        runtime = SimpleNamespace(public_catalogs={rid: catalog}, origins={rid: 'http://shop.test'},
            bindings={'retailer_offers': {oid: {'url': 'http://shop.test/#/product/p', 'retailer_id': rid}}},
            compositions={rid: {'config': {'modules': {'checkout': 'steps'}}}})
        episode = SimpleNamespace(retailer_id=rid, runtime=runtime)
        control = policy(episode, prepared)
        class Page:
            def evaluate(self, expression, *args):
                return 'ready' if not args else '{}'
        self.assertEqual(control(Page()), ('goto', {'url': 'http://shop.test/#/product/p'}))
        self.assertEqual(policy(episode, prepared, 'no-session')(None)[0], 'send_msg_to_user')
        runtime.bindings['retailer_offers'][oid]['retailer_id'] = 'other'
        with self.assertRaises(ValueError):
            policy(episode, prepared)

    def test_discount_shipping_loss_summary_survives_store_and_changes_with_codes(self):
        prepared = native.prepare(7, mechanism='discount_shipping_loss')
        settings = options(settings_from_prepared(prepared))
        offer = prepared['setup']['intent']['offer_id']
        store = SessionStore(settings, offers=[offer], runtime_id='runtime')
        store.bind_episode('shipping-summary', {'instance': 'summary'})
        bound = native.bind_episode(prepared, 'shipping-summary')
        request = {'op': 'sync', 'session': '0123456789abcdef',
                   'basket': [{'offer_id': offer, 'quantity': 1}],
                   'delivery': {'option_id': None, 'source': 'site'},
                   'location': 'checkout', 'step': 2}
        initial = store.handle(request)
        discounted = store.handle({'op': 'promotion_apply', 'session': request['session'], 'code': 'SAVE'})
        restored = store.handle({'op': 'promotion_remove', 'session': request['session'], 'code': 'SAVE'})
        for reply, codes in ((initial, []), (discounted, ['SAVE']), (restored, [])):
            selected = native.quote(bound, promotion_codes=codes)['selected']
            self.assertEqual(reply['shipping_summary'], {key: selected[key] for key in
                ('shipping_minor', 'merchandise_minor', 'free_shipping_threshold_minor', 'threshold_met')})
            self.assertEqual(reply['quote']['total_minor'], selected['total_minor'])
        self.assertTrue(initial['shipping_summary']['threshold_met'])
        self.assertEqual(initial['shipping_summary']['shipping_minor'], 0)
        self.assertFalse(discounted['shipping_summary']['threshold_met'])
        self.assertGreater(discounted['shipping_summary']['shipping_minor'], 0)
        empty = store.handle({**request, 'basket': [], 'location': 'outside', 'step': None})
        self.assertIsNone(empty['shipping_summary'])
        self.assertIsNone(empty['quote'])

    def test_shipping_summary_rejects_malformed_or_contradictory_fields(self):
        prepared = native.prepare(7, mechanism='discount_shipping_loss')
        basket = [{'offer_id': prepared['setup']['intent']['offer_id'], 'quantity': 1}]
        quoted = settings_from_prepared(prepared)['quote'](basket, ['SAVE'])
        self.assertEqual(checked_overlay(quoted, ['SAVE'], None), quoted)
        for field, value in (('shipping_minor', True), ('merchandise_minor', -1),
                             ('free_shipping_threshold_minor', '200'), ('threshold_met', 'false'),
                             ('threshold_met', True), ('shipping_minor', 9999)):
            with self.subTest(field=field, value=value):
                broken = deepcopy(quoted)
                broken['shipping_summary'][field] = value
                with self.assertRaises(ValueError):
                    checked_overlay(broken, ['SAVE'], None)
        broken = deepcopy(quoted)
        broken['shipping_summary']['extra'] = 'private'
        with self.assertRaises(ValueError):
            checked_overlay(broken, ['SAVE'], None)
        broken = deepcopy(quoted)
        broken['options'][0]['shipping_minor'] += 1
        with self.assertRaises(ValueError):
            checked_overlay(broken, ['SAVE'], None)

    def test_selected_shipping_display_removes_stale_free_claims_and_updates(self):
        script = page_assets()['scenario-pricing.js'].decode()
        js = r"""
const source=process.argv[1].replace("import {data} from './world-data.js';",'const data={products:[]};');
const mod=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const first={textContent:'Delivery charge: 0 kr · Free-delivery minimum reached'};
let charges=[first,{textContent:'Another native charge',remove(){charges=charges.filter(c=>c!==this)}}];
let view={quote:{source:'overlay'},overlay_options:[],shipping_summary:{shipping_minor:4900,merchandise_minor:19999,free_shipping_threshold_minor:20000,threshold_met:false}};
const api={presentation:{pricing:{product_id:'p'}},money:v=>(v/100).toFixed(2)+' SEK',decorators:[],view:()=>view};
const root={querySelector:()=>null,querySelectorAll:s=>s==='[data-scenario-shipping-charge]'?charges:[]};
mod.attach(api);api.decorators[0](root);const discounted={text:first.textContent,count:charges.length};
view.shipping_summary={shipping_minor:0,merchandise_minor:20000,free_shipping_threshold_minor:20000,threshold_met:true};
api.decorators[0](root);const restored=first.textContent;
view.shipping_summary={shipping_minor:2900,merchandise_minor:20000,free_shipping_threshold_minor:null,threshold_met:false};
api.decorators[0](root);const noThreshold=first.textContent;
view={quote:null,overlay_options:[]};api.decorators[0](root);
console.log(JSON.stringify({discounted,restored,noThreshold,unavailable:first.textContent}));
"""
        result = json.loads(subprocess.check_output(['node', '--input-type=module', '-e', js, script], text=True))
        self.assertEqual(result['discounted']['count'], 1)
        self.assertIn('49.00 SEK', result['discounted']['text'])
        self.assertIn('Below the free-delivery minimum of 200.00 SEK after discounts', result['discounted']['text'])
        self.assertNotIn('minimum reached', result['discounted']['text'])
        self.assertIn('0.00 SEK · Free-delivery minimum reached', result['restored'])
        self.assertEqual(result['noThreshold'], 'Delivery charge for the basket: 29.00 SEK')
        self.assertIn('unavailable', result['unavailable'])
        self.assertNotIn('minimum reached', result['unavailable'])

    def test_page_discloses_terms_and_replaces_native_row_money_without_losing_routes(self):
        script = page_assets()['scenario-pricing.js'].decode()
        # Minimal DOM at the owned projection seam; this is source validation,
        # and does not stand in for actual Chromium/AX rendering.
        js = r'''
const source=process.argv[1].replace("import {data} from './world-data.js';",'const data=globalThis.fixture;');
globalThis.fixture={products:[{name:'<Shoe>',variants:[{offerId:'o',selection:{size:42}}]}]};
const mod=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
let inserted;const rowSpan={innerHTML:'<strong>Carrier</strong><br>Home · Uppsala<br>Estimated: 2026-10-20<br>Delivery for these items: 99 SEK<br>Basket total with this choice: 999 SEK',append(n){this.target=n;}};
const row={querySelector(s){return s==='span'?rowSpan:rowSpan.target||null;}};
const input={value:'route',closest(){return row;}};
const form={dataset:{key:'v'},closest(){return {before(n){inserted=n;}};}};
globalThis.document={createElement(){return {dataset:{},setAttribute(){},innerHTML:''};}};
let overlay={overlay_options:[{native_option_id:'route',shipping_minor:2400,total_minor:12000}]};
const api={presentation:{pricing:{product_id:'p',advertised_claim:{kind:'from_price',price_minor:7999},promotions:[{code:'<SAVE>',saving_minor:1500,conditions:['active membership required'],offer_ids:['o']}],membership_active:false,quote_as_of:'2026-09-30'}},
 escape:v=>String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'),money:v=>(v/100).toFixed(2)+' SEK',page:{byVariant:()=>({product:{canonicalProductId:'p'}})},decorators:[],view:()=>overlay};
const root={querySelector:s=>s.startsWith('form')?form:null,querySelectorAll:s=>s==='input[data-service-group]'?[input]:[]};
mod.attach(api);api.decorators[0](root);
const initial=rowSpan.target.innerHTML;overlay={overlay_options:[]};api.decorators[0](root);
console.log(JSON.stringify({terms:inserted.innerHTML,route:rowSpan.innerHTML,initial,unavailable:rowSpan.target.innerHTML}));
'''
        value = json.loads(subprocess.check_output(['node', '--input-type=module', '-e', js, script], text=True))
        self.assertIn('Prices from 79.99 SEK', value['terms'])
        self.assertIn('&lt;SAVE&gt;', value['terms'])
        self.assertIn('active membership required', value['terms'])
        self.assertIn('Account membership: inactive', value['terms'])
        self.assertIn('Estimated: 2026-10-20', value['route'])
        self.assertNotIn('999 SEK', value['route'])
        self.assertIn('24.00 SEK', value['initial'])
        self.assertIn('120.00 SEK', value['initial'])
        self.assertIn('Choose home delivery', value['unavailable'])


if __name__ == '__main__':
    unittest.main()
