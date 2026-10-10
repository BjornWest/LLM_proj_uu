from copy import deepcopy

import pytest

from environments.website_world.catalog_predicates import PredicateSet

FIELDS = {
    'product.facts.mass_g': {'type': 'number', 'unit': 'g', 'min': 10, 'max': 1000, 'unknown_values': [-1]},
    'product.facts.washable': {'type': 'boolean', 'constant': True},
    'product.facts.material': {'type': 'string'},
    'product.facts.tags': {'type': 'set', 'items': {'type': 'string'}},
    'sku.size': {'type': 'integer', 'min': 36, 'max': 48},
    'sku.colour': {'type': 'enum', 'values': ['black', 'blue']},
}
PRODUCT = {'product_id': 'p', 'facts': {'mass_g': 200, 'washable': True,
                                      'material': 'cotton', 'tags': ['walking', 'casual']}}
SKU = {'product_id': 'p', 'sku_id': 's', 'size': 42, 'colour': 'black'}
STATUS = {'product.facts.mass_g': 'known', 'product.facts.material': 'known', 'product.facts.tags': 'known'}
SKU_STATUS = {'sku.size': 'known', 'sku.colour': 'known'}


def pred(path, op, value, **kwargs):
    return {'field': path, 'operator': op, 'value': value, **kwargs}


def evaluate(ps, *, product=None, sku=None, status=None):
    return ps.evaluate(PRODUCT if product is None else product, SKU if sku is None else sku,
                       catalog_status=STATUS if status is None else status, sku_status=SKU_STATUS)


@pytest.mark.parametrize('op,value,expected', [
    ('eq', 200, 'match'), ('ne', 200, 'mismatch'), ('ge', 200, 'match'),
    ('gt', 200, 'mismatch'), ('le', 200, 'match'), ('lt', 200, 'mismatch'),
    ('ge', 1200, 'mismatch'), ('in', [100, 200], 'match'), ('not_in', [100], 'match'),
])
def test_numeric_operators_and_impossible_threshold(op, value, expected):
    ps = PredicateSet(FIELDS, [pred('product.facts.mass_g', op, value, unit='g')])
    assert evaluate(ps)['state'] == expected


@pytest.mark.parametrize('op,value,expected', [
    ('contains', 'walking', 'match'), ('contains', 'walk', 'mismatch'),
    ('excludes', 'walking', 'mismatch'), ('excludes', 'running', 'match'),
])
def test_collection_membership_is_not_substring(op, value, expected):
    ps = PredicateSet(FIELDS, [pred('product.facts.tags', op, value)])
    assert evaluate(ps)['state'] == expected


@pytest.mark.parametrize('status', ['unknown', 'not_applicable'])
@pytest.mark.parametrize('op', ['eq', 'ne', 'le', 'not_in'])
def test_unknown_and_na_never_become_negative_matches(status, op):
    value = [200] if op == 'not_in' else 200
    ps = PredicateSet(FIELDS, [pred('product.facts.mass_g', op, value, unit='g')])
    result = evaluate(ps, status={'product.facts.mass_g': status})
    assert result['state'] == 'indeterminate'
    assert result['predicates'][0]['satisfied'] is None


def test_known_false_conjunct_dominates_unknown():
    ps = PredicateSet(FIELDS, [pred('product.facts.mass_g', 'le', 300, unit='g'),
                               pred('sku.colour', 'eq', 'blue')])
    assert evaluate(ps, status={})['state'] == 'mismatch'


def test_exact_constant_can_be_known_without_projection():
    ps = PredicateSet(FIELDS, [pred('product.facts.washable', 'eq', True)])
    assert evaluate(ps, status={})['state'] == 'match'
    assert evaluate(ps, status={'product.facts.washable': 'not_applicable'})['state'] == 'indeterminate'
    product = deepcopy(PRODUCT); product['facts']['washable'] = False
    assert evaluate(ps, product=product, status={})['state'] == 'indeterminate'


def test_conditional_constant_needs_status():
    fields = deepcopy(FIELDS); fields['product.facts.washable']['applicable_when'] = 'product.has_cloth'
    ps = PredicateSet(fields, [pred('product.facts.washable', 'eq', True)])
    assert evaluate(ps, status={})['state'] == 'indeterminate'


def test_pilot_known_scalars_are_an_explicit_capability():
    p = pred('product.facts.material', 'eq', 'cotton')
    assert evaluate(PredicateSet(FIELDS, [p]), status={})['state'] == 'indeterminate'
    assert evaluate(PredicateSet(FIELDS, [p], known_paths=['product.facts.material']), status={})['state'] == 'match'


def test_known_sentinel_conflict_rejects():
    ps = PredicateSet(FIELDS, [pred('product.facts.mass_g', 'le', 300, unit='g')])
    product = deepcopy(PRODUCT); product['facts']['mass_g'] = -1
    with pytest.raises(ValueError): evaluate(ps, product=product)
    assert evaluate(ps, product=product, status={})['state'] == 'indeterminate'


def test_missing_value_and_foreign_sku_reject():
    ps = PredicateSet(FIELDS, [pred('sku.colour', 'eq', 'black')])
    with pytest.raises(ValueError): evaluate(ps, sku={'product_id': 'foreign', 'colour': 'black'})
    with pytest.raises(ValueError): evaluate(ps, sku={'product_id': 'p'})


@pytest.mark.parametrize('p', [
    pred('product.facts.mass_g', 'ge', 300),
    pred('product.facts.mass_g', 'ge', 300, unit='kg'),
    pred('product.facts.mass_g', 'eq', -1, unit='g'),
    pred('product.facts.mass_g', 'ge', float('inf'), unit='g'),
    pred('sku.size', 'eq', True), pred('sku.colour', 'ge', 'black'),
    pred('sku.colour', 'in', []), pred('product.facts.material', 'contains', 'cot'),
    pred('product.facts.not_defined', 'eq', 'anything'),
    pred('product.name', 'eq', 'name'),
])
def test_invalid_predicates_reject_at_construction(p):
    with pytest.raises(ValueError): PredicateSet(FIELDS, [p])


def test_declarations_and_predicates_are_isolated_once():
    fields = deepcopy(FIELDS); predicates = [pred('sku.colour', 'eq', 'black')]
    ps = PredicateSet(fields, predicates)
    fields['sku.colour']['values'].clear(); predicates[0]['value'] = 'blue'
    assert evaluate(ps)['state'] == 'match'


def test_declared_na_constant_not_inferred_known():
    fields = deepcopy(FIELDS)
    fields['product.facts.material'].update(constant='not applicable', not_applicable_values=['not applicable'])
    ps = PredicateSet(fields, [pred('product.facts.material', 'ne', 'cotton')])
    p = deepcopy(PRODUCT); p['facts']['material'] = 'not applicable'
    result = evaluate(ps, product=p, status={})
    assert result['state'] == 'indeterminate'
    assert result['predicates'][0]['status'] == 'not_applicable'
    with pytest.raises(ValueError): PredicateSet(fields, [pred('product.facts.material', 'eq', 'not applicable')])


def test_known_enum_boolean_does_not_match_numeric_member():
    fields = deepcopy(FIELDS); fields['sku.size'] = {'type': 'enum', 'values': [1, 2]}
    ps = PredicateSet(fields, [pred('sku.size', 'eq', 1)])
    sku = deepcopy(SKU); sku['size'] = True
    with pytest.raises(ValueError): evaluate(ps, sku=sku)
