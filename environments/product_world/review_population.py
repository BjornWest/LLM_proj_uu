"""Shared review-site population settings and all-rating summaries."""
from copy import deepcopy
import math

DEFAULTS = {'requires_text': False, 'rating_only_probability': 0.75, 'ratings_per_product': 40}


def resolve_review_site(overrides=None):
    patch = {} if overrides is None else deepcopy(overrides)
    if set(patch) - set(DEFAULTS):
        raise ValueError('Unknown review-site population setting')
    cfg = {**DEFAULTS, **patch}
    if type(cfg['requires_text']) is not bool:
        raise ValueError('requires_text must be boolean')
    p = cfg['rating_only_probability']
    if isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1:
        raise ValueError('Invalid rating-only probability')
    if type(cfg['ratings_per_product']) is not int or not 1 <= cfg['ratings_per_product'] <= 10000:
        raise ValueError('Invalid ratings_per_product')
    return cfg


def effective_review_lengths(written_weights, site=None):
    """Written length preferences are independent of text being required/optional."""
    site = resolve_review_site(site)
    if not written_weights:
        raise ValueError('Missing written-review length weights')
    for key, value in written_weights.items():
        if str(key) not in {'1','2','3','4'} or isinstance(value, bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value < 0:
            raise ValueError('Invalid written-review length weights')
    total = sum(written_weights.values())
    if total <= 0:
        raise ValueError('Written-review lengths have no mass')
    empty = 0.0 if site['requires_text'] else site['rating_only_probability']
    return {'0': empty, **{str(k):(1-empty)*v/total for k,v in written_weights.items()}}


def summarize_ratings(reviews):
    histogram = {str(i):0 for i in range(1,6)}
    written = 0
    for review in reviews:
        rating = review['rating']
        if type(rating) is not int or not 1 <= rating <= 5:
            raise ValueError('Expected integer rating from 1 to 5')
        histogram[str(rating)] += 1
        written += bool(review['text'].strip())
    count = len(reviews)
    rating_sum = sum(int(k)*v for k,v in histogram.items())
    return {'rating_count':count, 'written_review_count':written, 'rating_only_count':count-written,
            'star_counts':histogram, 'rating_sum':rating_sum,
            'average_rating':rating_sum/count if count else None,
            'average_basis':'all ratings, including ratings without comments'}
