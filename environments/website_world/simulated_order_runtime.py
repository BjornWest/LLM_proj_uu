"""Fresh Runtime order wiring and receipt-only public projection.

No quote arithmetic or native record reimplementation lives here. Runtime invokes
this after attaching its authoritative basket transport and actual catalogs.
"""
from copy import deepcopy
from secrets import token_hex

from .simulated_order_store import OrderStore

VERSION='website-simulated-order-runtime-v1'


def initialize(runtime):
    if runtime.baskets is None:raise ValueError('Fresh simulated ordering requires the shared basket quote transport')
    runtime.orders=OrderStore(runtime.baskets,runtime_id=token_hex(16),
        precommit=lambda rid,record:public_confirmation(runtime,rid,record))


def public_confirmation(runtime,retailer_id,record):
    if (record.get('retailer_id')!=retailer_id or record.get('world_id')!=runtime.world['world_id']
            or record.get('simulated') is not True or record.get('status')!='confirmed'):
        raise ValueError('Confirmation belongs to another runtime/retailer or is not confirmed')
    variants={v['offerId']:(p,v) for p in runtime.public_catalogs[retailer_id]['products'] for v in p['variants']}
    items=[]
    for item in record['items']:
        product,variant=variants[item['offer_id']]
        if variant['skuId']!=item['sku_id'] or product['canonicalProductId']!=item['product_id']:
            raise ValueError('Recorded order subject differs from the actual storefront')
        labels={o['key']:o['label'] for o in product['options']}
        items.append({'name':product['name'],'skuId':item['sku_id'],'offerId':item['offer_id'],
            'quantity':item['quantity'],'options':' / '.join(labels[k]+': '+str(v) for k,v in variant['selection'].items())})
    def arrival(value):
        if value['status']!='estimated':return None
        return value['latest_date'] if value['earliest_date']==value['latest_date'] else value['earliest_date']+' to '+value['latest_date']
    shipments=[]
    for shipment in record['shipments']:
        delivery=shipment['delivery']
        shipments.append({k:deepcopy(delivery[k]) for k in ('company','name','type','location')})
        shipments[-1].update(arrival=arrival(shipment['arrival']),shippingMinor=shipment['shippingMinor'])
    return {'simulated':True,'id':record['order_id'],'date':runtime.world['quote_as_of'],
        'status':'Order received','items':items,'address':deepcopy(record['address']),
        'instructions':record['delivery_instructions'],'shipments':shipments,
        'currency':record['currency'],'subtotalMinor':record['subtotal_minor'],
        'discountMinor':record['discount_minor'],'shippingMinor':record['shipping_minor'],
        'totalMinor':record['total_minor']}


def submit(runtime,retailer_id,submission):
    record=runtime.orders.commit(retailer_id,submission)
    return {'confirmation':public_confirmation(runtime,retailer_id,record)}
