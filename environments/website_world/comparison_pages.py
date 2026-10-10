"""Four reused comparison body structures over explicit public view records.

Ported from connected_shopping comparison_designs/comparison_alternatives.
No legacy world conversion, quotation, stock feed or task access occurs here.
Header/footer and role choices are site-wide, independently sampled upstream.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode
import re
from .surrounding_pages import e, link, pretty, path, products_with_optional_facts

VERSION = 'public-comparison-pages-v2'
LAYOUTS = ('directory','ledger','specialist','finder')
STYLE = '''<style>body{margin:0;font:16px/1.55 system-ui;color:#21363e;background:#f6f8f8}a{color:#006a76}header,footer{padding:22px 5%;background:white}main{max-width:1250px;margin:auto;padding:25px}nav{display:flex;gap:18px;flex-wrap:wrap}input,select,button{font:inherit;padding:8px;max-width:100%;box-sizing:border-box}label{display:block;margin:8px 0}fieldset,details{border:1px solid #ccd;padding:12px;margin:12px 0}aside{background:white;padding:18px;align-self:start}.columns,.ledger-shell{display:grid;grid-template-columns:250px minmax(0,1fr);gap:25px}.finder-search{display:grid;grid-template-columns:minmax(0,1fr) 270px;gap:25px}.cards,.collections,.retailer-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(225px,1fr));gap:15px}.cards article,.offer,.hero{background:white;padding:18px;border:1px solid #dde}dl{display:grid;grid-template-columns:1fr 1fr;gap:6px}dt{font-weight:bold}dd{margin:0}.wide{overflow:auto}table{border-collapse:collapse;width:100%;background:white}td,th{padding:12px;border-bottom:1px solid #ccd;vertical-align:top;text-align:left}caption{font-weight:bold;text-align:left}section{margin:25px 0}.price{font-size:1.35rem;font-weight:bold}.refinements{display:flex;flex-wrap:wrap;gap:15px}.note{padding:12px;background:#e7eeee}small{display:block}.catalogue>li{padding:15px;background:white;margin:12px 0}summary{cursor:pointer}@media(max-width:650px){.columns,.ledger-shell,.finder-search{grid-template-columns:minmax(0,1fr)}main{padding:12px}dl{grid-template-columns:1fr}}</style>'''


def money(value):
    if value is None:return 'No tracked price'
    if type(value) is not int or value<0:raise ValueError('Expected integer SEK minor units')
    return f'{value//100}.{value%100:02d} SEK'


def field_info(family,key):
    # Display labels only, never substitute new semantic predicate names.
    return key.replace('_',' ').capitalize(),None


def fact(item,key):return pretty(item['attributes'][key])


def spec_table(item):
    if not item['attributes']:return ''
    return '<table><caption>Product details</caption><tbody>'+''.join(
        '<tr><th scope="row">'+e(field_info(item['category'],k)[0])+'</th><td>'+e(fact(item,k))+'</td></tr>'
        for k in item['attributes'])+'</tbody></table>'


def tokens(value):return re.findall(r'[^\W_]+',value.casefold())


def page_number(q):
    try:value=int(q.get('page','1'))
    except (ValueError,TypeError) as exc:raise ValueError('Invalid result page') from exc
    if str(value)!=str(q.get('page','1')) or value<1:raise ValueError('Invalid result page')
    return value


def pagination(route,q,current,total):
    return '<nav aria-label="Result pages">'+''.join(
        '<span aria-current="page">'+str(n)+'</span>' if n==current else link(route+'?'+urlencode({**q,'page':n}),str(n))
        for n in range(1,total+1))+'</nav>'


def editorial_result(design,item):
    url=design.review_url(item)
    return '<article><p>Customer experiences</p><h3>'+link(url,item['name'])+'</h3><p>Read attributed customer comments and product facts.</p></article>' if url else ''


def comparison_cards(design,items):return ''.join(design.card(x,i) for i,x in enumerate(items))


def comparison_options(design):return design.profile['permutations'].get('results',{})


def comparison_search(design,q):
    if not comparison_options(design).get('search_sections') or not q.get('q'):return ''
    items,_,_=design.filtered(q)
    body=''.join(editorial_result(design,x) for x in items[:2])
    return '<section aria-label="Customer reading"><h2>Related customer experiences</h2>'+body+'</section>' if body else ''


def comparison_offers(design,body):
    return '<details><summary>Show retailer offers</summary>'+body+'</details>' if design.profile['permutations'].get('product',{}).get('offer_disclosure')=='expand' else body


class Design:
    def __init__(self,site,items,retailer_names,index_origin,review_links,*,layout='directory'):
        self.site,self.profile=site,site['presentation']
        self.name,self.layout=site['name'],layout
        self.family=site['families'][0] if self.profile['scope']=='specialist' else None
        self.labels={**site['family_labels'],None:'Products'}
        self.families=list(site['families'])
        self.items=deepcopy(items);self.by_id={x['id']:x for x in self.items};self.by_path={x['path']:x for x in self.items}
        self.index_origin,self.review_links=index_origin,review_links
        self.stores={rid:{'name':name} for rid,name in retailer_names.items()}
        self.filter_config=self.profile['filters']
        self.discovery=None
        self.catalog_search=self.profile.get('catalog_search',True)
        if type(self.catalog_search) is not bool:raise ValueError('Catalog search must be a site-wide boolean')

    def offers(self,item):return item['listings']
    def price(self,item):return min((r['advertised_price_minor'] for r in self.offers(item)),default=None)
    def stock_text(self,item,row):return 'Stock not reported here — check your selected option at the retailer'
    def lowest_retailers(self,item):return sorted((r for r in self.offers(item) if r['advertised_price_minor']==self.price(item)),key=lambda r:r['retailer_id'])
    def retailer_url(self,row):return row['retailer_url']
    def merchant_review_link(self,rid):return ''  # This world has no native merchant-review corpus.
    def review_url(self,item):return self.review_links.get(item['id'])
    def review_link(self,item):
        url=self.review_url(item)
        return link(url,'Read attributed customer reviews') if url else ''
    def categories(self):return ''.join(link('/search?'+urlencode({'category':f}),self.labels[f]) for f in self.families)
    def about(self):
        return ('<h1>How comparison prices work</h1><p>Product and retailer coverage is partial. Missing here does not mean unavailable elsewhere.</p>'
            '<p>Listings are minimum listed native item-price snapshots for each model and retailer, dated '+e(self.site['as_of'])+'. '
            'Prices may cover different options and exclude checkout delivery charges. Select and verify the exact configuration, stock and final total at the retailer.</p>'
            '<p>Customer-review links refer to an attributed syndicated corpus. Repeated publication is not additional independent evidence.</p>')
    def document(self,title,body):
        nav=link('/','Home')+self.categories()+link('/about','How prices work')+self.discovery_link('Search other sites')
        if self.profile['navigation']=='disclosure':nav='<details><summary>Browse departments and services</summary><nav>'+nav+'</nav></details>'
        else:nav='<nav aria-label="Main navigation">'+nav+'</nav>'
        search='<form action="/search"><label>Search products<input type="search" name="q" placeholder="Product or model name"></label><button>Search</button></form>'
        if not self.catalog_search:search=''
        top=search+nav if self.profile['navigation']=='search-first' else nav+search
        foot='<footer><h2>Explore '+e(self.name)+'</h2><nav aria-label="Footer departments">'+self.categories()+'</nav><p>Item prices exclude delivery; the retailer confirms the selected option and final charges.</p><nav>'+link('/about','Sources and coverage')+self.discovery_link('More shopping websites')+'</nav></footer>'
        return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+e(title)+' — '+e(self.name)+'</title>'+STYLE+'</head><body><header>'+link('/',self.name)+top+'</header><main id="main">'+body+'</main>'+foot+'</body></html>'
    def discovery_link(self, text):
        return link(self.index_origin+'/', text) if self.index_origin else ''
    def discovery_section(self):return ''

    def specs(self,item,limit=None):
        rows=list(item['attributes'].items());rows=rows[:limit] if limit else rows
        if not rows:return ''
        return '<dl>'+''.join('<dt>'+e(field_info(item['category'],k)[0])+'</dt><dd>'+e(fact(item,k))+'</dd>' for k,v in rows)+'</dl>'

    def card(self,item,pick=None):
        price=self.price(item);rows=self.offers(item)
        check='' if pick is None else '<label><input type="checkbox" name="pick'+str(pick)+'" value="'+e(item['id'])+'">Compare '+e(item['name'])+'</label>'
        cheapest=self.lowest_retailers(item)
        where='<div class="lowest-retailers"><p>Lowest advertised at:</p><ul>'+''.join('<li>'+link(self.retailer_url(r),self.stores[r['retailer_id']]['name'])+'<small>'+e(self.stock_text(item,r))+'</small></li>' for r in cheapest)+'</ul></div>' if cheapest else ''
        return '<article><small>'+e(self.labels[item['category']])+'</small><h3>'+link(item['path'],item['name'])+'</h3>'+self.specs(item,3)+'<p class="price">'+('From '+money(price) if price is not None else 'No listed price')+'</p>'+where+'<p>'+str(len(rows))+' retailer'+('' if len(rows)==1 else 's')+'</p>'+link(item['path'],'Compare retailer prices')+check+'</article>'

    def facet_options(self,category):
        items=[x for x in self.items if x['category']==category];keys=self.filter_config['attributes'].get(category,[]) if self.filter_config is not None else []
        # Declared attributes can evolve without adding controls for unknown data.
        present={k for x in items for k in x['attributes']}
        keys=[k for k in keys if k in present]
        if not keys and self.filter_config is None:keys=sorted(present)[:4]
        options={k:sorted({str(x['attributes'][k]) for x in items if k in x['attributes']
            and x.get('attribute_status',{}).get(k) not in ('unknown','not_applicable')
            and str(x['attributes'][k]).casefold() not in ('not provided','not specified','unknown','not applicable')}) for k in keys}
        return {key:values for key,values in options.items() if values}

    def filtered(self,q):
        category=self.family or q.get('category','')
        if category and category not in self.families:raise ValueError('Unknown category')
        if self.family and q.get('category',self.family)!=self.family:raise ValueError('Outside specialist scope')
        facets=self.facet_options(category) if category else {}
        known={f'f_{k}_{i}':(k,v) for k,values in facets.items() for i,v in enumerate(values)}
        allowed={'category','page'}|set(known)
        if self.catalog_search:allowed.add('q')
        if self.filter_config is None or self.filter_config['price_ceiling']:allowed.add('max_price')
        if self.filter_config is None or self.filter_config['sorting']:allowed.add('sort')
        if set(q)-allowed:raise ValueError('Unknown or unavailable filter')
        wanted={}
        for key,(field,value) in known.items():
            if key in q:
                if q[key]!='1':raise ValueError('Invalid facet selection')
                wanted.setdefault(field,set()).add(value)
        words=set(tokens(q.get('q','')));items=[x for x in self.items if (not category or x['category']==category) and words<=set(tokens(x['name']+' '+x['id']+' '+str(x['attributes']))) and all(str(x['attributes'].get(k)) in values for k,values in wanted.items())]
        cap=q.get('max_price','')
        if cap:
            try:n=Decimal(cap)*100
            except InvalidOperation:raise ValueError('Invalid price')
            if not n.is_finite() or n<0 or n!=n.to_integral_value():raise ValueError('Invalid price')
            items=[x for x in items if self.price(x) is not None and self.price(x)<=int(n)]
        order=q.get('sort','name')
        if order not in ('name','price_asc','price_desc'):raise ValueError('Unknown sort')
        if order=='name':items.sort(key=lambda x:(x['name'],x['id']))
        else:items.sort(key=lambda x:(self.price(x) is None, (self.price(x) or 0)*(1 if order=='price_asc' else -1),x['id']))
        return items,category,facets

    def filters(self,q,category,facets):
        body='<form id="filters" action="/search"><h2>Refine products</h2>'
        if self.catalog_search:body+='<label>Product name<input name="q" value="'+e(q.get('q',''))+'"></label>'
        body+='<input type="hidden" name="category" value="'+e(category)+'"><p>Category: '+e(self.labels.get(category,'All categories'))+'</p>'
        if self.filter_config is None or self.filter_config['price_ceiling']:body+='<label>Maximum advertised price (SEK)<input type="number" min="0" step="0.01" name="max_price" value="'+e(q.get('max_price',''))+'"></label>'
        body+='<div class="refinements">'
        for k,values in facets.items():
            body+='<fieldset><legend>'+e(field_info(category,k)[0])+'</legend>'
            for i,value in enumerate(values):
                key=f'f_{k}_{i}';label={'True':'Yes','False':'No'}.get(value,value);unit=field_info(category,k)[1];label+=(' '+unit if unit else '')
                body+='<label><input type="checkbox" name="'+e(key)+'" value="1"'+(' checked' if key in q else '')+'>'+e(label)+'</label>'
            body+='</fieldset>'
        body+='</div>'
        if self.filter_config is None or self.filter_config['sorting']:body+='<label>Sort results<select name="sort">'+''.join('<option value="'+v+'"'+(' selected' if q.get('sort','name')==v else '')+'>'+label+'</option>' for v,label in [('name','Product name'),('price_asc','Lowest advertised price'),('price_desc','Highest advertised price')])+'</select></label>'
        body+='<button>Apply filters</button> '+link('/search'+('?category='+category if category else ''),'Clear filters')+'</form>'
        return body

    def home(self):
        body='<h1>'+('Compare products, prices and retailers' if not self.family else 'Find your next '+self.labels[self.family].lower())+'</h1><section class="hero"><h2>'+('Explore the catalog' if not self.family else 'Models, details and retailer prices')+'</h2><p>Browse product information, compare listed prices and continue to the retailer for the complete offer.</p><nav class="jump">'+self.categories()+'</nav></section>'
        body+=self.discovery_section()
        families=self.families
        for family in families:
            entries=[x for x in self.items if x['category']==family][:4]
            if not entries:continue
            body+='<section><h2>'+e(self.labels[family])+' to explore</h2><p>'+str(sum(x['category']==family for x in self.items))+' comparison products in this category</p><div class="cards">'+''.join(self.card(x) for x in entries)+'</div>'+link('/search?category='+family,'See all '+self.labels[family].lower())+'</section>'
        body+='<section><h2>Before choosing a retailer</h2><p>Compare the exact product you need, then check delivery and stock. An advertised model price need not cover every option.</p>'+link('/about','How our price listings work')+'</section>'
        return body

    def search(self,q):
        items,category,facets=self.filtered(q);page=page_number(q);total=max(1,(len(items)+11)//12);page=min(page,total)
        form=self.filters(q,category,facets);results='<section aria-label="Search results"><h1>'+e(self.labels.get(category,'All products'))+'</h1><p id="result-count">'+str(len(items))+' comparison products</p><form action="/compare"><div class="cards">'+comparison_cards(self,items[(page-1)*12:page*12])+'</div>'+('<button>Compare selected products</button>' if len(items[(page-1)*12:page*12])>=2 else '<p>Select two or more products from a broader result set to compare their facts.</p>' if items else '<p>No products match these filters on this site. Try clearing filters, changing your search, or using Search the web to check retailers and other comparison sites.</p>')+'</form>'+pagination('/search',q,page,total)+'</section>'
        if self.layout=='directory':return '<div class="columns"><aside aria-label="Product filters">'+form+'</aside>'+results+'</div>'
        return '<details open><summary>Filter this collection</summary>'+form+'</details>'+results

    def detail(self,item,q):
        if set(q)-{'merchant','offer_sort'}:raise ValueError('Unknown offer filter')
        related=[x for x in self.items if x['category']==item['category'] and x['id']!=item['id']][:4]
        rows=self.offers(item);merchant=q.get('merchant','')
        if merchant:rows=[r for r in rows if r['retailer_id']==merchant]
        sort=q.get('offer_sort','price')
        if sort not in ('price','retailer'):raise ValueError('Unknown offer order')
        rows.sort(key=lambda r:(r['advertised_price_minor'],r['retailer_id']) if sort=='price' else self.stores[r['retailer_id']]['name'])
        body='<nav aria-label="Breadcrumbs">'+link('/','Home')+' / '+link('/search?category='+item['category'],self.labels[item['category']])+'</nav><h1>'+e(item['name'])+'</h1><section class="hero"><p class="price">'+('From '+money(self.price(item)) if self.price(item) is not None else 'No listed price')+'</p><p>'+str(len(self.offers(item)))+' retailer'+('' if len(self.offers(item))==1 else 's')+'</p>'+self.specs(item,3)+'</section>'
        body+='<p class="note">Item prices exclude delivery. '+('Select your configuration at the retailer; some options may cost more. ' if item['kind']=='model' else '')+'Stock and delivery eligibility are confirmed at the retailer. Check the selected option and final total at the retailer.</p>'
        specs=(link('/details?'+urlencode({'id':item['id']}),'Full product specifications') if self.layout=='specialist' else link('#specifications','Specifications')) if item['attributes'] else ''
        body+='<nav class="jump" aria-label="Product sections">'+link('#prices','Retailer prices')+specs+self.review_link(item)+(link('#related','Related products') if related else '')+'</nav><section id="prices"><h2>Compare retailers</h2>'
        if self.offers(item):body+='<form action="'+item['path']+'"><label>Retailer<select name="merchant"><option value="">All retailers</option>'+''.join('<option value="'+r['retailer_id']+'"'+(' selected' if merchant==r['retailer_id'] else '')+'>'+e(self.stores[r['retailer_id']]['name'])+'</option>' for r in self.offers(item))+'</select></label><label>Order offers<select name="offer_sort"><option value="price"'+(' selected' if sort=='price' else '')+'>Item price</option><option value="retailer"'+(' selected' if sort=='retailer' else '')+'>Retailer name</option></select></label><button>Update offers</button></form>'
        prefix=body;body=''
        if self.layout=='directory' and rows:
            body+='<div class="wide"><table><caption>Advertised item prices</caption><thead><tr><th>Retailer</th><th>Item price</th><th>Reported stock</th><th>Offer information</th><th>Visit retailer</th></tr></thead><tbody>'
        for row in rows:
            sid=row['retailer_id'];name=self.stores[sid]['name'];visit=link(self.retailer_url(row),'View offer at '+name)
            info='<p>Delivery and selected-option availability are checked at the retailer.</p>'+self.merchant_review_link(sid)
            if self.layout=='directory':body+='<tr><th scope="row">'+e(name)+'</th><td>'+money(row['advertised_price_minor'])+'</td><td>'+e(self.stock_text(item,row))+'</td><td><details><summary>Offer details</summary>'+info+'</details></td><td>'+visit+'</td></tr>'
            else:body+='<details class="offer"><summary>'+e(name)+' · '+money(row['advertised_price_minor'])+' · '+e(self.stock_text(item,row))+'</summary><h3>'+e(name)+'</h3>'+info+visit+'</details>'
        if self.layout=='directory' and rows:body+='</tbody></table></div>'
        if not rows:body+='<p>No matching retailer listings on this comparison site.</p>'
        body=prefix+comparison_offers(self,body)+'</section>'
        if self.layout=='directory' and item['attributes']:body+='<section id="specifications"><h2>Product specifications</h2>'+spec_table(item)+'</section>'
        if related:body+='<section id="related"><h2>Related products</h2><div class="cards">'+''.join(self.card(x) for x in related)+'</div></section>'
        return body

    def compare(self,q):
        if any(not k.startswith('pick') or not k[4:].isdigit() for k in q):raise ValueError('Unknown comparison parameter')
        ids=list(dict.fromkeys(q.values()))
        if not 2<=len(ids)<=4:return '<h1>Compare products</h1><p>Select between two and four products.</p>'+link('/search','Return to products')
        items=[self.by_id[i] for i in ids];keys=sorted({k for x in items for k in x['attributes']})
        body='<h1>Compare product facts</h1><p>Different families may not share the same attributes. Missing information is shown explicitly.</p><div class="wide"><table><thead><tr><th>Attribute</th>'+''.join('<th>'+link(x['path'],x['name'])+'</th>' for x in items)+'</tr></thead><tbody><tr><th>Lowest listed item price</th>'+''.join('<td>'+money(self.price(x))+'</td>' for x in items)+'</tr>'
        for key in keys:body+='<tr><th>'+e(field_info(items[0]['category'],key)[0])+'</th>'+''.join('<td>'+e(fact(x,key) if key in x['attributes'] else 'Not specified')+'</td>' for x in items)+'</tr>'
        return body+'</tbody></table></div>'

    def render(self,path,q,raw=''):
        if path=='/':
            if q:raise ValueError('Unexpected parameters')
            body=self.home()
        elif path=='/search':
            body=comparison_search(self,q)+self.search(q)
        elif path in self.by_path:body=self.detail(self.by_path[path],q)
        elif path=='/compare':body=self.compare(q)
        elif path=='/details':
            if set(q)!={'id'}:raise ValueError('Expected product identity')
            item=self.by_id[q['id']];body='<h1>'+e(item['name'])+' specifications</h1>'+(spec_table(item) or '<p>No product specifications are published here.</p>')+link(item['path'],'Return to retailer prices')+self.review_link(item)
        elif path=='/about':
            if q:raise ValueError('Unexpected parameters')
            body=self.about()
        else:raise KeyError('Unknown comparison page')
        return 200,self.document(self.name,body)


class Ledger(Design):
    def home(self):
        body='<h1>Find a product. Check the stores.</h1><p>Search this price directory or open a department.</p><dl class="department-directory">'
        for family in self.families:
            n=sum(x['category']==family for x in self.items);body+='<dt>'+link('/search?category='+family,self.labels[family])+'</dt><dd>'+str(n)+' products tracked here</dd>'
        body+='</dl>'
        if self.items:body+='<section><h2>Around the departments</h2>'+self.matrix(self.items[:12],selectable=False)+'</section>'
        body+='<details><summary>Why a product may be missing</summary><p>Our directory does not track every product or retailer. An empty result is not evidence that no store sells it.</p>'+self.discovery_link( 'Search other sites')+'</details>'
        return body

    def matrix(self,items,selectable=True):
        if not items:return ''
        has_facts=any(item['attributes'] for item in items)
        columns=3+int(selectable)+int(has_facts)
        body='<div class="wide"><table><caption>Products and advertised prices</caption><thead><tr>' + ('<th>Select</th>' if selectable else '')+'<th>Product</th>'+('<th>Key facts</th>' if has_facts else '')+'<th>Lowest advertised</th><th>Retailers</th></tr></thead><tbody>'
        if items and selectable and comparison_options(self).get('search_sections'):
            editorial=editorial_result(self,items[0])
            if editorial:body+='<tr><td colspan="'+str(columns)+'">'+editorial+'</td></tr>'
        for i,item in enumerate(items):
            lowest=self.lowest_retailers(item)
            body+='<tr>'+('<td><label><input type="checkbox" name="pick'+str(i)+'" value="'+e(item['id'])+'">Compare '+e(item['name'])+'</label></td>' if selectable else '')+'<th scope="row">'+link(item['path'],item['name'])+'</th>'+('<td>'+(self.specs(item,2) or '<span>No product facts published here.</span>')+'</td>' if has_facts else '')+'<td>'+money(self.price(item))+('<ul>'+''.join('<li>'+link(self.retailer_url(r),self.stores[r['retailer_id']]['name'])+'</li>' for r in lowest)+'</ul>' if lowest else '')+'</td><td>'+str(len(self.offers(item)))+'</td></tr>'
        return body+'</tbody></table></div>'

    def search(self,q):
        items,category,facets=self.filtered(q);page=page_number(q);total=max(1,(len(items)+9)//10);page=min(page,total)
        body='<nav>'+link('/','Departments')+'</nav><h1>'+e(self.labels.get(category,'Product search'))+'</h1><details><summary>Change search and filters</summary>'+self.filters(q,category,facets)+'</details><p id="result-count">'+str(len(items))+' comparison products</p><form action="/compare">'+self.matrix(items[(page-1)*10:page*10])
        if len(items)>=2:body+='<button>Compare selected products</button>'
        body+='</form>'+pagination('/search',q,page,total)
        if not items:body+='<p>No matching product is listed here.</p>'+self.discovery_link( 'Search retailers and other comparison sites')
        return body

    def offer_list(self,item):
        rows=sorted(self.offers(item),key=lambda r:(r['advertised_price_minor'],r['retailer_id']));body='<ol class="offers">'
        for r in rows:
            sid=r['retailer_id'];name=self.stores[sid]['name']
            body+='<li class="offer"><article><h3>'+e(name)+'</h3><p class="price">'+money(r['advertised_price_minor'])+'</p><p>'+e(self.stock_text(item,r))+'</p>'+link(self.retailer_url(r),'View offer at '+name)+('<p>'+self.merchant_review_link(sid)+'</p>' if self.merchant_review_link(sid) else '')+'</article></li>'
        return comparison_offers(self,body+'</ol>') if rows else '<p>No retailer listings for this product on this site.</p>'

    def detail(self,item,q):
        if q:raise ValueError('Unknown product parameter')
        specifications='<p>'+link('/details?'+urlencode({'id':item['id']}),'Full specifications')+'</p>' if item['attributes'] else ''
        related=[x for x in self.items if x['category']==item['category'] and x['id']!=item['id']][:4]
        recommendations='<section><h2>Other products in this department</h2>'+self.matrix(related,selectable=False)+'</section>' if related else ''
        return '<nav aria-label="Breadcrumbs">'+link('/','Departments')+' / '+link('/search?category='+item['category'],self.labels[item['category']])+'</nav><div class="ledger-shell"><aside aria-label="Product summary"><h1>'+e(item['name'])+'</h1>'+self.specs(item)+self.review_link(item)+specifications+'</aside><section id="prices"><h2>Retailer price list</h2><p>Advertised item prices exclude delivery. Check the selected option, stock and delivery eligibility at the retailer.</p>'+self.offer_list(item)+recommendations+'</section></div>'


class Finder(Design):
    def home(self):
        body='<h1>'+e(self.labels[self.family])+' discovery guide</h1>'
        if self.catalog_search:body+='<form action="/search"><label>Search products<input type="search" name="q"></label><button>Search</button></form>'
        body+='<div class="collections">'
        for family in self.families:
            body+='<section><h2>'+link('/search?'+urlencode({'category':family}),self.labels[family])+'</h2>'
            for field,values in self.facet_options(family).items():
                body+='<h3>'+e(field_info(family,field)[0])+'</h3><ul>'
                for i,value in enumerate(values):body+='<li>'+link('/search?'+urlencode({'category':family,f'f_{field}_{i}':'1'}),{'True':'Yes','False':'No'}.get(value,value))+'</li>'
                body+='</ul>'
            body+='</section>'
        body+='</div>'
        if self.items:body+='<section><h2>Explore the selection</h2>'+self.catalogue(self.items[:6],False)+'</section>'
        else:body+='<p>No products are tracked in this guide.</p>'
        body+=link('/search','See the full collection')
        return body

    def catalogue(self,items,selectable=True):
        if not items:return ''
        body='<ol class="catalogue">'
        if items and selectable and comparison_options(self).get('search_sections'):
            editorial=editorial_result(self,items[0])
            if editorial:body+='<li>'+editorial+'</li>'
        for i,item in enumerate(items):
            body+='<li><article><h2>'+link(item['path'],item['name'])+'</h2>'+self.specs(item,4)+'<p>Advertised from '+money(self.price(item))+' across '+str(len(self.offers(item)))+' retailer listings</p>'
            if selectable:body+='<label><input type="checkbox" name="pick'+str(i)+'" value="'+e(item['id'])+'">Compare '+e(item['name'])+'</label>'
            body+=link(item['path'],'Read product details')+'</article></li>'
        return body+'</ol>'

    def search(self,q):
        items,category,facets=self.filtered(q);page=page_number(q);total=max(1,(len(items)+7)//8);page=min(page,total)
        body='<nav>'+link('/','Collections')+'</nav><h1>Find '+e(self.labels[self.family].lower())+'</h1><div class="finder-search"><section aria-label="Product catalogue"><p id="result-count">'+str(len(items))+' comparison products</p><form action="/compare">'+self.catalogue(items[(page-1)*8:page*8])
        if len(items)>=2:body+='<button>Compare selected products</button>'
        body+='</form>'+pagination('/search',q,page,total)
        if not items:body+='<p>No product matches in this guide. Check another comparison site or retailer.</p>'+self.discovery_link( 'Search the web')
        return body+'</section><aside aria-label="Refinements">'+self.filters(q,category,facets)+'</aside></div>'

    def detail(self,item,q):
        if q:raise ValueError('Unknown product parameter')
        specifications=spec_table(item);review=self.review_link(item);related=[x for x in self.items if x['id']!=item['id']][:3]
        body='<nav aria-label="Breadcrumbs">'+link('/','Collections')+' / '+link('/search','All '+self.labels[self.family].lower())+'</nav><h1>'+e(item['name'])+'</h1><section class="hero"><h2>Product dossier</h2><p>Advertised from '+money(self.price(item))+'</p>'+link('/retailers?'+urlencode({'id':item['id']}),'See '+str(len(self.offers(item)))+' retailer listings')+'</section>'
        if specifications:body+='<section><h2>What this product offers</h2>'+specifications+'</section>'
        if review:body+='<section><h2>Customer experiences</h2>'+review+'</section>'
        if related:body+='<section><h2>More in this collection</h2>'+self.catalogue(related,False)+'</section>'
        return body

    def render(self,path,q,raw=''):
        if path=='/retailers':
            if set(q)!={'id'}:raise ValueError('Expected product identity')
            item=self.by_id[q['id']];body='<nav>'+link(item['path'],'Back to '+item['name'])+'</nav><h1>Where to buy '+e(item['name'])+'</h1><p>Compare the advertised item prices, then select the exact option at the store. Stock is not a delivery guarantee.</p><div class="retailer-cards">'
            prefix=body;body=''
            for r in sorted(self.offers(item),key=lambda r:(r['advertised_price_minor'],r['retailer_id'])):
                sid=r['retailer_id'];name=self.stores[sid]['name'];body+='<article><h2>'+e(name)+'</h2><dl><dt>Item price</dt><dd>'+money(r['advertised_price_minor'])+'</dd><dt>Reported stock</dt><dd>'+e(self.stock_text(item,r))+'</dd></dl>'+link(self.retailer_url(r),'View offer at '+name)+('<p>'+self.merchant_review_link(sid)+'</p>' if self.merchant_review_link(sid) else '')+'</article>'
            if not self.offers(item):body+='<p>There are no tracked retailer listings for this product here.</p>'+self.discovery_link( 'Look for retailers elsewhere')
            return 200,self.document(item['name'],prefix+comparison_offers(self,body)+'</div>')
        return super().render(path,q,raw)


class ComparisonPage:
    """Dispatch independently selected bodies under the same sampled chrome."""
    def __init__(self,site,products,bindings,retailer_names,index_origin,review_links):
        self.site=deepcopy(site);self.products=products_with_optional_facts(products)
        items=[]
        for pid,p in self.products.items():
            rows=[]
            for row in p['listings']:
                binding=bindings[row['entry_offer_id']]
                if binding['retailer_id']!=row['retailer_id'] or binding['product_id']!=pid:
                    raise ValueError('Comparator retailer URL identity changed')
                rows.append({**deepcopy(row),'retailer_url':binding['model_url']})
            items.append({'id':pid,'name':p['name'],'category':p['family_id'],'attributes':deepcopy(p['facts']),
                'attribute_status':deepcopy(p.get('fact_status',{})),
                'kind':'model','path':path('models',pid),'listings':rows})
        self.views={name:cls(site,items,retailer_names,index_origin,review_links,layout=name)
            for name,cls in (('directory',Design),('specialist',Design),('ledger',Ledger),('finder',Finder))}

    def documents(self):
        return [{'path':path('models',pid),'title':p['name'],
            'description':'Compare tracked model item prices; verify selected options and delivery at the retailer.',
            'keywords':pid+' '+p['family_id']+' '+pretty(p['facts'])} for pid,p in self.products.items()]

    def page(self,route,query):
        role='home' if route=='/' else 'results' if route=='/search' else 'product'
        chosen=self.site['presentation']['modules'][role]
        status,body=self.views[chosen].render(route,query)
        return status,body,'text/html; charset=utf-8'
