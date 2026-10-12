"""Grounded public item/service mapping and task-neutral grading integration."""
from copy import deepcopy
from decimal import Decimal
import json
from types import SimpleNamespace

import pytest

from experiments.footwear_world_pilot.test_basket_quote import world
from environments.website_world.test_catalog_basket_task import fixture
from environments.website_world.catalog_basket_answer_grading import CatalogBasketAnswerGrader


def sample(world):
    w, t, p, d, ref, bindings = fixture(world)
    grader = CatalogBasketAnswerGrader(w, t, ref, bindings, plan=p, checkout_domain=d)
    spans = []
    def quoted(value, label):
        if value is None: return {'value': None, 'evidence': None}
        text = f'{label}: {value}'
        spans.append(text)
        return {'value': value, 'evidence': text}
    orders = []
    for order in ref['result']['solutions'][0]['orders']:
        rid = order['retailer_id']
        retailer = next(r for r in w['retailers'] if r['retailer_id'] == rid)
        lines = []
        quote = grader.quotes.quote(rid, order['lines'])
        for line in order['lines']:
            offer = grader.identity.offers[line['offer_id']]
            item = grader.identity.products[offer['product_id']]
            choice = next(c for c in quote['delivery_choices'] if c['choice_id'] == order['quote']['selection'][offer['offer_id']])
            values = {'carrier_name': choice['carrier_name'], 'tier': choice['tier'],
                      'delivery_type': choice['destination_type'], 'location_id': None, 'location_name': None}
            lines.append({'product_name': quoted(item['name'], 'product'),
                'offer_url': quoted(bindings['retailer_offers'][offer['offer_id']]['url'], 'product link'),
                'sku_id': quoted(None, 'SKU'), 'variant': {k: quoted(None, k) for k in grader.variant_fields},
                'quantity': quoted(line['quantity'], 'sale units'),
                'delivery': {k: quoted(v, k) for k, v in values.items()}})
        orders.append({'retailer_name': quoted(retailer['name'], 'retailer'),
                       'split': quoted(None, 'split'), 'lines': lines, 'total': None})
    total = ref['result']['total_minor']
    total_text = f'{Decimal(total)/100:.2f} SEK'
    spans.extend(['complete purchase plan', total_text])
    claims = {'interpretation': 'extracted', 'issues': [], 'status': {'value': 'plan', 'evidence': 'complete purchase plan'},
              'orders': orders, 'total': {'amount': f'{Decimal(total)/100:.2f}', 'currency': 'SEK', 'evidence': total_text},
              'source_urls': []}
    return grader, '. '.join(spans), claims


def test_complete_grounded_mixed_plan_passes_without_opaque_ids(world):
    g, text, claims = sample(world)
    result = g.grade(claims, text)
    assert result['structured_claims_correct']
    assert result['derivations'][0]['native_report']['verdict'] == 'pass'


@pytest.mark.parametrize('field', ['product_name', 'offer_url', 'quantity'])
def test_missing_identity_or_quantity_is_not_repaired_from_task(world, field):
    g, text, c = sample(world)
    c['orders'][0]['lines'][0][field] = {'value': None, 'evidence': None}
    assert not g.grade(c, text)['structured_claims_correct']


def test_service_and_money_cannot_disambiguate_an_unidentified_item(world):
    g, text, c = sample(world)
    first = c['orders'][0]['lines'][0]
    first['delivery']['carrier_name'] = {'value': None, 'evidence': None}
    assert not g.grade(c, text)['structured_claims_correct']
    c['total']['amount'] = '1.00'; c['total']['evidence'] = '1.00 SEK'
    assert not g.grade(c, text + '. 1.00 SEK')['structured_claims_correct']


def test_split_semantics_belong_to_extractor_not_lexical_validator(world):
    g, text, c = sample(world)
    c['orders'][0]['split'] = {'value': True, 'evidence': 'single shipment'}
    assert g.validate_claims(c, text + '. single shipment')['orders'][0]['split']==c['orders'][0]['split']


def test_wrong_order_currency_does_not_hide_behind_correct_combined_total(world):
    g, text, c = sample(world)
    c['orders'][0]['total'] = {'amount': '1.00', 'currency': 'EUR', 'evidence': '1.00 EUR'}
    assert not g.grade(c, text + '. 1.00 EUR')['structured_claims_correct']


def test_wrong_native_method_and_foreign_service_values_fail(world):
    g, text, c = sample(world)
    d = c['orders'][0]['lines'][0]['delivery']
    d['delivery_type'] = {'value': 'parcel_locker', 'evidence': 'home delivery'}
    assert not g.grade(c, text + '. home delivery')['structured_claims_correct']
    d['delivery_type'] = {'value': 'home', 'evidence': 'home delivery'}
    d['carrier_name'] = {'value': 'Foreign carrier', 'evidence': 'Foreign carrier'}
    assert not g.grade(c, text + '. home delivery. Foreign carrier')['structured_claims_correct']


def test_common_once_only_formatter_and_trace_grade(world, tmp_path):
    from experiments.answer_grading.task_answer import grade_saved_once
    from scripts.trace_grades import BOUND_FILES, read_grade
    g, text, c = sample(world)
    trace = tmp_path/'trace'; trace.mkdir()
    save = lambda p, v: p.write_text(json.dumps(v)+'\n')
    for n in BOUND_FILES: (trace/n).write_text('' if n.endswith('.jsonl') else '{}')
    save(trace/'natural-answer.json', {'text': text, 'stop_reason': 'agent_finished', 'technical_error': None})
    public = {'user_message': g.task['user_message'], 'memories': []}; save(trace/'policy-task.json', public)
    inputs = {}
    for k, v in {'world': g.world, 'task': g.task, 'reference': g.reference, 'bindings': g.bindings,
                 'plan': g.plan, 'checkout_domain': g.domain}.items():
        p = tmp_path/(k+'.json'); save(p, v); inputs[k] = p
    calls = []
    class Backend:
        def complete(self, messages):
            assert json.loads(messages[1]['content']) == {'public_task': public, 'final_answer': text}
            calls.append(messages)
            return SimpleNamespace(text=json.dumps(c), request={'messages': messages},
                raw={'model': 'scripted-basket-formatter', 'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(c)}}]})
        def close(self): pass
    kw = dict(trace=trace, inputs=inputs, output=tmp_path/'grade', grader_factory=CatalogBasketAnswerGrader,
              backend_factory=lambda _: Backend(), source_paths=[])
    result = grade_saved_once(**kw)
    assert result['structured_claims_correct'] and read_grade(trace)['binding_status'] == 'verified'
    with pytest.raises(FileExistsError): grade_saved_once(**kw)
    assert len(calls) == 1
