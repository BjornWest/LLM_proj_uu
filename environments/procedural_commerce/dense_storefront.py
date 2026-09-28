"""Broad catalog shell and dense product regions, consuming only public facts.

No new price/stock/cart semantics. Every recommendation is merchant-listed and
links to an existing product route. UI disclosure/gallery state is local only.
"""
from math import ceil
from . import retailer_designs as h
from .cart_interaction import cart_label, product_feedback

STYLE = """<style>
*{box-sizing:border-box}body{margin:0;color:#20262d;background:white;font:16px/1.5 system-ui}a{color:#174e68}button,input,select{font:inherit;padding:.6rem}button{cursor:pointer}header,main,footer,.surround{padding:1.2rem max(1rem,4vw)}header{border-bottom:1px solid #ccc;background:#f5f6f7}.utility,.topline,.section-links ul,.breadcrumbs ol{display:flex;gap:1.2rem;align-items:center;flex-wrap:wrap}.topline{justify-content:space-between}.brand{font-size:1.65rem;font-weight:bold}.utility ul,.section-links ul,.breadcrumbs ol{list-style:none;padding:0}.search-form{display:flex;gap:.8rem;align-items:end;flex-wrap:wrap}.search-form label,.purchase-form label{display:grid;gap:.3rem}.department-grid,.footer-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:1rem}.department-grid ul,.footer-grid ul{padding-left:1.2rem}.hero{display:grid;grid-template-columns:minmax(0,1fr) minmax(300px,42%);gap:2rem}.hero h1{font-size:1.8rem}.gallery{background:#f8f7f3;padding:1rem}.gallery figure{margin:0}.gallery img{width:100%;max-height:360px;object-fit:contain}.gallery-controls{display:flex;gap:.5rem;margin-top:1rem}.gallery button[aria-pressed=true]{outline:2px solid #174e68}.buy-box{padding:1rem;border:1px solid #c6cdd1}.purchase-form{display:grid;gap:1rem}.purchase-form fieldset{display:flex;gap:1rem;flex-wrap:wrap}.purchase-actions button{background:#174e68;color:white;border:0}.price{font-size:1.4rem;font-weight:bold}.section-links{position:relative;border-block:1px solid #ccc;margin:2rem 0}.information{max-width:65rem}.information details{border-bottom:1px solid #ccc;padding:1rem 0}summary{cursor:pointer;font-weight:650}table{border-collapse:collapse;width:100%}th,td{padding:.7rem;border:1px solid #ccc;text-align:left}dl{display:grid;grid-template-columns:minmax(120px,1fr) 2fr;gap:.5rem}dd{margin:0}.product-cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1.2rem;padding:0;list-style:none}.product-card{border:1px solid #ddd;padding:1rem;min-width:0}.product-card img{width:100%;height:120px;object-fit:contain}.product-card h3{font-size:1rem}.product-card .price{font-size:1.1rem}.product-card ul{padding-left:1rem}.surround{background:#fafafa}.surround section+section{margin-top:2rem}footer{background:#eef1f2;margin-top:2rem}.notice,[role=alert]{border-left:4px solid #a86500;padding:.7rem}.skip{position:absolute;left:-9999px}.skip:focus{left:1rem;z-index:10;background:white}.pagination{display:flex;gap:1rem;margin:1rem 0}[hidden]{display:none!important}@media(max-width:850px){.hero{grid-template-columns:1fr}.product-cards{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:450px){.product-cards{grid-template-columns:1fr}}
</style>"""


def listed(catalog):
    offers = h._offers(catalog)
    return [p for p in h._products(catalog) if p.get('product_id') in offers]


def document(site, origins, catalog, title, main, options):
    products = listed(catalog)
    def link(path, text, params=None):
        return f'<a href="{h._href(origins,site,path,params)}">{h._esc(text)}</a>'
    departments = []
    for category in ([] if catalog.get('storefront_links') else h._categories(products)):
        examples = [p for p in products if p.get('category') == category][:4]
        departments.append('<section><h3>' + link('/search',h._label(category),{'category':category}) + '</h3><ul>' + ''.join('<li>'+link(h._product_path(p['product_id']),p['name'])+'</li>' for p in examples) + '</ul></section>')
    open_attr = ' open' if options['nav_expanded'] else ''
    name = catalog.get('retailer',{}).get('name',site)
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{h._esc(title)} · {h._esc(name)}</title>{STYLE}</head><body>'
        '<a class="skip" href="#main-content">Skip to product or catalog</a>'
        '<header><nav class="utility" aria-label="Store services">' + link('/policy','Delivery and returns') + ' · ' + link('/search','Browse all products') + '</nav>'
        '<div class="topline"><p class="brand">'+link('/',name)+'</p>'
        + (catalog.get('storefront_search_form') or h._search_form(site,origins,products,{},label='Search the store'))
        + f'<a href="{h._href(origins,site,"/cart")}">{cart_label(catalog,"Shopping bag")}</a></div>'
        + (f'<details{open_attr}><summary>Shop by category</summary>'+h._storefront_navigation(catalog)+'</details>' if catalog.get('storefront_links') else f'<details{open_attr}><summary>Shop by department</summary><nav aria-label="Departments" class="department-grid">'+''.join(departments)+'</nav></details>')+'</header>'
        + main
        + '<footer><h2>Explore the store</h2><div class="footer-grid"><nav aria-label="All departments"><h3>Departments</h3><ul>'
        + (''.join('<li>'+link(r['href'],r['title'])+'</li>' for r in catalog['storefront_links']) if catalog.get('storefront_links') else ''.join('<li>'+link('/search',h._label(c),{'category':c})+'</li>' for c in h._categories(products)))
        + '</ul></nav><nav aria-label="Shopping help"><h3>Your shopping</h3><ul><li>'+link('/cart','Review your bag')+'</li><li>'+link('/policy','Delivery, returns and warranty')+'</li><li>'+link('/search','Find another product')+'</li></ul></nav>'
        + f'<section><h3>Prices and availability</h3><p>Prices in {h._esc(catalog.get("currency"))}. Delivery charges depend on your order and selected method.</p><p>Check the complete quote before ordering.</p></section></div>{h._service_links(catalog)}</footer></body></html>')


def cards(site,origins,catalog,products):
    offers=h._offers(catalog);items=[]
    for p in products:
        o=offers.get(p['product_id'])
        if o is None:continue
        url=h._href(origins,site,h._product_path(p['product_id']))
        facts=''.join(f'<li>{h._esc(h._label(k))}: {h._esc(v)}</li>' for k,v in h._attrs(p)[:3])
        items.append(f'<li class="product-card"><article><a href="{url}"><img loading="lazy" src="{h._svg_src(1)}" alt="{h._esc(p["name"])} — catalog illustration"></a><p>{h._esc(h._label(p.get("category")))}</p><h3><a href="{url}">{h._esc(p["name"])}</a></h3><p class="price">{h._esc(h._legacy()._minor(o.get("price_minor")))}</p><ul>{facts}</ul><p>{"In stock" if o.get("stock_quantity",0)>0 else "Out of stock"}</p><a href="{url}">View product</a></article></li>')
    return '<ul class="product-cards">'+''.join(items)+'</ul>' if items else '<p>No other listed products in this section.</p>'


def gallery(product,count):
    # Native radio/CSS state works under the runtime's no-script CSP.
    figures=''.join(f'<div data-gallery-panel="{i}">{h._figure(product,i)}</div>' for i in range(1,count+1))
    controls=''.join(f'<label><input type="radio" name="gallery-view" value="{i}"{" checked" if i==1 else ""}>View {i}</label>' for i in range(1,count+1))
    rules=''.join(f'.gallery:has(input[value="{i}"]:checked) [data-gallery-panel="{i}"]{{display:block}}' for i in range(1,count+1))
    return ('<section class="gallery" aria-label="Product images"><style>.gallery [data-gallery-panel]{display:none}'+rules+'</style><fieldset class="gallery-controls"><legend>Choose product image</legend>'+controls+'</fieldset>'+figures+'<p>Illustrative catalog artwork.</p></section>')


def policy(catalog):
    retailer=catalog.get('retailer',{});summary=retailer.get('policy_summary',{})
    methods=retailer.get('shipping_methods',{})
    rows=[]
    for name,m in methods.items():
        threshold=m.get('free_shipping_threshold_minor')
        free=f'Free from {h._legacy()._minor(threshold)}' if threshold is not None else 'No free-shipping threshold'
        rows.append(f'<tr><th scope="row">{h._esc(h._label(name))}</th><td>{h._esc(h._legacy()._minor(m.get("base_price_minor")))}</td><td>{h._esc(m.get("transit_days"))} transit day(s), plus dispatch</td><td>{h._esc(free)}</td></tr>')
    return ('<details id="delivery-information"><summary>Delivery options and costs</summary><p>Base delivery rates; the complete quote checks your destination and order.</p><table><caption>Available delivery methods</caption><thead><tr><th>Method</th><th>Base price</th><th>Transit time</th><th>Free delivery</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></details>'
        + '<details id="returns-information"><summary>Returns and warranty</summary><dl>'
        + ''.join(f'<dt>{label}</dt><dd>{h._esc(summary[key])}{unit}</dd>' for key,label,unit in [('returns_days','Return period',' days'),('return_shipping_paid_by','Return shipping paid by',''),('warranty_years','Listed warranty period',' years')] if summary.get(key) is not None)
        + '</dl><p>These are the store’s listed policy summaries, not a separate paid protection plan.</p></details>')


def purchase(site,origins,catalog,context,offer):
    if not context.get('product_selection') and offer.get('stock_quantity',0)<=0:
        return '<p role="status">This product is currently out of stock.</p>'+product_feedback(catalog,context.get('cart'),context.get('error'))
    form=h._purchase_form(site,origins,offer,grouped=False,catalog=catalog,context=context)
    stock=offer.get('stock_quantity',0)
    if stock>0:
        form=form.replace('name="quantity" min="1"','name="quantity" min="1" max="'+str(stock)+'"',1)
    return form


def product_page(site,origins,catalog,context,product_id,options,details_only=False):
    product=h._product(catalog,product_id);offer=h._offers(catalog).get(product_id)
    if product is None or offer is None:
        return document(site,origins,catalog,'Product unavailable','<main id="main-content"><h1>Product unavailable at this store</h1></main>',options)
    selection=context.get('product_selection')
    if selection:
        if selection['product_id']:
            product=h._product(catalog,selection['product_id']);offer=h._offers(catalog).get(selection['product_id'])
            if product is None or offer is None:
                return document(site,origins,catalog,'Product unavailable','<main id="main-content"><h1>Selected product unavailable at this store</h1></main>',options)
        else:
            product={'product_id':selection['group']['group_id'],'name':selection['group']['name'],'category':selection['group']['family'],'attributes':{},'traits':[]}
            offer={'price_minor':None,'stock_quantity':0}
    category=product.get('category','');url=h._href(origins,site,h._product_path(product_id))
    breadcrumbs=f'<nav class="breadcrumbs" aria-label="Breadcrumbs"><ol><li><a href="{h._href(origins,site,"/")}">Home</a></li><li><a href="{h._href(origins,site,"/search",{"category":category})}">{h._esc(h._label(category))}</a></li><li>{h._esc(product["name"])}</li></ol></nav>'
    facts=h._fact_table(product)
    if details_only:
        return document(site,origins,catalog,product['name'],f'<main id="main-content">{breadcrumbs}<h1>Full product information</h1>{facts}<a href="{url}">Back to product</a></main>',options)
    price=h._esc(h._legacy()._minor(offer.get('price_minor'))) if offer.get('offer_id') else 'Choose an available combination'
    info=(f'<section class="information" aria-labelledby="information-heading"><h2 id="information-heading">Product information</h2><details open><summary>About this product</summary><p>{h._esc(product["name"])} is listed in {h._esc(h._label(category))}.</p><ul>'
          + ''.join(f'<li>{h._esc(h._label(k))}: {h._esc(v)}</li>' for k,v in h._attrs(product))
          + '</ul></details><details id="specifications"><summary>Specifications and product identity</summary>'+facts+'</details>'+policy(catalog)+'</section>')
    main=(f'<main id="main-content">{breadcrumbs}<div class="hero">{gallery(product,options["image_count"])}<section class="buy-box" aria-labelledby="product-title"><p>{h._esc(h._label(category))}</p><h1 id="product-title">{h._esc(h._title(product,options["title_style"]))}</h1><p class="price">{price}</p>'
        + (f'<p>Dispatch in {h._esc(offer.get("dispatch_days"))} day(s); delivery transit is additional.</p>' if offer.get('offer_id') else '')
        + h._cart_notice(site,origins,catalog,context,product_id)
        + purchase(site,origins,catalog,context,offer)
        + h._quote_link(site,origins,offer)+'</section></div>'
        + '<nav class="section-links" aria-label="Product sections"><ul><li><a href="#information-heading">Product information</a></li><li><a href="#delivery-information">Delivery</a></li><li><a href="#returns-information">Returns and warranty</a></li><li><a href="#related-heading">Other products</a></li></ul></nav>'+info+'</main>')
    peers=[p for p in listed(catalog) if p['product_id'] != product['product_id'] and p.get('category')==category][:8]
    others=[p for p in listed(catalog) if p.get('category')!=category][:16]
    surroundings='<aside class="surround" aria-labelledby="related-heading"><h2 id="related-heading">More in '+h._esc(h._label(category))+'</h2>'+cards(site,origins,catalog,peers)+'</aside><section class="surround" aria-labelledby="other-heading"><h2 id="other-heading">Explore other departments</h2>'+cards(site,origins,catalog,others)+'</section>'
    return document(site,origins,catalog,product['name'],main+surroundings,options)


def render(site,path,query,context,origins,options):
    catalog=context.get('catalog',{});parts=path.strip('/').split('/')
    if len(parts) in (2,3) and parts[0]=='products' and (len(parts)==2 or parts[2]=='details'):
        from .product_controls import page_selection
        submitted={k[7:]:v for k,v in query.items() if k.startswith('option_')}
        selection=page_selection(catalog,parts[1],submitted if submitted else None)
        return product_page(site,origins,catalog,{**context,'product_selection':selection},parts[1],options,len(parts)==3)
    if path not in ('/','/search'):return None
    products=listed(catalog)
    if path=='/':
        sections=''.join(f'<section aria-labelledby="category-{i}"><h2 id="category-{i}">{h._esc(h._label(c))}</h2>'+cards(site,origins,catalog,[p for p in products if p.get('category')==c][:4])+f'<a href="{h._href(origins,site,"/search",{"category":c})}">All {h._esc(h._label(c))} products</a></section>' for i,c in enumerate(h._categories(products)))
        body='<main id="main-content"><h1>Find something for your everyday</h1><p>Explore our departments or search the catalog above.</p>'+sections+'</main>'
        return document(site,origins,catalog,'Shop the catalog',body,options)
    matches=h._matching(products,query);page=min(h._legacy()._page(query),max(1,ceil(len(matches)/12)))
    body=f'<main id="main-content"><h1>Search results</h1><p>{len(matches)} products found</p>'+h._search_form(site,origins,products,query,label='Refine your search')+cards(site,origins,catalog,matches[(page-1)*12:page*12])+h._pagination(site,origins,query,len(matches))+'</main>'
    return document(site,origins,catalog,'Search results',body,options)
