"""Scope-local brand priors for authoring; independent of names and execution."""
from collections import Counter
from copy import deepcopy
import math


def validate_brand_scopes(config):
    if config.get('schema_version') != 'brand-scopes-v1':
        raise ValueError('Unsupported brand scope schema')
    strength = config['diversity_strength']
    if isinstance(strength, bool) or not isinstance(strength, (int, float)) or not math.isfinite(strength) or strength < 0:
        raise ValueError('Invalid brand diversity strength')
    seen_names = set()
    if not config['scopes']:
        raise ValueError('At least one brand scope required')
    for scope in config['scopes'].values():
        names = scope['names']
        if not names or any(not isinstance(n, str) or not n.strip() for n in names):
            raise ValueError('Brand names must be nonempty strings')
        normalized = {n.strip().casefold() for n in names}
        if len(normalized) != len(names) or normalized & seen_names:
            raise ValueError('Brand name pools must be unique and disjoint')
        seen_names.update(normalized)
        if not scope['concepts'] or len(set(scope['concepts'])) != len(scope['concepts']):
            raise ValueError('Scope needs unique eligible concepts')
        for axis in ('positioning', 'emphasis'):
            profiles = scope[axis + '_profiles']
            base = scope[axis + '_weights']
            if set(profiles) != set(base) or not profiles:
                raise ValueError('Brand profiles must match sampling weights')
            domain = set(next(iter(profiles.values())))
            for weights in (base, *profiles.values()):
                if not weights or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in weights.values()):
                    raise ValueError('Brand weights must be finite and positive')
            if any(set(weights) != domain for weights in profiles.values()):
                raise ValueError('Brand profiles must share an eligible product domain')


def diversity_weights(base, existing, *, scope_id, field, strength):
    counts = Counter(b[field] for b in existing if b['scope_id'] == scope_id)
    return {value: weight / (1 + strength * counts[value]) for value, weight in base.items()}


def sample_scoped_brand(config, *, scope_id, brand_id, existing, rng_for):
    """Append-only sampling: callers retain returned identity for repeated refs.

    Name exhaustion fails explicitly; it never silently aliases distinct brands.
    Earlier brands remain fixed when later ones are drawn.
    """
    validate_brand_scopes(config)
    if any(b['brand_id'] == brand_id for b in existing):
        raise ValueError('Distinct brand variables require distinct identities')
    scope = config['scopes'][scope_id]
    used = {b['name'].strip().casefold() for b in existing}
    names = [n for n in scope['names'] if n.strip().casefold() not in used]
    if not names:
        raise ValueError('Brand name pool exhausted for ' + scope_id)
    result = {'brand_id': brand_id, 'scope_id': scope_id,
              'name': rng_for('name').choice(names),
              'eligible_concepts': list(scope['concepts']), 'sampling_trace': []}
    for axis in ('positioning', 'emphasis'):
        field = axis + '_tendency'
        base = scope[axis + '_weights']
        weights = diversity_weights(base, existing, scope_id=scope_id, field=field,
                                    strength=config['diversity_strength'])
        choice = rng_for(axis).choices(list(weights), weights=list(weights.values()))[0]
        result[field] = choice
        result[axis + '_weights'] = deepcopy(scope[axis + '_profiles'][choice])
        total = sum(weights.values())
        result['sampling_trace'].append({'field': field, 'selected': choice,
                                        'base_weights': deepcopy(base),
                                        'probabilities': {k: v / total for k, v in weights.items()}})
    # Compatibility label for the isolated preview, not a further coupled draw.
    result['profile'] = result['positioning_tendency'] + ' / ' + result['emphasis_tendency']
    return result
