"""Finite qualifier labels from declarations, never sampled answers or prose.

A registered fixed basis is a public measurement scope. A reference assembly
may instead be a literal member of a complete joint-choice table. Follow only
unconditional copies and literal tables; expressions outside this small closed
subset keep their existing literal extraction contract.
"""
import ast
from collections.abc import Mapping
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from .canonical_claims import UNMATCHED, canonical_claim

VERSION = 'website-canonical-qualifier-domains-v1'
ROOT = Path(__file__).resolve().parents[2]


def _labels(values):
    if not isinstance(values, (list, tuple)) or not values or any(type(v) is not str or not v.strip() for v in values):
        return None
    result = list(dict.fromkeys(values))
    folded = [v.strip().casefold() for v in result]
    if UNMATCHED.casefold() in folded or len(folded) != len(set(folded)):
        return None
    return result


def measurement_basis_values(scope):
    """Only source-declared scopes; a private expected basis is not a menu."""
    if not isinstance(scope, Mapping):
        return None
    basis = scope.get('basis')
    if scope.get('origin') == 'registered_constant_field':
        declared = scope.get('declaration', {})
        if declared.get('type') != 'string' or declared.get('constant') != basis:
            raise ValueError('Measurement basis differs from its declaration')
    elif scope.get('origin') != 'numeric_field_declaration':
        return None
    return _labels([basis])


def qualifier_claim(values):
    schema = canonical_claim(values)
    schema['properties']['value']['description'] += (
        ' This is a measurement/reference scope, not a selected-SKU label. '
        'Preserve every stated dimension, unit-count/size basis, capacity role, '
        'platform, connection and colour. Added explicit RAM/storage role words '
        'can be equivalent; missing, conflicting or different dimensions are not. '
        'Do not transfer a qualification to an unrelated fact.')
    return schema


def _path(expression):
    if type(expression) is not str:
        return None
    try:
        node = ast.parse(expression, mode='eval').body
    except SyntaxError:
        return None
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    return '.'.join([node.id, *reversed(parts)])


def finite_strings(document, field):
    """Complete constant/enum/table outputs, without invoking the sampler.

    No probabilities, cases, sampled models, stock, task selections or native
    reference values narrow the vocabulary. Conditional writes, multiple
    writers, missing table keys, cycles and computed expressions refuse it.
    """
    steps = document.get('steps', [])
    if not isinstance(steps, (list, tuple)):
        return None

    def flatten(rows, nested=False):
        result = []
        for step in rows:
            if isinstance(step, Mapping):
                result.append((step, nested))
                if 'steps' in step:
                    result.extend(flatten(step['steps'], True))
        return result

    written = flatten(steps)
    program_targets = []
    for program in document.get('programs', {}).values():
        if isinstance(program, Mapping):
            program_targets.extend(step['target'] for step, _ in flatten(program.get('steps', []))
                                   if type(step.get('target')) is str)

    def visit(path, visiting):
        if path in visiting:
            return None
        if any(path == target or path.startswith(target+'.') for target in program_targets):
            return None
        declaration = document.get('fields', {}).get(path, {})
        if declaration.get('type') == 'enum':
            return _labels(declaration.get('values', []))
        writers = [(step, nested) for step, nested in written
                   if type(step.get('target')) is str
                   and (path == step['target'] or path.startswith(step['target']+'.'))]
        if not writers and declaration.get('type') == 'string' and 'constant' in declaration:
            return _labels([declaration['constant']])
        if writers and 'constant' in declaration:
            return None
        if len(writers) != 1:
            return None
        step, nested = writers[0]
        marker = 'writer:'+step['target']
        if marker in visiting or len(visiting) > 128:
            return None
        if nested or 'when' in step:
            return None
        suffix = path[len(step['target']):].lstrip('.')
        if 'derive' in step and 'sample' not in step:
            source = _path(step['derive'])
            if source is not None:
                return visit(source+('.'+suffix if suffix else ''), visiting | {path, marker})
            if suffix:
                return None
            try:
                value = ast.literal_eval(step['derive'])
            except (ValueError, TypeError, SyntaxError):
                return None
            return _labels([value])
        if (any(key in step for key in ('values_expr', 'weights_from', 'values_from', 'eligible_from', 'domain_from'))
                or step.get('sample') != 'weighted_choice'
                or not isinstance(step.get('values'), Mapping)):
            return None
        # This subset permits only weight overrides, never alternate tables.
        if any(not isinstance(case, Mapping) or set(case)-{'when', 'weights'}
               for case in step.get('cases', [])):
            return None
        keys = set(step['values'])
        weights = [step.get('weights'), *[case.get('weights', {}) for case in step.get('cases', [])]]
        if any(not isinstance(row, Mapping) or not set(row) <= keys for row in weights):
            return None
        values = []
        for row in step['values'].values():
            for part in suffix.split('.') if suffix else []:
                if not isinstance(row, Mapping) or part not in row:
                    return None
                row = row[part]
            values.append(row)
        return _labels(values)

    values = visit(field, set())
    definition = document.get('fields', {}).get(field, {})
    sentinels = [*definition.get('unknown_values', []),
                 *definition.get('not_applicable_values', [])]
    return None if values is None else _labels([v for v in values if v not in sentinels])


def public_fact_domain(world, product_id, fact):
    """Source-bound public qualifier declarations; never use private profiles."""
    row = fact['row']
    qualifier = row.get('qualifier')
    if type(qualifier) is not str:
        return None
    assertions = [a for a in row.get('assertions', [])
                  if a.get('authority') == 'catalog_fact' and a.get('status') == 'known'
                  and a.get('subject') == {'kind': 'product', 'id': product_id}
                  and a.get('value') == qualifier and type(a.get('field')) is str
                  and a['field'].startswith('product.facts.')]
    if len(assertions) != 1:
        return None
    item = next(p for p in world['products'] if p['public']['product_id'] == product_id)
    concept = item['public'].get('concept_id')
    if type(concept) is not str:
        return None
    if '/' in concept or '\\' in concept:
        raise ValueError('Invalid qualifier concept declaration path')
    root = ROOT.resolve()
    gate = world.get('provenance', {}).get('accepted_package_gates', {}).get(concept, {})
    pinned = gate.get('source_hashes', {})
    names = ['environments/product_world/data/'+directory+'/'+concept+'.json'
             for directory in ('product_width', 'product_packages')]
    names = [name for name in names if name in pinned]
    # No world-bound declaration => keep the literal contract, regardless of
    # whether unrelated ambient declaration files happen to exist.
    if not names:
        return None
    if len(names) != 1:
        raise ValueError('Ambiguous world-pinned qualifier concept declaration')
    path = root/names[0]
    if not path.resolve().is_relative_to(path.parent.resolve()):
        raise ValueError('Invalid qualifier concept declaration path')
    sources = {}
    current = path.resolve()
    directory = path.parent.resolve()
    while True:
        if not current.is_relative_to(directory) or str(current.relative_to(root)) in sources:
            raise ValueError('Invalid qualifier declaration inheritance')
        name = str(current.relative_to(root))
        if name not in pinned or not current.is_file():
            raise ValueError('Missing world-pinned qualifier declaration: '+name)
        raw = current.read_bytes()
        observed = sha256(raw).hexdigest()
        if observed != pinned[name]:
            raise ValueError('Qualifier declaration differs from frozen world: '+name)
        sources[name] = observed
        parent = json.loads(raw).get('extends')
        if parent is None:
            break
        if type(parent) is not str:
            raise ValueError('Invalid qualifier declaration parent')
        current = (current.parent/parent).resolve()
    from environments.product_world.product_package import load_document
    document = load_document(path)
    field = assertions[0]['field']
    definition = document.get('fields', {}).get(field, {})
    if definition.get('type') not in ('string', 'enum'):
        return None
    values = finite_strings(document, field)
    for name, expected in sources.items():
        if sha256((root/name).read_bytes()).hexdigest() != expected:
            raise ValueError('Qualifier declaration source changed')
    if values is None:
        return None
    if qualifier not in values:
        raise ValueError('Public qualifier is outside its complete declaration domain')
    return {'version': VERSION, 'field': assertions[0]['field'],
            'values': deepcopy(values), 'source_sha256': sources}
