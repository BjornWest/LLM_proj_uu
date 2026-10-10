"""Statistics recipe binds the ordinary named comparison, without data repair."""
from copy import deepcopy
from . import unified_generation as unified,catalog_statistics_task as native

VERSION='website-catalog-statistics-generation-v1'


def compile_request(request):
    if type(request) is not dict or request.get('schema')!=unified.VERSION:raise ValueError('Declare a unified world recipe')
    if type(request.get('task')) is not dict or type(request.get('world', {})) is not dict:
        raise ValueError('Task and world configuration must be objects')
    proxy=deepcopy(request);proxy['task']={'user_message':'Browse the generated comparison publications. Do not place an order.','memories':[]}
    proxy.setdefault('world',{}).setdefault('tasks',[request.get('task',{}).get('concept_id')])
    config=unified.compile_request(proxy);spec=native.resolve(request.get('task'),concept_ids=config['world']['concept_ids'])
    inventory=native.FieldInventory(spec['concept_id']);opts=config['surrounding_options']
    if not opts['enabled'] or spec['comparison_site_id'] not in {f'comparison-{i:02d}' for i in range(opts['comparison_count'])}:
        raise ValueError('Enable the named comparison site before sampling')
    return {'proxy_request':proxy,'selection':spec,'inventory':inventory}


def generate(request,*,world_factory=None):
    config=compile_request(request);result=unified.generate(config['proxy_request'],world_factory=world_factory)
    task=native.make(result['world'],result['surrounding'],config['selection'],inventory=config['inventory'])
    reference=native.reference(result['world'],result['surrounding'],task,inventory=config['inventory'])
    result.update(catalog_statistics_task=task,catalog_statistics_reference=reference)
    result['episode'].update(task_id=task['task_id'],manual_task={'user_message':task['user_message'],'memories':[]})
    result['resolved_configuration'].update(request=deepcopy(request),task=deepcopy(config['selection']))
    result['audit']['proxy_request_sha256']=result['audit']['request_sha256'];result['audit']['request_sha256']=unified.shared.digest(request)
    return result
