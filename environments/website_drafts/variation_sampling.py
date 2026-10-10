"""Finite conditional UX choices, marginalized before the module draw.

Site conventions precede modules. Per-page weights depend only on that page's
selected unit. Navigation grouping uses a small local table; no complete-site
Cartesian products or task-dependent rendering repairs exist.
"""
from math import exp, fsum, log

from .component_sampling import probabilities, draw
from .variation_settings import CONTROLS

VERSION = 'website-variation-priors-v1'
AXES = {f'{role}.{key}': choices
        for role, fields in CONTROLS.items() for key, choices in fields.items()}
OWNERS = {axis: axis.split('.')[0] if axis.split('.')[0] in ('home', 'results', 'product')
          else 'product' if axis.startswith('recommendations.') else None for axis in AXES}
SITE_AXES = [axis for axis, role in OWNERS.items() if role is None]


def weights(value, choices):
    if not isinstance(value, dict) or set(value) != set(choices):
        raise ValueError('Declare the complete variation weight domain')
    probabilities(value)
    # Canonical value order makes input-object order irrelevant to seeded draws.
    return {choice: value[choice] for choice in choices}


def normalize(options, modules):
    if (not isinstance(options, dict) or
            set(options) - {'enabled', 'weights', 'unit_weights'} or
            type(options.get('enabled')) is not bool):
        raise ValueError('Page variations require an explicit enabled flag')
    if not options['enabled']:
        if set(options) != {'enabled'}:
            raise ValueError('Disabled variations cannot contain weights')
        return None
    supplied = options.get('weights', {})
    if not isinstance(supplied, dict) or set(supplied) - set(AXES):
        raise ValueError('Unknown variation weight')
    defaults = {axis: weights(supplied.get(axis, dict.fromkeys(choices, 1)), choices)
                for axis, choices in AXES.items()}
    units = options.get('unit_weights', {})
    if not isinstance(units, dict) or set(units) - {'home', 'results', 'product'}:
        raise ValueError('Unsupported variation unit owner')
    result = {}
    for role, by_unit in units.items():
        if not isinstance(by_unit, dict) or set(by_unit) - set(modules['module.' + role]):
            raise ValueError('Unknown variation module')
        result[role] = {}
        for unit, by_axis in by_unit.items():
            axes = {axis for axis, owner in OWNERS.items() if owner == role}
            if not isinstance(by_axis, dict) or set(by_axis) - axes:
                raise ValueError('Unit weights must belong to that selected page role')
            result[role][unit] = {axis: weights(value, AXES[axis]) for axis, value in by_axis.items()}
    return {'schema': VERSION, 'weights': defaults, 'unit_weights': result}


def validate_priors(priors, modules):
    if (not isinstance(priors, dict) or set(priors) != {'schema', 'weights', 'unit_weights'}
            or priors['schema'] != VERSION):
        raise ValueError('Invalid variation priors')
    if not isinstance(priors['weights'], dict) or set(priors['weights']) != set(AXES):
        raise ValueError('Missing variation axes')
    return normalize({'enabled': True, 'weights': priors['weights'],
                      'unit_weights': priors['unit_weights']}, modules)


def restrict(distribution, allowed):
    values = distribution if allowed is None else {v: p for v, p in distribution.items() if v in allowed}
    mass = fsum(values.values())
    return ({v: p / mass for v, p in values.items()} if mass > 0 else {}), (log(mass) if mass > 0 else float('-inf'))


def sum_logs(values):
    if not values or max(values) == float('-inf'):
        return float('-inf')
    maximum = max(values)
    return maximum + log(fsum(exp(v - maximum) for v in values))


def marginal(table):
    total = sum_logs(list(table.values()))
    distribution = {v: exp(m - total) for v, m in table.items() if m != float('-inf')} if total != float('-inf') else {}
    return distribution, total


def child(priors, axis, conditions, *, unit=None, owner=None, navigation=None):
    # Inactive choices have one fixed value and consume no conditional draw.
    if axis == 'product.gallery':
        base = {'stacked': 1.}  # Current released live adapter supplies no media.
    elif axis == 'site.navigationGrouping' and navigation != 'grouped':
        base = {'departments': 1.}
    else:
        declared = priors['unit_weights'].get(owner, {}).get(unit, {}).get(axis, priors['weights'][axis])
        base = probabilities(declared)
    return restrict(base, conditions.get('variation.' + axis))


def completion(modules, conditions, priors):
    """Return posterior parent tables and log P(conditions | profile).

    Intersected empty allowed sets return zero completion normally. Complexity
    is linear in unit × local-axis counts, not the number of complete sites.
    """
    priors = validate_priors(priors, modules)
    known = set(modules) | {'variation.' + axis for axis in AXES}
    if set(conditions) - known:
        raise ValueError('Unknown variation/component condition')
    for name, allowed in conditions.items():
        choices = AXES[name.removeprefix('variation.')] if name.startswith('variation.') else modules[name]
        if (not isinstance(allowed, list) or any(type(v) is not str for v in allowed) or
                len(set(allowed)) != len(allowed) or set(allowed) - set(choices)):
            raise ValueError('Invalid allowed variation values: ' + name)
    posterior, site, pages, terms = {}, {}, {}, []
    for name, distribution in modules.items():
        if not name.startswith('module.'):
            posterior[name], mass = restrict(distribution, conditions.get(name))
            terms.append(mass)
            continue
        owner = name.removeprefix('module.')
        axes = [axis for axis, role in OWNERS.items() if role == owner]
        table, by_unit = {}, {}
        for unit, probability in distribution.items():
            if probability <= 0 or name in conditions and unit not in conditions[name]:
                continue
            local, masses = {}, []
            for axis in axes:
                local[axis], mass = child(priors, axis, conditions, unit=unit, owner=owner)
                masses.append(mass)
            table[unit] = log(probability) + fsum(masses) if all(m != float('-inf') for m in masses) else float('-inf')
            by_unit[unit] = local
        posterior[name], mass = marginal(table)
        terms.append(mass)
        pages[owner] = by_unit
    # Marginalize grouping into navigation before selecting that convention.
    navigation = probabilities(priors['weights']['site.navigation'])
    table, groups = {}, {}
    for value, probability in navigation.items():
        if probability <= 0 or ('variation.site.navigation' in conditions and
                               value not in conditions['variation.site.navigation']):
            continue
        groups[value], mass = child(priors, 'site.navigationGrouping', conditions, navigation=value)
        table[value] = log(probability) + mass
    site['site.navigation'], mass = marginal(table)
    site['grouping_by_navigation'] = groups
    terms.append(mass)
    for axis in SITE_AXES:
        if axis in ('site.navigation', 'site.navigationGrouping'):
            continue
        site[axis], mass = child(priors, axis, conditions)
        terms.append(mass)
    total = fsum(terms) if all(m != float('-inf') for m in terms) else float('-inf')
    return {'parents': posterior, 'site': site, 'pages': pages, 'log_mass': total, 'mass': exp(total)}


def sample_site(world_seed, site_id, tables):
    values = {}
    for axis in SITE_AXES:
        if axis == 'site.navigationGrouping':
            distribution = tables['site']['grouping_by_navigation'][values['site']['navigation']]
        else:
            distribution = tables['site'][axis]
        value = next(iter(distribution)) if len(distribution) == 1 else draw(world_seed, site_id, 'variation/' + axis, distribution)
        role, key = axis.split('.')
        values.setdefault(role, {})[key] = value
    return values


def sample_page(world_seed, site_id, owner, unit, tables, values):
    for axis, distribution in tables['pages'][owner][unit].items():
        value = next(iter(distribution)) if len(distribution) == 1 else draw(world_seed, site_id, f'variation/{owner}/{unit}/{axis}', distribution)
        role, key = axis.split('.')
        values.setdefault(role, {})[key] = value
