"""Item delivery display from the same native basket oracle as checkout."""
from copy import deepcopy
from datetime import date
from .adapter import digest,supported_destination


def project(self,retailer_id,address,*,sku_ids=None):
    destination=supported_destination(self.world,address)
    retailer=self.retailers[retailer_id]
    wanted=None if sku_ids is None else frozenset(sku_ids)
    if wanted is not None and (not wanted or wanted-set(o['sku_id'] for o in retailer['offers'])):
        raise ValueError('Supply listed SKU identities for this retailer')
    key=(getattr(self,'prepared_identity',None),retailer_id,digest([destination,address]),None if wanted is None else tuple(sorted(wanted)))
    if key in self.cache:return deepcopy(self.cache[key])
    points={p['point_id']:p for p in self.world['address_context']['collection_points']}
    branches={b['branch_id']:b for b in retailer['geography']['branches']}
    services={s['service_id']:s for s in self.world['address_context']['services']}
    options={}
    for offer in retailer['offers']:
        if wanted is not None and offer['sku_id'] not in wanted:continue
        oid=offer['offer_id'];line={'line_id':oid,'offer_id':oid,'quantity':1}
        prepared=getattr(self,'prepared',None)
        raw=(prepared.quote(retailer_id,[line],destination=destination) if prepared is not None else
             self.oracle.quote(self.world,retailer_id,[line],plan=self.plan,destination=destination))
        choices={c['choice_id']:c for c in raw['delivery_choices']};rows=[]
        for option in raw['options']:
            shipment=option['shipments'][0];item=shipment['items'][0]
            choice=choices[shipment['choice_id']];kind=choice['destination_type'];point=points.get(choice['point_id']);branch=branches.get(choice.get('branch_id'))
            location={'id':choice['point_id'] or choice['destination']['location_id']}
            if kind=='home':location.update(name='Your address',address=', '.join([address['street'],address['postcode'],address['city']]))
            elif point:location.update(name=point['name'],address=point.get('address',point['location']['city']))
            elif branch:location.update(name=branch['name'],address=branch['location']['city'])
            else:raise ValueError('Unknown public collection destination')
            arrival=shipment['arrival'];arrival_text=arrival.get('latest_date') if arrival['status']=='estimated' else None
            rows.append({'id':choice['choice_id'],'offerId':oid,'skuId':offer['sku_id'],
                'sourceId':item['source_id'],'company':choice['carrier_name'] or retailer['name'],
                'name':choice['tier'].capitalize() if choice['tier'] else 'Shop collection',
                'tier':choice['tier'],'type':kind,'location':location,'arrival':arrival_text,
                'readyDays':(date.fromisoformat(arrival_text)-date.fromisoformat(self.world['quote_as_of'])).days if arrival_text else None,
                'supply':item['supply'],'fee':option['shipping_minor']/100,
                'shippingMinor':option['shipping_minor'],'totalMinor':option['total_minor'],
                'scheduling':services.get(item.get('service_id'),{}).get('scheduling','collection_after_ready' if kind!='home' else 'not_published'),
                'collectionHours':deepcopy(choice['collection_hours']),
                'branchId':choice.get('branch_id'),'requiresTransfer':item['requires_transfer']})
        if retailer_id in self.delivery_orders:
            from .delivery_options import sorted_item_rows
            rows=sorted_item_rows(rows,self.delivery_orders[retailer_id])
        options[offer['sku_id']]=rows
    result={'address':deepcopy(address),'optionsBySku':options}
    self.cache[key]=deepcopy(result);return result
