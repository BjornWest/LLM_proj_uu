"""Checkout composition is independent of storefront architecture and prices."""
from collections.abc import Mapping
import hashlib

CHECKOUT_MODES=('legacy','express','accordion','wizard')
CHECKOUT_SHOWCASE={'nordhem':'accordion','vardagslagret':'wizard','teknikgarden':'express'}


def resolve_checkout_flows(seed, retailer_ids, configured=None):
    if configured=='sampled':
        return {site:CHECKOUT_MODES[1:][int.from_bytes(hashlib.sha256(f'commerce-checkout-v1/{seed}/{site}'.encode()).digest()[:8],'big')%3] for site in retailer_ids}
    if configured is None:configured={}
    if not isinstance(configured,Mapping):raise ValueError('checkout_flows must be a mapping or sampled')
    if set(configured)-set(retailer_ids):raise ValueError('Unknown checkout retailer')
    result={site:configured.get(site,'legacy') for site in retailer_ids}
    if any(mode not in CHECKOUT_MODES for mode in result.values()):raise ValueError('Unknown checkout flow')
    return result
