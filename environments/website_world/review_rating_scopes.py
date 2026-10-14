"""Public option-rating projection over the existing syndicated corpus."""
from decimal import Decimal, ROUND_HALF_UP

from environments.product_world.review_population import summarize_ratings

SKU_SUMMARY_LAYOUTS = ('journal', 'community', 'lab-directory', 'editorial-magazine', 'community-feed')


def require_public_rating_scope(task, site):
    """Do not prepare a named SKU summary on an unsupported presentation."""
    if (task.get('operation') == 'rating_summary' and task.get('subject_scope') == 'sku'
            and site.get('layout') not in SKU_SUMMARY_LAYOUTS):
        raise ValueError('Review presentation does not support a public SKU rating summary')


def sku_rating_summary(product, sku_id):
    """Include silent ratings, once per canonical ID, for one actual option.

    Reads only the public corpus. Comment filters, pagination and private task
    references do not participate in the summary.
    """
    skus = {sku['sku_id'] for sku in product['skus']}
    if sku_id not in skus:
        raise ValueError('Unknown reviewed configuration')
    canonical = {}
    for review in product['reviews']:
        identity = review.get('review_id')
        if type(identity) is not str or not identity or review.get('sku_id') not in skus:
            raise ValueError('Rating lacks canonical identity or reviewed configuration')
        if identity in canonical and canonical[identity] != review:
            raise ValueError('Conflicting syndicated rating copies')
        canonical[identity] = review
    rows = [review for review in canonical.values() if review['sku_id'] == sku_id]
    summary = summarize_ratings(rows)
    summary['mean_rounded'] = (str((Decimal(summary['rating_sum']) / summary['rating_count'])
        .quantize(Decimal('.01'), rounding=ROUND_HALF_UP)) if rows else None)
    return summary
