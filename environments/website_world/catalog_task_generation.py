"""Opt-in native task dispatcher; no publication, grading or default adoption.

Each retained generator owns validation, sampling, task/reference binding and
failure semantics. This module only selects it from the declared task kind.
"""
from importlib import import_module
from types import MappingProxyType

VERSION = 'website-catalog-task-dispatch-v1'
_GENERATORS = MappingProxyType({
    'cheapest_available': 'unified_generation',
    'comparison_cheapest_exact_sku_stock': 'comparison_stock_generation',
    'cheapest_matching_available': 'feature_offer_generation',
    'matching_single_item_delivery': 'quote_offer_generation',
    'cheapest_matching_with_memory': 'memory_offer_generation',
    'cheapest_matching_after_clarification': 'hidden_offer_generation',
    'summarize_product_reviews': 'catalog_review_generation',
    'comparison_catalog_statistics': 'catalog_statistics_generation',
    'cheapest_matching_order_set': 'catalog_basket_generation',
    'shortlist_matching_models': 'catalog_shortlist_generation',
    'cheapest_matching_with_permitted_relaxations': 'catalog_relaxation_generation',
    'cheapest_matching_unit_price': 'catalog_unit_price_generation',
    'recommend_matching_by_priorities': 'catalog_priority_generation',
    'compare_product_facts': 'catalog_comparison_generation',
    'summarize_carrier_reviews': 'carrier_review_generation',
    'prepare_matching_carts': 'catalog_cart_generation',
    'audit_free_shipping_claim': 'catalog_shipping_claim_generation',
})


def generators():
    """Return detached native routing metadata, not runtime acceptance flags."""
    return {kind: __package__+'.'+module for kind,module in _GENERATORS.items()}


def _generator(request, profile):
    if type(request) is not dict or type(request.get('task')) is not dict:
        raise ValueError('Declare a structured catalog task')
    kind=request['task'].get('kind')
    if type(kind) is not str or kind not in _GENERATORS:
        raise ValueError('Unsupported native catalog task kind')
    if profile not in ('ordinary','feature_conditioned'):
        raise ValueError('Unsupported catalog generation profile')
    if profile=='feature_conditioned':
        if kind!='cheapest_matching_available':
            raise ValueError('Feature conditioning requires the feature task kind')
        module='conditioned_feature_generation'
    else:
        module=_GENERATORS[kind]
    return import_module('.'+module,__package__)


def compile_request(request, *, profile='ordinary'):
    """Run the selected existing compiler; preserve its exact return/error API."""
    return _generator(request,profile).compile_request(request)


def generate(request, *, world_factory=None, profile='ordinary'):
    """Forward once; no retries, extra compilation or native result rewriting."""
    return _generator(request,profile).generate(request,world_factory=world_factory)
