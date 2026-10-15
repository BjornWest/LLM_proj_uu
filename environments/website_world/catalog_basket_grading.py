"""Reuse native plan requotation/stock/allocation grading for mixed catalogs.

This is the structured-plan boundary. Natural final-answer extraction and actual
cart-state effects are separate capabilities, not claimed by these checks.
"""
from types import SimpleNamespace

from experiments.accepted_catalog_commerce import basket_quote, order_set_optimizer
from experiments.footwear_world_pilot import order_set_grader as historical
from . import catalog_basket_task as native, catalog_checkout_domain
from .adapter import digest
from experiments import source_binding

VERSION = 'website-catalog-basket-response-v1'


def _bound(world, task, reference, plan, domain, coupon_plan, admission_plan=None):
    if coupon_plan is not None:
        raise ValueError('Accepted-catalog account/coupon bridge is not adopted')
    matching = native.match(world, task, checkout_domain=domain)
    if (type(reference) is not dict or reference.get('schema_version') != native.REFERENCE_VERSION
            or reference.get('task_sha256') != digest(task)
            or reference.get('matching_sha256') != digest(matching)
            or reference.get('matching') != matching
            or reference.get('checkout_domain_sha256') != digest(domain)
            or not source_binding.same_code(reference.get('source_sha256'), native.source_identity(task))):
        raise ValueError('Stale task/matching/domain/source reference binding')
    result = reference.get('result', {})
    # The historical central quote/search uses compact JSON identities. Task
    # and public-domain digests use their own established spaced convention.
    commerce_digest = basket_quote.model.digest
    if (reference.get('result_sha256') != digest(result)
            or result.get('schema_version') != order_set_optimizer.VERSION
            or not result.get('complete') or result.get('status') not in ('optimal', 'infeasible')
            or result.get('world_id') != world['world_id'] or result.get('world_sha256') != commerce_digest(world)
            or result.get('plan_sha256') != commerce_digest(plan) or result.get('coupon_plan_sha256') is not None
            or result.get('admission_plan_sha256') != (commerce_digest(admission_plan) if admission_plan is not None else None)):
        raise ValueError('Incomplete, stale or unsupported exact reference')
    d = task['domain']
    expected = {'requirements': matching['requirements'], 'allow_extras': d['allow_extras'],
                'quantity_limits': domain['quantity_limits'],
                'max_lines_per_order': domain['options']['max_lines_per_order'],
                'allowed_destination_types': d['allowed_destination_types'], 'deadline': d['deadline'],
                'destination': world['user_location'], 'canonical_line_id': 'offer_id'}
    if any(result.get('domain', {}).get(k) != v for k, v in expected.items()):
        raise ValueError('Reference search domain differs from accessible checkout')
    if result['status'] == 'optimal' and (type(result.get('total_minor')) is not int or result['total_minor'] < 0):
        raise ValueError('Invalid exact optimum')
    basket_quote.validate_plan(world, plan)
    return matching, result


def grade(world, task, response, *, reference, plan, domain, coupon_plan=None,
          url_bindings=None, admission_plan=None):
    """Grade complete recommendation plans, with independent actual URL joins.

One sale unit cannot cover two requirements. Every order is requoted against
central monetary and fulfilment policies; source stock is checked across orders.
An incomplete oracle or missing runtime identity is inconclusive, never a pass.
    """
    def validate(request):
        if type(request) is not dict or request != task:
            raise ValueError('Structured task identity changed')
        expected = native.make(world, native._selection(request), checkout_domain=domain)
        if request != expected:
            raise ValueError('Basket task/world binding changed')
        return request
    bound_grade = order_set_optimizer._bind(historical.grade,
        order_set_task=SimpleNamespace(validate=validate), _bound=_bound,
        basket_quote=basket_quote, checkout_domain=catalog_checkout_domain, VERSION=VERSION)
    result = bound_grade(world, task, response, reference=reference, plan=plan, domain=domain,
                         coupon_plan=coupon_plan, url_bindings=url_bindings, admission_plan=admission_plan)
    return {**result, 'schema_version': 'website-catalog-basket-grade-v1',
            'limitations': ['Structured recommendation plans only; natural-answer extraction is separate.',
                            'No purchase or persisted cart/account side effects are certified.']}
