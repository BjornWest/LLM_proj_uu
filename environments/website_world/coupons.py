"""Explicit public boundary for the pinned native quantity-one coupon stage."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json

from experiments.footwear_world_pilot import coupon_quote
from .adapter import ROOT, supported_destination


def load_coupon_pin(path, world):
    path = Path(path)
    manifest = json.loads((path / 'manifest.json').read_text())
    if manifest['schema_version'] != 'footwear-coupon-fixture-pin-v1':
        raise ValueError('Unsupported native coupon pin')
    for name, expected in manifest['files'].items():
        if Path(name).name != name or sha256((path / name).read_bytes()).hexdigest() != expected:
            raise ValueError('Coupon artifact mismatch')
    for name, expected in {**manifest['source_sha256'], **manifest['native_quote_source_sha256']}.items():
        if sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise ValueError('Pinned coupon source mismatch')
    plan = json.loads((path / 'coupon-plan.json').read_text())
    coupon_quote.validate_plan(world, plan)
    return plan, manifest


class Coupons:
    def __init__(self, adapter, pin):
        self.adapter = adapter
        self.plan, self.manifest = load_coupon_pin(pin, adapter.world)

    def account(self, retailer_id):
        # Read-only initial account: no invented sign-in or redemption endpoint.
        return coupon_quote.public_account(self.plan, retailer_id)

    def quote(self, retailer_id, query):
        query = deepcopy(query)
        if not {'offer_id', 'quantity'} <= set(query):
            raise ValueError('Supply one carried offer and quantity one')
        offer_id = query.pop('offer_id')
        quantity = query.pop('quantity')
        if quantity != '1':
            raise ValueError('Only quantity one is supported')
        code = query.pop('coupon_code', None) or None
        destination = supported_destination(self.adapter.world, query)
        original = coupon_quote.quote(self.adapter.world, retailer_id, offer_id,
            plan=self.plan, coupon_code=code, destination=destination, quantity=1,
            signed_in=self.account(retailer_id)['signed_in'])
        public = {key: deepcopy(original[key]) for key in (
            'quote_id', 'offer_id', 'sku_id', 'quantity', 'currency', 'subtotal_minor',
            'discount_minor', 'merchandise_minor', 'coupon', 'status')}
        # Match source/service identities to the existing explicit projection;
        # preserve native fees/totals and never export private routes/geography.
        baseline = self.adapter.fulfilment(retailer_id, query)['optionsBySku'][original['sku_id']]
        indexed = {(o['sourceId'], o['carrierId'], o['tier'], o['type'],
                    o['location']['id']): o for o in baseline}
        rows = []
        for q in original['options']:
            key = (q['source_id'], q['carrier_id'], q['tier'], q['destination_type'], q['point_id'] or 'home')
            if key not in indexed:
                raise ValueError('Native coupon quote introduced an unsupported service identity')
            row = deepcopy(indexed[key])
            row.update(shippingMinor=q['shipping_minor'], totalMinor=q['total_minor'],
                       fee=q['shipping_minor']/100, tariff=q['shipping_minor']/100,
                       arrival=q['arrival_date'], readyDays=q['ready_days'])
            rows.append(row)
        public['options'] = rows
        return public
