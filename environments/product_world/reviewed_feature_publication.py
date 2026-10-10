"""Opt-in reviewed disclosure; immutable definitions and completed facts only.

This adds no manufacturing validation or product sampling. It reuses the shared
scalar projector/selector and withholds incomplete coupled disclosure groups.
The previously released catalogue and T-shirt adapter remain untouched.
"""
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path

from .feature_publication import ROOT, resolve_scalar_records, select_content
from .shared_state import freeze

CATALOGUE = Path(__file__).parent / 'data/product_feature_policies/catalogue_v2'


def _digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


@lru_cache(maxsize=1)
def _manifest():
    return freeze(json.loads((CATALOGUE / 'manifest.json').read_text()))


@lru_cache(maxsize=256)
def load_reviewed_policy(concept_id, *, verify_sources=False):
    manifest = _manifest()
    if concept_id not in manifest['concepts']:
        raise ValueError('No reviewed publication policy: ' + str(concept_id))
    entry = manifest['concepts'][concept_id]
    path = CATALOGUE / entry['file']
    if _digest(path) != entry['sha256']:
        raise ValueError('Reviewed policy digest mismatch')
    policy = json.loads(path.read_text())
    if verify_sources:
        for name, expected in policy['source_sha256'].items():
            if _digest(ROOT / name) != expected:
                raise ValueError('Publication source changed: ' + name)
    return freeze(policy)


def policy_sha256(concept_id):
    """Exact reviewed policy bytes, shared by generic producer inventories."""
    return _manifest()['concepts'][concept_id]['sha256']


def select_reviewed_content(policy, facts, *, seed, retailer_id, product_id,
                            probabilities=None, selected_groups=None):
    """Avoid publishing one half of a declared range/operation/composition.

    `facts` is the producer's authoritative completed projection. Compound-only
    groups require a later adapter and are withheld as a unit here. Retailer
    selection cannot change product/SKU manufacture or its random stream.
    """
    withheld_paths = set()
    for group in policy['disclosure_groups'].values():
        if not group.get('atomic'):
            continue
        if any(not policy['fields'][path]['semantic_id'] or
               path not in facts or facts[path].get('status') != 'known' or
               facts[path].get('applicable') is False
               for path in group['fields']):
            withheld_paths.update(group['fields'])
    available = {path: value for path, value in facts.items() if path not in withheld_paths}
    result = select_content(policy, available, seed=seed, retailer_id=retailer_id,
                            product_id=product_id, probabilities=probabilities,
                            selected_groups=selected_groups)
    result['publication_policy_version'] = 'reviewed-v2'
    result['publication_policy_sha256'] = _manifest()['concepts'][policy['concept_id']]['sha256']
    result['semantic_review_sha256'] = _manifest()['review_sha256']
    return result


__all__ = ['load_reviewed_policy', 'resolve_scalar_records', 'select_reviewed_content']
