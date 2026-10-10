"""Predeclare local collection before unchanged ordinary population sampling."""
from copy import deepcopy

from . import feature_offer_generation as feature_generation, catalog_branch_task as native

VERSION = 'website-catalog-branch-stock-generation-v1'


def compile_request(request):
    if type(request) is not dict or type(request.get('task')) is not dict:
        raise ValueError('Declare a branch-stock generation task')
    proxy = deepcopy(request)
    proxy['task'] = native.feature_spec(request['task'])
    config = feature_generation.compile_request(proxy)
    selection = native.resolve(request['task'], inventory=config['inventory'],
                               concept_ids=[config['inventory'].concept_id])
    return {'feature_request': proxy, 'selection': selection, 'inventory': config['inventory']}


def generate(request, *, world_factory=None):
    config = compile_request(request)
    result = feature_generation.generate(config['feature_request'], world_factory=world_factory)
    task = native.make(result['world'], config['selection'], inventory=config['inventory'],
                       surrounding=result['surrounding'])
    reference = native.reference(result['world'], task, inventory=config['inventory'],
                                  surrounding=result['surrounding'])
    result.update(catalog_branch_task=task, catalog_branch_reference=reference)
    result['episode'].update(task_id=task['task_id'],
                            manual_task={'user_message': task['user_message'], 'memories': task['memories']})
    result['resolved_configuration'].update(request=deepcopy(request), task=deepcopy(config['selection']))
    result['audit']['feature_request_sha256'] = result['audit']['request_sha256']
    result['audit']['request_sha256'] = feature_generation.unified_generation.shared.digest(request)
    return result
