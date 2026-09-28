"""Exact-option stock disclosures, using the same quotes as the task world."""
from .pages import e,link,query,money
from .interaction_patterns import needs_destination


def source_location(owner,offer,source_id):
    merchant=owner.merchants[offer['retailer_id']]
    locations=[merchant['warehouse']]+[b['location'] for b in merchant['branches']]
    return next((x for x in locations if x['location_id']==source_id),None)


def store_stock(owner,offer,quantity):
    site=offer['retailer_id'];sku=offer['product_id']
    delivery=owner.quote(offer['offer_id'],quantity=quantity)
    sources={x['stock_source']:x for x in delivery.get('delivery_sources',[])}
    body='<details id="store-stock"><summary>Stock in stores</summary>'
    body+='<p>Selected SKU: '+e(sku)+' · requested quantity: '+str(quantity)+'. Store and warehouse stock are separate; quantities are not combined.</p>'
    for branch in owner.merchants[site]['branches']:
        bid=branch['branch_id']
        pickup=owner.quote(offer['offer_id'],quantity=quantity,method='pickup',branch_id=bid)
        inspect=owner.quote(offer['offer_id'],quantity=quantity,method='inspect',branch_id=bid)
        source=sources.get(branch['location']['location_id'])
        body+='<article data-branch-id="'+e(bid)+'"><h3>'+e(branch['name'])+'</h3>'
        body+='<p>'+e(branch['location']['city'])+', '+e(branch['location']['country'])+'</p>'
        body+='<p>Stock at this store: '+str(pickup['branch_stock_quantity'])+' units</p>'
        if source and source['shipping_supported']:
            body+='<p>Ships online orders: Yes. '+('Check delivery for your address.' if needs_destination(owner,site) else 'Delivery in '+str(source['ready_days'])+' days; total '+money(source['total_minor']) if source['eligible'] else 'Unavailable for this quantity or destination: '+e(', '.join(source['reason_codes']).replace('_',' ')))+'</p>'
        else:body+='<p>Ships online orders: No</p>'
        if pickup['eligible']:
            message=('Warehouse transfer required; ready in '+str(pickup['ready_days'])+' days.' if pickup['requires_stock_transfer'] else 'Available from stock at this store.')
        else:message='Unavailable: '+', '.join(pickup['reason_codes']).replace('_',' ')+'.'
        body+='<p>Pickup: '+e(message)+'</p><p>In-store inspection: '+('Available' if inspect['eligible'] else 'Unavailable')+'</p>'
        body+=link(query('/quote',{'offer_id':offer['offer_id'],'quantity':quantity,'method':'pickup','branch_id':bid}),'Check pickup at '+branch['name'])+'</article>'
    if not owner.merchants[site]['branches']:body+='<p>This retailer has no physical stores.</p>'
    return body+'</details>'
