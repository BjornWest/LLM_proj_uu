"""Predeclare a shipping audit before sampling; never select by successful fees."""
from copy import deepcopy

from experiments.accepted_catalog_commerce.prepared_quote import prepare
from . import catalog_shipping_claim_task as native, catalog_checkout_domain as checkout, unified_generation

VERSION = 'website-catalog-shipping-claim-generation-v1'


def compile_request(request):
    if type(request) is not dict or request.get('schema') != unified_generation.VERSION or 'basket_search' in request:
        raise ValueError('Declare a unified shipping audit, not a basket optimization request')
    selection = native.resolve(request.get('task'))
    proxy = deepcopy(request)
    proxy['task'] = {'user_message': 'Browse the generated shops. Do not place an order.', 'memories': []}
    config = unified_generation.compile_request(proxy)
    domain = checkout.options(config.get('checkout_domain_options'))
    if selection['quantity'] > domain['max_quantity_per_offer']:
        raise ValueError('Quantity exceeds the compiled shared checkout domain')
    return {'proxy_request': proxy, 'selection': selection}


def generate(request, *, world_factory=None):
    config = compile_request(request)
    result = unified_generation.generate(config['proxy_request'], world_factory=world_factory)
    if native.selected_offer(result['world'], config['selection']) is None:
        result.update(shipping_claim_task=None, shipping_claim_reference=None,
            shipping_claim_binding={'status': 'unsupported_no_selected_offer', 'world_repaired': False})
    else:
        quotes = prepare(result['world'], plan=result['basket_plan'], admission_plan=result.get('delivery_plan'))
        task = native.make(result['world'], config['selection'], quote_context=quotes,
            checkout_domain=result['checkout_domain'])
        result.update(shipping_claim_task=task, shipping_claim_reference=native.reference(
            result['world'], task, quote_context=quotes, checkout_domain=result['checkout_domain']),
            shipping_claim_binding={'status': 'requires_public_quote_and_policy_adoption', 'world_repaired': False})
        result['episode'].update(task_id=task['task_id'], manual_task={'user_message': task['user_message'], 'memories': []})
    result['resolved_configuration'].update(request=deepcopy(request), task=deepcopy(config['selection']))
    result['audit']['proxy_request_sha256'] = result['audit']['request_sha256']
    result['audit']['request_sha256'] = unified_generation.shared.digest(request)
    return result
