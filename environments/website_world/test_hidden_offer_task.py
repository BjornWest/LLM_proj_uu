from copy import deepcopy

import pytest

from environments.website_world import hidden_offer_task as api, catalog_clarification as callback
from environments.website_world.hidden_offer_grading import HiddenOfferGrader
from environments.website_world.feature_offer_task import FieldInventory
from environments.website_world.test_feature_offer_task import fixture as feature_fixture
from environments.website_world.test_listed_offer_grading import answer


def slot(**changes):
    return {'id':'personal-size','subject':'self','predicate':{'field':'sku.size_eu','operator':'eq','value':42},
            'match_rule':'personal_shoe_size_en_v1','ordering':'before_final_answer','contrast_values':[43],**changes}


def fixture(**changes):
    w,_,_,b,i = feature_fixture()
    spec = {'kind':api.KIND,'concept_id':i.concept_id,'hidden_requirement':slot(),**changes}
    t = api.make(w,spec,inventory=i)
    return w,t,api.reference(w,t,inventory=i),b,i


def test_hidden_value_not_in_initial_public_task_and_native_reference_is_effectful():
    _,t,r,_,_ = fixture()
    assert '42' not in t['user_message'] and '43' not in t['user_message'] and t['memories'] == []
    assert 'Any model, variant or pack is acceptable' not in t['user_message']
    assert r['clarification_affects_eligibility'] and len(r['selection_reference']['winners']) == 4
    assert set(r['contrast_evaluations'][0]['eligible_offer_ids']).isdisjoint(
        {row['offer_id'] for row in r['selection_reference']['candidates']})


def test_hidden_values_not_chosen_from_price_and_request_is_not_mutated():
    w,t,_,_,i = fixture(); spec = {k:t[k] for k in ('kind','concept_id','predicates','hidden_requirement','availability')}
    before = deepcopy(spec)
    for retailer in w['retailers']:
        for o in retailer['offers']: o['price_minor'] = 1
    t2 = api.make(w,spec,inventory=i)
    assert spec == before and t2['hidden_requirement'] == t['hidden_requirement']
    assert t2['user_message'] == t['user_message']


@pytest.mark.parametrize('question', ['Which shoe size do you wear?', 'What EU size?', 'What is your usual size?', 'Which size should I buy?'])
def test_supported_personal_shoe_questions_receive_only_reply(question):
    _,t,_,_,_ = fixture(); responder = callback.Responder(t)
    assert responder(question) == 'For me, please use EU 42.'
    assert responder.audit_id not in responder(question)


@pytest.mark.parametrize('question', ['What is the cheapest size available?', 'Is your size in stock?', 'What clothing size do you wear?',
                                    'What size does Alex wear?', 'What size does your wife wear?', 'What is your budget?'])
def test_unrelated_or_other_person_question_does_not_reveal_preference(question):
    _,t,_,_,_ = fixture()
    assert callback.Responder(t)(question) == callback.FALLBACK


def test_known_other_recipient_requires_name_in_question():
    _,t,_,_,_ = fixture(hidden_requirement=slot(subject='alex'))
    responder = callback.Responder(t)
    assert responder('What size do you wear?') == callback.FALLBACK
    assert responder('What size does alex wear?') == 'For alex, please use EU 42.'


def test_clothing_label_and_range_replies_derive_from_declared_meaning():
    i = FieldInventory('tops.t_shirts')
    s = callback.compile_slot(slot(predicate={'field':'sku.size_label','operator':'eq','value':'M'},
        match_rule='personal_clothing_label_en_v1',contrast_values=['L']),i)
    assert callback.reply(s) == 'For me, please use clothing size label M.'
    assert callback.matches(s,'What clothing size do you wear?')
    assert not callback.matches(s,'What EU shoe size do you wear?')
    s = callback.compile_slot(slot(predicate={'field':'product.facts.market_range','operator':'in','value':['women','unisex']},
        match_rule='personal_clothing_range_en_v1',contrast_values=[['men']],ordering='before_search'),i)
    assert callback.reply(s) == "For me, please use women's or unisex clothing ranges."
    assert callback.matches(s,"Do you prefer women's, men's or unisex clothing?")
    assert not callback.matches(s,'Are the womens shirts available?')


@pytest.mark.parametrize('what', ['rule','type','contrast_type','duplicate_contrast','same_contrast','visible_field','field','range'])
def test_invalid_hidden_contract_rejects_before_binding(what):
    s = slot(); predicates = []
    if what == 'rule': s['match_rule'] = 'unsupported_nlp'
    elif what == 'type': s['predicate']['value'] = True
    elif what == 'contrast_type': s['contrast_values'] = ['43']
    elif what == 'duplicate_contrast': s['contrast_values'] = [43,43]
    elif what == 'same_contrast': s['contrast_values'] = [42]
    elif what == 'visible_field': predicates = [deepcopy(s['predicate'])]
    elif what == 'range': s['predicate']['value'] = 99
    else: s['predicate']['field'] = 'product.facts.cushioning'
    with pytest.raises(ValueError): fixture(hidden_requirement=s,predicates=predicates)


def test_native_correct_answer_does_not_prove_reply_delivery():
    w,t,r,b,i = fixture(); g = HiddenOfferGrader(w,t,r,b,inventory=i)
    grade = g.grade(*reversed(answer()))
    assert grade['answer_outcome_correct'] is True and grade['structured_claims_correct'] is None
    assert grade['clarification_evaluation']['status'] == 'unknown'


def test_wrong_variant_cannot_be_repaired_from_private_hidden_requirement():
    w,t,r,b,i = fixture(); g = HiddenOfferGrader(w,t,r,b,inventory=i)
    grade = g.grade(*reversed(answer(size='43')))
    assert grade['answer_outcome_correct'] is False and grade['structured_claims_correct'] is False


def test_contrast_no_match_is_retained_without_claiming_effectful_task():
    w,t,_,b,i = fixture()
    for retailer in w['retailers']:
        for o in retailer['offers']: o['stock_by_source'] = {}; o['supplier_order']['enabled'] = False
    spec = {k:t[k] for k in ('kind','concept_id','predicates','hidden_requirement','availability')}
    t = api.make(w,spec,inventory=i); r = api.reference(w,t,inventory=i)
    assert r['status'] == 'no_match' and r['clarification_affects_eligibility'] is False


@pytest.mark.parametrize('what', ['hidden','reply','prose','contrast','reference'])
def test_private_native_and_public_contract_tampering_rejects(what):
    w,t,r,b,i = fixture()
    if what == 'hidden': t['hidden_requirement']['predicate']['value'] = 43
    elif what == 'reply': t['reply_contract_version'] = 'wrong'
    elif what == 'prose': t['user_message'] += ' EU42.'
    elif what == 'contrast': t['hidden_requirement']['contrast_values'] = [44]
    else: r['clarification_affects_eligibility'] = False
    with pytest.raises(ValueError): HiddenOfferGrader(w,t,r,b,inventory=i)
