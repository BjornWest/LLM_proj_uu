"""Opt-in retailer review layouts over the existing complete public corpus."""
from hashlib import sha256
import json
from pathlib import Path

VERSION = 'website-retailer-review-presentation-v1'
DEFAULTS = {'mode': 'legacy', 'initial_count': 2, 'batch_size': 2}


def options(value=None):
    if value is not None and (type(value) is not dict or set(value) - set(DEFAULTS)):
        raise ValueError('Review presentation accepts mode and comment counts only')
    result = {**DEFAULTS, **(value or {})}
    if result['mode'] not in ('legacy', 'inline', 'paged'):
        raise ValueError('Use legacy, inline or paged review presentation')
    for key in ('initial_count', 'batch_size'):
        if type(result[key]) is not int or not 1 <= result[key] <= 100:
            raise ValueError('Review comment counts must be integers1..100')
    return result


def project_assets(assets, value=None):
    """Replace only a copied retailer-review asset; keep defaults byte-identical.

    This hook belongs before served-asset hashes/host publication. It neither
    changes review data/statistics nor samples task-related comments. Returned
    evidence is private; only the resulting JS belongs in the public assets.
    """
    settings = options(value)
    if 'retailer_reviews.js' not in assets or type(assets['retailer_reviews.js']) is not bytes:
        raise ValueError('Review presentation requires the existing retailer review asset')
    result = dict(assets)
    if settings['mode'] != 'legacy':
        source = Path(__file__).with_suffix('.js').read_text()
        config = {'mode': settings['mode'], 'initialCount': settings['initial_count'],
                  'batchSize': settings['batch_size']}
        source += '\nconst presentation=' + json.dumps(config, sort_keys=True) + ';\n'
        source += 'export function customerReviews(product,helpers){return renderReviews(product,helpers,presentation);}\n'
        result['retailer_reviews.js'] = source.encode()
    evidence = {'schema': VERSION, 'settings': settings,
                'before_asset_sha256': sha256(assets['retailer_reviews.js']).hexdigest(),
                'after_asset_sha256': sha256(result['retailer_reviews.js']).hexdigest(),
                'changed_assets': [] if settings['mode'] == 'legacy' else ['retailer_reviews.js'],
                'source': 'Existing attributed public review corpus and all-rating summary; no recomputation or row sampling.'}
    return result, evidence
