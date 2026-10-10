"""Version attribution through real constructors/reports and saved sidecars.

Fixed synthetic world only; native oracle boundaries are replaced with fixed
objects so these controls do not generate worlds or dispatch model requests.
"""
from copy import deepcopy
import json

import pytest

from environments.website_world import (
    basic_offer_task, feature_offer_task, feature_offer_grading,
    quote_offer_grading, catalog_shortlist_grading,
    catalog_shipping_claim_grading, catalog_basket_answer_grading,
    catalog_comparison_grading,
)
from environments.website_world.adapter import digest
from environments.website_world.listed_offer_grading import ListedOfferGrader, VERSION as IDENTITY_VERSION
from environments.website_world.test_listed_offer_grading import fixture, answer
from experiments.answer_grading.listed_offer import publish
from scripts.trace_grades import BOUND_FILES


def empty_claims(schema):
    if 'anyOf' in schema:
        assert any(s.get('type') == 'null' for s in schema['anyOf'])
        return None
    kind = schema['type']
    if kind == 'object':
        return {k: empty_claims(v) for k, v in schema['properties'].items()}
    if kind == 'array':
        return []
    if kind == 'string':
        return 'extracted' if 'extracted' in schema.get('enum', []) else ''
    # Claim value types can be ['string', 'null'] or ['integer', 'null'].
    assert 'null' in kind
    return None


@pytest.fixture
def fixed(monkeypatch):
    world, _, _, bindings = fixture()
    world['address_context'] = {'carriers': [], 'collection_points': []}
    base = basic_offer_task._make_bound(world, {'kind': 'cheapest_available',
        'concept_id': 'footwear.walking_shoes'}, digest(world))
    ref = basic_offer_task._reference_bound(world, base)
    identity = ListedOfferGrader(world, base, ref, bindings)
    feature_task = {**base, 'matching_policy': 'known_applicable', 'availability': 'shipping'}
    feature_ref = {**ref, 'predicate_evaluations': {
        r['sku_id']: {'state': 'match'} for r in ref['candidates']}}
    monkeypatch.setattr(feature_offer_task, 'reference', lambda *a, **k: deepcopy(feature_ref))
    feature = feature_offer_grading.FeatureOfferGrader(world, feature_task,
        feature_ref, bindings, inventory=object())
    return world, base, ref, bindings, identity, feature_task, feature_ref, feature


def published(tmp_path, report):
    trace = tmp_path/'trace';output = tmp_path/'extraction'
    trace.mkdir();output.mkdir()
    for name in BOUND_FILES:
        (trace/name).write_text('{}\n')
    (output/'usage.json').write_text(json.dumps({
        'model': 'fixed-no-provider', 'provider': 'none', 'reported_cost_usd': 0}))
    path = publish(trace, output, report, mode='saved', source_hashes={})
    return json.loads(path.read_text())


def test_real_feature_subclass_report_contract_and_sidecar(fixed, tmp_path):
    feature = fixed[-1]
    text, claims = answer()
    report = feature.grade(claims, text)
    assert report['structured_claims_correct'] is True
    assert report['grading_version'] == feature_offer_grading.VERSION
    assert report['identity_grading_version'] == IDENTITY_VERSION
    assert report['response_contract']['identity_grading_version'] == IDENTITY_VERSION
    sidecar = published(tmp_path, report)
    assert sidecar['grading_version'] == feature_offer_grading.VERSION
    assert sidecar['identity_grading_version'] == IDENTITY_VERSION


@pytest.mark.parametrize('name', ['quote', 'shortlist', 'shipping', 'basket', 'comparison'])
def test_wrapper_constructor_report_and_sidecar(fixed, monkeypatch, tmp_path, name):
    world, base, ref, bindings, identity, ft, fr, feature = fixed
    task = {**base, 'grain': 'model', 'tie_policy': 'all', 'limit': 2,
        'feature_task': ft, 'price_basis': 'listed', 'objective': 'minimum',
        'order_domain': 'home', 'delivery_types': ['home'],
        'subject': {'concept_id': base['concept_id'], 'offer_id': next(iter(identity.offers))},
        'requirements': [{'concept_id': base['concept_id']}],
        'fields': [], 'field_declarations': {}, 'measurement_scopes': {}}
    if name == 'quote':
        m = quote_offer_grading
        native = {'feature_reference': fr, 'candidates': [], 'winners': [], 'status': 'no_match'}
        monkeypatch.setattr(m.quote_offer_task, 'reference', lambda *a, **k: deepcopy(native))
        monkeypatch.setattr(m.quote_offer_task, 'home_record', lambda w: {'location': {}})
        monkeypatch.setattr(m, 'FeatureOfferGrader', lambda *a, **k: feature)
        grader = m.QuoteOfferGrader(world, task, native, bindings,
            inventory=object(), quote_context={})
    elif name == 'shortlist':
        m = catalog_shortlist_grading
        native = {'feature_reference': fr, 'selected_models': [], 'status': 'no_match'}
        monkeypatch.setattr(m.native, 'reference', lambda *a, **k: deepcopy(native))
        monkeypatch.setattr(m, 'FeatureOfferGrader', lambda *a, **k: feature)
        grader = m.CatalogShortlistGrader(world, task, native, bindings, inventory=object())
    elif name == 'shipping':
        m = catalog_shipping_claim_grading
        native = {'subject': task['subject'], 'quantity': 1, 'subtotal_test': 'no_threshold',
            'assessment': 'none_free', 'option_count': 0, 'free_option_count': 0,
            **{k: None for k in ('unit_price_minor', 'subtotal_minor',
                'advertised_threshold_minor', 'minimum_shipping_minor', 'maximum_shipping_minor')}}
        monkeypatch.setattr(m.native, 'reference', lambda *a, **k: deepcopy(native))
        grader = m.ShippingClaimGrader(world, task, native, bindings,
            quote_context={}, checkout_domain={})
    elif name == 'basket':
        m = catalog_basket_answer_grading
        native = {'result': {'status': 'no_match', 'total_minor': None}}
        monkeypatch.setattr(m.structured, '_bound', lambda *a, **k: None)
        monkeypatch.setattr(m.basic_offer_task, 'make', lambda *a, **k: deepcopy(base))
        monkeypatch.setattr(m.basic_offer_task, 'reference', lambda *a, **k: deepcopy(ref))
        monkeypatch.setattr(m, 'prepare', lambda *a, **k: {})
        grader = m.CatalogBasketAnswerGrader(world, task, native, bindings,
            plan={}, checkout_domain={})
    else:
        m = catalog_comparison_grading
        native = {'models': [], 'status': 'uncertain'}
        monkeypatch.setattr(m.native, 'reference', lambda *a, **k: deepcopy(native))
        grader = m.CatalogComparisonGrader(world, task, native, bindings, inventory=object())
    assert grader.contract['identity_grading_version'] == IDENTITY_VERSION
    claims = empty_claims(grader.schema)
    claims['status'] = {'value': 'uncertain', 'evidence': 'uncertain'}
    report = grader.grade(claims, 'uncertain')
    assert report['grading_version'] == m.VERSION
    assert report['identity_grading_version'] == IDENTITY_VERSION
    assert report['response_contract']['identity_grading_version'] == IDENTITY_VERSION
    sidecar = published(tmp_path, report)
    assert sidecar['grading_version'] == m.VERSION
    assert sidecar['identity_grading_version'] == IDENTITY_VERSION


def test_publish_does_not_tag_unrelated_grades(fixed, tmp_path):
    text, claims = answer()
    report = fixed[4].grade(claims, text)
    report.pop('identity_grading_version')
    report['response_contract'].pop('identity_grading_version')
    assert 'identity_grading_version' not in published(tmp_path, report)


@pytest.fixture
def shortlist_with_rows(fixed, monkeypatch):
    world, base, ref, bindings, identity, ft, fr, feature = fixed
    task = {**base, 'grain': 'model', 'tie_policy': 'all', 'limit': 1,
            'feature_task': ft}
    expected = {'feature_reference': fr, 'status': 'match',
                'selected_models': [{'product_id': 'p', 'price_minor': 74000,
                                     'winners': deepcopy(fr['winners'])}]}
    monkeypatch.setattr(catalog_shortlist_grading.native, 'reference',
                        lambda *a, **k: deepcopy(expected))
    monkeypatch.setattr(catalog_shortlist_grading, 'FeatureOfferGrader',
                        lambda *a, **k: feature)
    # Enforce the identity schema before legacy normalization can supply omitted
    # fields. This is the boundary exercised by the current composed runtime.
    from jsonschema import Draft202012Validator
    original_validate = feature.validate_claims
    def validate_identity(value, text):
        Draft202012Validator(feature.schema).validate(value)
        return original_validate(value, text)
    monkeypatch.setattr(feature, 'validate_claims', validate_identity)
    return catalog_shortlist_grading.CatalogShortlistGrader(
        world, task, expected, bindings, inventory=object())


def shortlist_claims(price='740'):
    text, single = answer(price=price)
    row = {k: single[k] for k in ('product_name', 'retailer_name', 'offer_url',
                                 'sku_id', 'variant', 'total')}
    return text, {'interpretation': 'extracted', 'issues': [],
                  'status': {'value': 'shortlist', 'evidence': text},
                  'rows': [row], 'source_urls': []}


@pytest.mark.parametrize('price,correct', [('740', True), ('700', False)])
def test_nonempty_shortlist_uses_real_identity_schema_and_grades(
        shortlist_with_rows, tmp_path, price, correct):
    text, claims = shortlist_claims(price)
    report = shortlist_with_rows.grade(claims, text)
    assert report['structured_claims_correct'] is correct
    assert report['oracle_grade']['requirements']['row_0'] is correct
    assert report['claims'] == claims
    assert published(tmp_path, report)['structured_claims_correct'] is correct


def test_shortlist_identity_delegation_preserves_issues(shortlist_with_rows):
    text, claims = shortlist_claims()
    claims['issues'] = ['Retained formatter diagnostic']
    from unittest.mock import patch
    identity = shortlist_with_rows.identity
    with patch.object(identity, 'validate_claims',
                      wraps=identity.validate_claims) as delegated:
        assert shortlist_with_rows.validate_claims(claims, text) == claims
    assert delegated.call_args.args[0]['issues'] == claims['issues']


def test_shortlist_identity_delegation_keeps_variant_grounding(shortlist_with_rows):
    text, claims = shortlist_claims()
    # Generic quote validation accepts the exact quote, but the real identity
    # validator must reject a variant value absent from that quote.
    claims['rows'][0]['variant']['size_eu']['value'] = '99'
    with pytest.raises(ValueError, match='Variant value absent'):
        shortlist_with_rows.grade(claims, text)
