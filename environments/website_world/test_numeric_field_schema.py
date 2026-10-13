"""One numeric-description contract control and unchanged native/provenance locks.

Supplied claims cannot establish actual extractor choices; Evaluation owns
saved-answer inference and exact quote/identity/native qualification.
"""
from copy import deepcopy
import pytest
from experiments.answer_grading.extraction import claim
from .canonical_claims import numeric_literal_claim, variant_schema, validate_variant_claims
from .catalog_comparison_grading import _value_matches
from .listed_offer_grading import _variant_matches
from .qualifier_domains import measurement_basis_values, qualifier_claim


def test_numeric_descriptions_use_declarations_without_menus_or_sampled_values():
    definition = {'type':'integer','unit':'g'}
    items = [{'variant_fields':{'net_mass_g':definition},'public':{'skus':[{'net_mass_g':1000}]}}]
    schema = variant_schema(items,['net_mass_g'])
    field = schema['properties']['net_mass_g']
    assert 'numeric token alone' in field['properties']['value']['description']
    assert 'different stated unit' in field['properties']['value']['description']
    assert '1000' not in field['properties']['value']['description']
    assert 'enum' not in field['properties']['value']
    items[0]['public']['skus'] = [{'net_mass_g':400}]
    assert variant_schema(items,['net_mass_g']) == schema
    stripped = deepcopy(field)
    stripped['properties']['value'].pop('description')
    assert stripped == claim()
    fact = numeric_literal_claim(definition)
    assert 'unit suffix' in fact['properties']['value']['description']
    assert 'actually stated unit separately' in fact['properties']['value']['description']
    assert numeric_literal_claim({'type':'string'}) == claim()
    assert numeric_literal_claim({'type':'integer'},retail_axis=True) == claim()
    mixed = items + [{'variant_fields':{'net_mass_g':{'type':'integer','unit':'kg'}}}]
    assert variant_schema(mixed,['net_mass_g'])['properties']['net_mass_g'] == claim()


@pytest.mark.parametrize('value,expected', [('1000',True),('1000 g',False),('400',False),('1000 kg',False)])
def test_supplied_pack_value_keeps_native_identity_comparison(value,expected):
    schema = variant_schema([{'variant_fields':{'net_mass_g':{'type':'integer','unit':'g'}}}],['net_mass_g'])
    text = 'Pack size: '+value+(' g' if value=='1000' else '')
    claims = {'net_mass_g':{'value':value,'evidence':text}}
    before = deepcopy(claims)
    assert validate_variant_claims(claims,text,schema) == before
    assert _variant_matches('net_mass_g',1000,value) is expected
    assert claims == before


@pytest.mark.parametrize('value,expected', [('312',True),('312 g',False),('291',False)])
def test_supplied_numeric_fact_keeps_native_decimal_comparison(value,expected):
    assert _value_matches(value,312,{'type':'integer','unit':'g'}) is expected


def test_reused_declared_basis_is_not_numeric_or_basis_claim_repair():
    scope = {'basis':'one item, EU 40 reference configuration','origin':'registered_constant_field',
             'declaration':{'type':'string','constant':'one item, EU 40 reference configuration'}}
    values = measurement_basis_values(scope)
    assert values == [scope['basis']]
    assert scope['basis'] in qualifier_claim(values)['properties']['value']['enum']
    # Enum interpretation remains extractor-owned. A raw paraphrase still does
    # not equal the native basis, and a suffixed mass remains nonnumeric.
    assert not _value_matches('312 g',312,{'type':'integer','unit':'g'})


def test_numeric_schema_guidance_does_not_weaken_exact_quote_or_missingness():
    schema = variant_schema([{'variant_fields':{'mass':{'type':'integer','unit':'g'}}}],['mass'])
    with pytest.raises(ValueError,match='quote'):
        validate_variant_claims({'mass':{'value':'312','evidence':'fabricated'}},'312 g',schema)
    with pytest.raises(ValueError,match='Absent'):
        validate_variant_claims({'mass':{'value':None,'evidence':'312 g'}},'312 g',schema)


def test_noninteger_and_blank_unit_retail_axes_retain_literal_contract():
    for definition in ({'type':'number','unit':'l'}, {'type':'integer','unit':' '}):
        assert numeric_literal_claim(definition,retail_axis=True)==claim()
    description=numeric_literal_claim({'type':'integer','unit':'g'})['properties']['value']['description']
    assert 'declaration uses unit' not in description


def test_actual_listed_schema_and_contract_use_declared_numeric_guidance():
    from .test_listed_offer_grading import fixture
    from .listed_offer_grading import ListedOfferGrader
    from .basic_offer_task import _make_bound, _reference_bound
    from .adapter import digest
    world, _, _, bindings=fixture()
    p=world['products'][0]
    p['variant_fields']['net_mass_g']={'type':'integer','unit':'g'}
    for sku in p['public']['skus']: sku['net_mass_g']=1000
    task=_make_bound(world,{'kind':'cheapest_available','concept_id':p['public']['concept_id']},digest(world))
    grader=ListedOfferGrader(world,task,_reference_bound(world,task),bindings)
    assert 'numeric token alone' in grader.schema['properties']['variant']['properties']['net_mass_g']['properties']['value']['description']
    assert grader.contract['canonical_options_version']=='website-canonical-claim-domains-v2'


def test_actual_comparison_schema_separates_numeric_token_unit_and_canonical_basis():
    from .test_catalog_comparison_task import fixture, answer
    from .catalog_comparison_grading import CatalogComparisonGrader
    world,task,ref,bindings,inventory=fixture()
    grader=CatalogComparisonGrader(world,task,ref,bindings,inventory=inventory)
    field='product.facts.reference_mass_g'
    cell=grader.cell_schemas[field]
    assert 'numeric token alone' in cell['properties']['value']['properties']['value']['description']
    assert 'declaration uses unit' not in cell['properties']['value']['properties']['value']['description']
    assert 'one item, EU 40 reference configuration' in cell['properties']['basis']['properties']['value']['enum']
    text,claims=answer(world,task,ref,bindings)
    grade=grader.grade(claims,text)
    assert grade['structured_claims_correct']
    from .qualifier_domains import VERSION as qualifier_version
    assert grader.contract['canonical_qualifiers_version']==qualifier_version
    row=claims['rows'][0]['facts'][field]
    quote=row['value']['evidence'].replace(' g',' kg')
    text+='\n'+quote
    row['unit']={'value':'kg','evidence':quote}
    assert not grader.grade(claims,text)['structured_claims_correct']


def test_shipping_consumer_uses_same_canonical_variant_validation():
    from types import SimpleNamespace
    from .catalog_shipping_claim_grading import ShippingClaimGrader, ENUMS, MONEY_FIELDS
    from experiments.answer_grading.extraction import obj
    schema=obj({'variant':variant_schema([{'variant_fields':{'colour':{'type':'enum','values':['olive','brown']}}}],['colour'])})
    grader=ShippingClaimGrader.__new__(ShippingClaimGrader)
    grader.schema=schema;grader.contract={'variant_fields':['colour']}
    null={'value':None,'evidence':None}
    schema['properties'].update({k:claim(enum=values+[None]) for k,values in ENUMS.items()})
    schema['properties'].update({k:{'type':'null'} for k in MONEY_FIELDS})
    schema['properties']['source_urls']={'type':'array','items':{'type':'string'}}
    schema['required']=list(schema['properties'])
    claims={'variant':{'colour':{'value':'olive','evidence':'Olive'}},'source_urls':[]}
    claims.update({k:deepcopy(null) for k in ENUMS});claims.update({k:None for k in MONEY_FIELDS})
    assert grader.validate_claims(claims,'Olive')['variant']==claims['variant']
    claims['variant']['colour']['value']='__unmatched_option__'
    assert grader.validate_claims(claims,'Olive')['variant']==claims['variant']


def test_mixed_integer_number_axes_keep_order_independent_literal_fallback():
    declarations=[{'variant_fields':{'mass':{'type':t,'unit':'g'}}} for t in ('integer','number')]
    assert variant_schema(declarations,['mass'])==variant_schema(list(reversed(declarations)),['mass'])
    assert variant_schema(declarations,['mass'])['properties']['mass']==claim()


def test_wrong_unit_semantic_accuracy_is_not_a_validator_guarantee():
    # Deliberate extractor-trust boundary: a bad extractor can strip a wrong
    # unit, and quote authentication alone cannot prove its interpretation.
    schema=variant_schema([{'variant_fields':{'net_mass_g':{'type':'integer','unit':'g'}}}],['net_mass_g'])
    claims={'net_mass_g':{'value':'1000','evidence':'Pack size: 1000 kg'}}
    assert validate_variant_claims(claims,'Pack size: 1000 kg',schema)==claims
    assert _variant_matches('net_mass_g',1000,claims['net_mass_g']['value'])
