"""Within-family structural choices for the department storefront.

No random DOM noise or commercial calculations. Other families deliberately reject
these settings until they implement their own appropriate realizations.
"""
CHOICES={
    'navigation_structure':('standard','flat','disclosure'),
    'result_structure':('cards','table'),
    'product_structure':('split','details-first'),
    'fact_structure':('table','definitions'),
    'delivery_control':('select','radio'),
}
DEFAULTS={key:values[0] for key,values in CHOICES.items()}
BASE={'nav_expanded':True,'image_count':2,'title_style':'short','details_presentation':'inline',**DEFAULTS,'navigation_structure':'flat'}
CONTRAST={**BASE,'navigation_structure':'disclosure','result_structure':'table','product_structure':'details-first','fact_structure':'definitions','details_presentation':'disclosure','delivery_control':'radio'}


def validate(design, options):
    for key,values in CHOICES.items():
        if key in options:
            if design!='department-market':raise ValueError(f'{key} is not yet supported by {design}')
            if options[key] not in values:raise ValueError(f'Invalid {key}')


def facts(product):
    from . import retailer_designs as r
    rows=[('Product ID',product.get('product_id')),('Category',r._label(product.get('category'))),*[(r._label(k),v) for k,v in r._attrs(product)]]
    traits=r._traits(product)
    if traits:rows.append(('Traits',', '.join(traits)))
    return '<dl class="product-facts">'+''.join(f'<dt>{r._esc(k)}</dt><dd>{r._esc(v)}</dd>' for k,v in rows)+'</dl>'


def navigation(site,origins,products,mode):
    from . import retailer_designs as r
    groups=[]
    for category in r._categories(products):
        link=f'<a href="{r._href(origins,site,"/search",{"category":category})}">Browse {r._esc(r._label(category))}</a>'
        if mode=='flat':
            groups.append('<li>'+link+'</li>');continue
        children=''.join(f'<li><a href="{r._href(origins,site,r._product_path(p["product_id"]))}">{r._esc(p["name"])}</a></li>' for p in products if p.get('category')==category)
        groups.append(f'<li><details><summary>{r._esc(r._label(category))}</summary>{link}<ul>{children}</ul></details></li>')
    return '<nav aria-label="Departments"><h2>Departments</h2><ul>'+''.join(groups)+'</ul></nav>'


def result_table(site,origins,shown,offers,options):
    from . import retailer_designs as r
    rows=[]
    for product in shown:
        offer=offers.get(r._text(product.get('product_id')), {})
        rows.append(f'<tr><td>{r._figure(product,1)}</td><th scope="row"><a href="{r._href(origins,site,r._product_path(product["product_id"]))}">{r._esc(r._title(product,options["title_style"]))}</a></th><td>{r._esc(r._label(product.get("category")))}</td><td>{r._esc(r._legacy()._minor(offer.get("price_minor")))}</td></tr>')
    return '<table class="result-table"><caption>Compare matching products</caption><thead><tr><th>Image</th><th>Product</th><th>Department</th><th>Price</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table>'


def product_page(site,origins,catalog,context,product,offer,options,figures,description,notice):
    from . import retailer_designs as r
    return (f'<main id="main-content" class="department-detail-first">{notice}<article><header><p>{r._esc(r._label(product.get("category")))}</p><h2>{r._esc(r._title(product,options["title_style"]))}</h2></header>'
            f'<div class="product-gallery">{figures}</div>{description}'
            f'<section aria-labelledby="purchase-heading"><h2 id="purchase-heading">Purchase options</h2><p class="price">{r._esc(r._legacy()._minor(offer.get("price_minor")))}</p><p>Offer ID: {r._esc(offer.get("offer_id"))}</p><p>Dispatch: {r._esc(offer.get("dispatch_days"))} day(s).</p>'
            +r._purchase_form(site,origins,offer,grouped=True,catalog=catalog,context=context,delivery_control=options['delivery_control'])
            +r._quote_link(site,origins,offer)+'</section></article>'+r._recommendations(site,origins,catalog,product)+'</main>')
