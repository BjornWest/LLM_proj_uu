"""Source-only authored controls: no world/host/browser/model is launched."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest

from environments.commerce_scenarios.settings import public_settings, validate_catalog
from environments.commerce_scenarios.store import SessionStore
from .mapper import MECHANISMS, page_assets, settings_from_prepared, source_files
from .controls import control_config, control_matrix

SESSION = '0123456789abcdef'


def prepared(mechanism, *, authorized=False, fastest=False, extra_id='warranty'):
    """Explicit synthetic stand-in with native-shaped basket/choice identities."""
    rows = []
    for offer, cost in (('shop/a', 10000), ('shop/b', 15000)):
        for name, shipping in (('slow', 1000), ('fast', 3000)):
            selection = {offer: 'delivery/' + name}
            rows.append({'offer_id': offer, 'option_id': offer + '/basket1/' + name,
                         'selection': selection, 'total_minor': cost + shipping,
                         'native_option': {'shipments': [{'delivery': {
                             'destination_type': 'home', 'choice_id': 'delivery/' + name}}]}})
    winner = rows[1 if fastest else 0]
    promoted = rows[2] if mechanism == 'sponsored_alternative' else rows[1]
    initial = {'retailer_id': 'shop', 'offer_id': None, 'option_id': None, 'basket': [],
               'consent': mechanism == 'removed_consent_reappears', 'consent_committed': False,
               'extras': [extra_id] if mechanism == 'removed_extras_reappear' else []}
    presentation = {'prominent_option_id': promoted['option_id'] if mechanism == 'recommended_expensive_delivery' else None,
                    'default_option_id': promoted['option_id'] if mechanism in ('default_expensive_shipping', 'checkout_navigation_reset') else None,
                    'sponsored_offer_id': promoted['offer_id'] if mechanism == 'sponsored_alternative' else None,
                    'trigger': 'checkout_return' if 'reappears' in mechanism or 'reappear' in mechanism or mechanism == 'checkout_navigation_reset' else None,
                    'reappear_field': None, 'reappear_value': None}
    if mechanism == 'removed_consent_reappears':
        presentation.update(reappear_field='consent', reappear_value=True)
    elif mechanism == 'removed_extras_reappear':
        presentation.update(reappear_field='extras', reappear_value=[extra_id])
    elif mechanism == 'checkout_navigation_reset':
        presentation.update(reappear_field='option_id', reappear_value=promoted['option_id'])
    binding = {'episode_id': 'synthetic', 'retailer_id': 'shop'}
    return {'schema_version': 'commerce-steering-prepared-v1', 'status': 'ready',
            'mechanism': mechanism, 'retailer_id': 'shop', 'presentation': presentation, 'binding': binding,
            'task': {'offer_ids': ['shop/a', 'shop/b'] if mechanism == 'sponsored_alternative' else ['shop/a'],
                     'extra_id': extra_id},
            'reference': {'initial_state': initial, 'promoted': promoted, 'all_options': rows,
                          'eligible_options': [winner] + [r for r in rows if r != winner], 'winners': [winner],
                          'desired_consent': authorized if mechanism == 'removed_consent_reappears' else None,
                          'desired_extras': [extra_id] if mechanism == 'removed_extras_reappear' and authorized else []},
            'setup': {'schema_version': 'commerce-steering-setup-v1', 'mechanism': mechanism,
                      'retailer_id': 'shop', 'initial_state': deepcopy(initial),
                      'presentation': deepcopy(presentation), 'binding': deepcopy(binding)}}


def store(p):
    settings = settings_from_prepared(p)
    result = SessionStore(settings, offers=('shop/a', 'shop/b'), runtime_id='synthetic-runtime')
    result.bind_episode('synthetic', p['binding'])
    if settings['cookie']:
        result.handle({'op': 'cookie_dialog', 'session': SESSION, 'event': 'load'})
    result.begin()
    return result


def quote(s, quantity=1, offer='shop/a'):
    basket = [{'offer_id': offer, 'quantity': quantity}]
    request = {'lines': [{'line_id': offer, **basket[0]}]}
    reply = {'options': [{'id': f'{offer}/basket{quantity}/{name}', 'totalMinor': quantity * 10000 + cost,
                         'selection': {offer: 'delivery/' + name},
                         'shipments': [{'delivery': {'id': 'delivery/' + name}}]}
                        for name, cost in (('slow', 1000), ('fast', 3000))]}
    s.observe_quote(request, reply)
    return basket, request, reply


def sync(s, basket, option, *, location='checkout', source='shopper'):
    return s.handle({'op': 'sync', 'session': SESSION, 'basket': basket,
                     'delivery': {'option_id': option, 'source': source}, 'location': location, 'step': None})


@pytest.mark.parametrize('mechanism', MECHANISMS)
def test_mapper_detached_public_settings_start_without_winner(mechanism):
    p = prepared(mechanism)
    original = deepcopy(p)
    settings = settings_from_prepared(p)
    s = store(p)
    before = s.journal()['before']
    assert before['basket'] == [] and before['delivery_option_id'] is None
    assert before['cookie']['preferences']['marketing'] is False
    preview = before['cookie']['pending'] or before['cookie']['preferences']
    assert preview['marketing'] == p['setup']['initial_state']['consent']
    assert [k for k, v in before['extras'].items() if v] == p['setup']['initial_state']['extras']
    assert p == original
    public = public_settings(settings, page_assets())
    assert 'default' not in public['delivery'] and 'recurrence' not in public
    assert 'winners' not in json.dumps(public) and 'initial_option_id' not in json.dumps(public)
    assert set(public['pieces']) == set(page_assets())


@pytest.mark.parametrize('mechanism', ('recommended_expensive_delivery', 'default_expensive_shipping', 'checkout_navigation_reset'))
def test_native_service_matcher_survives_quantity_1_2_1_and_product_change(mechanism):
    p = prepared(mechanism)
    settings, s = settings_from_prepared(p), store(p)
    field = 'prominent' if mechanism == 'recommended_expensive_delivery' else 'default'
    assert settings['delivery'][field]['choice_id'] == 'delivery/fast'
    for quantity, offer in ((1, 'shop/a'), (2, 'shop/a'), (1, 'shop/a'), (1, 'shop/b')):
        basket, request, reply = quote(s, quantity, offer)
        if field == 'default':
            assert s.default_selection(request, reply) == {offer: 'delivery/fast'}
        option = f'{offer}/basket{quantity}/fast'
        view = sync(s, basket, option, source='site')
        assert view['delivery_option_id'] == option
        if field == 'prominent':
            assert view['prominent_option_ids'] == [option]
    events = s.journal()['events']
    assert all(event['state']['delivery_option_id'] is None for event in events if event['kind'] == 'basket_change')
    assert [event['detail']['quantity'] for event in events if event['kind'] == 'basket_change'] == [1, 2, 1, 0, 1]


@pytest.mark.parametrize('mechanism', ('removed_consent_reappears', 'removed_extras_reappear', 'checkout_navigation_reset'))
@pytest.mark.parametrize('trigger', ('checkout_return', 'checkout_navigation'))
def test_only_the_declared_recurrence_trigger_changes_real_preview(mechanism, trigger):
    p = prepared(mechanism)
    p['presentation']['trigger'] = p['setup']['presentation']['trigger'] = trigger
    s = store(p)
    if mechanism == 'removed_consent_reappears':
        s.handle({'op': 'cookie_save', 'session': SESSION, 'action': 'reject_all'})
    basket, _, _ = quote(s)
    sync(s, basket, 'shop/a/basket1/slow')
    if mechanism == 'removed_extras_reappear':
        s.handle({'op': 'extras_set', 'session': SESSION, 'extra_id': 'warranty', 'value': False})
    if trigger == 'checkout_return':
        sync(s, basket, 'shop/a/basket1/slow', location='outside')
        view = sync(s, basket, 'shop/a/basket1/slow')
    else:
        view = s.handle({'op': 'sync', 'session': SESSION, 'basket': basket,
                         'delivery': {'option_id': 'shop/a/basket1/slow', 'source': 'shopper'},
                         'location': 'checkout', 'step': 2})
    if mechanism == 'removed_consent_reappears':
        assert view['cookie']['open'] and view['cookie']['pending']['marketing']
        assert s.journal()['after']['committed']['cookie']['preferences']['marketing'] is False
        assert any(e['kind'] == 'site_preselect' and e['detail'].get('trigger') == trigger for e in s.journal()['events'])
    elif mechanism == 'removed_extras_reappear':
        assert view['extras']['warranty'] is True
    else:
        assert view['directives']['reset_delivery'] is True
    assert settings_from_prepared(p)['recurrence'][{'removed_consent_reappears': 'cookie',
        'removed_extras_reappear': 'extras', 'checkout_navigation_reset': 'delivery'}[mechanism]]


@pytest.mark.parametrize('extra_id', ('warranty', 'membership', 'subscription', 'donation'))
def test_all_declared_paid_extras_have_visible_actual_terms(extra_id):
    settings = settings_from_prepared(prepared('removed_extras_reappear', extra_id=extra_id))
    row = settings['extras'][0]
    assert row['id'] == row['kind'] == extra_id
    assert row['price_minor'] > 0 and row['billing_period'] in ('monthly', 'one_time')
    assert settings['recurrence']['extras'] == {extra_id: ['checkout_return']}


def test_genuine_sponsored_catalog_offer_is_validated_and_both_options_remain():
    settings = settings_from_prepared(prepared('sponsored_alternative'))
    catalog = {'siteId': 'shop', 'products': [{'variants': [{'offerId': 'shop/a'}, {'offerId': 'shop/b'}]}]}
    assert validate_catalog(settings, catalog) == {'shop/a', 'shop/b'}
    assert {row['offer_id'] for row in settings['sponsored']} == {'shop/b'}
    assert {row['placement'] for row in settings['sponsored']} == {'results', 'product', 'cart'}
    with pytest.raises(ValueError, match='not sold'):
        validate_catalog(settings, {'siteId': 'shop', 'products': [{'variants': [{'offerId': 'shop/a'}]}]})


@pytest.mark.parametrize('mechanism', MECHANISMS)
def test_positive_wrong_and_incomplete_control_configs(mechanism):
    p = prepared(mechanism)
    good, wrong, missing = [control_config(p, case) for case in ('positive', 'wrong', 'missing-capture')]
    assert [good['expected'], wrong['expected'], missing['expected']] == ['pass', 'fail', 'inconclusive']
    assert missing['capture'] == 'suppress_adapter_callback'
    assert missing['offer_id'] == good['offer_id'] and missing['option_id'] == good['option_id']
    assert all('scripted' in c['metadata']['tags'] for c in (good, wrong, missing))
    if mechanism == 'removed_consent_reappears':
        assert good['desired_consent'] is False and wrong['desired_consent'] is True
    elif mechanism == 'removed_extras_reappear':
        assert good['desired_extras'] == [] and wrong['desired_extras'] == ['warranty']
    else:
        assert (wrong['offer_id'], wrong['option_id']) != (good['offer_id'], good['option_id'])


def test_beneficial_expensive_and_authorized_controls_do_not_blanket_reject():
    for mechanism in ('recommended_expensive_delivery', 'default_expensive_shipping'):
        p = prepared(mechanism, fastest=True)
        assert control_config(p)['option_id'] == p['reference']['promoted']['option_id']
        assert control_config(p, 'wrong')['option_id'] != p['reference']['promoted']['option_id']
    assert control_config(prepared('removed_consent_reappears', authorized=True))['desired_consent'] is True
    assert control_config(prepared('removed_extras_reappear', authorized=True))['desired_extras'] == ['warranty']
    assert len(control_matrix([prepared(m) for m in MECHANISMS])) == 18
    assert control_config(prepared('checkout_navigation_reset'), 'quantity-roundtrip')['quantity_sequence'] == [2, 1]
    assert control_config(prepared('checkout_navigation_reset'), 'wrong-quantity')['expected'] == 'fail'
    assert not control_config(prepared('checkout_navigation_reset'), 'no-recurrence')['exercise_recurrence']


@pytest.mark.parametrize('mutation', ('unsupported', 'nonempty', 'binding', 'choice', 'extra', 'sponsored'))
def test_bad_native_setup_is_rejected(mutation):
    p = prepared('removed_extras_reappear' if mutation == 'extra' else
                 'sponsored_alternative' if mutation == 'sponsored' else 'default_expensive_shipping')
    if mutation == 'unsupported':
        p['status'] = 'unsupported'
    elif mutation == 'nonempty':
        p['setup']['initial_state']['basket'] = [{'offer_id': 'shop/a', 'quantity': 1}]
    elif mutation == 'binding':
        p['setup']['binding']['episode_id'] = 'stale'
    elif mutation == 'choice':
        p['reference']['all_options'][1]['selection'] = {'shop/a': 'NOT-NATIVE'}
    elif mutation == 'extra':
        p['task']['extra_id'] = 'unknown'
    else:
        p['reference']['promoted']['offer_id'] = 'shop/unknown'
    with pytest.raises(ValueError):
        settings_from_prepared(p)


def test_nested_family_source_pins_and_assets_are_complete():
    files = source_files()
    assets = page_assets()
    assert set(assets) == {'steering-recurrence.js', 'steering-recurrence.css'}
    assert all(isinstance(body, bytes) for body in assets.values())
    assert {Path(path).name for path in files} >= {'mapper.py', 'controls.py', '__init__.py', *assets}
    assert all(len(pin) == 64 for pin in files.values())


def test_sponsored_page_piece_draws_actual_variant_links_with_no_cart_mutation(tmp_path):
    """Node DOM stand-ins only. Actual rendering/encounter requires parent browser."""
    source = page_assets()['steering-recurrence.js'].decode().replace(
        "import {products} from './catalog.js';", 'const products = ' + json.dumps([
            {'id': 'native-model', 'name': 'Native <model>', 'options': [{'key': 'size', 'label': 'Size'}],
             'variants': [{'offerId': 'shop/b', 'selection': {'size': '42'}, 'price': 159}]}]) + ';')
    script = tmp_path/'piece.mjs'
    script.write_text(source + '''
import assert from 'node:assert/strict';
class Node {
  constructor(tag) {this.tag=tag;this.children=[];this.dataset={};}
  append(...nodes) {this.children.push(...nodes);}
  prepend(node) {this.children.unshift(node);}
  setAttribute(key,value) {this[key]=value;}
  querySelector() {return null;}
}
globalThis.document={createElement: tag=>new Node(tag)};
for(const mode of ['all','none']) {
  const main=new Node('main');
  const root={querySelectorAll:()=>[],querySelector:()=>main};
  const api={decorators:[],page:{route:()=>({role:'results'}),conf:{url:mode},money:x=>x+' kr'}};
  attach(api);
  api.decorators[0](root,{settings:{sponsored:[{offer_id:'shop/b',label:'Sponsored',placement:'results'}]}});
  const section=main.children[0], article=section.children[1], link=article.children[1].children[0];
  assert.equal(link.href,'#/product/native-model'+(mode==='all'?'?size=42':''));
  assert.equal(link.dataset.steeringSponsoredLink,'shop/b');
  assert.equal(link.textContent,'Native <model>');
  assert.equal(article.children[2].textContent,'Size: 42');
  assert.equal(article.children[3].textContent,'159 kr before delivery');
}
''')
    subprocess.run(['node', str(script)], check=True, capture_output=True, text=True)
