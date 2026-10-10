"""Retailer-wide disclosure tendency, then per-product count-first topics.

Derived from existing retailer profiles without mutating commerce worlds. The
immutable rule file and small keyed profile results are cached in memory.
"""
from functools import lru_cache
from hashlib import sha256
import json
import math
from pathlib import Path

from .count_first_publication import (
    _distribution, export_count_first_tablet_content, export_count_first_tshirt_content,
)
from .disclosure_sampling import DisclosureDistribution, DEFAULT_HIGHLIGHT_BIAS
from .shared_state import freeze, mutable

VERSION = 'retailer-disclosure-profile-v1'
SPEC = Path(__file__).parent / 'data/product_feature_policies/retailer_disclosure_v1.json'


@lru_cache(maxsize=1)
def _spec():
    raw = SPEC.read_bytes()
    return freeze(json.loads(raw)), sha256(raw).hexdigest()


def _inputs(retailer):
    spec, _ = _spec()
    fields = ('retailer_id', 'template_id', 'scale', 'specificity', 'price_preference')
    if not isinstance(retailer, dict) or any(k not in retailer for k in fields):
        raise ValueError('Declare existing retailer identity/profile fields')
    values = {k: retailer[k] for k in fields}
    if not all(type(v) is str and v for v in values.values()):
        raise ValueError('Declare existing retailer identity/profile fields')
    for field, table in [('scale', 'base_weights_by_scale'), ('specificity', 'specificity_multipliers'),
                         ('price_preference', 'price_preference_multipliers')]:
        if values[field] not in spec[table]:
            raise ValueError('Unsupported retailer profile field: ' + field)
    return values


def retailer_disclosure_probabilities(retailer):
    """Unconditioned soft prior over tendencies from already sampled profiles."""
    values = _inputs(retailer); spec, _ = _spec()
    template_group = next((key for key, ids in spec['template_groups'].items()
                           if values['template_id'] in ids), 'other')
    weights = {
        mode: spec['base_weights_by_scale'][values['scale']][mode]
              * spec['specificity_multipliers'][values['specificity']][mode]
              * spec['price_preference_multipliers'][values['price_preference']][mode]
              * spec['template_multipliers'][template_group][mode]
        for mode in spec['modes']
    }
    total = math.fsum(weights.values())
    return {mode: value / total for mode, value in weights.items()}


@lru_cache(maxsize=4096)
def _sample_profile(seed, profile_inputs):
    values = dict(profile_inputs)
    probabilities = retailer_disclosure_probabilities(values)
    raw = json.dumps([VERSION, seed, values['retailer_id'], 'tendency'], separators=(',', ':')).encode()
    u = (int.from_bytes(sha256(raw).digest()[:6], 'big') + .5) / 2**48
    cumulative = 0.0
    chosen = next(reversed(probabilities))
    for mode, probability in probabilities.items():
        cumulative += probability
        if u < cumulative:
            chosen = mode; break
    spec, digest = _spec()
    return freeze({'protocol': VERSION, 'seed': seed, 'retailer_id': values['retailer_id'],
                   'tendency': chosen, 'mode_probabilities': probabilities,
                   'profile_inputs': values, 'policy_sha256': digest,
                   'count_family': spec['count_family'],
                   'count_fraction': spec['count_fraction_by_mode'][chosen]})


def sample_retailer_disclosure(seed, retailer):
    """One keyed tendency per world/retailer; product/concept/SKU are not inputs."""
    if type(seed) is not int:
        raise ValueError('Declare an integer world seed')
    return mutable(_sample_profile(seed, tuple(sorted(_inputs(retailer).items()))))


@lru_cache(maxsize=256)
def _count_weights(capacity, tendency):
    spec, _ = _spec()
    if type(capacity) is not int or capacity < 0 or tendency not in spec['modes']:
        raise ValueError('Declare nonnegative integer capacity and known tendency')
    p = spec['count_fraction_by_mode'][tendency]
    weights = {k: math.exp(math.lgamma(capacity + 1) - math.lgamma(k + 1)
                           - math.lgamma(capacity - k + 1) + k * math.log(p)
                           + (capacity-k) * math.log1p(-p)) for k in range(capacity + 1)}
    return freeze(weights)


def disclosure_count_weights(capacity, tendency):
    """Count-first Binomial(capacity, tendency fraction), no per-group trials."""
    # Validate before the cache to reject bool/int aliases.
    if type(capacity) is not int or capacity < 0 or type(tendency) is not str:
        raise ValueError('Declare nonnegative integer capacity and known tendency')
    return mutable(_count_weights(capacity, tendency))


def retailer_disclosure_event_mass(retailer, groups, *, required_groups=(),
                                  forbidden_groups=(), allowed_counts=None,
                                  highlight_bias=DEFAULT_HIGHLIGHT_BIAS):
    """Prior-weighted topic event mass across all three possible store tendencies.

    This is a single product's topic event, not visible evidence or multiple
    product joint mass. Shared tendency must be retained for joint conditions.
    """
    probabilities = retailer_disclosure_probabilities(retailer)
    required_groups, forbidden_groups = tuple(required_groups), tuple(forbidden_groups)
    allowed_counts = None if allowed_counts is None else tuple(allowed_counts)
    masses = {}
    terms = []
    for mode, prior in probabilities.items():
        d = DisclosureDistribution(groups, count_weights=disclosure_count_weights(len(groups), mode),
                                   highlight_bias=highlight_bias)
        event = d.event_mass(required_groups=required_groups, forbidden_groups=forbidden_groups,
                             allowed_counts=allowed_counts)
        masses[mode] = event['probability']
        terms.append(math.log(prior) + event['log_probability'])
    top = max(terms)
    log_mass = min(0.0, top + math.log(math.fsum(math.exp(t-top) for t in terms))) if top != float('-inf') else top
    return {'probability': math.exp(log_mass), 'log_probability': log_mass,
            'mode_probabilities': probabilities, 'event_mass_by_mode': masses,
            'conditioned_mode_probabilities': {mode: math.exp(t-log_mass) if log_mass != float('-inf') else 0.0
                                               for mode, t in zip(probabilities, terms)}}


def _export(item, *, retailer, seed, sku_id=None, highlight_bias=DEFAULT_HIGHLIGHT_BIAS):
    profile = sample_retailer_disclosure(seed, retailer)
    cid = item['public']['concept_id']
    capacity = _distribution(cid, None, highlight_bias).capacity
    weights = disclosure_count_weights(capacity, profile['tendency'])
    args = dict(seed=seed, retailer_id=profile['retailer_id'], count_weights=weights, highlight_bias=highlight_bias)
    packet = export_count_first_tablet_content(item, sku_id=sku_id, **args) if cid == 'tablets.everyday_media_tablets' else export_count_first_tshirt_content(item, **args)
    packet['retailer_disclosure'] = profile
    packet['disclosure_selection']['count_source'] = VERSION
    return packet


def export_profiled_tablet_content(item, *, sku_id, **kwargs):
    if item['public']['concept_id'] != 'tablets.everyday_media_tablets':
        raise ValueError('Select the declared media-tablet concept')
    return _export(item, sku_id=sku_id, **kwargs)


def export_profiled_tshirt_content(item, **kwargs):
    if item['public']['concept_id'] != 'tops.t_shirts':
        raise ValueError('Select the declared T-shirt concept')
    return _export(item, **kwargs)
