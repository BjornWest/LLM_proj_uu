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


def _resolve(schema, ref):
    if ref == '#':return schema
    if type(ref) is not str or not ref.startswith('#/'):
        raise ValueError('Schema audit requires local JSON-pointer references')
    target=schema
    try:
        for token in ref[2:].split('/'):
            token=token.replace('~1','/').replace('~0','~')
            if isinstance(target,list):
                if not token.isdigit() or str(int(token))!=token:raise KeyError(token)
                target=target[int(token)]
            else:target=target[token]
    except (KeyError,TypeError,IndexError) as error:
        raise ValueError('Unresolved local schema reference: '+ref) from error
    return target


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
            target=_resolve(schema,ref)
            if ref not in references:
                visit(target, path+'/$ref', references | {ref})
        for key in ('properties', 'patternProperties', 'dependentSchemas'):
            for name, value in node.get(key, {}).items():
                visit(value, path+'/'+key+'/'+_pointer(name), references)
        for key in ('items', 'additionalProperties', 'unevaluatedProperties', 'unevaluatedItems', 'propertyNames', 'contains', 'not', 'if', 'then', 'else'):
            if isinstance(node.get(key), (dict, bool)):
                visit(node[key], path+'/'+key, references)
        for key in ('anyOf', 'oneOf', 'allOf', 'prefixItems'):
            for index, value in enumerate(node.get(key, [])):
                visit(value, path+'/'+key+'/'+str(index), references)
    visit(schema, '', set())
    return result


def _types(node, root=None, seen=frozenset()):
    if type(node) is bool:
        return {'object','array','string','number','integer','boolean','null'} if node else set()
    value=node.get('type');types=set(value if isinstance(value,list) else [value] if value else [])
    if '$ref' in node and root is not None and node['$ref'] not in seen:
        types |= _types(_resolve(root,node['$ref']),root,seen|{node['$ref']})
    for key in ('anyOf','oneOf','allOf'):
        for alternative in node.get(key,[]):types |= _types(alternative,root,seen)
    if not types:
        for value in node.get('enum',[node['const']] if 'const' in node else []):
            types.add('null' if value is None else 'boolean' if type(value) is bool else
                'integer' if type(value) is int else 'number' if type(value) is float else
                'string' if type(value) is str else 'array' if type(value) is list else 'object')
    return types


def _domain(node, root, seen=frozenset()):
    if node is False:return []
    if not isinstance(node,dict):return None
    if 'enum' in node:return node['enum']
    if 'const' in node:return [node['const']]
    if node.get('type')=='null':return [None]
    if '$ref' in node and node['$ref'] not in seen:return _domain(_resolve(root,node['$ref']),root,seen|{node['$ref']})
    for key in ('anyOf','oneOf'):
        if key in node:
            children=[_domain(value,root,seen) for value in node[key]]
            return None if any(value is None for value in children) else [v for values in children for v in values]
    return None


def _container_restricted(node, root, kind, seen=frozenset()):
    # Alternatives inherit their own restrictions; absence of a keyword on
    # the wrapper is not proof that the allowed values are open.
    if node is False:return True
    if node is True:return False
    if 'enum' in node or 'const' in node:return True
    if kind=='object' and (node.get('additionalProperties') is False or node.get('unevaluatedProperties') is False):return True
    if kind=='array':
        if node.get('items',True) is not True:return True
        if node.get('maxItems',float('inf'))<=len(node.get('prefixItems',[])):return True
    if '$ref' in node and node['$ref'] not in seen:
        if _container_restricted(_resolve(root,node['$ref']),root,kind,seen|{node['$ref']}):return True
    if any(_container_restricted(child,root,kind,seen) for child in node.get('allOf',[])):return True
    for key in ('anyOf','oneOf'):
        if key in node:
            relevant=[child for child in node[key] if not _types(child,root) or kind in _types(child,root)]
            return all(_container_restricted(child,root,kind,seen) for child in relevant)
    return False


def _pair_wire_gap(schema, node):
    # Do not infer pairing from the mere presence of an unrelated applicator.
    # Prove rejection of invalid pairs only for an isolated value/evidence node.
    if set(node['properties'])!={'value','evidence'}:return 'nullable_pair_rule_not_verified'
    validator=Draft202012Validator(schema).evolve(schema=node)
    if validator.is_valid({'value':None,'evidence':'quoted'}):return 'nullable_pair_validator_dependency'
    domain=_domain(node['properties']['value'],schema)
    samples=(domain or [])+['quoted','',0,1,True,False]
    nonnull=[v for v in samples if v is not None and validator.is_valid({'value':v,'evidence':'quoted'})]
    if not validator.is_valid({'value':None,'evidence':None}) or not nonnull:
        return 'nullable_pair_rule_not_verified'
    if any(validator.is_valid({'value':v,'evidence':None}) for v in nonnull):return 'nullable_pair_validator_dependency'
    return None


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
        types = _types(node,schema)
        fields.append({'path': path, 'types': sorted(types),
                       'enum': deepcopy(node.get('enum')),
                       'required': deepcopy(node.get('required', [])),
                       'description': node.get('description')})
        if not types and not any(k in node for k in ('$ref', 'enum', 'const', 'allOf', 'not')):
            finding(path, 'type_not_enforced', 'No explicit wire type or categorical restriction.')
        if '$dynamicRef' in node:
            finding(path,'unsupported_dynamic_reference','Dynamic reference behavior is not audited.')
        if 'array' in types and not _container_restricted(node,schema,'array'):
            finding(path,'array_items_unconstrained','Array items have no declared wire restriction.')
        if 'object' in types or 'properties' in node:
            if not _container_restricted(node,schema,'object'):
                finding(path, 'open_object', 'Unexpected fields are not explicitly prohibited.')
            props = node.get('properties',{})
            for name in props:
                if name not in node.get('required',[]):finding(path+'/properties/'+_pointer(name),'property_optional','Declared property is optional at this schema node.')
            if {'value', 'evidence'} <= props.keys():
                if not {'value', 'evidence'} <= set(node.get('required', [])):
                    finding(path, 'claim_pair_not_required', 'Value/evidence pair is not required by schema.')
                # Pairing may be checked by the mechanical validator; record the
                # wire-schema gap separately rather than claiming it is absent.
                if 'null' in _types(props['value'],schema) and (node.get('type')=='object' or {'value','evidence'}<=set(node.get('required',[]))):
                    gap=_pair_wire_gap(schema,node)
                    if gap:finding(path,gap,'Nullable pairing requires post-validation or further schema-rule inspection.')
    for expected in expectations:
        if type(expected) is not dict or not {'path', 'role'} <= expected.keys():
            raise ValueError('Schema expectation requires path and role')
        path, role = expected['path'], expected['role']
        node = by_path.get(path)
        if type(node) is not dict:
            finding(path, 'expected_field_missing', 'Expected schema field is absent.')
            continue
        types = _types(node,schema)
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
            if any(v is None or v=='__unmatched_option__' for v in choices):raise ValueError('Canonical choices exclude reserved null/unmatched entries; use explicit flags')
            if len({digest(v) for v in choices})!=len(choices):raise ValueError('Canonical choices must be unique')
            actual = _domain(node,schema)
            if not isinstance(actual, list):
                finding(path, 'canonical_domain_not_enforced', 'Declared choices use an open claim.')
            else:
                label = lambda v: json.dumps(v, sort_keys=True, allow_nan=False)
                wanted = {label(v) for v in choices}
                seen = {label(v) for v in actual if v not in (None, '__unmatched_option__')}
                for key,choice in (('nullable',None),('unmatched_option','__unmatched_option__')):
                    if key in expected and (label(choice) in {label(v) for v in actual}) is not expected[key]:
                        finding(path,'canonical_special_choice_differs','Declared null/unmatched behavior differs.')
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
    if not hasattr(grader,'contract'):result['findings'].append({'path':'grader.contract','kind':'grader_contract_missing','detail':'No explicit response contract supplied.'})
    if not hasattr(grader,'extraction_instructions'):result['findings'].append({'path':'grader.extraction_instructions','kind':'grader_instructions_missing','detail':'No explicit extraction instructions supplied.'})
    result.update(source_hash_scope='defining_class_module_only_not_transitive_dependencies',grader_class=type(grader).__module__+'.'+type(grader).__qualname__,
                  source={'path': source, 'sha256': source_sha},
                  contract=deepcopy(getattr(grader, 'contract', {})),
                  extraction_instructions_sha256=digest(getattr(grader, 'extraction_instructions', None)))
    rows = []
    for entry in observations:
        if entry.get('control') not in ('correct', 'wrong', 'missing', 'malformed'):
            raise ValueError('Declare correct/wrong/missing/malformed audit control')
        grade = entry.get('grade')
        oracle=grade.get('oracle_grade') if isinstance(grade,dict) else None
        checks=oracle.get('requirements',{}) if isinstance(oracle,dict) else {}
        if isinstance(grade,dict) and 'oracle_grade' in grade and not isinstance(oracle,dict):
            result['findings'].append({'path':'observations','kind':'native_checks_unavailable','detail':'Oracle check structure is absent or malformed.'})
        if not isinstance(checks, dict):
            raise ValueError('Observed native requirements must be an object')
        verdict=None if not isinstance(grade,dict) else grade.get('structured_claims_correct')
        if type(verdict) is not bool and entry.get('error') is None:
            result['findings'].append({'path':'observations','kind':'native_verdict_missing','detail':'Control returned no Boolean native verdict.'})
        expected=entry.get('expected_verdict',True if entry['control']=='correct' else False if entry['control'] in ('wrong','missing') else None)
        if expected is not None and type(expected) is not bool:raise ValueError('Expected native verdict must be Boolean')
        if entry['control']=='malformed' and entry.get('error') is not None:
            result['findings'].append({'path':'observations','kind':'malformed_control_rejected_without_task_verdict','detail':'Validator rejection is separate from a native task verdict.'})
        elif expected is not None and verdict is not expected:
            result['findings'].append({'path':'observations','kind':'native_verdict_mismatch','detail':'Control verdict does not match its explicit expected outcome.'})
        rows.append({'control': entry['control'],
                     'verdict': None if not isinstance(grade, dict) else grade.get('structured_claims_correct'),
                     'native_checks': deepcopy(checks),
                     'error': deepcopy(entry.get('error')),
                     'expected_verdict': expected,
                     'mutation': deepcopy(entry.get('mutation'))})
    result['observed_grading'] = rows
    result['limitations'] = [
        'Schema validation and supplied claims do not prove actual extractor interpretation.',
        'Observed checks describe these controls, not full-answer or whole-run effect coverage.',
        'Reference-to-grade roundtrip alone is not independent oracle validation.',
    ]
    return result
