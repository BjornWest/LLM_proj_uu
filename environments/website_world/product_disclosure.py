"""Recipe validation for the released Product count-first protocol."""
from copy import deepcopy
from environments.product_world import catalog_publication
from environments.product_world.disclosure_sampling import (
    VERSION as PROTOCOL, DEFAULT_HIGHLIGHT_BIAS, DisclosureDistribution, count_weights_from_entries,
)

VERSION='website-product-disclosure-v1'
PROFILE_VERSION='website-profiled-product-disclosure-v1'
# Capacity is the declared inventory in the frozen producer release, not current
# SKU availability. The producer resolves actual groups and values after drawing.
CAPACITIES={'tops.t_shirts':11,'tablets.everyday_media_tablets':15,
            **{cid:catalog_publication.inventory(cid)['capacity'] for cid in catalog_publication.CONCEPTS}}


def options(value):
    if not isinstance(value,dict) or set(value)-{'enabled','mode','highlight_bias','count_weights'} or type(value.get('enabled')) is not bool:
        raise ValueError('Product disclosure requires an explicit enabled flag')
    if not value['enabled']:
        if set(value)!={'enabled'}:raise ValueError('Disabled product disclosure cannot contain controls')
        return None
    bias=value.get('highlight_bias',DEFAULT_HIGHLIGHT_BIAS)
    mode=value.get('mode','count_first')
    if mode not in ('count_first','retailer_profile'):raise ValueError('Unknown disclosure mode')
    if mode=='retailer_profile':
        if 'count_weights' in value:raise ValueError('Retailer-profile disclosure cannot override count weights')
        from environments.product_world.retailer_disclosure import VERSION as PROFILE_PROTOCOL
        DisclosureDistribution({'validate_bias':0},highlight_bias=bias)
        return {'schema':PROFILE_VERSION,'protocol':PROFILE_PROTOCOL,'mode':mode,'highlight_bias':bias}
    weights=value.get('count_weights',{})
    if not isinstance(weights,dict) or set(weights)-set(CAPACITIES):raise ValueError('Unknown count-first concept')
    parsed={cid:count_weights_from_entries(entries) for cid,entries in weights.items()}
    for cid,capacity in CAPACITIES.items():
        DisclosureDistribution({str(i):0 for i in range(capacity)},count_weights=parsed.get(cid),highlight_bias=bias)
    return {'schema':VERSION,'protocol':PROTOCOL,'highlight_bias':bias,
            'count_weights':{cid:[[k,v] for k,v in sorted(parsed[cid].items())] for cid in sorted(parsed)}}


def validate_settings(value):
    if isinstance(value,dict) and value.get('schema')==PROFILE_VERSION:
        from environments.product_world.retailer_disclosure import VERSION as PROFILE_PROTOCOL
        if set(value)!={'schema','protocol','mode','highlight_bias'} or value['protocol']!=PROFILE_PROTOCOL or value['mode']!='retailer_profile':
            raise ValueError('Invalid normalized retailer-profile disclosure controls')
        return options({'enabled':True,'mode':'retailer_profile','highlight_bias':value['highlight_bias']})
    if not isinstance(value,dict) or set(value)!={'schema','protocol','highlight_bias','count_weights'} or value['schema']!=VERSION or value['protocol']!=PROTOCOL:
        raise ValueError('Invalid normalized product disclosure controls')
    return options({'enabled':True,'highlight_bias':value['highlight_bias'],'count_weights':deepcopy(value['count_weights'])})


def producer_arguments(settings,concept_id):
    entries=settings['count_weights'].get(concept_id)
    return {'highlight_bias':settings['highlight_bias'],
            'count_weights':count_weights_from_entries(entries) if entries is not None else None}


def retailer_profiles(world,settings):
    if settings is None or settings.get('schema')!=PROFILE_VERSION:return None
    from environments.product_world.retailer_disclosure import sample_retailer_disclosure
    return {r['retailer_id']:sample_retailer_disclosure(world['seed'],r) for r in world['retailers']}


def validate_profiles(world,settings,profiles):
    expected=retailer_profiles(world,settings)
    if profiles!=expected:raise ValueError('Stale or missing retailer disclosure profiles')
    return deepcopy(expected)
