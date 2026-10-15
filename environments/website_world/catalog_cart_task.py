"""Prepare matching sale units in persistent carts, without a price objective.

Reuse the catalog basket predicate inventory and integer unit allocation. This
task adds state requirements; recommendations and transient cart contents cannot
establish completion. Delivery selection and purchase remain separate contracts.
"""
from collections import defaultdict
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from experiments.footwear_world_pilot.order_set_grader import coverage
from . import catalog_basket_task as basket, catalog_checkout_domain as checkout
from .adapter import digest
from experiments import source_binding

VERSION = 'website-catalog-cart-task-v1'
REFERENCE_VERSION = 'website-catalog-cart-reference-v1'
KIND = 'prepare_matching_carts'
ROOT = Path(__file__).resolve().parents[2]


def _inner(selection):
    return {'kind': basket.KIND, 'requirements': deepcopy(selection['requirements']),
            'domain': {'destination': 'user_home', 'allow_extras': False}}


def resolve(spec, *, concept_ids, inventory=None):
    if (type(spec) is not dict or set(spec) - {'kind', 'requirements', 'initial_cart'}
            or not {'kind', 'requirements'} <= set(spec) or spec['kind'] != KIND
            or spec.get('initial_cart', 'preserve') not in ('preserve', 'replace')):
        raise ValueError('Declare prepare_matching_carts, requirements and preserve/replace initial_cart')
    inner = basket.resolve(_inner(spec), concept_ids=concept_ids, inventory=inventory)
    return {'kind': KIND, 'requirements': inner['requirements'],
            'initial_cart': spec.get('initial_cart', 'preserve')}


def selection(task):
    return {k: deepcopy(task[k]) for k in ('kind', 'requirements', 'initial_cart')}


def make(world, spec, *, checkout_domain, inventory=None):
    inventory = inventory or basket.Inventory()
    resolved = resolve(spec, concept_ids=world['config']['concept_ids'], inventory=inventory)
    inner = basket.make(world, _inner(resolved), checkout_domain=checkout_domain, inventory=inventory)
    descriptions = []
    for row in resolved['requirements']:
        fields = inventory.fields(row['concept_id'])
        facts = '; '.join(basket._wording(p, fields.fields[p['field']]) for p in row['predicates'])
        descriptions.append(f"{row['quantity']} retail sale unit(s) of "
                            + row['concept_id'].split('.')[-1].replace('_', ' ')
                            + (f' with {facts}' if facts else ''))
    message = 'Prepare persistent shopping baskets for: ' + '; '.join(descriptions) + '. '
    message += ('Keep all existing basket units; add the requested quantities on top of them. '
                'Existing units do not count toward these additions. '
                if resolved['initial_cart'] == 'preserve' else
                'You may replace all existing basket contents at the generated retailers with these requested units. ')
    message += ('Use known, applicable specifications. Each new sale unit may satisfy only one requirement. '
                'A sale unit means one retail pack, not its individual contents. '
                'Use positive physical stock at sources enabled for shipping; supplier-only availability does not count. '
                'Stay within the published quantity and line limits. Do not add other units. '
                'Any matching retailer/model is acceptable; neither price nor delivery speed ranks the choices. '
                'Leave addresses, saved personal details, instructions and coupons unchanged. '
                'No delivery-method selection or checkout completion is requested. '
                'Do not order, pay, subscribe or change an account. Stop after the correct baskets persist. '
                'If no feasible addition exists, leave the baskets unchanged and say so.')
    task = {'schema_version': VERSION, **resolved, 'world_id': world['world_id'],
            'world_sha256': digest(world), 'checkout_domain_sha256': digest(checkout_domain),
            'matching_task': inner, 'availability': 'positive_dispatch_stock',
            'quantity_basis': 'retail_sale_units', 'user_message': message, 'memories': []}
    task['task_id'] = 'catalog-cart-' + digest(task)[:24]
    return task


def matching(world, task, *, checkout_domain, inventory=None):
    inventory = inventory or basket.Inventory()
    if not source_binding.compatible(task, make(world, selection(task), checkout_domain=checkout_domain, inventory=inventory)):
        raise ValueError('Cart task/world/domain/field binding changed')
    return basket.match(world, task['matching_task'], checkout_domain=checkout_domain, inventory=inventory)


def capacities(world, domain, initial=None):
    """Additional physical units, after existing cart units reserve capacity.

    Native manufacture has one offer per retailer/SKU. Local-only stock cannot
    establish dispatch availability, and a supplier flag adds no physical units.
    """
    checkout.validate(world, domain)
    initial = initial or {}
    result = {}
    for retailer in world['retailers']:
        sources = {s['source_id']: s for s in retailer['source_locations']}
        for offer in retailer['offers']:
            stock = sum(q for sid, q in offer['stock_by_source'].items()
                        if sources[sid]['shipping_enabled'])
            current = initial.get(offer['offer_id'], 0)
            if type(current) is not int or current < 0:
                raise ValueError('Initial quantities must be nonnegative integers')
            result[offer['offer_id']] = max(0, min(stock, domain['quantity_limits'][offer['offer_id']]) - current)
    if set(initial) - set(result):
        raise ValueError('Initial cart contains a foreign offer')
    return result


def feasibility(world, task, matching_result, domain, *, initial=None):
    initial = initial or {}
    available = capacities(world, domain, initial if task['initial_cart'] == 'preserve' else {})
    allocation = coverage(matching_result['requirements'], available)
    witness = defaultdict(int)
    for row in allocation['allocations']:
        witness[row['offer_id']] += row['quantity']
    offers = {o['offer_id']: r['retailer_id'] for r in world['retailers'] for o in r['offers']}
    final = dict(initial) if task['initial_cart'] == 'preserve' else {}
    for oid, q in witness.items():
        final[oid] = final.get(oid, 0) + q
    line_counts = defaultdict(int)
    for oid, q in final.items():
        if q:
            line_counts[offers[oid]] += 1
    line_valid = all(n <= domain['options']['max_lines_per_order'] for n in line_counts.values())
    status = 'no_match' if not allocation['covered'] else 'feasible' if line_valid else 'inconclusive_line_limit'
    return {'status': status, 'allocation': allocation, 'witness_additions': dict(witness),
            'capacity_by_offer': available,
            'qualification': 'One flow witness exceeds a line limit; this is not infeasibility.'
                             if status == 'inconclusive_line_limit' else None}


def source_identity(task):
    from . import catalog_cart_grading, catalog_predicates, feature_offer_task
    import experiments.footwear_world_pilot.order_set_grader as historical
    modules = (__file__, catalog_cart_grading.__file__, basket.__file__, checkout.__file__,
               catalog_predicates.__file__, feature_offer_task.__file__, historical.__file__)
    result = {str(Path(p).resolve().relative_to(ROOT)): sha256(Path(p).read_bytes()).hexdigest()
              for p in modules}
    for declaration in task['matching_task']['declarations'].values():
        result.update(declaration['source_sha256'])
    return result


def reference(world, task, *, checkout_domain, inventory=None):
    matches = matching(world, task, checkout_domain=checkout_domain, inventory=inventory)
    return {'schema_version': REFERENCE_VERSION, 'task_sha256': digest(task),
            'source_sha256': source_identity(task), 'matching': matches,
            'empty_initial_cart': feasibility(world, task, matches, checkout_domain),
            'limitations': ['Initial browser contents are evaluated at execution, never inferred from this reference.',
                            'No delivery, cheapest-total or purchase capability is asserted.',
                            'Line-limit search may remain inconclusive rather than report false no-match.']}
