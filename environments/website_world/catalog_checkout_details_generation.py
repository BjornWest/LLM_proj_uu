"""Known address/instruction memories over the unchanged cart population caller."""
from copy import deepcopy
from . import catalog_cart_generation as carts, catalog_checkout_details_task as native

VERSION='website-catalog-checkout-details-generation-v1'


def compile_request(request):
    if type(request) is not dict or type(request.get('task')) is not dict:
        raise ValueError('Declare checkout-details task notation')
    spec=request['task']
    if (spec.get('kind')!=native.KIND or 'requirements' not in spec or 'delivery_note' not in spec
        or set(spec)-{'kind','requirements','initial_cart','delivery_note'}):
        raise ValueError('Unsupported checkout-details task notation')
    proxy=deepcopy(request);proxy['task']=native.cart_selection(spec)
    config=carts.compile_request(proxy)
    selection=native.resolve(spec,concept_ids=[r['concept_id'] for r in config['selection']['requirements']],inventory=config['inventory'])
    return {**config,'selection':selection,'checkout_proxy_request':proxy}


def generate(request,*,world_factory=None):
    config=compile_request(request)
    result=carts.generate(config['checkout_proxy_request'],world_factory=world_factory)
    task=native.make(result['world'],config['selection'],checkout_domain=result['checkout_domain'],inventory=config['inventory'])
    reference=native.reference(result['world'],task,checkout_domain=result['checkout_domain'],inventory=config['inventory'])
    result.update(checkout_details_task=task,checkout_details_reference=reference,
        checkout_details_binding={'status':'requires_actual_saved_delivery_fields_and_effect_adoption','world_repaired':False})
    result['episode'].update(task_id=task['task_id'],manual_task={'user_message':task['user_message'],'memories':deepcopy(task['memories'])})
    result['resolved_configuration'].update(request=deepcopy(request),task=deepcopy(config['selection']))
    result['audit']['checkout_cart_proxy_request_sha256']=result['audit']['request_sha256']
    result['audit']['request_sha256']=carts.basket_generation.unified.shared.digest(request)
    return result
