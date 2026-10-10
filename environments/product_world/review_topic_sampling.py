"""Shared topic-frequency policy for product-context authoring, across families.

This controls mention frequency, not sentiment. Existing live review generators
must explicitly adopt this contract; historical corpora are not rewritten.
"""
from copy import deepcopy
import math

VERSION = 'review-topic-policy-v3'
DEFAULTS = {
    'base_weight': 1.0,
    'base_weights': {},
    'value_baseline_probability': 0.30,
    'value_extreme_frequency_ratio': 1.5,
}
DIRECTION = {'budget': 1, 'mainstream': 0, 'premium': -1}


def resolve_topic_config(overrides=None):
    cfg = deepcopy(DEFAULTS)
    patch = {} if overrides is None else deepcopy(overrides)
    if set(patch) - set(cfg):
        raise ValueError('Unknown review topic configuration field')
    cfg.update(patch)
    values = [cfg['base_weight'], *cfg['base_weights'].values()]
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in values):
        raise ValueError('Topic weights must be finite and positive')
    baseline, ratio = cfg['value_baseline_probability'], cfg['value_extreme_frequency_ratio']
    if not isinstance(baseline, (int, float)) or not math.isfinite(baseline) or not 0 <= baseline <= 1:
        raise ValueError('Invalid value baseline probability')
    if not isinstance(ratio, (int, float)) or not math.isfinite(ratio) or ratio < 1:
        raise ValueError('Value extreme frequency ratio must be finite and at least 1')
    return cfg


def topic_policy(*, positioning, execution, eligible, length_weights, config=None, topic_multipliers=None):
    """Keep the value marginal independent of eligible topic count.

    A linear probability multiplier gives the requested frequency ratio exactly
    at execution 0 and 1. Reject impossible length/anchor settings instead of
    silently clipping and changing that ratio.
    """
    cfg = resolve_topic_config(config)
    if positioning not in DIRECTION or not isinstance(execution, (int, float)) or not math.isfinite(execution) or not 0 <= execution <= 1:
        raise ValueError('Invalid positioning or execution')
    lengths = {}
    for key, weight in length_weights.items():
        try:
            length = int(key)
        except (TypeError, ValueError):
            raise ValueError('Invalid review length') from None
        if str(length) != str(key) or length < 0 or isinstance(weight, bool) or not isinstance(weight, (int, float)) or not math.isfinite(weight) or weight < 0:
            raise ValueError('Invalid review length distribution')
        lengths[length] = weight
    if not lengths or sum(lengths.values()) <= 0:
        raise ValueError('Empty review length distribution')
    topics = list(eligible)
    if len(topics) != len(set(topics)):
        raise ValueError('Duplicate eligible review topics')
    weights = {a: cfg['base_weights'].get(a, cfg['base_weight']) for a in topics}
    modifiers = {} if topic_multipliers is None else dict(topic_multipliers)
    if set(modifiers) - set(topics) or 'value' in modifiers:
        raise ValueError('Topic multipliers must reference eligible non-value topics')
    if any(isinstance(v, bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v <= 0 for v in modifiers.values()):
        raise ValueError('Topic multipliers must be finite and positive')
    effective = {a:w*modifiers.get(a,1) for a,w in weights.items()}
    nonempty = 1 - lengths.get(0, 0) / sum(lengths.values())
    ratio = cfg['value_extreme_frequency_ratio']
    strength = (ratio - 1) / (ratio + 1)
    multiplier = 1 + strength * DIRECTION[positioning] * (2 * execution - 1)
    baseline = cfg['value_baseline_probability'] * weights.get('value', 0)
    maximum = baseline * (1 + strength if positioning != 'mainstream' else 1)
    if maximum > 1 + 1e-12:
        raise ValueError('Value anchor exceeds probability 1 among written reviews')
    other_count = len(topics) - ('value' in weights)
    if max(k for k, v in lengths.items() if v > 0) > other_count:
        raise ValueError('Not enough non-value topics for requested review lengths')
    conditional = baseline * multiplier
    return {
        'schema_version': VERSION,
        'base_weights': weights,
        'topic_multipliers': modifiers,
        'effective_weights': effective,
        'value_profile_multiplier': multiplier,
        'value_extreme_frequency_ratio': ratio,
        'value_frequency_basis': 'written_comments',
        'comment_probability': nonempty,
        'value_probability_given_comment': conditional,
        'value_probability_all_reviews': conditional * nonempty,
    }
