"""Two additional AX-distinct bases sharing only comparison semantics.

Ledger: directory landing, inline comparison matrix, product aside + ranked offer list.
Finder: attribute collections, ordered catalogue, product dossier -> separate retailers page.
"""
from urllib.parse import urlencode
from .comparison_designs import Design,LABELS,STYLE,fact,spec_table
from .pages import e,link,money,path_product,pagination,page_number
from .interaction_patterns import comparison_offers, comparison_options, editorial_result

EXTRA='''<style>.ledger header{background:#e8eff9}.ledger .ledger-shell{display:grid;grid-template-columns:280px minmax(0,1fr);gap:25px}.ledger li.offer{margin:16px 0}.finder header{background:#fcf0df}.finder .finder-search{display:grid;grid-template-columns:minmax(0,1fr) 280px;gap:24px}.finder ol.catalogue{padding:0;list-style-position:inside}.finder .catalogue>li{padding:18px;margin:14px 0;border:1px solid #cdbf9f;background:#fff}.finder .catalogue dl{max-width:650px}.finder .collections{display:flex;gap:20px;flex-wrap:wrap}.finder .collections section{padding:14px;background:white;min-width:180px}.retailer-cards{display:grid;gap:20px;grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}@media(max-width:750px){.ledger .ledger-shell,.finder .finder-search{grid-template-columns:minmax(0,1fr)}.ledger-shell>*,.finder-search>*{min-width:0}.wide{max-width:100%;overflow:auto}}</style>'''


class Ledger(Design):
    def __init__(self,owner,**kwargs):
        super().__init__(owner,layout='directory',**kwargs);self.layout='ledger'
    def document(self,title,body):
        head='<header><p>'+link('/',self.name)+'</p><form action="/search"><label>Search products<input type="search" name="q"></label><button>Search</button></form><details><summary>Browse departments</summary><nav aria-label="Departments">'+self.categories()+'</nav></details><nav>'+link('/about','About our listings')+link(self.owner.index_origin,'Search the web')+'</nav></header>'
        foot='<footer><h2>Shopping directory</h2><nav>'+self.categories()+link(self.owner.origins['merchant-reviews'],'Retailer reviews')+'</nav><p>Only prices reported by stores covered here are compared. Other stores may carry the product.</p></footer>'
        return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+e(title)+' — '+e(self.name)+'</title>'+STYLE+EXTRA+'</head><body class="ledger">'+head+'<main id="main">'+body+'</main>'+foot+'</body></html>'
    def home(self):
        body='<h1>Find a product. Check the stores.</h1><p>Search this price directory or open a department.</p><dl class="department-directory">'
        for family in self.families:
            n=sum(x['category']==family for x in self.items);body+='<dt>'+link('/search?category='+family,LABELS[family])+'</dt><dd>'+str(n)+' products tracked here</dd>'
        body+='</dl><section><h2>Around the departments</h2>'+self.matrix(self.items[:12],selectable=False)+'</section><details><summary>Why a product may be missing</summary><p>Our directory does not track every product or retailer. An empty result is not evidence that no store sells it.</p>'+link(self.owner.index_origin,'Search other sites')+'</details>'
        return body
    def matrix(self,items,selectable=True):
        body='<div class="wide"><table><caption>Products and advertised prices</caption><thead><tr>' + ('<th>Select</th>' if selectable else '')+'<th>Product</th><th>Key facts</th><th>Lowest advertised</th><th>Retailers</th></tr></thead><tbody>'
        if items and selectable and comparison_options(self).get('search_sections'):
            body+='<tr><td colspan="5">'+editorial_result(self,items[0])+'</td></tr>'
        for i,item in enumerate(items):
            lowest=self.lowest_retailers(item)
            body+='<tr>'+('<td><label><input type="checkbox" name="pick'+str(i)+'" value="'+e(item['id'])+'">Compare '+e(item['name'])+'</label></td>' if selectable else '')+'<th scope="row">'+link(item['path'],item['name'])+'</th><td>'+self.specs(item,2)+'</td><td>'+money(self.price(item))+'<ul>'+''.join('<li>'+link(self.owner.origins[r['retailer_id']]+path_product(r['entry_product_id']),self.owner.stores[r['retailer_id']]['name'])+'</li>' for r in lowest)+'</ul></td><td>'+str(len(self.offers(item)))+'</td></tr>'
        return body+'</tbody></table></div>'
    def search(self,q):
        items,category,facets=self.filtered(q);page=page_number(q);total=max(1,(len(items)+9)//10);page=min(page,total)
        body='<nav>'+link('/','Departments')+'</nav><h1>'+e(LABELS.get(category,'Product search'))+'</h1><details><summary>Change search and filters</summary>'+self.filters(q,category,facets)+'</details><p id="result-count">'+str(len(items))+' comparison products</p><form action="/compare">'+self.matrix(items[(page-1)*10:page*10])
        if len(items)>=2:body+='<button>Compare selected products</button>'
        body+='</form>'+pagination('/search',q,page,total)
        if not items:body+='<p>No matching product is listed here.</p>'+link(self.owner.index_origin,'Search retailers and other comparison sites')
        return body
    def offer_list(self,item):
        rows=sorted(self.offers(item),key=lambda r:(r['advertised_price_minor'],r['retailer_id']));body='<ol class="offers">'
        for r in rows:
            sid=r['retailer_id'];name=self.owner.stores[sid]['name']
            body+='<li class="offer"><article><h3>'+e(name)+'</h3><p class="price">'+money(r['advertised_price_minor'])+'</p><p>'+e(self.stock_text(item,r))+'</p>'+link(self.owner.origins[sid]+path_product(r['entry_product_id']),'View offer at '+name)+'<p>'+link(self.owner.origins['merchant-reviews']+'/review/'+sid,'Read reviews of '+name)+'</p></article></li>'
        return comparison_offers(self,body+'</ol>') if rows else '<p>No retailer listings for this product on this site.</p>'
    def detail(self,item,q):
        if q:raise ValueError('Unknown product parameter')
        return '<nav aria-label="Breadcrumbs">'+link('/','Departments')+' / '+link('/search?category='+item['category'],LABELS[item['category']])+'</nav><div class="ledger-shell"><aside aria-label="Product summary"><h1>'+e(item['name'])+'</h1>'+self.specs(item)+link(self.review_url(item),'Independent product review')+'<p>'+link('/details?'+urlencode({'id':item['id']}),'Full specifications')+'</p></aside><section id="prices"><h2>Retailer price list</h2><p>Advertised item prices exclude delivery. Check the selected option, stock and delivery eligibility at the retailer.</p>'+self.offer_list(item)+'<h2>Other products in this department</h2>'+self.matrix([x for x in self.items if x['category']==item['category'] and x['id']!=item['id']][:4],selectable=False)+'</section></div>'


class Finder(Design):
    def __init__(self,owner,**kwargs):
        super().__init__(owner,layout='specialist',**kwargs);self.layout='finder'
    def document(self,title,body):
        head='<header><p>'+link('/',self.name)+'</p><nav aria-label="Specialist navigation">'+link('/','Collections')+link('/search','All '+LABELS[self.family].lower())+link('/about','How this guide works')+'</nav></header>'
        foot='<footer><h2>Continue your search</h2><nav>'+link('/search','Browse our tracked products')+link(self.owner.index_origin,'Search the web')+link(self.owner.origins['reviews-'+self.family],'Independent product reviews')+'</nav><p>Our selection and retailer coverage are limited; missing here does not mean unavailable elsewhere.</p></footer>'
        return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+e(title)+' — '+e(self.name)+'</title>'+STYLE+EXTRA+'</head><body class="finder">'+head+'<main id="main">'+body+'</main>'+foot+'</body></html>'
    def home(self):
        body='<h1>'+e(LABELS[self.family])+' discovery guide</h1><form action="/search"><label>Search products<input type="search" name="q"></label><button>Search</button></form><div class="collections">'
        for field,values in self.facet_options(self.family).items():
            from environments.product_review_sites.data import field_info
            body+='<section><h2>'+e(field_info(self.family,field)[0])+'</h2><ul>'
            for i,value in enumerate(values):body+='<li>'+link('/search?'+urlencode({'category':self.family,f'f_{field}_{i}':'1'}),{'True':'Yes','False':'No'}.get(value,value))+'</li>'
            body+='</ul></section>'
        body+='</div><h2>Explore the selection</h2>'+self.catalogue(self.items[:6],False)+link('/search','See the full collection')
        return body
    def catalogue(self,items,selectable=True):
        body='<ol class="catalogue">'
        if items and selectable and comparison_options(self).get('search_sections'):
            body+='<li>'+editorial_result(self,items[0])+'</li>'
        for i,item in enumerate(items):
            body+='<li><article><h2>'+link(item['path'],item['name'])+'</h2>'+self.specs(item,4)+'<p>Advertised from '+money(self.price(item))+' across '+str(len(self.offers(item)))+' retailer listings</p>'
            if selectable:body+='<label><input type="checkbox" name="pick'+str(i)+'" value="'+e(item['id'])+'">Compare '+e(item['name'])+'</label>'
            body+=link(item['path'],'Read product details')+'</article></li>'
        return body+'</ol>'
    def search(self,q):
        items,category,facets=self.filtered(q);page=page_number(q);total=max(1,(len(items)+7)//8);page=min(page,total)
        body='<nav>'+link('/','Collections')+'</nav><h1>Find '+e(LABELS[self.family].lower())+'</h1><div class="finder-search"><section aria-label="Product catalogue"><p id="result-count">'+str(len(items))+' comparison products</p><form action="/compare">'+self.catalogue(items[(page-1)*8:page*8])
        if len(items)>=2:body+='<button>Compare selected products</button>'
        body+='</form>'+pagination('/search',q,page,total)
        if not items:body+='<p>No product matches in this guide. Check another comparison site or retailer.</p>'+link(self.owner.index_origin,'Search the web')
        return body+'</section><aside aria-label="Refinements">'+self.filters(q,category,facets)+'</aside></div>'
    def detail(self,item,q):
        if q:raise ValueError('Unknown product parameter')
        body='<nav aria-label="Breadcrumbs">'+link('/','Collections')+' / '+link('/search','All '+LABELS[self.family].lower())+'</nav><h1>'+e(item['name'])+'</h1><section class="hero"><h2>Product dossier</h2><p>Advertised from '+money(self.price(item))+'</p>'+link('/retailers?'+urlencode({'id':item['id']}),'See '+str(len(self.offers(item)))+' retailer listings')+'</section><section><h2>What this product offers</h2>'+spec_table(item)+'</section><section><h2>Read independent experiences</h2>'+link(self.review_url(item),'Independent product review')+'</section><h2>More in this collection</h2>'+self.catalogue([x for x in self.items if x['id']!=item['id']][:3],False)
        return body
    def render(self,path,q,raw=''):
        if path=='/retailers':
            if set(q)!={'id'}:raise ValueError('Expected product identity')
            item=self.by_id[q['id']];body='<nav>'+link(item['path'],'Back to '+item['name'])+'</nav><h1>Where to buy '+e(item['name'])+'</h1><p>Compare the advertised item prices, then select the exact option at the store. Stock is not a delivery guarantee.</p><div class="retailer-cards">'
            prefix=body;body=''
            for r in sorted(self.offers(item),key=lambda r:(r['advertised_price_minor'],r['retailer_id'])):
                sid=r['retailer_id'];name=self.owner.stores[sid]['name'];body+='<article><h2>'+e(name)+'</h2><dl><dt>Item price</dt><dd>'+money(r['advertised_price_minor'])+'</dd><dt>Reported stock</dt><dd>'+e(self.stock_text(item,r))+'</dd></dl>'+link(self.owner.origins[sid]+path_product(r['entry_product_id']),'View offer at '+name)+'<p>'+link(self.owner.origins['merchant-reviews']+'/review/'+sid,'Customer reviews of '+name)+'</p></article>'
            if not self.offers(item):body+='<p>There are no tracked retailer listings for this product here.</p>'+link(self.owner.index_origin,'Look for retailers elsewhere')
            return 200,self.document(item['name'],prefix+comparison_offers(self,body)+'</div>')
        return super().render(path,q,raw)
