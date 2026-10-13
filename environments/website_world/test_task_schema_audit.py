from copy import deepcopy
import pytest

from .task_schema_audit import audit_schema, schema_nodes


def value_claim(typ='string'):
    return {'type':'object','additionalProperties':False,'required':['value','evidence'],
            'properties':{'value':{'type':[typ,'null']},'evidence':{'type':['string','null']}}}


def test_wire_and_validator_pairing_are_distinct_without_modifying_schema():
    schema=value_claim('integer');before=deepcopy(schema)
    report=audit_schema(schema,expectations=[{'path':'/properties/value','role':'integer'}])
    assert report['schema_valid'] and schema==before
    assert [x['kind'] for x in report['findings']]==['nullable_pair_validator_dependency']
    assert report['extractor_semantic_accuracy']=='not_measured'


@pytest.mark.parametrize('role', ['integer','number','boolean'])
def test_prompt_description_does_not_replace_wire_type(role):
    schema=value_claim();schema['properties']['value']['description']='Use a '+role
    report=audit_schema(schema,expectations=[{'path':'/properties/value','role':role}])
    assert any(x['kind']=='semantic_type_not_enforced' for x in report['findings'])


def test_full_canonical_domain_is_checked_without_sampled_truth():
    schema=value_claim();schema['properties']['value']['enum']=['navy','black','__unmatched_option__',None]
    expectation={'path':'/properties/value','role':'canonical','domain_source':'public_declaration',
                 'choices':['black','navy']}
    assert not any(x['kind'].startswith('canonical') for x in audit_schema(schema,expectations=[expectation])['findings'])
    expectation['choices'].append('olive')
    assert any(x['kind']=='canonical_domain_differs' for x in audit_schema(schema,expectations=[expectation])['findings'])
    expectation['domain_source']='native_winner'
    with pytest.raises(ValueError,match='public declaration'):audit_schema(schema,expectations=[expectation])


def test_references_arrays_and_recursive_schema_have_finite_paths():
    schema={'type':'object','additionalProperties':False,'properties':{
        'rows':{'type':'array','items':{'$ref':'#/$defs/row'}}},
        '$defs':{'row':{'type':'object','properties':{'child':{'$ref':'#/$defs/row'},'amount':{'type':'number'}}}}}
    nodes=schema_nodes(schema)
    assert len(nodes)<20
    assert any(x['path'].endswith('/properties/amount') for x in nodes)
    with pytest.raises(ValueError,match='local'):schema_nodes({'$ref':'https://example.invalid/schema'})
    with pytest.raises(ValueError,match='Unresolved'):schema_nodes({'$ref':'#/$defs/missing'})


def test_invalid_schema_and_open_claim_are_not_silently_certified():
    from jsonschema.exceptions import SchemaError
    with pytest.raises(SchemaError):audit_schema({'type':'not_a_JSON_type'})
    report=audit_schema({'type':'object','properties':{'value':{}}})
    assert {'open_object','type_not_enforced'}<={x['kind'] for x in report['findings']}
