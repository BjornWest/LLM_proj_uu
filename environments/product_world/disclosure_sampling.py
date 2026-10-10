"""Count-first, weighted semantic-group subsets with exact cardinality mass.

Capacity is model-level approved topic inventory, never current SKU availability.
This module selects topics only; existing adapters resolve completed facts.
"""
from hashlib import sha256
import json
import math

VERSION = 'semantic-group-count-first-v1'
DEFAULT_HIGHLIGHT_BIAS = .25
NEG_INF = float('-inf')


def count_weights_from_entries(entries):
    """JSON notation: [[integer_count, finite_nonnegative_weight], ...]."""
    if not isinstance(entries, (list, tuple)) or not entries:
        raise ValueError('Declare nonempty count/weight pairs')
    result = {}
    for pair in entries:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError('Declare count/weight pairs')
        count, weight = pair
        if type(count) is not int or count < 0 or count in result:
            raise ValueError('Counts must be unique nonnegative integers')
        if type(weight) not in (int, float) or not math.isfinite(weight) or weight < 0:
            raise ValueError('Count weights must be finite and nonnegative')
        result[count] = weight
    if not any(result.values()):
        raise ValueError('Count weights must have positive mass')
    return result


def _add(a, b):
    if a == NEG_INF: return b
    if b == NEG_INF: return a
    top = max(a, b)
    return top + math.log1p(math.exp(min(a, b) - top))


def _suffix(log_weights):
    """Log elementary symmetric coefficients, O(n²), no subset enumeration."""
    rows = [[0.0]]
    for weight in reversed(log_weights):
        prev = rows[-1]
        row = [0.0]
        for k in range(1, len(prev) + 1):
            row.append(_add(prev[k] if k < len(prev) else NEG_INF, weight + prev[k-1]))
        rows.append(row)
    return list(reversed(rows))


def _draw(seed, retailer_id, product_id, concept_id, stream):
    raw = json.dumps([VERSION, seed, retailer_id, product_id, concept_id, stream],
                     ensure_ascii=False, separators=(',', ':')).encode()
    # Midpoints avoid log(0) and exact unit endpoints.
    return (int.from_bytes(sha256(raw).digest()[:6], 'big') + .5) / 2**48


def _weighted_index(log_masses, u):
    top = max(log_masses)
    weights = [math.exp(x - top) for x in log_masses]
    target = u * math.fsum(weights)
    cumulative = 0.0
    last = None
    for i, weight in enumerate(weights):
        if not weight: continue
        last = i
        cumulative += weight
        if target < cumulative: return i
    return last


class DisclosureDistribution:
    """Reusable model-topic distribution; definitions only, no input facts/IO.

    `groups` maps stable group keys to existing numeric highlight priorities.
    `count_weights` is a finite integer-count -> nonnegative-weight mapping.
    None means uniform over 0..capacity, including empty/full disclosure.
    """
    def __init__(self, groups, *, count_weights=None, highlight_bias=DEFAULT_HIGHLIGHT_BIAS):
        if type(highlight_bias) not in (int, float) or not math.isfinite(highlight_bias) or not 0 <= highlight_bias <= 1:
            raise ValueError('Highlight bias must be a finite number in [0,1]')
        if not hasattr(groups, 'items') or any(type(k) is not str or not k for k in groups):
            raise ValueError('Declare stable nonempty semantic group keys')
        if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in groups.values()):
            raise ValueError('Existing highlight priorities must be finite and nonnegative')
        self.keys = tuple(sorted(groups))
        self.capacity = len(self.keys)
        self.highlight_bias = highlight_bias
        peak = max(groups.values(), default=0)
        self.log_weights = tuple(math.log1p(highlight_bias * (groups[k] / peak if peak else 0)) for k in self.keys)
        self.suffix = _suffix(self.log_weights)
        if count_weights is None:
            count_weights = {k: 1 for k in range(self.capacity + 1)}
        if not hasattr(count_weights, 'items') or not count_weights:
            raise ValueError('Declare a nonempty finite count PMF')
        if any(type(k) is not int or not 0 <= k <= self.capacity for k in count_weights):
            raise ValueError('Disclosure counts must be integers within model capacity')
        if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in count_weights.values()) or not any(count_weights.values()):
            raise ValueError('Count weights must be finite, nonnegative and have positive mass')
        logs = [math.log(count_weights[k]) if count_weights.get(k, 0) else NEG_INF for k in range(self.capacity + 1)]
        norm = NEG_INF
        for log in logs: norm = _add(norm, log)
        self.log_count_pmf = tuple(log - norm for log in logs)

    def _event(self, required_groups, forbidden_groups, allowed_counts):
        required, forbidden = set(required_groups), set(forbidden_groups)
        if (required | forbidden) - set(self.keys) or required & forbidden:
            raise ValueError('Unknown or conflicting disclosure requirements')
        raw_counts = range(self.capacity + 1) if allowed_counts is None else tuple(allowed_counts)
        if any(type(k) is not int or not 0 <= k <= self.capacity for k in raw_counts):
            raise ValueError('Allowed counts must be integers within model capacity')
        counts = set(raw_counts)
        optional = tuple((k, w) for k, w in zip(self.keys, self.log_weights) if k not in required | forbidden)
        suffix = self.suffix if not required and not forbidden else _suffix([w for _, w in optional])
        required_weight = math.fsum(w for k, w in zip(self.keys, self.log_weights) if k in required)
        masses = []
        for k, pk in enumerate(self.log_count_pmf):
            remaining = k - len(required)
            if k not in counts or not 0 <= remaining <= len(optional):
                masses.append(NEG_INF)
            else:
                masses.append(pk + required_weight + suffix[0][remaining] - self.suffix[0][k])
        mass = NEG_INF
        for p in masses: mass = _add(mass, p)
        # Rounding can place a total event infinitesimally above one.
        return required, optional, suffix, masses, min(mass, 0.0)

    def event_mass(self, *, required_groups=(), forbidden_groups=(), allowed_counts=None):
        """True unconditioned mass, including count AND subset restrictions."""
        *_, log_mass = self._event(required_groups, forbidden_groups, allowed_counts)
        return {'probability': math.exp(log_mass), 'log_probability': log_mass}

    def sample(self, *, seed, retailer_id, product_id, concept_id,
               required_groups=(), forbidden_groups=(), allowed_counts=None):
        if type(seed) is not int or not all(type(x) is str and x for x in (retailer_id, product_id, concept_id)):
            raise ValueError('Declare seed and retailer/product/concept identity')
        required, optional, suffix, masses, log_mass = self._event(required_groups, forbidden_groups, allowed_counts)
        if log_mass == NEG_INF:
            raise ValueError('Disclosure requirement has zero probability mass')
        draw = lambda stream: _draw(seed, retailer_id, product_id, concept_id, stream)
        count = _weighted_index(masses, draw('count'))
        selected = set(required)
        remaining = count - len(required)
        for i, (key, weight) in enumerate(optional):
            if not remaining: break
            if remaining == len(optional) - i:
                selected.update(k for k, _ in optional[i:]); break
            log_include = weight + suffix[i+1][remaining-1] - suffix[i][remaining]
            if math.log(draw('group:' + key)) < log_include:
                selected.add(key); remaining -= 1
        return {
            'protocol': VERSION, 'capacity': self.capacity, 'requested_count': count,
            'selected_groups': sorted(selected),
            'count_pmf': [math.exp(x) for x in self.log_count_pmf],
            'conditioned_count_pmf': [math.exp(x - log_mass) for x in masses],
            'conditioning_mass': math.exp(log_mass), 'conditioning_log_mass': log_mass,
            'highlight_bias': self.highlight_bias,
            'group_weights': {k: math.exp(w) for k, w in zip(self.keys, self.log_weights)},
        }
