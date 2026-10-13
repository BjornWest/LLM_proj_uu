"""Audit extractor wire contracts and observed grading, without parsing answers.

An audit finding is not a task verdict. Public declaration expectations must be
supplied explicitly; private winners are never used to construct schema choices.
"""
from copy import deepcopy
from hashlib import sha256
import inspect
import json

from jsonschema import Draft202012Validator

VERSION = 'website-task-schema-audit-v1'


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def _pointer(part):
    return str(part).replace('~', '~0').replace('/', '~1')


def schema_nodes(schema):
    """Reachable schema nodes, preserving alternatives and internal ref paths."""
    Draft202012Validator.check_schema(schema)
    result = []

    def visit(node, path, references):
        if len(result) >= 10000:
            raise ValueError('Schema audit exceeds finite node limit')
        if type(node) is bool:
            result.append({'path': path, 'schema': node})
            return
        result.append({'path': path, 'schema': deepcopy(node)})
        if '$ref' in node:
            ref = node['$ref']
            if type(ref) is not str or not ref.startswith('#/'):
                raise ValueError('Schema audit requires local JSON-pointer references')
            if ref not in references:
                target = schema
                try:
                    for part in ref[2:].split('/'):
                        target = target[part.replace('~1', '/').replace('~0', '~')]
                except (KeyError, TypeError) as error:
                    raise ValueError('Unresolved local schema reference: '+ref) from error
                visit(target, path+'/$ref', references | {ref})
        for key in ('properties', 'patternProperties', 'dependentSchemas'):
            for name, value in node.get(key, {}).items():
                visit(value, path+'/'+key+'/'+_pointer(name), references)
        for key in ('items', 'additionalProperties', 'contains', 'not', 'if', 'then', 'else'):
            if isinstance(node.get(key), (dict, bool)):
                visit(node[key], path+'/'+key, references)
        for key in ('anyOf', 'oneOf', 'allOf', 'prefixItems'):
            for index, value in enumerate(node.get(key, [])):
                visit(value, path+'/'+key+'/'+str(index), references)
    visit(schema, '', set())
    return result


def _types(node):
    value = node.get('type')
    types = set(value if isinstance(value, list) else [value] if value else [])
    for key in ('anyOf', 'oneOf'):
        for alternative in node.get(key, []):
            if type(alternative) is dict:
                types |= _types(alternative)
    return types


def audit_schema(schema, *, expectations=()):
    """Report enforced wire types, nullable pairs and declared categorical gaps.

    Expectations name exact schema pointers and roles. A canonical expectation
    supplies the complete public declaration domain, not a sampled menu/answer.
    This function never changes the schema or evaluates answer prose.
    """
    nodes = schema_nodes(schema)
    by_path = {row['path']: row['schema'] for row in nodes}
    findings, fields = [], []

    def finding(path, kind, detail):
        findings.append({'path': path, 'kind': kind, 'detail': detail})

    for row in nodes:
        path, node = row['path'], row['schema']
        if type(node) is bool:
            if node:
                finding(path, 'unconstrained_schema', 'Any JSON value is accepted here.')
            continue
        types = _types(node)
        fields.append({'path': path, 'types': sorted(types),
                       'enum': deepcopy(node.get('enum')),
                       'required': deepcopy(node.get('required', [])),
                       'description': node.get('description')})
        if not types and not any(k in node for k in ('$ref', 'enum', 'const', 'allOf', 'not')):
            finding(path, 'type_not_enforced', 'No explicit wire type or categorical restriction.')
        if 'object' in types and 'properties' in node:
            if node.get('additionalProperties') is not False:
                finding(path, 'open_object', 'Unexpected fields are not explicitly prohibited.')
            props = node['properties']
            if {'value', 'evidence'} <= props.keys():
                if not {'value', 'evidence'} <= set(node.get('required', [])):
                    finding(path, 'claim_pair_not_required', 'Value/evidence pair is not required by schema.')
                # Pairing may be checked by the mechanical validator; record the
                # wire-schema gap separately rather than claiming it is absent.
                if 'null' in _types(props['value']) and not any(k in node for k in ('if', 'oneOf', 'allOf')):
                    finding(path, 'nullable_pair_validator_dependency',
                            'Value/evidence null pairing depends on the post-extraction validator.')
    for expected in expectations:
        if type(expected) is not dict or not {'path', 'role'} <= expected.keys():
            raise ValueError('Schema expectation requires path and role')
        path, role = expected['path'], expected['role']
        node = by_path.get(path)
        if type(node) is not dict:
            finding(path, 'expected_field_missing', 'Expected schema field is absent.')
            continue
        types = _types(node)
        if role in ('integer', 'number', 'boolean'):
            allowed = {'integer', 'number'} if role == 'number' else {role}
            if not types & allowed or types - allowed - {'null'}:
                finding(path, 'semantic_type_not_enforced',
                        'Declared '+role+' is represented by wire types '+str(sorted(types))+'.')
        elif role == 'canonical':
            if expected.get('domain_source') != 'public_declaration':
                raise ValueError('Canonical audit needs a complete public declaration domain')
            choices = expected.get('choices')
            if type(choices) is not list or not choices:
                raise ValueError('Canonical audit requires nonempty full choices')
            actual = node.get('enum')
            if not isinstance(actual, list):
                finding(path, 'canonical_domain_not_enforced', 'Declared choices use an open claim.')
            else:
                label = lambda v: json.dumps(v, sort_keys=True, allow_nan=False)
                wanted = {label(v) for v in choices}
                seen = {label(v) for v in actual if v not in (None, '__unmatched_option__')}
                if seen != wanted:
                    finding(path, 'canonical_domain_differs',
                            'Schema choices differ from the full declared public domain.')
        else:
            raise ValueError('Unsupported schema expectation role: '+str(role))
    return {'schema': VERSION, 'schema_sha256': digest(schema), 'fields': fields,
            'expectations': deepcopy(list(expectations)), 'findings': findings,
            'schema_valid': True, 'extractor_semantic_accuracy': 'not_measured'}


def audit_grader(grader, *, observations=(), expectations=()):
    """Bind actual grader code/contract and expose observed native assertions."""
    schema = deepcopy(grader.schema)
    result = audit_schema(schema, expectations=expectations)
    source = inspect.getsourcefile(type(grader))
    if source is None:
        raise ValueError('Grader has no inspectable source')
    with open(source, 'rb') as file:
        source_sha = sha256(file.read()).hexdigest()
    result.update(grader_class=type(grader).__module__+'.'+type(grader).__qualname__,
                  source={'path': source, 'sha256': source_sha},
                  contract=deepcopy(getattr(grader, 'contract', {})),
                  extraction_instructions_sha256=digest(getattr(grader, 'extraction_instructions', None)))
    rows = []
    for entry in observations:
        if entry.get('control') not in ('correct', 'wrong', 'missing', 'malformed'):
            raise ValueError('Declare correct/wrong/missing/malformed audit control')
        grade = entry.get('grade')
        checks = {} if not isinstance(grade, dict) else grade.get('oracle_grade', {}).get('requirements', {})
        if not isinstance(checks, dict):
            raise ValueError('Observed native requirements must be an object')
        rows.append({'control': entry['control'],
                     'verdict': None if not isinstance(grade, dict) else grade.get('structured_claims_correct'),
                     'native_checks': deepcopy(checks),
                     'error': deepcopy(entry.get('error')),
                     'expected_verdict': entry.get('expected_verdict'),
                     'mutation': deepcopy(entry.get('mutation'))})
    result['observed_grading'] = rows
    result['limitations'] = [
        'Schema validation and supplied claims do not prove actual extractor interpretation.',
        'Observed checks describe these controls, not full-answer or whole-run effect coverage.',
        'Reference-to-grade roundtrip alone is not independent oracle validation.',
    ]
    return result
