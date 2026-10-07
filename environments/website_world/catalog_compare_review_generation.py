"""Predeclare comparison/review obligations; leave native world sampling unchanged."""
from copy import deepcopy

from . import unified_generation, catalog_compare_review_task as native
from .catalog_comparison_task import make as make_comparison
from .feature_offer_task import FieldInventory
from .catalog_review_task import ReviewInventory

VERSION = 'website-catalog-compare-review-generation-v1'


def compile_request(request):
    if type(request) is not dict or request.get('schema') != unified_generation.VERSION:
        raise ValueError('Declare a unified accepted-catalog request')
    spec = request.get('task')
    if type(spec) is not dict or spec.get('kind') != native.KIND:
        raise ValueError('Declare a comparison plus same-model review task')
    inventory, reviews = FieldInventory(spec.get('concept_id')), ReviewInventory(spec.get('concept_id'))
    proxy = deepcopy(request)
    proxy['task'] = {'user_message': 'Browse retailer and review publications. Do not place an order.', 'memories': []}
    world = proxy.setdefault('world', {})
    if type(world) is not dict:
        raise ValueError('World options must be an object')
    world.setdefault('tasks', [inventory.concept_id])
    config = unified_generation.compile_request(proxy)
    selection = native.resolve(spec, inventory=inventory, review_inventory=reviews,
                               concept_ids=config['world']['concept_ids'])
    if not config['surrounding_options']['enabled'] or config['surrounding_options']['review_count'] == 0:
        raise ValueError('Enable review publications before sampling')
    return {'proxy_request': proxy, 'selection': selection,
            'inventory': inventory, 'review_inventory': reviews}


def generate(request, *, world_factory=None):
    config = compile_request(request)
    result = unified_generation.generate(config['proxy_request'], world_factory=world_factory)
    spec = config['selection']
    compared = make_comparison(result['world'], {'kind': 'compare_product_facts',
        'concept_id': spec['concept_id'], 'fields': spec['fields'], 'model_limit': 2},
        inventory=config['inventory'])
    task = reference = None
    binding = {'status': 'unsupported_fewer_than_two_carried_models', 'world_repaired': False}
    if len(compared['models']) == 2:
        task = native.make(result['world'], spec, inventory=config['inventory'],
                           review_inventory=config['review_inventory'])
        reference = native.reference(result['world'], task, inventory=config['inventory'],
                                     review_inventory=config['review_inventory'])
        coverage = {role: [s['site_id'] for s in result['surrounding']['sites']
            if s['kind'] == 'product_reviews' and t['subject']['product_id'] in s['product_ids']]
            for role, t in task['review_tasks'].items()}
        binding = {'status': 'bound' if all(coverage.values()) else 'unsupported_no_review_publication',
                   'publication_ids': coverage, 'world_repaired': False}
    result.update(catalog_compare_review_task=task, catalog_compare_review_reference=reference,
                  compare_review_task_binding=binding)
    # A consumer must additionally certify public field/corpus coverage. Never
    # launch the proxy manual task when the structured identity binding is absent.
    result['episode'].update(task_id=task['task_id'] if task else None,
        manual_task={'user_message': task['user_message'], 'memories': task['memories']}
                    if binding['status'] == 'bound' else None)
    result['resolved_configuration'].update(request=deepcopy(request), task=deepcopy(spec))
    result['audit']['proxy_request_sha256'] = result['audit']['request_sha256']
    result['audit']['request_sha256'] = unified_generation.shared.digest(request)
    return result
