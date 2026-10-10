"""Additive carrier-profile task over unchanged accepted-world generation."""
from copy import deepcopy
from . import carrier_review_task as native, unified_generation

VERSION = 'website-carrier-review-generation-v1'


def compile_request(request):
    if type(request) is not dict or request.get('schema') != unified_generation.VERSION:
        raise ValueError('Declare an accepted-catalog generation request')
    selection = native.resolve(request.get('task'))
    inventory = native.ReviewInventory()
    proxy = deepcopy(request)
    proxy['task'] = {'user_message': 'Browse the published carrier reviews. Do not place an order.', 'memories': []}
    unified_generation.compile_request(proxy)
    return {'proxy_request': proxy, 'selection': selection, 'inventory': inventory}


def generate(request, *, world_factory=None):
    config = compile_request(request)
    result = unified_generation.generate(config['proxy_request'], world_factory=world_factory)
    publication = native.public_projection(result['world'])
    if config['selection']['carrier_index'] >= len(publication['profiles']):
        result.update(carrier_review_task=None, carrier_review_reference=None,
            carrier_review_binding={'status': 'unsupported_no_carrier_identity', 'world_repaired': False})
    else:
        task = native.make(result['world'], config['selection'], inventory=config['inventory'])
        reference = native.reference(result['world'], task, inventory=config['inventory'])
        result.update(carrier_review_task=task, carrier_review_reference=reference,
            carrier_review_binding={'status': 'requires_carrier_publication_adoption', 'world_repaired': False})
        result['episode'].update(task_id=task['task_id'], manual_task={
            'user_message': task['user_message'], 'memories': []})
    result['carrier_review_publication'] = publication
    result['resolved_configuration'].update(request=deepcopy(request), task=deepcopy(config['selection']))
    result['audit']['proxy_request_sha256'] = result['audit']['request_sha256']
    result['audit']['request_sha256'] = unified_generation.shared.digest(request)
    return result
