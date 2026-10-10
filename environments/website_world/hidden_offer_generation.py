"""Validate missing personal information before sampling, never repair the world."""
from copy import deepcopy
from . import feature_offer_generation, feature_offer_task, hidden_offer_task

VERSION = 'website-hidden-offer-generation-v1'


def compile_request(request):
    if type(request) is not dict or request.get('schema') != feature_offer_generation.unified_generation.VERSION:
        raise ValueError('Declare a unified accepted-catalog request')
    value = request.get('task'); world = request.get('world',{})
    if type(value) is not dict or value.get('kind') != hidden_offer_task.KIND or type(world) is not dict:
        raise ValueError('Declare hidden task and object world options')
    inventory = feature_offer_task.FieldInventory(value.get('concept_id'))
    spec,selection = hidden_offer_task.resolve(value,inventory=inventory,
        concept_ids=world.get('concept_ids',[inventory.concept_id]))
    proxy = deepcopy(request); proxy['task'] = selection
    feature_offer_generation.compile_request(proxy)
    return {'proxy_request':proxy,'spec':spec,'inventory':inventory}


def generate(request,*,world_factory=None):
    config = compile_request(request)
    result = feature_offer_generation.generate(config['proxy_request'],world_factory=world_factory)
    task = hidden_offer_task.make(result['world'],config['spec'],inventory=config['inventory'],surrounding=result['surrounding'])
    reference = hidden_offer_task.reference(result['world'],task,inventory=config['inventory'],surrounding=result['surrounding'])
    result['hidden_offer_task'],result['hidden_offer_reference'] = task,reference
    result['hidden_offer_binding'] = {'status':'bound' if reference['clarification_affects_eligibility'] else 'unsupported_no_effectful_clarification',
                                     'world_repaired':False,'task_id':task['task_id']}
    result['resolved_configuration'].update(request=deepcopy(request),task=deepcopy(config['spec']))
    result['audit']['feature_request_sha256'] = result['audit']['request_sha256']
    result['audit']['request_sha256'] = feature_offer_generation.unified_generation.shared.digest(request)
    result['episode'].update(task_id=task['task_id'],manual_task={'user_message':task['user_message'],'memories':task['memories']})
    return result
