"""Seeded, finite presentation plans; no commercial facts or quote arithmetic."""
from copy import deepcopy

from environments.website_drafts.component_sampling import (
    draw, load_priors, probabilities, sample_components,
)

VERSION = 'website-runtime-presentation-v1'
RESET_WEIGHTS = {'preserve': .9, 'services': .05, 'delivery': .03, 'checkout': .02}
POLICY_WEIGHTS = {'footer': 1, 'checkout': 1, 'help': 1}
FORM_MODES = {'producer', 'canonical', 'blank', 'correct', 'old', 'postcode',
              'missing_unit', 'old_missing_unit'}


def validate_request(world, request):
    if request is None:
        return None
    request = deepcopy(request)
    if set(request) - {'schema', 'world_id', 'sites', 'reset_weights', 'policy_weights', 'component_priors', 'variation_priors', 'selected_content', 'delivery_options', 'product_disclosure', 'retailer_disclosure_profiles'} or request.get('schema') != VERSION:
        raise ValueError('Invalid runtime presentation request')
    if request.get('world_id') != world['world_id']:
        raise ValueError('Presentation request belongs to another world')
    for key, defaults in (('reset_weights', RESET_WEIGHTS), ('policy_weights', POLICY_WEIGHTS)):
        weights = request.get(key, defaults)
        if not isinstance(weights, dict) or set(weights) != set(defaults):
            raise ValueError(f'Declare the entire finite domain: {key}')
        probabilities(weights)
    if type(request.get('selected_content',False)) is not bool:raise ValueError('selected_content must be boolean')
    if 'product_disclosure' in request:
        from .product_disclosure import validate_settings,validate_profiles
        settings=validate_settings(request['product_disclosure'])
        validate_profiles(world,settings,request.get('retailer_disclosure_profiles'))
        if not request.get('selected_content'):raise ValueError('Count-first disclosure requires selected content')
    elif 'retailer_disclosure_profiles' in request:raise ValueError('Retailer profiles require disclosure controls')
    if 'variation_priors' in request:
        from environments.website_drafts.component_sampling import factors
        from environments.website_drafts.variation_sampling import validate_priors
        validate_priors(request['variation_priors'],factors('typical',request['component_priors'] if 'component_priors' in request else load_priors()))
    if 'delivery_options' in request:
        from .delivery_options import validate_settings
        validate_settings(request['delivery_options'])
    sites = request.get('sites', {})
    if not isinstance(sites, dict) or set(sites) - {r['retailer_id'] for r in world['retailers']}:
        raise ValueError('Unknown presentation retailer')
    for spec in sites.values():
        if not isinstance(spec, dict) or set(spec) - {'conditions', 'initial_form'}:
            raise ValueError('Unknown retailer presentation option')
        if not isinstance(spec.get('initial_form', 'producer'), str) or spec.get('initial_form', 'producer') not in FORM_MODES:
            raise ValueError('Unknown initial form mode')
        if not isinstance(spec.get('conditions', {}), dict):
            raise ValueError('Conditions must be an object')
    return request


def restrict(weights, allowed, name):
    base = probabilities(weights)
    allowed = list(base) if allowed is None else allowed
    if not isinstance(allowed, list) or not allowed or len(set(allowed)) != len(allowed) or set(allowed) - set(base):
        raise ValueError(f'Invalid finite condition: {name}')
    selected = {key: value for key, value in base.items() if key in allowed}
    mass = sum(selected.values())
    return probabilities(selected), mass


def site_plan(world, retailer, request, *, coupon_supported=False, basket_policy=None):
    sid = retailer['retailer_id']
    profile = {'small': 'boutique', 'medium': 'typical', 'large': 'huge'}[retailer['scale']]
    policy = {'split': False, 'policy': 'footer', 'qualification': 'basket', 'collectionPayment': 'online'}
    if basket_policy is not None:
        policy.update(split=basket_policy['optional_split'],
                      qualification='basket' if basket_policy['qualification_scope']=='checkout' else 'shipment')
    if request is None:
        # Historical first-journey behavior is explicit and unchanged.
        return sample_components(world['seed'], sid, profile=profile, policy=policy,
                                 conditions={'site.url': ['all'], 'site.opaque': ['false']})
    spec = request.get('sites', {}).get(sid, {})
    conditions = deepcopy(spec.get('conditions', {}))
    resets, reset_mass = restrict(request.get('reset_weights', RESET_WEIGHTS), conditions.pop('site.resetPolicy', None), 'resetPolicy')
    boolean = conditions.pop('site.reset', None)
    if boolean is not None:
        if not isinstance(boolean, list) or not boolean or len(set(boolean)) != len(boolean) or set(boolean) - {'true', 'false'}:
            raise ValueError('Invalid reset condition')
        allowed = [key for key in resets if ('false' if key == 'preserve' else 'true') in boolean]
        resets, mass = restrict(resets, allowed, 'reset')
        reset_mass *= mass
    entries, policy_mass = restrict(request.get('policy_weights', POLICY_WEIGHTS), conditions.pop('site.policyEntry', None), 'policyEntry')
    ordering, order_mass = None, 1.
    if 'delivery_options' in request:
        orders, order_mass = restrict(request['delivery_options']['order_weights'],
            conditions.pop('site.deliveryOrder', None), 'deliveryOrder')
        ordering = draw(world['seed'], sid, 'delivery/order', orders)
    # Compatibility precedes the conditioned module draw. A coupon-enabled
    # publication can retain the ordinary opacity distribution.
    opacity = conditions.get('site.opaque')
    if opacity is not None and (not isinstance(opacity, list) or not opacity or
            len(set(opacity)) != len(opacity) or set(opacity) - {'true', 'false'}):
        raise ValueError('Invalid coupon opacity condition')
    if not coupon_supported:
        if opacity is not None and 'false' not in opacity:
            raise ValueError('Opaque coupons require an authoritative coupon producer')
        conditions['site.opaque'] = ['false']
    priors = deepcopy(request['component_priors'] if 'component_priors' in request else load_priors())
    priors['site_choices']['reset'] = {
        'false': resets.get('preserve', 0),
        'true': sum(value for key, value in resets.items() if key != 'preserve'),
    }
    policy['policy'] = draw(world['seed'], sid, 'site.policyEntry', entries)
    plan = sample_components(world['seed'], sid, profile=profile, policy=policy,
                             priors=priors, conditions=conditions, variation_priors=request.get('variation_priors'))
    conditional = {key: value for key, value in resets.items()
                   if (key != 'preserve') == plan['config']['reset']}
    reset = draw(world['seed'], sid, 'site.resetPolicy', probabilities(conditional))
    plan['config']['resetPolicy'] = reset
    if ordering is not None:
        plan['config']['deliveryOrder'] = ordering
        if basket_policy is not None and 'delivery_admission' in basket_policy:
            plan['config']['deliveryCount'] = basket_policy['delivery_admission']['sampled_count']
    plan['presentation'] = {'schema': VERSION, 'world_id': world['world_id'],
        'requested': deepcopy(spec), 'reset_policy': reset, 'policy_entry': policy['policy'],
        'initial_form': spec.get('initial_form', 'producer'),
        'initial_form_override': spec.get('initial_form', 'producer') not in ('producer', 'canonical'),
        'condition_mass': plan['condition_mass'] * reset_mass * policy_mass * order_mass,
        'limitations': ['Finite site conditions only; no whole-world weighted compiler.',
                       'Explicit form examples are setup overrides, not conditional world sampling.',
                       ('Basket quotes use explicit policies; task/grader adoption is separate.'
                        if basket_policy is not None else 'Multi-item quote producers are not available.')],
        'coupon_supported': coupon_supported}
    return plan
