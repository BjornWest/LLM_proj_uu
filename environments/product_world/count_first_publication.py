"""Additive count-first entrypoints; pinned legacy exporters remain unchanged."""
from functools import lru_cache

from .disclosure_sampling import DisclosureDistribution, DEFAULT_HIGHLIGHT_BIAS
from .feature_publication import load_policy
from .tablet_publication import _loaded as tablet_policy, export_tablet_content
from .tshirt_publication import export_tshirt_content

# Approved prose-supported topics only: the standalone size-chart declaration
# is a native sizing surface, not a prose group in the existing T-shirt adapter.
TSHIRT_GROUPS = ('main_fabric', 'fit', 'neckline', 'fabric_weight', 'neck_trim',
                 'style', 'machine_wash', 'drying', 'bleach', 'dry_cleaning', 'ironing')


@lru_cache(maxsize=128)
def _distribution(concept_id, weights, highlight_bias):
    if concept_id == 'tablets.everyday_media_tablets':
        groups = tablet_policy()[0]['disclosure_groups']
        priorities = {k: v['highlight_priority'] for k, v in groups.items()}
    elif concept_id == 'tops.t_shirts':
        groups = load_policy(concept_id)['disclosure_groups']
        priorities = {k: groups[k]['highlight_priority'] for k in TSHIRT_GROUPS}
    else:
        raise ValueError('No released count-first prose adapter for this concept')
    return DisclosureDistribution(priorities, count_weights=None if weights is None else dict(weights),
                                  highlight_bias=highlight_bias)


def _export(item, *, sku_id=None, seed, retailer_id, count_weights=None,
            highlight_bias=DEFAULT_HIGHLIGHT_BIAS, required_groups=(),
            forbidden_groups=(), allowed_counts=None):
    cid = item['public']['concept_id']
    # Construct/validate configuration before using it as a cache key: bools
    # must not alias integers in Python's cache and malformed PMFs must fail.
    if count_weights is not None:
        if not isinstance(count_weights, dict) or any(type(k) is not int or type(v) not in (int, float) for k, v in count_weights.items()):
            raise ValueError('Declare numeric count weights with integer keys')
        weights = tuple(sorted(count_weights.items()))
    else:
        weights = None
    if type(highlight_bias) not in (int, float):
        raise ValueError('Declare a numeric highlight bias')
    distribution = _distribution(cid, weights, highlight_bias)
    selection = distribution.sample(seed=seed, retailer_id=retailer_id, product_id=item['public']['product_id'],
                                    concept_id=cid, required_groups=required_groups,
                                    forbidden_groups=forbidden_groups, allowed_counts=allowed_counts)
    args = dict(seed=seed, retailer_id=retailer_id, selected_groups=selection['selected_groups'])
    if cid == 'tablets.everyday_media_tablets':
        packet = export_tablet_content(item, sku_id=sku_id, **args)
    else:
        packet = export_tshirt_content(item, **args)
    published = {slot['group_key'] for group in packet['display_groups'] for slot in group['slots']}
    selection['published_count'] = len(published)
    selection['unavailable_selected_groups'] = sorted(set(selection['selected_groups']) - published)
    # Legacy Bernoulli probabilities were bypassed using explicit topic groups.
    packet.pop('probabilities', None)
    packet['disclosure_selection'] = selection
    return packet


def export_count_first_tablet_content(item, *, sku_id, **kwargs):
    if item['public']['concept_id'] != 'tablets.everyday_media_tablets':
        raise ValueError('Select the declared media-tablet concept')
    return _export(item, sku_id=sku_id, **kwargs)


def export_count_first_tshirt_content(item, **kwargs):
    if item['public']['concept_id'] != 'tops.t_shirts':
        raise ValueError('Select the declared T-shirt concept')
    return _export(item, **kwargs)
