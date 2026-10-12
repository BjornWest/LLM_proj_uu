"""Finite declaration/schema controls, no sampler, browser or inference."""
from copy import deepcopy

import pytest
from jsonschema import ValidationError

from .canonical_claims import declared_values, variant_schema, validate_variant_claims, UNMATCHED
from .test_listed_offer_grading import fixture, answer
from .listed_offer_grading import ListedOfferGrader


def declared_fixture():
    args = fixture()
    args[0]['products'][0]['variant_fields'].update(
        colour={'type': 'enum', 'values': ['olive', 'brown', 'blue']},
        width={'type': 'enum', 'values': ['standard', 'narrow', 'wide']},
        size_eu={'type': 'integer', 'min': 40, 'max': 44})
    # Fixture task binding must follow the explicitly authored declarations.
    from .basic_offer_task import _make_bound, _reference_bound
    from .adapter import digest
    world, _, _, bindings = args
    task = _make_bound(world, {'kind': 'cheapest_available', 'concept_id': 'footwear.walking_shoes'}, digest(world))
    return world, task, _reference_bound(world, task), bindings


@pytest.mark.parametrize('definition,axis,expected', [
    ({'type': 'enum', 'values': ['navy', 'white']}, False, ['navy', 'white']),
    ({'type': 'boolean'}, False, ['false', 'true']),
    ({'type': 'integer', 'min': 1, 'max': 2}, True, ['1', '2']),
    ({'type': 'integer', 'min': 1, 'max': 2}, False, None),
    ({'type': 'integer', 'min': 0, 'max': 100000}, True, None),
    ({'type': 'number', 'min': 0, 'max': 1}, True, None),
    ({'type': 'string', 'constant': 'cotton'}, False, None),
    ({'type': 'string'}, True, None),
    ({'type': 'integer', 'min': {'field': 'lower'}, 'max': 10}, True, None),
])
def test_only_declared_finite_domains_become_choices(definition, axis, expected):
    assert declared_values(definition, retail_axis=axis) == expected


@pytest.mark.parametrize('values', ([], ['navy', 'navy'], [1, '1'], [float('inf')], [{}]))
def test_invalid_or_colliding_declarations_fail_closed(values):
    with pytest.raises(ValueError): declared_values({'type': 'enum', 'values': values})


def test_union_uses_full_declarations_not_sampled_skus_or_stock_or_winners():
    args = declared_fixture();world = args[0]
    grader = ListedOfferGrader(*args)
    properties = grader.schema['properties']['variant']['properties']
    assert properties['colour']['properties']['value']['enum'] == ['olive', 'brown', 'blue', UNMATCHED, None]
    assert properties['size_eu']['properties']['value']['enum'] == ['40', '41', '42', '43', '44', UNMATCHED, None]
    assert not any(s['colour'] == 'blue' for s in world['products'][0]['public']['skus'])
    items = deepcopy(world['products'])
    items[0]['public']['skus'] = []
    assert variant_schema(items, properties) == grader.schema['properties']['variant']
    items.append({'variant_fields': {'colour': {'type': 'enum', 'values': ['red', 'olive']}}})
    assert variant_schema(items, ['colour'])['properties']['colour']['properties']['value']['enum'] == ['olive', 'brown', 'blue', 'red', UNMATCHED, None]
    items.append({'variant_fields': {'colour': {'type': 'string'}}})
    assert 'enum' not in variant_schema(items, ['colour'])['properties']['colour']['properties']['value']


def test_canonical_labels_keep_original_case_and_wording_in_evidence():
    grader = ListedOfferGrader(*declared_fixture())
    text, claims = answer()
    text += '\nThe finish is OLIVE. It has standard width.'
    claims['variant']['colour'] = {'value': 'olive', 'evidence': 'The finish is OLIVE.'}
    claims['variant']['width'] = {'value': 'standard', 'evidence': 'It has standard width.'}
    before = deepcopy(claims)
    assert grader.grade(claims, text)['structured_claims_correct']
    assert claims == before


@pytest.mark.parametrize('field,value', [('colour', 'blue'), ('width', 'wide'), ('size_eu', '41')])
def test_legitimate_but_wrong_choice_reaches_native_failure(field, value):
    grader = ListedOfferGrader(*declared_fixture());text, claims = answer()
    text += '\nChoice: '+value
    claims['variant'][field] = {'value': value, 'evidence': 'Choice: '+value}
    assert not grader.grade(claims, text)['structured_claims_correct']


@pytest.mark.parametrize('mutation', ('outside_domain', 'missing', 'invented_quote', 'empty_quote', 'null_quote', 'null_value'))
def test_closed_choice_schema_does_not_bypass_provenance_or_missingness(mutation):
    grader = ListedOfferGrader(*declared_fixture());text, claims = answer()
    entry = claims['variant']['colour']
    if mutation == 'outside_domain': entry.update(value='violet', evidence='violet');text += '\nviolet'
    elif mutation == 'missing': entry.update(value=None, evidence=None)
    elif mutation == 'invented_quote': entry['evidence'] = 'Never in the answer'
    elif mutation == 'empty_quote': entry['evidence'] = ''
    elif mutation == 'null_quote': entry['evidence'] = None
    else: entry['value'] = None
    if mutation == 'missing':
        result = grader.grade(claims, text)
        assert result['claims']['variant']['colour']['value'] is None
        # The exact URL may already identify colour; an absent size leaves
        # multiple SKU candidates and must not be filled from a winner.
        claims['variant']['size_eu'] = {'value': None, 'evidence': None}
        assert not grader.grade(claims, text)['structured_claims_correct']
    else:
        with pytest.raises((ValueError, ValidationError)): grader.grade(claims, text)


def test_canonical_provenance_is_not_a_second_semantic_interpreter():
    schema = variant_schema([{'variant_fields': {'colour': {'type': 'enum', 'values': ['black', 'white']}}}], ['colour'])
    supplied = {'colour': {'value': 'black', 'evidence': 'This is not black.'}}
    # Evaluation must test extractor negation; validator proves provenance only.
    assert validate_variant_claims(supplied, 'This is not black.', schema) == supplied


def test_legacy_missing_declarations_preserve_literal_validation():
    schema = variant_schema([{'public': {}}], ['size_eu'])
    assert 'enum' not in schema['properties']['size_eu']['properties']['value']
    with pytest.raises(ValueError):
        validate_variant_claims({'size_eu': {'value': '42', 'evidence': 'EU 43'}}, 'EU 43', schema)


@pytest.mark.parametrize('kind', ('enum', 'boolean'))
def test_model_fact_schema_uses_complete_declared_domain_and_native_comparison(kind):
    from . import catalog_comparison_task as native
    from .catalog_comparison_grading import CatalogComparisonGrader
    from .test_catalog_comparison_task import fixture as models, answer as model_answer
    world, _, _, bindings, inventory = models()
    field = 'product.facts.cushioning'
    # Synthetic declaration/observations for a finite fact, never a real source
    # edit or accepted runtime qualification. Include an unobserved legal enum.
    definition = ({'type': 'enum', 'values': ['soft', 'firm', 'balanced']}
                  if kind == 'enum' else {'type': 'boolean'})
    inventory.fields[field] = definition
    for index, item in enumerate(world['products']):
        item['public']['facts']['cushioning'] = ('soft' if index % 2 == 0 else 'firm') if kind == 'enum' else index % 2 == 0
    task = native.make(world, {'kind': native.KIND, 'concept_id': inventory.concept_id,
                       'fields': [field], 'model_limit': 2}, inventory=inventory)
    reference = native.reference(world, task, inventory=inventory)
    grader = CatalogComparisonGrader(world, task, reference, bindings, inventory=inventory)
    text, claims = model_answer(world, task, reference, bindings)
    domain = grader.schema['properties']['rows']['items']['properties']['facts']['properties'][field]['properties']['value']['properties']['value']['enum']
    assert domain == (['soft', 'firm', 'balanced', UNMATCHED, None] if kind == 'enum' else ['false', 'true', UNMATCHED, None])
    cell = claims['rows'][0]['facts'][field]['value']
    paraphrase = 'SOFT underfoot.' if kind == 'enum' else 'Yes, that feature is present.'
    cell['evidence'] = paraphrase; text += '\n'+paraphrase
    assert grader.grade(claims, text)['structured_claims_correct']
    cell['value'] = 'balanced' if kind == 'enum' else 'false'
    assert not grader.grade(claims, text)['structured_claims_correct']


@pytest.mark.parametrize('field', ('colour', 'width'))
def test_stated_unmatched_option_cannot_disappear_behind_correct_identity(field):
    grader = ListedOfferGrader(*declared_fixture());text, claims = answer()
    text += '\nThe chosen '+field+' is violet.'
    claims['variant'][field] = {'value': UNMATCHED, 'evidence': 'The chosen '+field+' is violet.'}
    claims['issues'] = ['Stated '+field+' is outside the vocabulary.']
    result = grader.grade(claims, text)
    assert result['claims']['variant'][field]['value'] == UNMATCHED
    assert not result['structured_claims_correct']


def test_full_variant_link_with_unmatched_manual_instruction_still_fails():
    from .test_variant_link_task import fixture as linked
    from . import variant_link_task as native
    from .variant_link_answer_grading import VariantLinkGrader
    from .test_variant_link_answer_grading import sample
    world, spec, inputs = linked('all')
    world['products'][0]['variant_fields'] = {'colour': {'type': 'enum', 'values': ['brown', 'black']},
                                            'size_eu': {'type': 'enum', 'values': ['38', '39']}}
    task = native.make(world, spec, **inputs);reference = native.reference(world, task, **inputs)
    grader = VariantLinkGrader(world, task, reference, **inputs)
    _, text, claims = sample('all')
    assert grader.grade(claims, text)['structured_claims_correct']
    text += '\nAfter opening, choose colour violet.'
    claims['manual_selection']['colour'] = {'value': UNMATCHED, 'evidence': 'After opening, choose colour violet.'}
    assert not grader.grade(claims, text)['structured_claims_correct']


@pytest.mark.parametrize('wrapper', ('frozen', 'tuple'))
def test_immutable_declarations_compile_like_mutable_ones(wrapper):
    from environments.product_world.shared_state import freeze
    original = {'type': 'enum', 'values': ['navy', 'white']}
    wrapped = freeze(original) if wrapper == 'frozen' else {**original, 'values': tuple(original['values'])}
    assert declared_values(wrapped) == declared_values(original)
    assert variant_schema([{'variant_fields': {'colour': wrapped}}], ['colour']) == variant_schema([{'variant_fields': {'colour': original}}], ['colour'])


def test_unknown_and_na_sentinels_are_not_known_choices():
    assert declared_values({'type': 'enum', 'values': ['complete', 'not specified', 'not applicable'],
                            'unknown_values': ['not specified'], 'not_applicable_values': ['not applicable']}) == ['complete']
    assert declared_values({'type': 'enum', 'values': [1, 2], 'unknown_values': [1.0]}) == ['2']
    assert declared_values({'type': 'boolean', 'unknown_values': [0]}) == ['false', 'true']
    assert declared_values({'type': 'integer', 'min': 0, 'max': 3,
                            'unknown_values': [0], 'not_applicable_values': [1]}, retail_axis=True) == ['0', '1', '2', '3']


def test_unknown_fact_has_status_evidence_and_null_value():
    from . import catalog_comparison_task as native
    from .catalog_comparison_grading import CatalogComparisonGrader
    from .test_catalog_comparison_task import fixture as models, answer as model_answer
    world, _, _, bindings, inventory = models();field = 'product.facts.cushioning'
    inventory.fields[field] = {'type': 'enum', 'values': ['soft', 'not specified'], 'unknown_values': ['not specified']}
    for item in world['products']: item['public']['facts']['cushioning'] = 'not specified'
    task = native.make(world, {'kind': native.KIND, 'concept_id': inventory.concept_id,
                       'fields': [field], 'model_limit': 2}, inventory=inventory)
    reference = native.reference(world, task, inventory=inventory)
    grader = CatalogComparisonGrader(world, task, reference, bindings, inventory=inventory)
    domain = grader.cell_schemas[field]['properties']['value']['properties']['value']['enum']
    assert domain == ['soft', UNMATCHED, None]
    text, claims = model_answer(world, task, reference, bindings)
    assert grader.grade(claims, text)['structured_claims_correct']
    assert all(row['facts'][field]['value'] == {'value': None, 'evidence': None} for row in claims['rows'])


@pytest.mark.parametrize('definition', [
    {'type': 'integer', 'min': 64, 'max': 128, 'unit': 'GB'},
    {'type': 'integer', 'min': 0, 'max': 10, 'step': 2},
    {'type': 'integer', 'min': -2, 'max': 3},
])
def test_measurement_stepped_and_negative_ranges_do_not_become_categorical_menus(definition):
    assert declared_values(definition, retail_axis=True) is None


def test_boolean_retail_labels_match_native_string_tuple_encoding():
    assert declared_values({'type': 'boolean'}, retail_axis=True) == [str(False), str(True)]
    assert declared_values({'type': 'enum', 'values': [False, True]}, retail_axis=True) == [str(False), str(True)]


@pytest.mark.parametrize('name', ('status', 'total', 'offers', 'source_urls', 'factual_details'))
def test_nested_field_names_do_not_trigger_flat_validator_special_cases(name):
    schema = variant_schema([{'variant_fields': {name: {'type': 'string'}}}], [name])
    good = {name: {'value': 'new', 'evidence': 'It is new.'}}
    assert validate_variant_claims(good, 'It is new.', schema) == good
    with pytest.raises(ValueError):
        validate_variant_claims({name: {'value': 'new', 'evidence': 'It is old.'}}, 'It is old.', schema)


@pytest.mark.parametrize('bad', (None, [], 'invalid'))
def test_invalid_declaration_shapes_fail_with_a_clear_validation_error(bad):
    with pytest.raises(ValueError): variant_schema([{'variant_fields': bad}], ['colour'])
    with pytest.raises(ValueError): declared_values(bad)


@pytest.mark.parametrize('values', (['Black', 'black'], ['a', ' a'], [''], [UNMATCHED]))
def test_blank_reserved_and_native_equivalent_labels_are_rejected(values):
    with pytest.raises(ValueError): declared_values({'type': 'enum', 'values': values})


def test_retail_label_status_does_not_remove_a_real_menu_identity():
    declaration = {'type': 'enum', 'values': ['black', 'not specified'], 'unknown_values': ['not specified']}
    assert declared_values(declaration) == ['black']
    assert declared_values(declaration, retail_axis=True) == ['black', 'not specified']


def test_canonical_review_variant_and_unmatched_product_scope(monkeypatch):
    from . import test_catalog_review_task as reviews
    monkeypatch.setattr(reviews, 'offer_fixture', declared_fixture)
    args = reviews.fixture(subject_scope='sku');text, claims = reviews.claims_for(args[1], args[2])
    grader = reviews.grader(*args)
    sku = next(s for s in args[0]['products'][0]['public']['skus'] if s['sku_id'] == args[1]['subject']['sku_id'])
    quote = sku['colour'].upper()+', EU '+str(sku['size_eu'])+', '+sku['width']+' width.'
    text += '\n'+quote
    claims['variant'] = {k: {'value': str(sku[k]), 'evidence': quote} for k in ('colour', 'size_eu', 'width')}
    assert grader.grade(claims, text)['structured_claims_correct']
    args = reviews.fixture();text, claims = reviews.claims_for(args[1], args[2]);grader = reviews.grader(*args)
    text += '\nFor the violet version.'
    claims['variant']['colour'] = {'value': UNMATCHED, 'evidence': 'For the violet version.'}
    assert not grader.grade(claims, text)['structured_claims_correct']


def test_canonical_shipping_claim_and_unmatched_variant():
    from experiments.footwear_world_pilot.test_basket_quote import world as basket_world
    from . import test_catalog_shipping_claim_task as shipping
    from experiments.accepted_catalog_commerce import basket_quote
    from experiments.accepted_catalog_commerce.prepared_quote import prepare
    from . import catalog_checkout_domain, catalog_shipping_claim_task as native
    from .catalog_shipping_claim_grading import ShippingClaimGrader
    world, old_task, _, _, _, old_grader = shipping.fixture(basket_world.__wrapped__())
    values = list(dict.fromkeys(s['colour'] for p in world['products'] for s in p['public']['skus']))
    for item in world['products']: item['variant_fields']['colour'] = {'type': 'enum', 'values': values}
    plan = basket_quote.make_plan(world);quotes = prepare(world, plan=plan);domain = catalog_checkout_domain.make(world)
    task = native.make(world, {'kind': native.KIND, 'quantity': 2, 'delivery_types': ['home']}, quote_context=quotes, checkout_domain=domain)
    reference = native.reference(world, task, quote_context=quotes, checkout_domain=domain)
    grader = ShippingClaimGrader(world, task, reference, {'retailer_offers': old_grader.identity.links}, quote_context=quotes, checkout_domain=domain)
    text, claims = shipping.claims((world, task, reference, quotes, domain, grader))
    sku = grader.identity.skus[task['subject']['sku_id']];label = sku['colour']
    text += '\nChosen colour: '+label.upper()
    claims['variant']['colour'] = {'value': label, 'evidence': 'Chosen colour: '+label.upper()}
    assert grader.grade(claims, text)['structured_claims_correct']
    text += '\nChosen colour: impossible violet'
    claims['variant']['colour'] = {'value': UNMATCHED, 'evidence': 'Chosen colour: impossible violet'}
    assert not grader.grade(claims, text)['structured_claims_correct']


def test_canonical_mixed_basket_and_unmatched_assertion():
    from experiments.footwear_world_pilot.test_basket_quote import world as basket_world
    from .test_catalog_basket_task import fixture as basket_fixture
    from .test_catalog_basket_answer_grading import sample as basket_answer
    from . import test_catalog_basket_answer_grading as answers, catalog_basket_task as native, catalog_checkout_domain
    from experiments.accepted_catalog_commerce import basket_quote
    from .catalog_basket_answer_grading import CatalogBasketAnswerGrader
    world, old_task, _, _, _, bindings = basket_fixture(basket_world.__wrapped__())
    colours = list(dict.fromkeys(s['colour'] for p in world['products'] for s in p['public']['skus']))
    for item in world['products']:
        if 'colour' in item['variant_fields']: item['variant_fields']['colour'] = {'type': 'enum', 'values': colours}
    domain = catalog_checkout_domain.make(world, {'max_quantity_per_offer': 2, 'max_lines_per_order': 3})
    task = native.make(world, native._selection(old_task), checkout_domain=domain)
    plan = basket_quote.make_plan(world);reference = native.reference(world, task, plan=plan, checkout_domain=domain)
    grader = CatalogBasketAnswerGrader(world, task, reference, bindings, plan=plan, checkout_domain=domain)
    # Existing authored answer construction remains reusable for these exact
    # world/task/domain values; claims are authored and no extractor is dispatched.
    from unittest.mock import patch
    with patch.object(answers, 'fixture', return_value=(world, task, plan, domain, reference, bindings)):
        _, text, claims = basket_answer(world)
    line = next(line for order in claims['orders'] for line in order['lines']
                if any(link['url'] == line['offer_url']['value']
                       and 'colour' in grader.identity.dimensions[link['product_id']]
                       for link in bindings['retailer_offers'].values()))
    link = next(link for link in bindings['retailer_offers'].values() if link['url'] == line['offer_url']['value'])
    colour = grader.identity.skus[link['sku_id']]['colour']
    text += '\nThe chosen colour is '+colour.upper()+'.'
    line['variant']['colour'] = {'value': colour, 'evidence': 'The chosen colour is '+colour.upper()+'.'}
    assert grader.grade(claims, text)['structured_claims_correct']
    line['variant']['colour'] = {'value': UNMATCHED, 'evidence': 'The selected colour is violet.'}
    assert grader.grade(claims, text+'\nThe selected colour is violet.')['structured_claims_correct'] is False
