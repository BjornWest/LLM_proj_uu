"""Typed multi-concept matching and exact combined-payable basket references.

Manufacturer predicates reuse the same known/applicable field inventory as single
item tasks. Matching retains sold-out offers; physical fulfilment, supplier waits
and service admission are evaluated only by the shared basket oracle.
"""
from copy import deepcopy
from datetime import date
from hashlib import sha256
from pathlib import Path

from experiments.accepted_catalog_commerce import basket_quote, order_set_optimizer
from . import catalog_checkout_domain
from .adapter import digest
from .catalog_predicates import PredicateSet
from .feature_offer_task import FieldInventory, _wording

VERSION = 'website-catalog-basket-task-v1'
REFERENCE_VERSION = 'website-catalog-basket-reference-v1'
KIND = 'cheapest_matching_order_set'
ROOT = Path(__file__).resolve().parents[2]
DESTINATIONS = {'home', 'parcel_locker', 'staffed_counter', 'retailer_branch'}


class Inventory:
    def __init__(self):
        self._fields = {}

    def fields(self, concept_id):
        if concept_id not in self._fields:
            self._fields[concept_id] = FieldInventory(concept_id)
        return self._fields[concept_id]


def resolve(value, *, concept_ids, inventory=None):
    inventory = inventory or Inventory()
    if (type(value) is not dict or set(value) != {'kind', 'requirements', 'domain'}
            or value['kind'] != KIND or type(value['requirements']) is not list
            or not value['requirements']):
        raise ValueError('Declare cheapest_matching_order_set, requirements and domain')
    rows, ids = [], set()
    for row in value['requirements']:
        if (type(row) is not dict or set(row) != {'requirement_id', 'quantity', 'concept_id', 'predicates'}
                or type(row['requirement_id']) is not str or not row['requirement_id'].strip()
                or row['requirement_id'] in ids or type(row['quantity']) is not int or row['quantity'] < 1
                or type(row['concept_id']) is not str or row['concept_id'] not in concept_ids):
            raise ValueError('Each requirement needs a unique ID, positive quantity, enabled concept and predicates')
        fields = inventory.fields(row['concept_id'])
        fields.check_sources()
        compiled = PredicateSet(fields.fields, row['predicates'], known_paths=fields.known_paths)
        rows.append({**deepcopy(row), 'predicates': compiled.predicates})
        ids.add(row['requirement_id'])
    domain = value['domain']
    if (type(domain) is not dict or set(domain) - {'destination', 'allowed_destination_types', 'deadline', 'allow_extras'}
            or domain.get('destination') != 'user_home'):
        raise ValueError('Use the generated user_home destination and declared delivery restrictions')
    allowed = domain.get('allowed_destination_types', sorted(DESTINATIONS))
    if (type(allowed) is not list or not allowed or any(type(v) is not str or v not in DESTINATIONS for v in allowed)
            or len(set(allowed)) != len(allowed)):
        raise ValueError('Declare nonempty distinct supported destination types')
    deadline = domain.get('deadline')
    if deadline is not None:
        try:
            if type(deadline) is not str or date.fromisoformat(deadline).isoformat() != deadline:
                raise ValueError()
        except ValueError as exc:
            raise ValueError('Deadline must be an ISO date or null') from exc
    if type(domain.get('allow_extras', True)) is not bool:
        raise ValueError('Extras policy must be boolean')
    return {'kind': KIND, 'requirements': rows,
            'domain': {'destination': 'user_home', 'allowed_destination_types': sorted(allowed),
                       'deadline': deadline, 'allow_extras': domain.get('allow_extras', True)}}


def _selection(task):
    return {k: deepcopy(task[k]) for k in ('kind', 'requirements', 'domain')}


def make(world, spec, *, checkout_domain, inventory=None):
    inventory = inventory or Inventory()
    selection = resolve(spec, concept_ids=world['config']['concept_ids'], inventory=inventory)
    domain_sha = catalog_checkout_domain.validate(world, checkout_domain)
    declarations = {}
    parts = []
    for row in selection['requirements']:
        fields = inventory.fields(row['concept_id'])
        compiled = PredicateSet(fields.fields, row['predicates'], known_paths=fields.known_paths)
        declarations[row['requirement_id']] = {
            'fields': deepcopy(compiled.fields), 'source_sha256': deepcopy(fields.source_hashes),
            'known_paths': sorted(set(compiled.fields) & set(fields.known_paths))}
        features = '; '.join(_wording(p, fields.fields[p['field']]) for p in row['predicates'])
        label = row['concept_id'].split('.')[-1].replace('_', ' ')
        parts.append(f"{row['quantity']} retail sale unit(s) of {label}" + (f' with {features}' if features else ''))
    message = ('Find the lowest combined payable total including shipping for: ' + '; '.join(parts) + '. '
               'One or more separate orders at the same or different retailers are allowed. '
               'Each purchased unit may satisfy only one requested unit. Quantities count retail sale units, '
               'not the individual contents of a multipack. Use known, applicable specifications; unknown '
               'or not-applicable values do not establish a match. Compare the complete checkout totals '
               'within the published cart quantity and line limits. Do not place an order. ')
    message += ('Extra unrequested products or quantities are allowed if they reduce the combined payable total. '
                if selection['domain']['allow_extras'] else 'Do not add unrequested products or quantities. ')
    message += 'Do not use account discounts or coupons; those are outside this task. '
    message += 'Allowed delivery modes: ' + ', '.join(selection['domain']['allowed_destination_types']) + '. '
    if selection['domain']['deadline']:
        message += 'Every order must have an estimated latest arrival on or before ' + selection['domain']['deadline'] + '. '
    else:
        message += 'Arrival speed does not affect ranking. '
    message += 'Give every item/variant link, retailer, quantity, chosen delivery option and complete total; if no feasible plan exists, say so.'
    task = {'schema_version': VERSION, **selection, 'world_id': world['world_id'],
            'world_sha256': digest(world), 'checkout_domain_sha256': domain_sha,
            'declarations': declarations, 'user_message': message, 'memories': [],
            'quantity_basis': 'retail_sale_units', 'objective': 'minimum_combined_payable_minor'}
    task['task_id'] = 'catalog-basket-' + digest(task)[:24]
    return task


def match(world, task, *, checkout_domain, inventory=None):
    inventory = inventory or Inventory()
    if task != make(world, _selection(task), checkout_domain=checkout_domain, inventory=inventory):
        raise ValueError('Basket task/world/field/domain binding changed')
    products = {p['public']['product_id']: p for p in world['products']}
    matches, evaluations = {}, {}
    for row in task['requirements']:
        declaration = task['declarations'][row['requirement_id']]
        compiled = PredicateSet(declaration['fields'], row['predicates'], known_paths=declaration['known_paths'])
        matched = set()
        for pid, item in products.items():
            if item['public']['concept_id'] != row['concept_id']:
                continue
            for sku in item['public']['skus']:
                outcome = compiled.evaluate(item['public'], sku,
                    catalog_status=item.get('catalog_status', {}),
                    sku_status=item.get('sku_status', {}).get(sku['sku_id'], {}))
                key = row['requirement_id'] + '/' + sku['sku_id']
                evaluations[key] = outcome
                if outcome['state'] == 'match':
                    matched.add(sku['sku_id'])
        matches[row['requirement_id']] = matched
    requirements = [{'requirement_id': row['requirement_id'], 'quantity': row['quantity'],
                     'offer_ids': sorted(o['offer_id'] for r in world['retailers'] for o in r['offers']
                                         if o['sku_id'] in matches[row['requirement_id']])}
                    for row in task['requirements']]
    return {'requirements': requirements, 'evaluations': evaluations,
            'policy': 'known_applicable_manufacture; stock_and_supplier_feasibility_in_checkout'}


def source_identity(task):
    names = [__file__, order_set_optimizer.__file__, basket_quote.__file__,
             catalog_checkout_domain.__file__]
    from . import catalog_predicates, feature_offer_task, catalog_basket_grading
    from experiments.footwear_world_pilot import order_set_optimizer as historical
    names += [catalog_predicates.__file__, feature_offer_task.__file__,
              catalog_basket_grading.__file__, historical.__file__]
    result = {str(Path(name).resolve().relative_to(ROOT)): sha256(Path(name).read_bytes()).hexdigest()
              for name in names}
    for declaration in task['declarations'].values():
        result.update(declaration['source_sha256'])
    return result


def reference(world, task, *, plan, checkout_domain, admission_plan=None, inventory=None, budget=None):
    matching = match(world, task, checkout_domain=checkout_domain, inventory=inventory)
    domain = task['domain']
    result = order_set_optimizer.solve(world, matching['requirements'], plan=plan,
        allowed_destination_types=domain['allowed_destination_types'], deadline=domain['deadline'],
        allow_extras=domain['allow_extras'], quantity_limits=checkout_domain['quantity_limits'],
        max_lines_per_order=checkout_domain['options']['max_lines_per_order'],
        admission_plan=admission_plan, budget=budget)
    return {'schema_version': REFERENCE_VERSION, 'task_sha256': digest(task),
            'matching_sha256': digest(matching), 'checkout_domain_sha256': digest(checkout_domain),
            'source_sha256': source_identity(task), 'matching': matching, 'result': result,
            'result_sha256': digest(result),
            'limitations': ['Exact search-budget exhaustion remains inconclusive.',
                            'Native truth does not establish public exposure or a purchase.']}
