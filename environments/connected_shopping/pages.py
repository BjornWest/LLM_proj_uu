"""Research storefronts using existing layout shells and authoritative geographic quotes."""
from html import escape
from urllib.parse import urlencode,quote
from environments.procedural_commerce import retailer_designs as layout, dense_storefront as dense, product_controls as controls
from environments.product_review_sites.data import field_info,pretty
from .index import tokens,STYLE
from . import interaction_patterns as patterns


def e(value):return escape(str(value),quote=True)
def path_product(sku):return '/products/'+quote(sku,safe='')
def money(value):return 'Unavailable' if value is None else f'{value/100:.2f} SEK'
def fact_value(family,key,value):
    unit=field_info(family,key)[1]
    return pretty(value)+(' '+unit if unit else '')
def factrows(p):return ''.join('<tr><th scope="row">'+e(field_info(p['category'],k)[0])+'</th><td>'+e(fact_value(p['category'],k,v))+'</td></tr>' for k,v in p['attributes'].items())
def table(p):return '<table class="fact-table"><caption>Product details</caption><tbody>'+factrows(p)+'</tbody></table>'
def link(url,label):return '<a href="'+e(url)+'">'+e(label)+'</a>'
def query(path,q):return path+'?'+urlencode(q)


def connections(owner,site,sku=None):
    links=[link(owner.index_origin,'Search the web'),link(owner.origins['aggregator'],'Compare prices')]
    if site in owner.stores:links.append(link(owner.origins['merchant-reviews']+'/review/'+site,'Independent merchant reviews'))
    if sku:
        group=owner.group_for[sku];review_site='reviews-'+group['family']
        links.append(link(owner.origins[review_site]+'/reviews/'+group['group_id'],'Independent product review'))
    return '<nav aria-label="Other websites">'+' · '.join(links)+'</nav>'


def shell(owner,site,title,body,sku=None):
    from .storefront import catalog_fields
    catalog=owner.catalog(site);design=owner.designs[site];options=layout._options(design,None)
    account_navigation=owner.account_pages.navigation(site) if getattr(owner,'account_pages',None) else ''
    catalog={**catalog,'products':display_products(owner,catalog['products']),**catalog_fields(owner,site)}
    main='<main id="main-content">'+account_navigation+body+'</main>'
    return layout._design_document(site,owner.origins,catalog,design,title,main,options)


def display_products(owner,products):
    """Footwear browsing is by model; sizes remain on exact product pages.

    Search filters apply first, so an exact size/SKU query still leads to a matching
    entry SKU. Other families retain their meaningful configuration listings.
    Only presentation copies change; canonical products/offers stay untouched.
    """
    result=[];grouped={}
    for p in products:
        if p.get('category')!='footwear' or not getattr(owner,'group_for',None) or '_browse_variants' in p:
            result.append(p);continue
        group=owner.group_for[p['product_id']];gid=group['group_id']
        if gid not in grouped:
            excluded={a['field'] for a in group['axes']}
            row={**p,'name':group['name'],'attributes':{k:v for k,v in p['attributes'].items() if k not in excluded},'_browse_variants':[]}
            grouped[gid]=row;result.append(row)
        row=grouped[gid];row['_browse_variants'].append(p['product_id'])
        row['attributes']={k:v for k,v in row['attributes'].items() if p['attributes'].get(k)==v}
    return result


def cards(owner,site,products,*,force_cards=False):
    # Display metadata belongs here, never in the canonical product attributes.
    items=[]
    listed=not force_cards and patterns.options(owner,site).get('result_presentation')=='list'
    for p in display_products(owner,products):
        offer=owner.offer_by_store.get((site,p['product_id']))
        if offer is None:continue
        url=owner.origins[site]+path_product(p['product_id'])
        facts=''.join('<li>'+e(field_info(p['category'],k)[0])+': '+e(fact_value(p['category'],k,v))+'</li>' for k,v in list(p['attributes'].items())[:3])
        available=owner.quote(offer['offer_id'])['eligible'] if not patterns.needs_destination(owner,site) else None
        availability=('Warehouse stock: '+str(offer['stock_quantity'])+'. Check delivery for your address.' if available is None else 'Available for delivery' if available else 'Unavailable for delivery; check store stock')
        price=money(offer['price_minor'])
        if p.get('_browse_variants'):
            variant_offers=[owner.offer_by_store[(site,sku)] for sku in p['_browse_variants']]
            price='From '+money(min(o['price_minor'] for o in variant_offers))
            availability=('Some options in stock.' if any(o['stock_quantity']>0 for o in variant_offers) else 'Listed options are out of stock.')+' Choose size and colour to check the exact price and availability.'
        if listed:
            items.append('<tr><th scope="row">'+link(url,p['name'])+'</th><td>'+price+'</td><td>'+e(availability)+'</td><td><details><summary>Product details</summary><ul>'+facts+'</ul>'+link(url,'View product')+'</details></td></tr>')
            continue
        items.append('<li class="product-card"><article><a href="'+e(url)+'"><img loading="lazy" src="'+e(layout._svg_src(1))+'" alt="'+e(p['name'])+' — catalog illustration"></a>'+'<p>'+e(p['category'].replace('_',' '))+'</p><h3>'+link(url,p['name'])+'</h3><p class="price">'+price+'</p><ul>'+facts+'</ul><p>'+availability+'</p>'+link(url,'View product')+'</article></li>')
    if not items:return '<p>No other listed products in this section.</p>'
    if listed:return '<div class="wide"><table><caption>Product price list</caption><thead><tr><th>Product</th><th>Item price</th><th>Availability</th><th>Details</th></tr></thead><tbody>'+''.join(items)+'</tbody></table></div>'
    return '<ul class="product-cards">'+''.join(items)+'</ul>'


def related_products(owner,site,sku,limit=8):
    # Show other models, not eight near-identical sizes of the current model.
    # Stable catalog order; no task facts, stock preference or winning-offer ranking.
    if limit==0:return []
    seen={owner.group_for[sku]['group_id']};result=[]
    for p in display_products(owner,owner.catalog(site)['products']):
        group=owner.group_for[p['product_id']]['group_id']
        if group not in seen:
            seen.add(group);result.append(p)
            if len(result)>=limit:break
    return result


def listing(owner,site,q,home=False):
    from . import storefront
    row=storefront.content(owner,site)
    if set(q)-({'q','category','page','collection'} if row else {'q','category','page'}):raise ValueError('Unknown search field')
    if home and not q:return home_page(owner,site)
    words=set(tokens(q.get('q','')));category=q.get('category','');catalog=owner.catalog(site)['products']
    if q.get('collection'):
        collection=next((c for c in row['collections'] if c['collection_id']==q['collection']),None)
        if collection is None:raise KeyError('Unknown collection')
        members=set(collection['product_ids']);catalog=[p for p in catalog if p['product_id'] in members]
    products=[p for p in catalog if (not category or p['category']==category) and words<=set(tokens(p['name']+' '+p['product_id']+' '+p['category']+' '+str(p['attributes'])))]
    products=display_products(owner,products)
    page=page_number(q);size=12;total=max(1,(len(products)+size-1)//size);page=min(page,total)
    body='<h1>Search results</h1>'+storefront.search_form(owner,site,q)
    body+=patterns.retailer_search(owner,site,products,q.get('q',''))
    body+='<section aria-label="Product results"><p>'+str(len(products))+' product listings</p>'+cards(owner,site,products[(page-1)*size:page*size])+pagination('/search',q,page,total)+'</section>'
    return shell(owner,site,'Search results',body)


def home_page(owner,site):
    from . import storefront
    if storefront.content(owner,site) is not None:return storefront.home(owner,site)
    products=display_products(owner,owner.catalog(site)['products'])
    families=list(dict.fromkeys(p['category'] for p in products))
    body='<h1>Welcome to '+e(owner.stores[site]['name'])+'</h1><section aria-label="Explore our collection"><h2>Find your next favourite</h2><p>Explore our collections and choose the options that suit you.</p>'+link('/search','Shop the collection')+'</section>'
    body+=layout._search_form(site,owner.origins,products,{},label='Search products')
    body+='<nav aria-label="Shop by category">'+''.join(link(query('/search',{'category':f}),f.replace('_',' ').title())+' ' for f in families)+'</nav>'
    for family in families:
        selected=[p for p in products if p['category']==family][:4]
        body+='<section aria-label="'+e(family.replace('_',' ').title())+' collection"><h2>Explore '+e(family.replace('_',' '))+'</h2>'+cards(owner,site,selected,force_cards=True)+link(query('/search',{'category':family}),'View the full collection')+'</section>'
    body+='<section><h2>Shopping with us</h2>'+link('/policy','Delivery and store information')+' · '+link('/branches','Find our stores')+'</section>'
    return shell(owner,site,owner.stores[site]['name'],body)


def page_number(q):
    s=q.get('page','1')
    if not s.isascii() or not s.isdigit() or not 1<=int(s)<=10000:raise ValueError('Invalid page')
    return int(s)


def pagination(path,q,page,total):
    out='<nav aria-label="Pagination"><span>Page '+str(page)+' of '+str(total)+'</span>'
    if page>1:out+=link(query(path,{**q,'page':page-1}),'Previous')
    if page<total:out+=link(query(path,{**q,'page':page+1}),'Next')
    return out+'</nav>'


def quantity(q):
    val=q.get('quantity','1')
    if not val.isascii() or not val.isdigit() or not 1<=int(val)<=100:raise ValueError('Invalid quantity')
    return int(val)


def product(owner,site,source_sku,q,details=False):
    if source_sku not in owner.products:raise KeyError('Unknown product')
    group=owner.group_for[source_sku]
    if group['group_id'] not in owner.groups_by_store[site]:raise KeyError('Model not carried by this store')
    allowed={'quantity'}|{'option_'+a['field'] for a in group['axes']}
    if set(q)-allowed:raise ValueError('Unknown selection field')
    selection={a['field']:q.get('option_'+a['field'],'') for a in group['axes']} if any(k.startswith('option_') for k in q) else None
    state=controls.resolve(group,source_sku,selection);sku=state['product_id'];n=quantity(q)
    styles={a['field']:('radio' if a['field']=='colour' and owner.designs[site]=='editorial-boutique' else 'select') for a in group['axes']}
    form='<form method="get" action="'+path_product(source_sku)+'">'+controls.render_controls(group,state,styles)+'<label>Quantity<input type="number" name="quantity" min="1" max="100" value="'+str(n)+'"></label><button>Update selection</button></form>'
    body='<nav aria-label="Breadcrumbs">'+link('/','Home')+' / '+link('/search','Products')+'</nav><h1>'+e(group['name'])+'</h1>'+form
    if not sku:
        body+='<p role="status">'+('Choose all product options.' if state['status']=='incomplete' else 'This combination has no catalogued SKU.')+'</p>'
        return shell(owner,site,group['name'],body)
    p=owner.products[sku];offer=owner.offer_by_store.get((site,sku))
    body+='<h2>'+e(p['name'])+'</h2><p>SKU: <strong id="selected-sku">'+e(sku)+'</strong></p>'+dense.gallery(p,2)
    if offer:
        body+='<section aria-label="Offer"><h2>Price and availability</h2><p class="price">'+money(offer['price_minor'])+' per unit</p><p>Online warehouse stock: '+str(offer['stock_quantity'])+'</p>'
        body+=link(query('/quote',{'offer_id':offer['offer_id'],'quantity':n,'method':'delivery'}),'Check delivery total and arrival')+' · '+link('/branches','Find pickup and inspection locations')+'</section>'
        if patterns.options(owner,site).get('shipping_disclosure')!='separate' and not patterns.needs_destination(owner,site):
            body+=quote_block(owner,offer['offer_id'],n,'delivery',None)
        from .stock import store_stock
        body+=store_stock(owner,offer,n)
    else:body+='<p role="status">This exact SKU exists, but this store does not list it. Change options to check another variant.</p>'
    if owner.designs[site]=='editorial-boutique' and not details and not patterns.options(owner,site):body+=link(path_product(sku)+'/details','Read full product details')
    else:body+='<details'+('' if patterns.options(owner,site).get('specification_disclosure')=='expand' else ' open')+'><summary>Product specifications</summary>'+table(p)+'</details>'
    body+='<section><h2>Other products at this store</h2>'+cards(owner,site,related_products(owner,site,sku,limit=patterns.options(owner,site).get('related_limit',8)))+'</section>'
    if details:body+=link(path_product(sku),'Back to product')
    return shell(owner,site,p['name'],body,sku)


def quote_block(owner,offer_id,n,method,branch_id,coupon_code=None,destination_query=None):
    site=owner.offers[offer_id]['retailer_id']
    if method=='delivery' and not patterns.destination_valid(owner,site,destination_query or {}):
        return '<p role="status">Enter your delivery postcode to check charges, availability and arrival. This address has no delivery quote yet.</p>'
    kwargs={'coupon_code':coupon_code} if coupon_code else {}
    q=owner.quote(offer_id,quantity=n,method=method,branch_id=branch_id,**kwargs);offer=owner.offers[offer_id]
    p=owner.products[offer['product_id']];location=owner.locations['public']['user_location']
    body='<section id="offer-quote" data-offer-id="'+e(offer_id)+'"><h2>'+({'delivery':'Delivery quote','pickup':'Pickup quote','inspect':'Inspection availability'}[method])+'</h2><p>'+e(p['name'])+' · '+str(n)+' unit(s)</p><p>Destination: '+e(location['city'])+', '+e(location['country'])+'</p>'
    body+='<p>Availability: <strong>'+('Available' if q['eligible'] else 'Unavailable')+'</strong></p>'
    if q['reason_codes']:body+='<ul>'+''.join('<li>'+e(x.replace('_',' '))+'</li>' for x in q['reason_codes'])+'</ul>'
    if method!='inspect':body+='<dl><dt>Item subtotal</dt><dd>'+money(offer['price_minor']*n)+'</dd><dt>Shipping / collection charge</dt><dd id="shipping-total">'+money(q['shipping_minor'])+'</dd><dt>Total including mandatory charges</dt><dd id="delivered-total">'+money(q['total_minor'])+'</dd></dl>'
    if coupon_code:body+='<p>Coupon entered: '+e(coupon_code)+'</p><p id="coupon-discount">Item discount: '+money(q.get('discount_minor',0))+'</p><p>Coupons are checked for this quote only; no coupon has been redeemed.</p>'
    body+='<p id="arrival-days">'+('No arrival/ready estimate available.' if q['ready_days'] is None else 'Ready in '+str(q['ready_days'])+' calendar days after ordering.')+'</p>'
    if q['requires_stock_transfer']:body+='<p>Warehouse transfer is required before collection.</p>'
    if branch_id:
        branch=next(b for b in owner.merchants[offer['retailer_id']]['branches'] if b['branch_id']==branch_id)
        body+='<p>Branch: '+e(branch['name'])+'</p>'+link(owner.travel_url+'/journey?'+urlencode({'from':'home','to':branch_id,'mode':'driving'}),'Plan a journey to this branch')
    else:
        from .stock import source_location
        origin=source_location(owner,offer,q.get('stock_source'))
        if q['eligible'] and origin:body+='<p>Ships from '+e(origin['city'])+', '+e(origin['country'])+'. Check the total and arrival estimate above for your destination.</p>'
        if q.get('dispatch_policy'):body+='<p>Delivery source is selected by fastest arrival, then lowest delivered total. One source must cover the full quantity.</p>'
    return body+'</section>'


def quote_page(owner,site,q):
    if set(q)-({'offer_id','quantity','method','branch_id','coupon_code'}|({'destination_country','postcode','postcode_1','postcode_2'} if patterns.needs_destination(owner,site) else set())):raise ValueError('Unknown quote field')
    offer=owner.offers.get(q.get('offer_id'))
    if not offer or offer['retailer_id']!=site:raise KeyError('Offer not at this store')
    method=q.get('method','delivery');bid=q.get('branch_id') or None;n=quantity(q)
    if method not in ('delivery','pickup','inspect'):raise ValueError('Unknown method')
    if method=='delivery' and bid:raise ValueError('Delivery has no pickup branch')
    branches=owner.merchants[site]['branches'];body='<h1>Check fulfillment</h1>'+link(path_product(offer['product_id']),'Return to product')
    body+='<form action="/quote"><input type="hidden" name="offer_id" value="'+e(offer['offer_id'])+'"><label>Quantity<input type="number" name="quantity" min="1" max="100" value="'+str(n)+'"></label><label>Method<select name="method">'+''.join('<option value="'+m+'"'+(' selected' if m==method else '')+'>'+label+'</option>' for m,label in [('delivery','Home delivery'),('pickup','Pickup'),('inspect','Inspect in store')])+'</select></label><label>Branch<select name="branch_id"><option value="">No branch (home delivery)</option>'+''.join('<option value="'+e(b['branch_id'])+'"'+(' selected' if b['branch_id']==bid else '')+'>'+e(b['name'])+'</option>' for b in branches)+'</select></label><button>Calculate quote</button></form>'
    if method=='delivery':
        body=body.replace('<button>Calculate quote</button>',patterns.destination_form(owner,site,q)+'<button>Calculate quote</button>')
        if patterns.needs_destination(owner,site) and any(q.get(k) for k in ('postcode','postcode_1','postcode_2')) and not patterns.destination_valid(owner,site,q):
            body+='<p role="alert">No delivery quote is modelled for that address. Check the country and all postcode fields.</p>'
    if getattr(owner,'account_pages',None):
        coupon='<label>Coupon code<input name="coupon_code" value="'+e(q.get('coupon_code',''))+'" maxlength="100"></label>'
        body=body.replace('<button>Calculate quote</button>',coupon+'<button>Calculate quote</button>')
        body+=link('/account/coupons','View your available coupons')
    if method!='delivery' and not bid:body+='<p>Select a branch for pickup or inspection.</p>'
    else:body+=quote_block(owner,offer['offer_id'],n,method,bid,q.get('coupon_code') or None,destination_query=q)
    return shell(owner,site,'Fulfillment quote',body,offer['product_id'])


def branches(owner,site):
    body='<h1>Stores and pickup locations</h1>'
    for b in owner.merchants[site]['branches']:
        body+='<article><h2>'+e(b['name'])+'</h2><p>'+e(b['location']['city'])+', '+e(b['location']['country'])+'</p><p>'+('Pickup available' if b['pickup_enabled'] else 'Pickup unavailable')+'</p>'+link(owner.travel_url+'/journey?'+urlencode({'from':'home','to':b['branch_id'],'mode':'driving'}),'Directions to '+b['name'])+'</article>'
    if not owner.merchants[site]['branches']:body+='<p>This retailer has no physical branches.</p>'
    return shell(owner,site,'Locations',body)


def policy(owner,site):
    m=owner.merchants[site];p=m['fulfilment_policy'];body='<h1>Delivery and store information</h1><p>Warehouse: '+e(m['warehouse']['city'])+', '+e(m['warehouse']['country'])+'</p><p>Delivery countries: '+e(', '.join(p['delivery_countries']))+'</p><p>Delivery charges and time depend on the selected product, quantity and destination. Use the product quote for the complete total.</p><p>Times are calendar days after ordering. Opening-hour schedules are not provided.</p>'+link('/branches','Our branches and pickup locations')
    return shell(owner,site,'Delivery information',body)


def aggregator(owner,path,q):
    if getattr(owner,'interaction_patterns',None) is not None:
        from .comparison_designs import Design
        # Explicit opt-in also upgrades the legacy single comparator to the
        # existing full comparison renderer; canonical membership is unchanged.
        if path.startswith('/products/'):
            p=owner.products.get(path.split('/')[-1])
            if p and p['category']=='footwear':path='/models/'+owner.group_for[p['product_id']]['group_id']
        return Design(owner).render(path,q)[1]
    if set(q)-{'q','category','page'}:raise ValueError('Unknown search field')
    words=set(tokens(q.get('q','')));products=[p for p in owner.comparisons if words<=set(tokens(p['name']+' '+p['id']+' '+str(p['attributes']))) and (not q.get('category') or q['category']==p['category'])]
    form='<form action="/search"><label>Search products<input type="search" name="q" value="'+e(q.get('q',''))+'"></label><label>Category<select name="category"><option value="">All categories</option>'+''.join('<option value="'+e(f)+'"'+(' selected' if f==q.get('category') else '')+'>'+e(f.replace('_',' '))+'</option>' for f in owner.families)+'</select></label><button>Search</button></form>'
    body='<h1>Prislyktan</h1><p>Compare footwear models and other product configurations. Choose shoe size and colour at the retailer; check the selected price, availability and delivery there.</p>'+form
    model=None
    if path.startswith('/models/') and path.count('/')==2:
        model=owner.comparison_by_id.get(path.split('/')[-1])
        if not model or model['kind']!='model':raise KeyError('Unknown model')
    elif path.startswith('/products/') and path.count('/')==2:
        alias=owner.products.get(path.split('/')[-1])
        if alias and alias['category']=='footwear':model=owner.comparison_by_id[owner.group_for[alias['product_id']]['group_id']]
    if model:
        body+='<h2>'+e(model['name'])+'</h2>'+table(model)
        body+='<p>Choose size, fit and colour at the retailer. Listed prices exclude delivery; selected options can change the price. Stock must be checked at the store.</p>'
        label='Advertised item price' if model['price_basis']=='advertised' else 'From price (listed options)'
        body+='<table id="model-listings"><caption>Retailer listings — '+label.lower()+'</caption><thead><tr><th>Retailer</th><th>'+label+'</th><th>Product page</th></tr></thead><tbody>'
        for row in sorted(model['listings'],key=lambda r:(r['advertised_price_minor'],r['retailer_id'])):
            sid=row['retailer_id'];body+='<tr><td>'+e(owner.stores[sid]['name'])+'</td><td>'+money(row['advertised_price_minor'])+'</td><td>'+link(owner.origins[sid]+path_product(row['entry_product_id']),'View offer at '+owner.stores[sid]['name'])+'</td></tr>'
        body+='</tbody></table>'
        if not model['listings']:body+='<p>No retailer currently lists this model.</p>'
        body+=link(owner.origins['reviews-footwear']+'/reviews/'+model['id'],'Independent product review')
    elif path.startswith('/products/') and path.count('/')==2:
        sku=path.split('/')[-1]
        if sku not in owner.products:raise KeyError('Unknown product')
        p=owner.products[sku];body+='<h2>'+e(p['name'])+'</h2><p>SKU: '+e(sku)+'</p>'+table(p)+'<table><caption>Retailer listings — item prices exclude delivery</caption><thead><tr><th>Retailer</th><th>Item price</th><th>Product page</th></tr></thead><tbody>'
        offers=[o for o in owner.offers.values() if o['product_id']==sku]
        for o in sorted(offers,key=lambda o:(o['price_minor'],o['offer_id'])):
            body+='<tr><td>'+e(owner.stores[o['retailer_id']]['name'])+'</td><td>'+money(o['price_minor'])+'</td><td>'+link(owner.origins[o['retailer_id']]+path_product(sku),'View offer at '+owner.stores[o['retailer_id']]['name'])+'</td></tr>'
        body+='</tbody></table>'
        if not offers:body+='<p>No retailer currently lists this exact option.</p>'
        group=owner.group_for[sku];body+='<h2>Other product options</h2><ul>'+''.join('<li>'+link(path_product(v['product_id']),owner.products[v['product_id']]['name'])+'</li>' for v in group['variants'] if v['product_id']!=sku)+'</ul>'+connections(owner,'aggregator',sku)
    elif path in ('/','/search'):
        page=page_number(q);total=max(1,(len(products)+11)//12);page=min(page,total)
        body+='<p>'+str(len(products))+' comparison products</p>'+''.join('<article><h2>'+link(p['path'],p['name'])+'</h2><p>'+e(p['category'].replace('_',' '))+'</p></article>' for p in products[(page-1)*12:page*12])+pagination('/search',q,page,total)
    else:raise KeyError('Unknown page')
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Prislyktan</title>'+STYLE+'</head><body><header>'+link('/','Prislyktan')+' · '+link(owner.index_origin,'Search the web')+'</header><main>'+body+'</main></body></html>'
