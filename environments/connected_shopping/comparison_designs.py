"""Reference-informed comparison layouts over the same public listing contract.

Directory: wide category navigation, sidebar facets, card collection, offer table.
Specialist: family editorial landing, horizontal refinements, offer disclosures,
separate specifications page. No layout-specific pricing or inventory semantics.
"""
from decimal import Decimal,InvalidOperation
from urllib.parse import urlencode
from .pages import e,link,money,table,path_product,pagination,page_number
from .index import tokens
from .comparison_scope import membership,filter_profile
from .comparison_discovery import validate as discovery_config,select as discovery_items,LABELS as DISCOVERY_LABELS
from environments.product_review_sites.data import field_info,pretty

LABELS={'footwear':'Footwear','laptops':'Laptops','cat_food':'Cat food','dog_food':'Dog food','beer':'Beer','wine':'Wine'}
FACETS={'footwear':['shoe_type','activity','waterproof'],'laptops':['ram_gb','storage_gb','keyboard_layout','weight_kg'],
        'cat_food':['life_stage','food_type','complete_food'],'dog_food':['life_stage','food_type','complete_food'],
        'beer':['beer_style','alcohol_abv','unfiltered','origin_country'],'wine':['wine_colour','sweetness','sparkling']}
STYLE='''<style>body{margin:0;font:16px/1.5 system-ui;color:#21363e;background:#f6f8f8}a{color:#006a76}header,footer{padding:22px 5%;background:#fff;border-bottom:1px solid #bbb}header nav,footer nav,.jump{display:flex;gap:18px;flex-wrap:wrap}main{max-width:1250px;margin:auto;padding:25px}h1{font-size:2rem}h2{line-height:1.3}input,select,button{font:inherit;padding:8px;max-width:100%;box-sizing:border-box}button{background:#006a76;color:white;border:0;border-radius:4px;cursor:pointer}label{display:block;margin:8px 0}fieldset{border:1px solid #c8d7d7;margin:12px 0;min-width:0}legend{font-weight:bold}aside{background:#fff;padding:18px;align-self:start}.columns{display:grid;grid-template-columns:250px minmax(0,1fr);gap:25px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(225px,1fr));gap:15px}.cards article,.offer,.hero{background:white;padding:20px;border:1px solid #d9e0e0;border-radius:6px}.cards h3{font-size:1.08rem}dl{display:grid;grid-template-columns:1fr 1fr;gap:6px}dt{font-weight:bold}dd{margin:0}.price{font-size:1.4rem;font-weight:bold}.wide{overflow:auto}table{border-collapse:collapse;width:100%;background:white}th,td{padding:12px;text-align:left;border-bottom:1px solid #ccd;vertical-align:top}caption{font-weight:bold;text-align:left;margin:12px 0}details{background:white;border:1px solid #c8d7d7;padding:15px;margin:10px 0}summary{cursor:pointer;font-weight:bold}.specialist header{background:#233431;color:white}.specialist header a{color:white}.specialist .refinements{display:flex;gap:15px;flex-wrap:wrap}.specialist .refinements fieldset{flex:1;min-width:180px}.specialist main{max-width:1100px}.note{padding:12px;background:#e7eeee}small{display:block}nav a{padding:5px 0}section{margin:25px 0}@media(max-width:650px){.columns{grid-template-columns:1fr}main{padding:12px}header{padding:16px}.cards{grid-template-columns:1fr}dl{grid-template-columns:1fr}h1{font-size:1.5rem}}</style>'''


def fact(item,key):
    unit=field_info(item['category'],key)[1]
    return pretty(item['attributes'][key])+(' '+unit if unit else '')


def spec_table(item):
    return '<table><caption>Product details</caption><tbody>'+''.join('<tr><th scope="row">'+e(field_info(item['category'],key)[0])+'</th><td>'+e(fact(item,key))+'</td></tr>' for key in item['attributes'])+'</tbody></table>'


class Design:
    def __init__(self,owner,*,layout='directory',family=None,name=None,coverage=None,filter_config=None,discovery=None):
        if layout not in ('directory','specialist'):raise ValueError('Unknown comparison design')
        if layout=='specialist' and family not in owner.families:raise ValueError('Specialist needs a supported family')
        self.owner=owner;self.layout=layout;self.family=family
        self.name=name or ('Prislyktan' if layout=='directory' else LABELS[family]+' Finder')
        items,self.listing_membership=membership(owner,coverage)
        self.filter_config=filter_profile(owner,filter_config)
        self.discovery=discovery_config(discovery)
        self.coverage=coverage
        self.families=([family] if family else list(coverage['families']) if coverage is not None else list(owner.families))
        if family and coverage is not None and coverage['families']!=[family]:raise ValueError('Specialist coverage must match its family')
        self.items=[x for x in items if not family or x['category']==family]
        self.by_id={x['id']:x for x in self.items};self.by_path={x['path']:x for x in self.items}
    def offers(self,item):
        rows=item['listings'] if item['kind']=='model' else [{'retailer_id':o['retailer_id'],'advertised_price_minor':o['price_minor'],'entry_product_id':o['product_id']} for o in self.owner.offers.values() if o['product_id']==item['id']]
        return [r for r in rows if self.listing_membership is None or (item['id'],r['retailer_id']) in self.listing_membership]
    def price(self,item):return min((r['advertised_price_minor'] for r in self.offers(item)),default=None)
    def stock(self,item,row):
        sid=row['retailer_id']
        ids={v['product_id'] for v in self.owner.group_for[row['entry_product_id']]['variants']} if item['kind']=='model' else {item['id']}
        quantities=[o.get('stock_quantity') for o in self.owner.offers.values() if o['retailer_id']==sid and o['product_id'] in ids]
        if any(type(q) is int and q>0 for q in quantities):return 'some_options' if item['kind']=='model' else 'in_stock'
        if quantities and all(type(q) is int and q==0 for q in quantities):return 'out_of_stock'
        return 'unknown'
    def stock_text(self,item,row):
        return {'some_options':'Some options in stock — check your size at the retailer',
                'in_stock':'In stock', 'out_of_stock':'No listed options in stock' if item['kind']=='model' else 'Out of stock',
                'unknown':'Stock not reported'}[self.stock(item,row)]
    def lowest_retailers(self,item):
        price=self.price(item)
        return sorted((r for r in self.offers(item) if r['advertised_price_minor']==price),key=lambda r:r['retailer_id'])
    def review_url(self,item):
        gid=item['id'] if item['kind']=='model' else self.owner.group_for[item['id']]['group_id']
        return self.owner.origins['reviews-'+item['category']]+'/reviews/'+gid
    def categories(self):
        return ''.join(link('/search?'+urlencode({'category':f}),LABELS[f]) for f in self.families)
    def document(self,title,body):
        nav=link('/','Home')+self.categories()+link('/about','How prices work')+link(self.owner.index_origin,'Search the web')
        header='<header>'+link('/',self.name)+'<nav aria-label="Main navigation">'+nav+'</nav><form action="/search"><label>Search products<input type="search" name="q" placeholder="Product or model name"></label><button>Search</button></form></header>'
        footer='<footer><h2>Explore '+e(self.name)+'</h2><nav aria-label="Footer categories">'+self.categories()+'</nav><p>Prices shown here are item prices. Retailers confirm selected options, stock and final charges.</p><nav>'+link('/about','About price comparisons')+link(self.owner.origins['merchant-reviews'],'Customer reviews of retailers')+link(self.owner.index_origin,'More shopping websites')+'</nav></footer>'
        return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+e(title)+' — '+e(self.name)+'</title>'+STYLE+'</head><body class="'+self.layout+'">'+header+'<main id="main">'+body+'</main>'+footer+'</body></html>'
    def specs(self,item,limit=None):
        rows=list(item['attributes'].items());rows=rows[:limit] if limit else rows
        return '<dl>'+''.join('<dt>'+e(field_info(item['category'],k)[0])+'</dt><dd>'+e(fact(item,k))+'</dd>' for k,v in rows)+'</dl>'
    def card(self,item,pick=None):
        price=self.price(item);rows=self.offers(item)
        check='' if pick is None else '<label><input type="checkbox" name="pick'+str(pick)+'" value="'+e(item['id'])+'">Compare '+e(item['name'])+'</label>'
        cheapest=self.lowest_retailers(item)
        where='<div class="lowest-retailers"><p>Lowest advertised at:</p><ul>'+''.join('<li>'+link(self.owner.origins[r['retailer_id']]+path_product(r['entry_product_id']),self.owner.stores[r['retailer_id']]['name'])+'<small>'+e(self.stock_text(item,r))+'</small></li>' for r in cheapest)+'</ul></div>' if cheapest else ''
        return '<article><small>'+e(LABELS[item['category']])+'</small><h3>'+link(item['path'],item['name'])+'</h3>'+self.specs(item,3)+'<p class="price">'+('From '+money(price) if price is not None else 'No listed price')+'</p>'+where+'<p>'+str(len(rows))+' retailer'+('' if len(rows)==1 else 's')+'</p>'+link(item['path'],'Compare retailer prices')+check+'</article>'
    def facet_options(self,category):
        items=[x for x in self.items if x['category']==category];keys=self.filter_config['attributes'].get(category,[]) if self.filter_config is not None else FACETS.get(category,[])
        # Declared attributes can evolve without adding controls for unknown data.
        present={k for x in items for k in x['attributes']}
        keys=[k for k in keys if k in present]
        if not keys and self.filter_config is None:keys=sorted(present)[:4]
        return {k:sorted({str(x['attributes'][k]) for x in items if k in x['attributes']}) for k in keys}
    def filtered(self,q):
        category=self.family or q.get('category','')
        if category and category not in self.families:raise ValueError('Unknown category')
        if self.family and q.get('category',self.family)!=self.family:raise ValueError('Outside specialist scope')
        facets=self.facet_options(category) if category else {}
        known={f'f_{k}_{i}':(k,v) for k,values in facets.items() for i,v in enumerate(values)}
        allowed={'q','category','page'}|set(known)
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
        body='<form id="filters" action="/search"><h2>Refine products</h2><label>Product name<input name="q" value="'+e(q.get('q',''))+'"></label>'
        body+='<input type="hidden" name="category" value="'+e(category)+'"><p>Category: '+e(LABELS.get(category,'All categories'))+'</p>'
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
    def discovery_section(self):
        items=discovery_items(self.items,self.discovery)
        if not items:return ''
        title=DISCOVERY_LABELS[self.discovery['mode']]
        return '<section aria-labelledby="discovery-heading"><h2 id="discovery-heading">'+e(title)+'</h2><p>Explore products across our categories.</p><div class="cards">'+''.join(self.card(x) for x in items)+'</div></section>'
    def home(self):
        body='<h1>'+('Compare products, prices and retailers' if not self.family else 'Find your next '+LABELS[self.family].lower())+'</h1><section class="hero"><h2>'+('Explore the catalog' if not self.family else 'Models, details and retailer prices')+'</h2><p>Browse product information, compare listed prices and continue to the retailer for the complete offer.</p><nav class="jump">'+self.categories()+'</nav></section>'
        body+=self.discovery_section()
        families=self.families
        for family in families:
            entries=[x for x in self.items if x['category']==family][:4]
            if not entries:continue
            body+='<section><h2>'+e(LABELS[family])+' to explore</h2><p>'+str(sum(x['category']==family for x in self.items))+' comparison products in this category</p><div class="cards">'+''.join(self.card(x) for x in entries)+'</div>'+link('/search?category='+family,'See all '+LABELS[family].lower())+'</section>'
        body+='<section><h2>Before choosing a retailer</h2><p>Compare the exact product you need, then check delivery and stock. An advertised model price need not cover every option.</p>'+link(self.owner.origins['merchant-reviews'],'Read customer experiences')+'</section>'
        return body
    def search(self,q):
        items,category,facets=self.filtered(q);page=page_number(q);total=max(1,(len(items)+11)//12);page=min(page,total)
        from .interaction_patterns import comparison_cards
        form=self.filters(q,category,facets);results='<section aria-label="Search results"><h1>'+e(LABELS.get(category,'All products'))+'</h1><p id="result-count">'+str(len(items))+' comparison products</p><form action="/compare"><div class="cards">'+comparison_cards(self,items[(page-1)*12:page*12])+'</div>'+('<button>Compare selected products</button>' if len(items[(page-1)*12:page*12])>=2 else '<p>Select two or more products from a broader result set to compare their facts.</p>' if items else '<p>No products match these filters on this site. Try clearing filters, changing your search, or using Search the web to check retailers and other comparison sites.</p>')+'</form>'+pagination('/search',q,page,total)+'</section>'
        if self.layout=='directory':return '<div class="columns"><aside aria-label="Product filters">'+form+'</aside>'+results+'</div>'
        return '<details open><summary>Filter this collection</summary>'+form+'</details>'+results
    def detail(self,item,q):
        if set(q)-{'merchant','offer_sort'}:raise ValueError('Unknown offer filter')
        rows=self.offers(item);merchant=q.get('merchant','')
        if merchant:rows=[r for r in rows if r['retailer_id']==merchant]
        sort=q.get('offer_sort','price')
        if sort not in ('price','retailer'):raise ValueError('Unknown offer order')
        rows.sort(key=lambda r:(r['advertised_price_minor'],r['retailer_id']) if sort=='price' else self.owner.stores[r['retailer_id']]['name'])
        body='<nav aria-label="Breadcrumbs">'+link('/','Home')+' / '+link('/search?category='+item['category'],LABELS[item['category']])+'</nav><h1>'+e(item['name'])+'</h1><section class="hero"><p class="price">'+('From '+money(self.price(item)) if self.price(item) is not None else 'No listed price')+'</p><p>'+str(len(self.offers(item)))+' retailer'+('' if len(self.offers(item))==1 else 's')+'</p>'+self.specs(item,3)+'</section>'
        body+='<p class="note">Item prices exclude delivery. '+('Select size, fit and colour at the retailer; some options may cost more. ' if item['kind']=='model' else '')+'Stock indicates warehouse availability, not delivery eligibility. Check the selected option and final total at the retailer.</p>'
        specs=link('/details?'+urlencode({'id':item['id']}),'Full product specifications') if self.layout=='specialist' else link('#specifications','Specifications')
        body+='<nav class="jump" aria-label="Product sections">'+link('#prices','Retailer prices')+specs+link(self.review_url(item),'Independent product review')+link('#related','Related products')+'</nav><section id="prices"><h2>Compare retailers</h2>'
        body+='<form action="'+item['path']+'"><label>Retailer<select name="merchant"><option value="">All retailers</option>'+''.join('<option value="'+r['retailer_id']+'"'+(' selected' if merchant==r['retailer_id'] else '')+'>'+e(self.owner.stores[r['retailer_id']]['name'])+'</option>' for r in self.offers(item))+'</select></label><label>Order offers<select name="offer_sort"><option value="price"'+(' selected' if sort=='price' else '')+'>Item price</option><option value="retailer"'+(' selected' if sort=='retailer' else '')+'>Retailer name</option></select></label><button>Update offers</button></form>'
        prefix=body;body=''
        if self.layout=='directory':
            body+='<div class="wide"><table><caption>Advertised item prices</caption><thead><tr><th>Retailer</th><th>Item price</th><th>Reported stock</th><th>Offer information</th><th>Visit retailer</th></tr></thead><tbody>'
        for row in rows:
            sid=row['retailer_id'];name=self.owner.stores[sid]['name'];visit=link(self.owner.origins[sid]+path_product(row['entry_product_id']),'View offer at '+name)
            info='<p>Delivery and selected-option availability are checked at the retailer.</p>'+link(self.owner.origins['merchant-reviews']+'/review/'+sid,'Customer reviews of '+name)
            if self.layout=='directory':body+='<tr><th scope="row">'+e(name)+'</th><td>'+money(row['advertised_price_minor'])+'</td><td>'+e(self.stock_text(item,row))+'</td><td><details><summary>Offer details</summary>'+info+'</details></td><td>'+visit+'</td></tr>'
            else:body+='<details class="offer"><summary>'+e(name)+' · '+money(row['advertised_price_minor'])+' · '+e(self.stock_text(item,row))+'</summary><h3>'+e(name)+'</h3>'+info+visit+'</details>'
        if self.layout=='directory':body+='</tbody></table></div>'
        if not rows:body+='<p>No matching retailer listings on this comparison site.</p>'
        from .interaction_patterns import comparison_offers
        body=prefix+comparison_offers(self,body)+'</section>'
        if self.layout=='directory':body+='<section id="specifications"><h2>Product specifications</h2>'+spec_table(item)+'</section>'
        related=[x for x in self.items if x['category']==item['category'] and x['id']!=item['id']][:4]
        body+='<section id="related"><h2>Related products</h2><div class="cards">'+''.join(self.card(x) for x in related)+'</div></section>'
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
            from .interaction_patterns import comparison_search
            body=comparison_search(self,q)+self.search(q)
        elif path in self.by_path:body=self.detail(self.by_path[path],q)
        elif path=='/compare':body=self.compare(q)
        elif path=='/details':
            if set(q)!={'id'}:raise ValueError('Expected product identity')
            item=self.by_id[q['id']];body='<h1>'+e(item['name'])+' specifications</h1>'+spec_table(item)+link(item['path'],'Return to retailer prices')+link(self.review_url(item),'Read independent review')
        elif path=='/about':
            if q:raise ValueError('Unexpected parameters')
            body='<h1>How comparison prices work</h1><p>Listings show item prices, excluding delivery. Footwear is compared by model; select size, colour and fit at the retailer. The retailer confirms the price and availability of that selection.</p><p>Reported stock refers to retailer warehouse availability; it does not establish eligibility for delivery to your address. For footwear, some options may be available while your size is sold out. No price-history feed or discount campaign feed is available in this catalog. Product facts and customer reviews can be explored through their linked sites.</p>'
        else:raise KeyError('Unknown comparison page')
        return 200,self.document(self.name,body)
