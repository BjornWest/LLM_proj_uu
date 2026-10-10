"""Predeclare factual dimensions, then bind named models without winner conditioning."""
from copy import deepcopy

from . import unified_generation, catalog_comparison_task as native
from .feature_offer_task import FieldInventory

VERSION = 'website-catalog-comparison-generation-v1'


def compile_request(request):
    if type(request) is not dict or request.get('schema') != unified_generation.VERSION:
        raise ValueError('Declare a unified catalog comparison request')
    spec = request.get('task')
    if type(spec) is not dict or spec.get('kind') != native.KIND:
        raise ValueError('Declare a model factual comparison task')
    inventory = FieldInventory(spec.get('concept_id'))
    proxy = deepcopy(request)
    proxy['task'] = {'user_message': 'Browse generated retailers. Do not place an order.', 'memories': []}
    world = proxy.setdefault('world', {})
    if type(world) is not dict:
        raise ValueError('World options must be an object')
    world.setdefault('tasks', [inventory.concept_id])
    config = unified_generation.compile_request(proxy)
    selection = native.resolve(spec, inventory=inventory, concept_ids=config['world']['concept_ids'])
    return {'proxy_request': proxy, 'selection': selection, 'inventory': inventory}


def generate(request, *, world_factory=None):
    config = compile_request(request)
    result = unified_generation.generate(config['proxy_request'], world_factory=world_factory)
    task = native.make(result['world'], config['selection'], inventory=config['inventory'])
    reference = native.reference(result['world'], task, inventory=config['inventory'])
    result.update(catalog_comparison_task=task, catalog_comparison_reference=reference)
    result['resolved_configuration'].update(request=deepcopy(request), task=deepcopy(config['selection']))
    result['audit']['proxy_request_sha256'] = result['audit']['request_sha256']
    result['audit']['request_sha256'] = unified_generation.shared.digest(request)
    result['episode'].update(task_id=task['task_id'],
        manual_task={'user_message': task['user_message'], 'memories': []})
    return result
