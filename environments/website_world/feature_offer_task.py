"""Feature-constrained listed-price tasks using the existing finite offer domain.

Field meanings/types come from inherited concept declarations. Unknown and logical
NA never satisfy a requirement. Publication/evidence coverage is a separate sidecar;
native known facts are not proof that any retailer disclosed them.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from environments.product_world.product_package import load_document
from environments.product_world import reviewed_feature_publication as publication
from environments.product_world.shared_state import mutable
from experiments.accepted_catalog_commerce import package_export
from . import basic_offer_task
from .adapter import digest
from .catalog_predicates import PredicateSet
from experiments import source_binding

VERSION = 'website-feature-listed-offer-task-v1'
KIND = 'cheapest_matching_available'
ROOT = Path(__file__).resolve().parents[2]


class FieldInventory:
    """Load declarations once; source hashes follow the exact inheritance chain."""
    def __init__(self, concept_id):
        if concept_id not in package_export.SUPPORTED_CONCEPTS:
            raise ValueError('Concept is not in the accepted commerce slice')
        directory = ROOT/'environments/product_world/data'/(
            'product_packages' if concept_id in package_export.PILOTS else 'product_width')
        path = directory/(concept_id+'.json')
        self.source_hashes = {}
        current = path.resolve()
        while True:
            if not current.is_relative_to(directory.resolve()) or str(current.relative_to(ROOT)) in self.source_hashes:
                raise ValueError('Invalid package inheritance chain')
            raw = current.read_bytes()
            self.source_hashes[str(current.relative_to(ROOT))] = sha256(raw).hexdigest()
            parent = json.loads(raw).get('extends')
            if parent is None:
                break
            current = (current.parent/parent).resolve()
        document = load_document(path)
        policy = publication.load_reviewed_policy(concept_id)
        manifest = json.loads((publication.CATALOGUE/'manifest.json').read_text())
        policy_path = publication.CATALOGUE/manifest['concepts'][concept_id]['file']
        self.source_hashes[str(policy_path.relative_to(ROOT))] = publication.policy_sha256(concept_id)
        self.publication = {k: mutable(v) for k, v in policy['fields'].items()
                            if v['role'] in {'literal', 'descriptive', 'buying_choice', 'operational'}}
        self.fields = {k: d for k, d in document['fields'].items() if k in self.publication or
                       k.startswith('sku.') and 'retail_presentation' in d}
        # The reviewed projection supplies logical NA/sentinel meanings and
        # measurement scope sometimes absent from the old raw graph declaration.
        # Keep sampling types/domains; preserve this authored semantic metadata.
        for field, definition in self.fields.items():
            semantic = self.publication.get(field, {}).get('definition', {})
            for key in ('unknown_values', 'not_applicable_values', 'applicable_when', 'basis', 'unit', 'component'):
                if key in semantic:
                    definition[key] = deepcopy(semantic[key])
        self.concept_id = concept_id
        # Pilot exports predate status projections. Restrict the adapter to the
        # concept's declared fact/variant scalars; declared sentinels still win.
        self.known_paths = tuple(k for k, d in self.fields.items()
            if concept_id in package_export.PILOTS and
            (k.startswith('product.facts.') or k.startswith('sku.')) and
            d['type'] in {'boolean', 'integer', 'number', 'enum', 'string'})
        self.check_sources()

    def check_sources(self):
        for name, expected in self.source_hashes.items():
            if sha256((ROOT/name).read_bytes()).hexdigest() != expected:
                raise ValueError('Field declaration source changed: '+name)


def resolve(value, *, inventory, concept_ids):
    allowed = {'kind', 'concept_id', 'predicates', 'availability', 'max_price_minor', 'comparison_site_id'}
    if type(value) is not dict or set(value)-allowed or not {'kind', 'concept_id', 'predicates'} <= set(value):
        raise ValueError('Declare kind, concept_id and predicates')
    if value['kind'] != KIND or value['concept_id'] != inventory.concept_id or value['concept_id'] not in concept_ids:
        raise ValueError('Task concept must match its field inventory and world slice')
    if type(value['predicates']) is not list or not value['predicates']:
        raise ValueError('A feature task needs at least one predicate')
    compiled = PredicateSet(inventory.fields, value['predicates'], known_paths=inventory.known_paths)
    availability = value.get('availability', 'purchasable')
    if availability not in ('purchasable', 'positive_stock'):
        raise ValueError('Availability is purchasable or positive_stock')
    cap = value.get('max_price_minor')
    if cap is not None and (type(cap) is not int or cap < 0):
        raise ValueError('Price threshold must be nonnegative integer ore')
    result = {'kind': KIND, 'concept_id': inventory.concept_id,
              'predicates': compiled.predicates, 'availability': availability}
    if 'max_price_minor' in value:
        if cap is None:
            raise ValueError('An explicit price threshold cannot be null')
        result['max_price_minor'] = cap
    if 'comparison_site_id' in value:
        # Reuse the existing comparison-scope ID contract, independently of prices.
        basic_offer_task.resolve({'kind': 'cheapest_available', 'concept_id': inventory.concept_id,
            'comparison_site_id': value['comparison_site_id']}, seed=0, concept_ids=concept_ids)
        result['comparison_site_id'] = value['comparison_site_id']
    return result


def _base_task(world, spec, surrounding):
    selection = {'kind': 'cheapest_available', 'concept_id': spec['concept_id']}
    if 'comparison_site_id' in spec:
        selection['comparison_site_id'] = spec['comparison_site_id']
    return basic_offer_task._make_bound(world, selection, digest(world), surrounding=surrounding)


def _wording(predicate, definition):
    labels = {'eq': 'equal to', 'ne': 'different from', 'ge': 'at least', 'le': 'at most',
              'gt': 'greater than', 'lt': 'less than', 'in': 'one of', 'not_in': 'not any of',
              'contains': 'including', 'excludes': 'excluding'}
    field = predicate['field'].removeprefix('product.facts.').removeprefix('sku.').replace('_', ' ')
    value = json.dumps(predicate['value'], ensure_ascii=False)
    unit = ' '+definition['unit'] if 'unit' in definition else ''
    basis = ' ('+definition['basis']+')' if 'basis' in definition else ''
    return field+' '+labels[predicate['operator']]+' '+value+unit+basis


def make(world, selection, *, inventory, surrounding=None):
    """Bind a predeclared task without repairing population or selecting a winner."""
    inventory.check_sources()
    spec = resolve(selection, inventory=inventory, concept_ids=world['config']['concept_ids'])
    base = _base_task(world, spec, surrounding)
    compiled = PredicateSet(inventory.fields, spec['predicates'], known_paths=inventory.known_paths)
    requirements = '; '.join(_wording(p, inventory.fields[p['field']]) for p in spec['predicates'])
    message = base['user_message'].replace('Any model, variant or pack is acceptable.',
        'Requirements: '+requirements+'. Any model or variant satisfying all these requirements is acceptable. '
        'Use known, applicable specifications; unknown or not-applicable values do not establish a match.')
    if spec['availability'] == 'positive_stock':
        message = message.replace('Stock at any shop or warehouse and supplier orders count as available.',
            'Require positive physical stock at a shop or warehouse; supplier-only orders do not count.')
    if 'max_price_minor' in spec:
        cap = spec['max_price_minor']
        message += f' The listed price must be at most {cap//100}.{cap%100:02d} SEK.'
    message = message.replace('If none are available, say so.',
        'If no available option has specifications establishing all requirements, say so; '
        'do not claim an unknown specification is physically false.')
    task = {**base, 'schema_version': VERSION, **deepcopy(spec), 'user_message': message,
            'field_declarations': compiled.fields, 'field_source_sha256': deepcopy(inventory.source_hashes),
            'field_publication': {k: deepcopy(inventory.publication.get(k, {
                'role': 'buying_choice', 'definition': compiled.fields[k],
                'mapping_status': 'declared_pilot_variant_without_authored_meaning'})) for k in compiled.fields},
            'known_scalar_paths': sorted(set(compiled.fields) & set(inventory.known_paths)),
            'matching_policy': 'known_applicable_native_values'}
    task.pop('task_id')
    task['task_id'] = 'feature-offer-'+digest(task)[:24]
    return task


def reference(world, task, *, inventory, surrounding=None):
    spec = {k: task[k] for k in ('kind', 'concept_id', 'predicates', 'availability',
            'max_price_minor', 'comparison_site_id') if k in task}
    if not source_binding.compatible(task, make(world, spec, inventory=inventory, surrounding=surrounding)):
        raise ValueError('Feature task/world/declaration binding changed')
    base = _base_task(world, spec, surrounding)
    native = basic_offer_task._reference_bound(world, base)
    compiled = PredicateSet(inventory.fields, task['predicates'], known_paths=task['known_scalar_paths'])
    products = {item['public']['product_id']: item for item in world['products']}
    evaluations = {}
    for item in products.values():
        if item['public']['concept_id'] != task['concept_id']:
            continue
        for sku in item['public']['skus']:
            evaluations[sku['sku_id']] = compiled.evaluate(item['public'], sku,
                catalog_status=item.get('catalog_status', {}),
                sku_status=item.get('sku_status', {}).get(sku['sku_id'], {}))
    offers = {o['offer_id']: o for r in world['retailers'] for o in r['offers']}
    candidates, excluded, indeterminate = [], [], []
    for row in native['candidates']:
        oid = row['offer_id']
        state = evaluations[row['sku_id']]['state']
        if state == 'indeterminate':
            indeterminate.append(oid)
        positive_stock = any(q > 0 for q in offers[oid]['stock_by_source'].values())
        if (state != 'match' or task['availability'] == 'positive_stock' and not positive_stock or
                'max_price_minor' in task and row['price_minor'] > task['max_price_minor']):
            excluded.append(oid)
            continue
        candidates.append(deepcopy(row))
    price = candidates[0]['price_minor'] if candidates else None
    return {**native, 'schema_version': VERSION, 'task_id': task['task_id'],
            'status': 'match' if candidates else 'no_match', 'minimum_price_minor': price,
            'candidates': candidates, 'winners': [r for r in candidates if r['price_minor'] == price],
            'excluded_offer_ids': sorted(excluded), 'indeterminate_offer_ids': sorted(indeterminate),
            'predicate_evaluations': evaluations, 'matching_policy': task['matching_policy'],
            'evidence_coverage': 'not_inferred_from_native_truth'}
