from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from environments.website_world import quote_offer_generation as api
from environments.website_world.test_quote_offer_task import fixture, Quotes, claims_for


def request(**task):
    return {'schema': 'website-world-generation-v2', 'seed': 75,
        'world': {'concept_ids': ['footwear.walking_shoes'], 'controls': {'world_size': .8}},
        'task': {'kind': 'matching_single_item_delivery', 'concept_id': 'footwear.walking_shoes',
            'predicates': [{'field': 'sku.size_eu', 'operator': 'eq', 'value': 42}], **task}}


def test_compile_preserves_explicit_population_and_predeclares_objective():
    req = request(objective='fastest_then_cheapest', arrival_deadline='2026-10-07')
    req['world']['tasks'] = ['footwear.walking_shoes']; before = deepcopy(req)
    compiled = api.compile_request(req)
    assert req == before
    assert compiled['proxy_request']['world'] == req['world']
    assert compiled['selection']['objective'] == 'fastest_then_cheapest'
    assert compiled['selection']['arrival_deadline'] == '2026-10-07'


@pytest.mark.parametrize('change', [dict(arrival_deadline='tomorrow'),
    dict(predicates=[{'field': 'sku.size_eu', 'operator': 'eq', 'value': 42, 'unit': 'cm'}]),
    dict(coupon_code='SAVE'), dict(delivery_types=['retailer_branch'])])
def test_invalid_notation_rejects_before_sampling(monkeypatch, change):
    calls = []
    monkeypatch.setattr(api.unified_generation, 'generate', lambda *a, **kw: calls.append(kw))
    with pytest.raises(ValueError): api.generate(request(**change))
    assert calls == []


def test_late_binding_calls_world_once_preserves_no_match_and_admission(monkeypatch):
    w, _, _, _, _, _ = fixture(); calls = []
    result = {'world': w, 'surrounding': None, 'basket_plan': {'fixture': True},
        'delivery_plan': {'explicit_admission': True}, 'resolved_configuration': {},
        'audit': {'request_sha256': 'proxy-fixture'}, 'episode': {}}
    def generate(proxy, *, world_factory):
        calls.append(deepcopy(proxy))
        return deepcopy(result)
    def prepare(world, *, plan, admission_plan):
        assert plan == result['basket_plan'] and admission_plan == result['delivery_plan']
        return Quotes(world, admitted='express-only')
    monkeypatch.setattr(api.unified_generation, 'generate', generate)
    monkeypatch.setattr(api, 'prepare', prepare)
    req = request(max_total_minor=1)
    actual = api.generate(req)
    assert len(calls) == 1
    assert actual['world'] == w
    assert actual['quote_offer_reference']['status'] == 'no_match'
    assert actual['quote_offer_task']['quote_binding']['admission_plan_sha256'] == 'express-only'
    assert actual['resolved_configuration']['request'] == req
    assert actual['episode']['manual_task']['user_message'] == actual['quote_offer_task']['user_message']


def test_common_extractor_receives_public_contract_only_and_publishes_version(tmp_path):
    from experiments.answer_grading import task_answer
    _, task, ref, _, _, grader = fixture()
    text, claims = claims_for(ref['winners'][0]); calls = []
    class Backend:
        def complete(self, messages):
            calls.append(messages)
            assert 'quote_inventory' not in messages[1]['content']
            assert 'optimal_score' not in messages[1]['content']
            assert '80000' not in messages[0]['content']
            content = json.dumps(claims)
            return SimpleNamespace(text=content, request={'messages': messages}, raw={
                'model': 'scripted', 'provider': 'offline', 'usage': {},
                'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]})
    actual = task_answer.extract_and_grade(grader, {'user_message': task['user_message'], 'memories': []},
        text, tmp_path/'extract', Backend())
    assert actual['structured_claims_correct']
    assert actual['grading_version'] == 'website-single-item-quote-grading-v1'
    assert len(calls) == 1
