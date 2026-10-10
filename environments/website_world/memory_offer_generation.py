"""Resolve typed defaults before sampling, without preference/population repair."""
from copy import deepcopy

from . import feature_offer_task, feature_offer_generation, memory_offer_task

VERSION = 'website-memory-feature-generation-v1'


def compile_request(request):
    if type(request) is not dict or request.get('schema') != feature_offer_generation.unified_generation.VERSION:
        raise ValueError('Declare a unified accepted-catalog request')
    value = request.get('task')
    if type(value) is not dict or value.get('kind') != memory_offer_task.KIND:
        raise ValueError('Declare a memory feature task')
    world = request.get('world', {})
    if type(world) is not dict:
        raise ValueError('World options must be an object')
    inventory = feature_offer_task.FieldInventory(value.get('concept_id'))
    concepts = world.get('concept_ids', [inventory.concept_id])
    spec, selection, resolution = memory_offer_task.resolve(value, inventory=inventory, concept_ids=concepts)
    proxy = deepcopy(request); proxy['task'] = selection
    # This validates the actual world slice and all ordinary options too.
    feature_offer_generation.compile_request(proxy)
    return {'proxy_request': proxy, 'spec': spec, 'inventory': inventory, 'resolution': resolution}


def generate(request, *, world_factory=None):
    config = compile_request(request)
    result = feature_offer_generation.generate(config['proxy_request'], world_factory=world_factory)
    task = memory_offer_task.make(result['world'], config['spec'], inventory=config['inventory'], surrounding=result['surrounding'])
    reference = memory_offer_task.reference(result['world'], task, inventory=config['inventory'], surrounding=result['surrounding'])
    result['memory_offer_task'], result['memory_offer_reference'] = task, reference
    result['memory_offer_request'] = deepcopy(request)
    result['resolved_configuration'].update(request=deepcopy(request), task=deepcopy(config['spec']))
    result['audit']['feature_request_sha256'] = result['audit']['request_sha256']
    result['audit']['request_sha256'] = feature_offer_generation.unified_generation.shared.digest(request)
    result['episode'].update(task_id=task['task_id'], manual_task={
        'user_message': task['user_message'], 'memories': task['memories']})
    return result
