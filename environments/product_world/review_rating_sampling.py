"""Shared synthetic star distribution; parameters are authored, not fitted."""
import math


DEFAULT_CONCENTRATION = 1.5


def validate_concentration(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError('Rating concentration must be finite and positive')


def sample_rating(rng, execution, concentration=DEFAULT_CONCENTRATION):
    """Draw 1 + BetaBinomial(4, p*k, (1-p)*k).

    Execution remains a quality input in [0,1]. The interior mapping keeps even
    the endpoints from implying unanimous ratings. Details can then be sampled
    conditional on this reviewer's overall satisfaction.
    """
    validate_concentration(concentration)
    if isinstance(execution, bool) or not isinstance(execution, (int, float)) or not math.isfinite(execution) or not 0 <= execution <= 1:
        raise ValueError('Execution must be finite and within [0,1]')
    mean_affinity = .05 + .9 * execution
    affinity = rng.betavariate(mean_affinity * concentration, (1 - mean_affinity) * concentration)
    rating = 1 + sum(rng.random() < affinity for _ in range(4))
    return {'rating': rating, 'schema_version': 'review-rating-beta-binomial-v1',
            'concentration': concentration, 'expected_rating': 1 + 4 * mean_affinity,
            'reviewer_affinity': affinity}
