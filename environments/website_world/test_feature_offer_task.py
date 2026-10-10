from copy import deepcopy

import pytest

from environments.website_world import feature_offer_task as api
from environments.website_world.feature_offer_grading import FeatureOfferGrader
from environments.website_world.test_listed_offer_grading import fixture as base_fixture, answer


def fixture(predicates=None, **options):
    world, _, _, bindings = base_fixture()
    product = world['products'][0]
    product['public']['facts'] = {'cushioning': 'moderate', 'reference_mass_g': 300}
    product['catalog_status'] = {}; product['sku_status'] = {}
    inventory = api.FieldInventory('footwear.walking_shoes')
    spec = {'kind': api.KIND, 'concept_id': inventory.concept_id,
            'predicates': predicates if predicates is not None else [
                {'field': 'sku.size_eu', 'operator': 'eq', 'value': 42}], **options}
    task = api.make(world, spec, inventory=inventory)
    reference = api.reference(world, task, inventory=inventory)
    return world, task, reference, bindings, inventory


def test_declared_fields_and_basis_preserved():
    _, task, _, _, inventory = fixture([{'field': 'product.facts.reference_mass_g',
        'operator': 'le', 'value': 350, 'unit': 'g'}])
    assert task['field_declarations']['product.facts.reference_mass_g'] == inventory.fields['product.facts.reference_mass_g']
    assert 'reference mass g at most 350 g' in task['user_message']
    assert task['field_source_sha256'] == inventory.source_hashes


def test_predicate_filters_variants_and_keeps_all_price_ties():
    world, task, ref, bindings, inventory = fixture()
    assert len(ref['winners']) == 4  # two colours, two tied shops; size42 only
    assert all(r['sku_id'].endswith('-42') for r in ref['candidates'])
    grader = FeatureOfferGrader(world, task, ref, bindings, inventory=inventory)
    for name, url in [('Veska', 'https://a.test/#/product/olive'), ('Tied Shop', 'https://d.test/#/product/olive')]:
        text, claims = answer(name=name, url=url)
        assert grader.grade(claims, text)['structured_claims_correct']


def test_wrong_variant_not_repaired_by_features_or_price():
    w, t, r, b, i = fixture()
    g = FeatureOfferGrader(w, t, r, b, inventory=i)
    text, claims = answer(size='43')
    grade = g.grade(claims, text)
    assert grade['oracle_grade']['requirements']['reported_price']
    assert not grade['oracle_grade']['requirements']['known_applicable_features']
    text, claims = answer(); claims['variant']['size_eu'] = {'value': None, 'evidence': None}
    assert not g.grade(claims, text)['structured_claims_correct']
    assert len(g.grade(claims, text)['identity_resolution']['offer_ids']) == 2


def test_price_threshold_and_natural_no_match():
    w, t, r, b, i = fixture(max_price_minor=73999)
    assert r['status'] == 'no_match'
    g = FeatureOfferGrader(w, t, r, b, inventory=i)
    c = {'interpretation': 'extracted', 'status': {'value': 'no_match', 'evidence': 'None establish all requirements.'}}
    assert g.grade(c, 'None establish all requirements.')['structured_claims_correct']
    assert fixture(max_price_minor=74000)[2]['status'] == 'match'


def test_stock_requirement_excludes_backorder_and_changes_rank():
    w, _, _, b, i = fixture()
    for o in w['retailers'][0]['offers']:
        o['stock_by_source'] = {'a': 0}; o['supplier_order']['enabled'] = True
    # Remove the other740SEK retailer's physical stock too.
    for o in w['retailers'][3]['offers']: o['stock_by_source'] = {'d': 0}
    base = {'kind': api.KIND, 'concept_id': i.concept_id,
            'predicates': [{'field': 'sku.size_eu', 'operator': 'eq', 'value': 42}]}
    t = api.make(w, base, inventory=i); r = api.reference(w, t, inventory=i)
    assert r['minimum_price_minor'] == 74000
    t = api.make(w, {**base, 'availability': 'positive_stock'}, inventory=i)
    r = api.reference(w, t, inventory=i)
    assert r['minimum_price_minor'] == 80000


@pytest.mark.parametrize('status', ['unknown', 'not_applicable'])
def test_unknown_and_na_cannot_satisfy_even_negative_predicates(status):
    w, _, _, b, i = fixture()
    w['products'][0]['catalog_status']['product.facts.cushioning'] = status
    spec = {'kind': api.KIND, 'concept_id': i.concept_id, 'predicates': [
        {'field': 'product.facts.cushioning', 'operator': 'ne', 'value': 'firm'}]}
    t = api.make(w, spec, inventory=i); r = api.reference(w, t, inventory=i)
    assert r['status'] == 'no_match' and r['indeterminate_offer_ids']
    assert 'do not claim an unknown specification is physically false' in t['user_message']


def test_omitted_pilot_placeholder_not_available_as_a_shopping_requirement():
    w, _, _, _, i = fixture()
    w['products'][0]['public']['facts']['waterproof_rating'] = 'not specified'
    spec = {'kind': api.KIND, 'concept_id': i.concept_id, 'predicates': [
        {'field': 'product.facts.waterproof_rating', 'operator': 'ne', 'value': 'none'}]}
    with pytest.raises(ValueError): api.make(w, spec, inventory=i)


def test_private_price_factor_not_available_as_a_shopping_requirement():
    i = api.FieldInventory('tablets.everyday_media_tablets')
    assert 'product.facts.model_price_factor' not in i.fields


def test_inherited_field_units_and_public_qualifiers_preserved():
    i = api.FieldInventory('tops.t_shirts')
    assert i.fields['product.facts.main_fabric_cotton_percent']['unit'] == '%'
    assert i.publication['product.facts.main_fabric_cotton_percent']['role'] == 'literal'
    assert 'Commercial model range only' in i.fields['product.facts.market_range']['basis']


def test_shared_extraction_uses_feature_contract_without_native_expectations(tmp_path):
    import json
    from types import SimpleNamespace
    from experiments.answer_grading import task_answer
    w, t, r, b, i = fixture()
    grader = FeatureOfferGrader(w, t, r, b, inventory=i)
    text, claims = answer(); events = []
    class Backend:
        def complete(self, messages):
            events.append(messages)
            assert '74000' not in messages[0]['content']
            assert 'predicate_evaluations' not in messages[1]['content']
            content = json.dumps(claims)
            return SimpleNamespace(text=content, request={'messages': messages}, raw={
                'model': 'scripted', 'provider': 'offline', 'usage': {},
                'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]})
    grade = task_answer.extract_and_grade(grader, {'user_message': t['user_message'], 'memories': []},
        text, tmp_path/'extract', Backend())
    assert grade['structured_claims_correct']
    assert grade['grading_version'] == 'website-feature-listed-offer-grading-v1'
    assert len(events) == 1


@pytest.mark.parametrize('what', ['task', 'reference', 'unit', 'inventory'])
def test_tampering_rejected(what):
    w, t, r, b, i = fixture()
    if what == 'task': t['predicates'][0]['value'] = 43
    elif what == 'reference': r['minimum_price_minor'] = 1
    elif what == 'unit': t['predicates'][0]['unit'] = 'cm'
    else: i.fields['sku.size_eu']['type'] = 'boolean'
    with pytest.raises(ValueError): FeatureOfferGrader(w, t, r, b, inventory=i)


def test_construction_does_not_use_prices_or_stock_to_choose_requirements():
    w, t, _, _, i = fixture()
    w2 = deepcopy(w)
    for retailer in w2['retailers']:
        for o in retailer['offers']: o['price_minor'] = 123; o['stock_by_source'] = {retailer['retailer_id']: 0}
    spec = {k:t[k] for k in ('kind', 'concept_id', 'predicates', 'availability')}
    t2 = api.make(w2, spec, inventory=i)
    for k in ('predicates', 'field_declarations', 'user_message', 'availability'):
        assert t2[k] == t[k]


def test_reference_is_not_public_evidence():
    _, _, r, _, _ = fixture()
    assert r['evidence_coverage'] == 'not_inferred_from_native_truth'
