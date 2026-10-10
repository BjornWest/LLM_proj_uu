"""Predeclare mixed-product basket requirements, then bind the natural world.

The complete ordinary population, assortment, stock and public checkout domain
are retained. Search limits bound computation only; incomplete search cannot
support a graded optimum or an infeasibility answer.
"""
from copy import deepcopy

from . import catalog_basket_task as native, unified_generation as unified

VERSION = 'website-catalog-basket-generation-v1'


def compile_request(request):
    if type(request) is not dict or request.get('schema') != unified.VERSION:
        raise ValueError('Declare a unified accepted-catalog request')
    spec = request.get('task')
    if type(spec) is not dict or spec.get('kind') != native.KIND:
        raise ValueError('Declare a mixed-catalog basket task')
    search = request.get('basket_search', {'max_work': 250000, 'max_seconds': 30.0})
    from experiments.footwear_world_pilot.order_set_optimizer import _Work
    search = deepcopy(_Work(search).budget)  # defensive finite budget validation, no search
    proxy = deepcopy(request)
    proxy.pop('basket_search', None)
    proxy['task'] = {'user_message': 'Browse the generated retailers. Do not place an order.', 'memories': []}
    world = proxy.setdefault('world', {})
    if type(world) is not dict:
        raise ValueError('World configuration must be an object')
    if type(spec.get('requirements')) is not list:
        raise ValueError('Basket requirements must be a list')
    concepts = [row.get('concept_id') for row in spec['requirements'] if type(row) is dict]
    if 'tasks' not in world:
        # This is the existing soft concentration control, not a guarantee that
        # enough products/stores/stock exist to make the basket feasible.
        world['tasks'] = list(dict.fromkeys(c for c in concepts if type(c) is str))
    config = unified.compile_request(proxy)
    inventory = native.Inventory()
    selection = native.resolve(spec, concept_ids=config['world']['concept_ids'], inventory=inventory)
    return {'proxy_request': proxy, 'selection': selection, 'inventory': inventory, 'search': search}


def generate(request, *, world_factory=None):
    config = compile_request(request)
    result = unified.generate(config['proxy_request'], world_factory=world_factory)
    task = native.make(result['world'], config['selection'],
                       checkout_domain=result['checkout_domain'], inventory=config['inventory'])
    reference = native.reference(result['world'], task, plan=result['basket_plan'],
        checkout_domain=result['checkout_domain'], admission_plan=result.get('delivery_plan'),
        inventory=config['inventory'], budget=config['search'])
    result.update(catalog_basket_task=task, catalog_basket_reference=reference,
                  catalog_basket_binding={'status': 'bound_exact_reference' if reference['result']['complete']
                                          else 'inconclusive_search', 'world_repaired': False})
    result['episode'].update(task_id=task['task_id'],
                            manual_task={'user_message': task['user_message'], 'memories': task['memories']})
    result['resolved_configuration'].update(request=deepcopy(request), task=deepcopy(config['selection']),
                                          basket_search=deepcopy(config['search']))
    result['audit']['proxy_request_sha256'] = result['audit']['request_sha256']
    result['audit']['request_sha256'] = unified.shared.digest(request)
    return result
