"""World-facing page composition, separate from authoring presets and commerce.

This small factorized sampler is not the whole-world SAT/weighted compiler. It
exposes exact domain-constraint masses at a fixed upstream retailer profile.
Commercial choices must already exist; this module never manufactures offers.
"""
from copy import deepcopy
from hashlib import sha256
from math import isfinite, prod
from pathlib import Path
import json

VERSION = 'website-component-sampler-v1'
PRIORS = Path(__file__).with_name('component-priors-v1.json')
POLICY_KEYS = {'split', 'policy', 'qualification', 'collectionPayment'}
POLICY_DOMAINS = {
    'split': [True, False], 'policy': ['footer', 'checkout', 'help'],
    'qualification': ['basket', 'shipment'],
    'collectionPayment': ['online', 'collection'],
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def scoped_seed(world_seed, site_id, scope):
    # Browser-safe integer; namespaced streams isolate unrelated new choices.
    material = canonical([VERSION, world_seed, site_id, scope]).encode()
    return int.from_bytes(sha256(material).digest()[:6], 'big')


def load_priors():
    return json.loads(PRIORS.read_text())


def probabilities(weights):
    if not weights or any(type(w) not in (int, float) or not isfinite(w) or w < 0
                          for w in weights.values()):
        raise ValueError('Weights must be finite nonnegative numbers')
    total = sum(weights.values())
    if not isfinite(total) or total <= 0:
        raise ValueError('Weights require positive finite total mass')
    return {key: value / total for key, value in weights.items()}


def factors(profile, priors):
    if priors.get('schema') != 'website-component-priors-v1':
        raise ValueError('Unsupported component priors')
    if profile not in priors['profiles']:
        raise ValueError(f'Unknown retailer architecture profile: {profile}')
    spec = priors['profiles'][profile]
    family_weights = spec['family_weights']
    if set(family_weights) != {'boutique', 'typical', 'huge'}:
        raise ValueError('Declare all three architecture family weights')
    probabilities(family_weights)
    result = {}
    for name, weights in priors['site_choices'].items():
        result['site.' + name] = probabilities(weights)
    required = {'global', 'iconCart', 'url', 'reset', 'opaque'}
    if set(priors['site_choices']) != required:
        raise ValueError('Unexpected or missing shared site choice')
    p = spec['search_probability']
    if type(p) not in (int, float) or not isfinite(p) or not 0 <= p <= 1:
        raise ValueError('Search probability must lie in [0, 1]')
    result['site.search'] = {'true': p, 'false': 1 - p}
    for role, families in priors['roles'].items():
        # Family mass is divided across its available units. A family with more
        # designs therefore doesn't automatically get more probability.
        weights = {}
        for family, ids in families.items():
            if not ids:
                raise ValueError(f'Empty architecture family: {role}/{family}')
            for unit in ids:
                if unit in weights:
                    raise ValueError(f'Ambiguous unit: {role}/{unit}')
                weights[unit] = family_weights[family] / len(ids)
        result['module.' + role] = probabilities(weights)
    return result


def conditioned_factors(profile, *, priors=None, conditions=None, variation_priors=None):
    """Return posterior factors and P(constraints | fixed upstream profile).

    Conditions are allowed-value lists for site.X/module.X. They cannot express
    cross-role relations or sample an upstream retailer profile. A parent sampler
    must multiply its prior by the returned mass when conditioning that parent.
    """
    priors = load_priors() if priors is None else priors
    domains = factors(profile, priors)
    if variation_priors is not None:
        from .variation_sampling import completion
        tables=completion(domains, conditions or {}, variation_priors)
        if tables['log_mass']==float('-inf'):raise ValueError('Condition has zero supported variation mass')
        return tables['parents'],tables['mass']
    conditions = {} if conditions is None else conditions
    if set(conditions) - set(domains):
        raise ValueError('Unknown component condition')
    restricted, masses = {}, []
    for name, distribution in domains.items():
        allowed = conditions.get(name, list(distribution))
        if not isinstance(allowed, list) or not allowed or len(set(allowed)) != len(allowed):
            raise ValueError(f'Condition requires distinct allowed values: {name}')
        if set(allowed) - set(distribution):
            raise ValueError(f'Unknown allowed value: {name}')
        weights = {value: weight for value, weight in distribution.items() if value in allowed}
        mass = sum(weights.values())
        if mass <= 0:
            raise ValueError(f'Condition has zero prior mass: {name}')
        masses.append(mass)
        restricted[name] = probabilities(weights)
    return restricted, prod(masses)


def draw(world_seed, site_id, scope, distribution):
    number = scoped_seed(world_seed, site_id, scope) / 2**48
    cumulative = 0
    for value, probability in distribution.items():
        cumulative += probability
        if number < cumulative:
            return value
    return next(reversed(distribution))  # Floating-point summation at the endpoint.


def sample_components(world_seed, site_id, *, profile, policy, priors=None, conditions=None, variation_priors=None):
    """Materialize a private, pinned composition plan plus browser config.

    `profile` comes from the retailer's upstream scale/profile mapping; it is not
    chosen from the page appearance. `policy` supplies canonical retailer choices.
    No task/reference is accepted and no request-time draw is made.
    """
    if type(world_seed) is not int or not isinstance(site_id, str) or not site_id:
        raise ValueError('Expected integer world seed and nonempty retailer identity')
    if set(policy) != POLICY_KEYS:
        raise ValueError('Pass the explicit upstream policy binding')
    for key, values in POLICY_DOMAINS.items():
        if not any(type(policy[key]) is type(value) and policy[key] == value for value in values):
            raise ValueError(f'Invalid upstream policy binding: {key}')
    priors = load_priors() if priors is None else deepcopy(priors)
    tables=None
    if variation_priors is None:
        distributions, mass = conditioned_factors(profile, priors=priors, conditions=conditions)
    else:
        from .variation_sampling import completion, sample_site, sample_page
        tables=completion(factors(profile, priors),conditions or {},variation_priors)
        if tables['log_mass']==float('-inf'):raise ValueError('Condition has zero supported variation mass')
        distributions,mass=tables['parents'],tables['mass']
    config = {'schema': 'website-draft-v1',
              'seed': scoped_seed(world_seed, site_id, 'render-content'),
              'scale': profile, 'modules': {}}
    # Shared conventions/capabilities precede the independent page-role draws.
    for name, distribution in distributions.items():
        if name.startswith('site.'):
            value = draw(world_seed, site_id, name, distribution)
            config[name[5:]] = {'true': True, 'false': False}.get(value, value)
    config.update(deepcopy(policy))
    if tables is not None:config["variations"]=sample_site(world_seed,site_id,tables)
    unit_permutations = {}
    for name, distribution in distributions.items():
        if name.startswith('module.'):
            role = name[7:]
            unit = draw(world_seed, site_id, name, distribution)
            config['modules'][role] = unit
            if tables is not None:sample_page(world_seed,site_id,role,unit,tables,config['variations'])
            # Permutations are available only for the selected unit, rather than
            # extra outcomes in the base-unit prior. Renderers must consume these
            # bindings when they adopt this world-facing plan.
            unit_permutations[role] = {
                'unit': unit, 'seed': scoped_seed(world_seed, site_id, f'permutation/{role}/{unit}')}
    config['unitPermutations'] = deepcopy(unit_permutations)
    result = {'schema': VERSION, 'world_seed': world_seed, 'site_id': site_id,
            'profile': profile, 'priors_sha256': sha256(canonical(priors).encode()).hexdigest(),
            'conditions': deepcopy(conditions or {}), 'condition_mass': mass,
            'config': config, 'unit_permutations': unit_permutations,
            'limitations': ['Composition sampler only; no world/offer/oracle/task export.',
                            'Domain constraints only; no whole-world SAT/compiler adoption.',
                            'Whole-world producer/renderer adoption is separate.']}

    if tables is not None:
        result['variation_sampling']={'schema':variation_priors['schema'],
            'priors_sha256':sha256(canonical(variation_priors).encode()).hexdigest(),
            'log_condition_mass':tables['log_mass'],
            'inactive_rules':['Navigation grouping is fixed to departments unless navigation is grouped.',
                'Gallery is fixed to stacked: current live catalog exports no media.']}
    return result
