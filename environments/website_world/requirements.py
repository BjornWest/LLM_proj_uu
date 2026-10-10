"""Finite website completion masses for upstream world conditioning.

No page is sampled here. Commercial ranking and form state come from the native
producer. The finite factors make SAT unnecessary for this bounded conjunction.
"""
from copy import deepcopy
from math import log, fsum

from environments.website_drafts.component_sampling import factors, probabilities
from .presentation import RESET_WEIGHTS, POLICY_WEIGHTS

PROFILES = {'small': 'boutique', 'medium': 'typical', 'large': 'huge'}
FORM_FIELDS = {'autofill', 'incorrect_values', 'missing_fields', 'wrong_mode', 'home_delivery_available'}
FORM_VALUES = {
    'autofill': [True, False], 'incorrect_values': [True, False],
    'missing_fields': [True, False],
    'wrong_mode': [None, 'previous_home', 'minor_field_mismatch'],
    'home_delivery_available': [True, False],
}


def domains(profile, priors, resets=None, policies=None, variation_priors=None, delivery_options=None):
    result = factors(profile, priors)
    # resetPolicy is authoritative; the boolean is its derived projection.
    result.pop('site.reset')
    result['site.resetPolicy'] = probabilities(resets or RESET_WEIGHTS)
    result['site.policyEntry'] = probabilities(policies or POLICY_WEIGHTS)
    if variation_priors is not None:
        from environments.website_drafts.variation_sampling import AXES, validate_priors
        validate_priors(variation_priors, factors(profile, priors))
        result.update({'variation.' + axis: dict.fromkeys(choices, 1.) for axis, choices in AXES.items()})
    if delivery_options is not None:
        result['site.deliveryOrder'] = probabilities(delivery_options['order_weights'])
    return result


def normalized_conditions(conditions, known):
    if not isinstance(conditions, dict) or set(conditions) - (set(known) | {'site.reset'}):
        raise ValueError('Unknown website requirement condition')
    result = deepcopy(conditions)
    for name, allowed in result.items():
        values = {'true', 'false'} if name == 'site.reset' else set(known[name])
        if (not isinstance(allowed, list) or not allowed or
                any(type(v) is not str for v in allowed) or
                len(set(allowed)) != len(allowed) or set(allowed) - values):
            raise ValueError('Invalid allowed-value domain: ' + name)
    boolean = result.pop('site.reset', None)
    if boolean is not None:
        allowed = [v for v in known['site.resetPolicy']
                   if ('false' if v == 'preserve' else 'true') in boolean]
        if 'site.resetPolicy' in result:
            allowed = [v for v in allowed if v in result['site.resetPolicy']]
        result['site.resetPolicy'] = allowed
    return result


def intersect(first, second):
    result = deepcopy(first)
    for name, allowed in second.items():
        result[name] = [v for v in result[name] if v in allowed] if name in result else list(allowed)
    return result


def log_mass(known, conditions):
    terms = []
    for name, allowed in conditions.items():
        mass = fsum(known[name][v] for v in allowed)
        if mass <= 0:
            return float('-inf')
        terms.append(log(min(1., mass)))
    return fsum(terms)


def site_log_mass(profile, priors, resets, policies, conditions, variation_priors=None, delivery_options=None):
    if variation_priors is None:
        return log_mass(domains(profile, priors, resets, policies, delivery_options=delivery_options), conditions)
    from environments.website_drafts.variation_sampling import completion
    independent = {name: allowed for name, allowed in conditions.items()
                   if name in ('site.resetPolicy', 'site.policyEntry', 'site.deliveryOrder')}
    dependent = {name: allowed for name, allowed in conditions.items() if name not in independent}
    terms = [log_mass(domains(profile, priors, resets, policies, delivery_options=delivery_options), independent),
             completion(factors(profile, priors), dependent, variation_priors)['log_mass']]
    return fsum(terms) if all(t != float('-inf') for t in terms) else float('-inf')


def validate(requirements, priors, resets=None, policies=None, *, variation_priors=None, delivery_options=None):
    if not isinstance(requirements, list):
        raise ValueError('Requirements must be a list')
    known = {p: domains(p, priors, resets, policies, variation_priors, delivery_options) for p in PROFILES.values()}
    ids = set()
    compiled = []
    for requirement in requirements:
        if (not isinstance(requirement, dict) or
                set(requirement) - {'id', 'target', 'conditions', 'initial_form', 'best_offer_count', 'status'}):
            raise ValueError('Unknown requirement option')
        rid = requirement.get('id')
        if not isinstance(rid, str) or not rid or rid in ids:
            raise ValueError('Requirement IDs must be unique nonempty strings')
        ids.add(rid)
        target = requirement.get('target')
        if not isinstance(target, dict) or set(target) - {'kind', 'scale', 'retailer_id'}:
            raise ValueError('Invalid requirement target')
        kind = target.get('kind')
        if kind == 'world_reference':
            if set(target) != {'kind'} or set(requirement) & {'conditions', 'initial_form'}:
                raise ValueError('World reference requirements cannot contain page conditions')
            bounds = requirement.get('best_offer_count')
            if bounds is not None and (not isinstance(bounds, dict) or set(bounds) != {'min', 'max'} or
                    any(type(v) is not int or v < 0 for v in bounds.values()) or bounds['min'] > bounds['max']):
                raise ValueError('Declare nonnegative best_offer_count min/max bounds')
            status = requirement.get('status')
            if status is not None and (not isinstance(status, list) or not status or
                    any(v not in ('match', 'no_match') for v in status) or len(set(status)) != len(status)):
                raise ValueError('Invalid native reference status')
            if bounds is None and status is None:
                raise ValueError('Empty world reference requirement')
            compiled.append({**deepcopy(requirement), 'log_upper_bound': 0.})
            continue
        if set(requirement) & {'best_offer_count', 'status'}:
            raise ValueError('Reference predicates require world_reference target')
        if kind in ('best_matching_retailers', 'all_retailers'):
            if set(target) != {'kind'}:
                raise ValueError('Unexpected selector option')
        elif kind == 'retailer_scale':
            if set(target) != {'kind', 'scale'} or target['scale'] not in PROFILES:
                raise ValueError('Unknown retailer scale')
        elif kind == 'retailer_id':
            if set(target) != {'kind', 'retailer_id'} or not isinstance(target['retailer_id'], str) or not target['retailer_id']:
                raise ValueError('Invalid retailer identity')
        else:
            raise ValueError('Unsupported requirement target')
        conditions = normalized_conditions(requirement.get('conditions', {}), known['typical'])
        initial = requirement.get('initial_form', {})
        if not isinstance(initial, dict) or set(initial) - FORM_FIELDS:
            raise ValueError('Unknown producer form predicate')
        for field, allowed in initial.items():
            if (not isinstance(allowed, list) or not allowed or
                    any(not any(type(v) is type(a) and v == a for a in FORM_VALUES[field]) for v in allowed) or
                    len({(type(v), v) for v in allowed}) != len(allowed)):
                raise ValueError('Invalid producer form predicate: ' + field)
        if not conditions and not initial:
            raise ValueError('Empty requirement')
        profiles = [PROFILES[target['scale']]] if kind == 'retailer_scale' else list(known)
        upper = max(site_log_mass(p, priors, resets, policies, conditions, variation_priors, delivery_options) for p in profiles)
        if upper == float('-inf'):
            raise ValueError('Requirement has zero supported prior mass: ' + rid)
        compiled.append({**deepcopy(requirement), 'conditions': conditions,
                         'initial_form': deepcopy(initial), 'log_upper_bound': upper})
    return compiled


def targets(world, selector):
    kind = selector['kind']
    if kind == 'best_matching_retailers':
        winners = world['reference']['winners']
        return sorted({w['retailer_id'] for w in winners})
    return sorted(r['retailer_id'] for r in world['retailers'] if
        kind == 'all_retailers' or
        kind == 'retailer_scale' and r['scale'] == selector['scale'] or
        kind == 'retailer_id' and r['retailer_id'] == selector['retailer_id'])


def initial_home_delivery_available(world, retailer, selector_kind):
    from experiments.footwear_world_pilot.model import delivery_options
    from .adapter import browser_address, supported_destination
    try:
        address = browser_address(retailer['initial_form'])
        destination = supported_destination(world, address)
    except ValueError:
        return False
    offers = retailer['offers']
    winner_ids = {w['offer_id'] for w in world['reference']['winners']
                  if w['retailer_id'] == retailer['retailer_id'] and 'offer_id' in w}
    if selector_kind == 'best_matching_retailers' and winner_ids:
        offers = [o for o in offers if o['offer_id'] in winner_ids]
        return bool(offers) and all(any(q['destination_type'] == 'home' for q in
            delivery_options(world, retailer, o, destination=destination)) for o in offers)
    return any(any(q['destination_type'] == 'home' for q in
        delivery_options(world, retailer, o, destination=destination)) for o in offers)


def evaluate(world, compiled, priors, resets=None, policies=None, *, home_delivery_checker=None, variation_priors=None, delivery_options=None):
    """P(requirements | world), keeping all ties and overlapping scopes.

    Empty target sets fail rather than satisfying a constraint vacuously. Natural
    form predicates have 0/1 mass at this stage: the upstream proposal already
    sampled them. Intersect overlapping conditions once, never double count them.
    """
    retailers = {r['retailer_id']: r for r in world['retailers']}
    conditions, resolved = {}, []
    for requirement in compiled:
        if requirement['target']['kind'] == 'world_reference':
            reference = world['reference']
            status = requirement.get('status', ['match', 'no_match'])
            if reference.get('status') not in status:
                return {'log_mass': float('-inf'), 'reason': 'reference_status', 'resolved': resolved, 'conditions': {}}
            if 'best_offer_count' in requirement:
                # Service/source ties are occurrences of the same commercial
                # offer. Widest-assortment winners have no offer identity.
                if any('offer_id' not in w for w in reference['winners']):
                    raise ValueError('Native reference does not expose best offer identities')
                count = len({w['offer_id'] for w in reference['winners']})
                bounds = requirement['best_offer_count']
                if not bounds['min'] <= count <= bounds['max']:
                    return {'log_mass': float('-inf'), 'reason': 'best_offer_count', 'resolved': resolved, 'conditions': {}}
                resolved.append({'id': requirement['id'], 'best_offer_count': count})
            else:
                resolved.append({'id': requirement['id'], 'status': reference['status']})
            continue
        selected = targets(world, requirement['target'])
        resolved.append({'id': requirement['id'], 'retailer_ids': selected})
        if not selected:
            return {'log_mass': float('-inf'), 'reason': 'empty_target', 'resolved': resolved, 'conditions': {}}
        for sid in selected:
            provenance = deepcopy(retailers[sid]['initial_form']['provenance'])
            initial = requirement['initial_form']
            # A requested stale-home shipping case must be usable at the native
            # destination. Do not silently replace it with the known current home.
            needs_stale_coverage = 'wrong_mode' in initial and provenance['wrong_mode'] == 'previous_home'
            if needs_stale_coverage or 'home_delivery_available' in initial:
                checker = home_delivery_checker or initial_home_delivery_available
                provenance['home_delivery_available'] = checker(
                    world, retailers[sid], requirement['target']['kind'])
                if needs_stale_coverage and not provenance['home_delivery_available']:
                    return {'log_mass': float('-inf'), 'reason': 'native_stale_coverage', 'resolved': resolved, 'conditions': {}}
            if any(not any(type(provenance.get(k)) is type(v) and provenance.get(k) == v for v in allowed)
                   for k, allowed in initial.items()):
                return {'log_mass': float('-inf'), 'reason': 'producer_form', 'resolved': resolved, 'conditions': {}}
            conditions[sid] = intersect(conditions.get(sid, {}), requirement['conditions'])
    value = fsum(site_log_mass(PROFILES[retailers[sid]['scale']], priors, resets, policies, cond, variation_priors, delivery_options)
                 for sid, cond in conditions.items())
    return {'log_mass': value, 'reason': 'zero_completion' if value == float('-inf') else 'feasible',
            'resolved': resolved, 'conditions': conditions}


def log_upper_bound(compiled):
    # Every requirement targets at least one site. The joint mass cannot exceed
    # the smallest individual maximum. Multiplying overlapping maxima is unsafe.
    return min((r['log_upper_bound'] for r in compiled), default=0.)
