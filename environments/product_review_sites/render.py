"""Three structural designs: specification directory, paged magazine, activity feed."""
from html import escape
from urllib.parse import quote, urlencode
from decimal import Decimal, ROUND_HALF_UP
from .data import field_info, fact_text, pretty
from .presentation import vocabulary, common_vocabulary
from .facets import token
from . import structure


def e(v):return escape(str(v),quote=True)
def u(path,q=None):return path+('?' + urlencode({k:v for k,v in (q or {}).items() if v!=''},doseq=True) if any(v!='' for v in (q or {}).values()) else '')
def review_url(a):return '/reviews/'+quote(a['id'],safe='')
def variant_url(v):return '/variants/'+quote(v['sku'],safe='')
def family_label(f):return f.replace('_',' ').title()
def mean(a):
    rows=a['reader_opinions']
    return str((Decimal(sum(r['stars'] for r in rows))/len(rows)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)) if rows else 'Not rated'

GROUPS={
    'footwear':(('Size and fit',('size_eu','width','colour')),('Use and protection',('activity','waterproof'))),
    'laptops':(('Configuration',('ram_gb','storage_gb','keyboard_layout')),('Portability and connections',('weight_kg','ports'))),
    'dog_food':(('Recipe and ingredients',('recipe','ingredients')),('Pack and feeding label',('net_weight_kg','life_stage','food_type','complete_food'))),
    'cat_food':(('Recipe and ingredients',('recipe','ingredients')),('Pack and feeding label',('net_weight_kg','life_stage','food_type','complete_food'))),
    'beer':(('Style and production',('beer_style','origin_country','production_region','marketed_bitterness','unfiltered')),('Strength and pack',('alcohol_abv','volume_ml','pack_count'))),
    'wine':(('Vintage and character',('vintage','wine_colour','grapes','sweetness','sparkling')),('Origin and bottle',('origin_country','alcohol_abv','volume_ml','pack_count'))),
}
CAUTIONS={
    'footwear':'A labelled wide option is not a measurement of internal shoe width. Check the reviewed size and width against the offer you select.',
    'laptops':'RAM, storage and keyboard layout belong to this configuration. Benchmark speed and battery endurance cannot be inferred from these specification fields.',
    'dog_food':'Ingredient presence is reported from the recipe. This is not a feeding prescription, allergy diagnosis or independent nutritional certification.',
    'cat_food':'A recipe label does not establish that it suits every cat. Ingredients and life-stage claims are separate from individual dietary requirements.',
    'beer':'Style, alcohol content and producer-described bitterness are distinct facts. A reader rating does not measure bitterness or guarantee that you will enjoy it.',
    'wine':'The vintage identifies the wine reviewed here. Reviews of one vintage do not automatically establish the taste of another.',
}
STYLE='''<style>
*{box-sizing:border-box}body{margin:0;color:#202827;background:#f4f5f4;font:16px/1.6 system-ui,sans-serif}a{color:#175d85}header,footer{padding:20px max(24px,5vw);background:#183d3e;color:white}header a,footer a{color:inherit}header .brand{font-size:27px;font-weight:800;text-decoration:none}header nav,footer nav{display:flex;gap:24px;flex-wrap:wrap}input,select,button{font:inherit;padding:10px;max-width:100%;border:1px solid #abb4b2;border-radius:4px}button,.button{cursor:pointer;background:#235957;color:white;padding:10px 18px;border:0;text-decoration:none;display:inline-block}label{display:grid;gap:4px}fieldset{min-width:0;border:1px solid #c5d1ca;padding:10px;margin:0}legend{font-weight:650}.facets{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;width:100%}.facets>label{align-self:start}.choice{display:flex;align-items:center;gap:8px}.choice input{margin:0;padding:0}.catalog-filters{align-items:start}.catalog aside .facets{grid-template-columns:1fr}form{display:flex;align-items:end;gap:12px;flex-wrap:wrap}main{max-width:1350px;margin:auto;padding:30px 24px}.hero{padding:35px;background:#e6eeea}.hero h1{font-size:36px}.columns{display:grid;grid-template-columns:220px minmax(0,1fr) 250px;gap:26px}.two{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:28px}.catalog{display:grid;grid-template-columns:250px minmax(0,1fr);gap:28px}.card,article.entry{background:white;border:1px solid #d3dcda;padding:24px;margin:16px 0}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}.grid .card{margin:0}h1{line-height:1.25}h2{margin-top:1.5em}.muted{color:#516563;font-size:14px}.tag{background:#e6eeee;border:1px solid #c3d3cd;padding:4px 8px;display:inline-block;margin:3px}.facts{width:100%;border-collapse:collapse;background:white}.facts th,.facts td{border:1px solid #c4cfcb;padding:12px;text-align:left;vertical-align:top;overflow-wrap:anywhere}.facts th{background:#edf1ee}.scroll-table{overflow-x:auto}aside nav ul{padding-left:20px}aside form{display:grid}figure{margin:0;background:#e6eeeb;text-align:center;padding:22px}figure svg{width:160px;height:100px}figcaption{font-size:13px}.headline{max-width:950px}.score{font-size:28px;font-weight:800}.topic-strip{display:flex;gap:20px;flex-wrap:wrap;padding:12px 0}.topic-strip details{margin:0;color:#20332e}.topic-strip details a{color:#175d85}meter{display:block;width:100%;max-width:260px}.pagination{display:flex;gap:20px;align-items:center;margin:25px 0}.feed .entry{border:0;border-bottom:1px solid #c8d0cc;margin:0}.byline{font-size:14px}.editorial-magazine header{background:#fff;color:#202425;border-top:8px solid #9c302c}.editorial-magazine .brand{font-family:Georgia,serif;font-size:32px}.editorial-magazine header nav{background:#96322b;color:white;padding:12px;margin-top:15px}.editorial-magazine h1,.editorial-magazine article h2{font-family:Georgia,serif}.editorial-magazine article{max-width:850px}.editorial-magazine .hero{background:#f0e8df}.community-feed header{background:#eabd44;color:#252015}.community-feed .two{max-width:1100px;margin:auto}.community-feed .product-head{display:grid;grid-template-columns:180px 1fr;gap:20px}.community-feed dl{display:grid;grid-template-columns:1fr 1fr;gap:8px}.community-feed dt{font-weight:700}.community-feed dd{margin:0}details{background:#edf1ed;padding:15px;margin:15px 0}summary{cursor:pointer;font-weight:650}.skip{position:absolute;left:-9999px}.skip:focus{left:10px;background:white}a,td,p,h1,h2,h3{overflow-wrap:anywhere}button:focus-visible,a:focus-visible,summary:focus-visible{outline:3px solid #bd7620;outline-offset:3px}@media(max-width:1000px){.columns{grid-template-columns:180px minmax(0,1fr)}.columns>aside:last-child{grid-column:1/-1}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:700px){.columns,.two,.catalog,.grid{display:block}.community-feed .product-head{grid-template-columns:1fr}main{padding:16px}.card{margin:14px 0}header nav{gap:12px}}
</style>'''


def document(site,title,body):
    words=common_vocabulary(site.db.families)
    cats=''.join(f'<a href="{e(u("/catalog",{"family":f}))}">{e(family_label(f))}</a>' for f in site.db.families)
    search='<form action="/catalog" method="get"><label>Search reviews<input type="search" name="q"></label><button>Search</button></form>'
    # Different nav placement/depth is intentional, not CSS-only variation.
    if site.layout=='lab-directory':nav=f'<div>{search}</div><nav aria-label="Categories">{cats}<a href="/compare">Compare</a><a href="/methodology">Methodology</a></nav>'
    elif site.layout=='editorial-magazine':nav=f'<nav aria-label="Sections"><a href="/catalog">Latest reviews</a>{cats}<a href="/compare">Side by side</a><a href="/methodology">Our approach</a></nav><details><summary>Search the magazine</summary>{search}</details>'
    else:nav=f'<nav aria-label="Community"><a href="/catalog">Discover</a>{cats}<a href="/catalog?sort=rating">Reader ratings</a><a href="/methodology">About ratings</a></nav>{search}'
    return f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)} | {e(site.name)}</title>{STYLE}</head><body class="{site.layout}"><a class="skip" href="#main">Skip to content</a><header><a class="brand" href="/">{e(site.name)}</a>{nav}{structure.discovery_nav(site)}</header>{body}<footer><nav><a href="/catalog">All reviews</a><a href="/compare">Compare {e(words.plural)}</a><a href="/methodology">How this publication works</a></nav>{structure.footer(site)}<p>Independent fictional publication for a generated shopping world. Reader opinions are not product specifications.</p></footer></body></html>'


def picture(v):
    # Local symbolic illustration, not a borrowed photo or an invented measurement.
    shapes={'footwear':'<path d="M10 65 L35 25 L60 30 L70 60 L135 65 L150 80 L10 80Z"/>',
            'laptops':'<path d="M35 10 H125 V65 H35Z M15 80 L35 65 H125 L150 80Z"/>',
            'beer':'<path d="M60 5 H90 V25 L105 45 V90 H45 V45 L60 25Z"/>',
            'wine':'<path d="M65 5 H85 V35 L95 45 V90 H55 V45 L65 35Z"/>'}
    shape=shapes.get(v['family'],'<path d="M40 10 H115 L130 90 H25Z M40 30 H115"/>')
    return f'<figure><svg role="img" aria-label="{e(family_label(v["family"]))} illustration" viewBox="0 0 160 100"><g fill="#8aada3" stroke="#254940" stroke-width="3">{shape}</g></svg><figcaption>Illustration · {e(v["name"])}</figcaption></figure>'


def fact_table(v,keys=None):
    keys=list(v['facts']) if keys is None else keys
    return '<table class="facts"><caption>'+e(vocabulary(v['family']).facts_title)+'</caption><thead><tr><th scope="col">Attribute</th><th scope="col">Value</th></tr></thead><tbody>'+''.join(f'<tr><th scope="row">{e(field_info(v["family"],k)[0])}</th><td>{e(fact_text(v,k))}</td></tr>' for k in keys if k in v['facts'])+'</tbody></table>'


def card(site,a):
    v=site.db.variants[a['reviewed_sku']]
    return f'<section class="card"><span class="tag">{e(family_label(a["family"]))}</span><h3><a href="{review_url(a)}">{e(a["model_name"])}</a></h3><p>{e(v["name"])}</p><p class="muted">Published {a["published"]} · {a["reader_statistics"]["count"]} reader ratings</p><a href="{e(u("/compare",{"left":a["id"]}))}">Compare this {e(vocabulary(a['family']).item)}</a></section>'


def home(site):
    rows=site.db.find({'sort':'newest'});words=common_vocabulary(site.db.families)
    if site.layout=='lab-directory':
        title='Look closely. Compare the details.'
        body='<div class="catalog"><aside><h2>Browse a category</h2><ul>'+''.join(f'<li><a href="{e(u("/catalog",{"family":f}))}">{family_label(f)}</a></li>' for f in site.db.families)+'</ul><a href="/compare">Compare reviewed products</a></aside><section><h2>Specification notebooks</h2><div class="grid">'+''.join(card(site,a) for a in rows[:12])+'</div></section></div>'
    elif site.layout=='editorial-magazine':
        title='A closer look before you choose'
        body='<section><h2>From the review desk</h2>'+''.join('<article class="card"><p class="byline">'+e(a['author'])+' · '+a['published']+'</p><h2><a href="'+review_url(a)+'">'+e(a['model_name'])+': details and reader responses</a></h2><p>Read the specification breakdown and check which version is covered.</p></article>' for a in rows[:8])+'</section>'
    else:
        title='Find your next favourite. Read what others thought.'
        body='<div class="two"><section class="feed"><h2>Recent community activity</h2>'
        recent=sorted(((a,c) for a in rows for c in a['reader_opinions']),key=lambda x:(x[1]['date'],x[1]['id']),reverse=True)[:16]
        body+=''.join(opinion(site,a,c) for a,c in recent) or '<p>No reader activity yet.</p>'
        body+='</section><aside><h2>Explore products</h2>'+''.join(card(site,a) for a in rows[:5])+'</aside></div>'
    return document(site,'Home',f'<main id="main"><section class="hero"><h1>{title}</h1><p>Browse {len(rows)} reviews across this publication’s coverage.</p><a class="button" href="/catalog">Explore reviews</a></section>{body}</main>')


def select(name,label,options,current=''):
    return f'<label>{e(label)}<select name="{name}">'+''.join(f'<option value="{e(value)}"'+(' selected' if str(value)==current else '')+f'>{e(text)}</option>' for value,text in options)+'</select></label>'


def pagination(path,q,count,size):
    total=max(1,(count+size-1)//size);page=min(int(q.get('page','1')),total)
    bits=[f'<span>Page {page} of {total}</span>']
    if page>1:bits.insert(0,f'<a href="{e(u(path,{**q,"page":page-1}))}">Previous</a>')
    if page<total:bits.append(f'<a href="{e(u(path,{**q,"page":page+1}))}">Next</a>')
    return page,'<nav class="pagination" aria-label="Pagination">'+''.join(bits)+'</nav>'


def facet_controls(site,q):
    out=[]
    for key,facet in site.db.facets().items():
        title,unit=field_info(facet['family'],key)
        if unit and unit not in title:title+=' ('+unit+')'
        values=facet['values']
        if facet['kind']=='range':
            choices=[('', 'Any')]+[(str(v),pretty(v)) for v in values]
            controls=''
            for op,label in [('min','Minimum'),('max','Maximum')]:
                options=list(choices);selected=q.get(op+'.'+key,'')
                if selected and selected not in [v for v,_ in options]:options.append((selected,selected))
                controls+=select(op+'.'+key,title+' — '+label.lower(),options,selected)
            out.append('<fieldset><legend>'+e(title)+'</legend>'+controls+'</fieldset>');continue
        if facet['kind']=='boolean':
            selected=q.get('f.'+key,[])
            if isinstance(selected,str):selected=[selected]
            if len(selected)>1:raise ValueError('Choose Any rather than both boolean values')
            out.append(select('f.'+key,title,[('','Any')]+[(token(v),pretty(v)) for v in values],selected[0] if selected else ''));continue
        for op,legend in [('f',title)]+([('x','Exclude '+title.lower())] if facet['exclude'] else []):
            selected=q.get(op+'.'+key,[])
            if isinstance(selected,str):selected=[selected]
            labels=''.join('<label class="choice"><input type="checkbox" name="'+op+'.'+e(key)+'" value="'+e(token(v))+'"'+(' checked' if token(v) in selected else '')+'>'+e(pretty(v))+'</label>' for v in values)
            out.append('<fieldset><legend>'+e(legend)+'</legend>'+labels+'</fieldset>')
    return '<div class="facets">'+''.join(out)+'</div>'


def listing(site,q):
    rows=site.db.find(q);page,pages=pagination('/catalog',q,len(rows),site.page_size)
    words=common_vocabulary(site.db.families)
    header='<label>Product or keyword<input type="search" name="q" value="'+e(q.get('q',''))+'"></label>'+select('family','Category',[('','All categories')]+[(f,family_label(f)) for f in site.db.families],q.get('family',''))+select('sort','Sort reviews',[('name','Product name'),('newest','Newest review'),('rating','Reader rating')],q.get('sort','name'))
    legacy=''
    if q.get('field'):
        legacy='<p>Exact filter: '+e(q['field'])+' = '+e(q['value'])+'</p><input type="hidden" name="field" value="'+e(q['field'])+'"><input type="hidden" name="value" value="'+e(q['value'])+'">'
    exclusion_help=' Exclusions remove products containing any checked ingredient.' if any(f['exclude'] for f in site.db.facets().values()) else ''
    form='<form class="catalog-filters" action="/catalog" method="get">'+header+'<button>Apply filters</button><a href="/catalog">Clear filters</a>'+legacy+facet_controls(site,q)+'</form><p class="muted">Match any checked value within a group, and every selected group.'+exclusion_help+' Filters apply to the '+e(words.item)+' covered by each review.</p>'
    selected=rows[(page-1)*site.page_size:page*site.page_size]
    cards=''.join(card(site,a) for a in selected) or '<p>No reviewed products match these filters.</p>'
    if site.layout=='lab-directory':body='<div class="catalog"><aside><h2>Filters</h2>'+form+'</aside><section><div class="grid">'+cards+'</div>'+pages+'</section></div>'
    elif site.layout=='editorial-magazine':body='<details open><summary>Find a review</summary>'+form+'</details><section>'+cards+'</section>'+pages
    else:body=form+'<section class="grid">'+cards+'</section>'+pages
    return document(site,'Review catalog',f'<main id="main"><h1>Reviews ({len(rows)})</h1>{body}</main>')


def byline(a):return f'<p class="byline">By <a href="{structure.person_url("contributors",a["author"])}">{e(a["author"])}</a> · Published <time>{a["published"]}</time></p>'
def scope(site,a):
    v=site.db.variants[a['reviewed_sku']];words=vocabulary(a['family'])
    return f'<section class="card" id="scope"><h2>{e(words.covered)}</h2><p><strong>{e(v["name"])}</strong></p><p>SKU: <a href="{variant_url(v)}">{e(v["sku"])}</a></p><p>{e(words.coverage_note)}</p></section>'


def related(site,a):
    peers=[x for x in site.db.articles if x['family']==a['family'] and x['id']!=a['id']]
    return '<section><h2>More in this category</h2>'+(''.join(card(site,p) for p in peers[:site.related_count]) or '<p>No other reviewed products in this category.</p>')+'</section>'


def variants(site,a):
    rows=sorted((v for v in site.db.variants.values() if v['model_id']==a['id']),key=lambda v:v['sku'])
    return '<details><summary>'+e(vocabulary(a['family']).alternatives)+' ('+str(len(rows))+')</summary><p>Product details are available for these options; they are not separate reviewed results.</p><ul>'+''.join(f'<li><a href="{variant_url(v)}">{e(v["name"])}</a></li>' for v in rows)+'</ul></details>'


def retailer_link(site,v):
    link=site.db.bindings.get(v['sku'])
    return f'<p><a class="button" href="{e(link)}">View this {e(vocabulary(v['family']).item)} at a retailer</a></p>' if link else ''


def grouped_sections(v):
    used=set();parts=[]
    for index,(title,keys) in enumerate(GROUPS[v['family']]):
        present=[k for k in keys if k in v['facts']];used.update(present)
        sentences=' '.join(f'{field_info(v["family"],k)[0]}: {fact_text(v,k)}.' for k in present)
        parts.append(f'<section id="section-{index}"><h2>{e(title)}</h2><p>{e(sentences) if present else "No fields supplied for this section."}</p>'+fact_table(v,present)+'</section>')
    extra=[k for k in v['facts'] if k not in used]
    if extra:parts.append('<section><h2>Additional recorded details</h2>'+fact_table(v,extra)+'</section>')
    return ''.join(parts)


def opinion(site,a,c):
    return f'<article class="entry"><p><strong><a href="{structure.person_url("members",c["handle"])}">{e(c["handle"])}</a></strong> reviewed <a href="{review_url(a)}">{e(a["model_name"])}</a></p><p><span role="img" aria-label="{c["stars"]} out of 5 stars">'+('★'*c['stars'])+f'</span> · <time>{c["date"]}</time></p><h3>{e(c["title"])}</h3><p>{e(c["body"])}</p><a href="{review_url(a)}/opinions/{c["id"]}">Read this reader note</a></article>'


def reader_section(site,a,q):
    rows=site.db.opinions(a,q);page,pages=pagination(review_url(a),q,len(rows),site.page_size)
    controls='<form method="get" action="'+review_url(a)+'">'
    if site.layout=='editorial-magazine':controls+='<input type="hidden" name="part" value="readers">'
    controls+=select('stars','Rating',[('','All ratings')]+[(str(i),f'{i} stars') for i in range(1,6)],q.get('stars',''))+select('sort','Sort reader notes',[('newest','Newest first'),('lowest','Lowest rating first')],q.get('sort','newest'))+'<button>Filter reader notes</button></form>'
    summary=f'<p class="score">{mean(a)}'+(' / 5' if a['reader_opinions'] else '')+f'</p><p>{len(a["reader_opinions"])} total reader ratings · {len(rows)} match filters</p>'
    hist='<ul>'+''.join(f'<li>{i} stars: {a["reader_statistics"]["histogram"][str(i)]}</li>' for i in range(5,0,-1))+'</ul>'
    return '<section id="readers"><h2>Reader opinions</h2>'+summary+hist+controls+'<div class="feed">'+(''.join(opinion(site,a,c) for c in rows[(page-1)*site.page_size:page*site.page_size]) or '<p>No reader notes match.</p>')+'</div>'+pages+'</section>'


def review(site,a,q):
    v=site.db.variants[a['reviewed_sku']];words=vocabulary(a['family']);title=e(a['model_name'])+' review'
    header='<nav aria-label="Breadcrumb"><a href="/catalog">Reviews</a> / <a href="'+e(u('/catalog',{'family':a['family']}))+'">'+family_label(a['family'])+'</a></nav><h1>'+title+'</h1>'+byline(a)
    caution='<section id="limitations"><h2>What this does and does not establish</h2><p>'+e(CAUTIONS[a['family']])+'</p><p>These are recorded catalog facts, not independent laboratory measurements. No lab result is available for fields not shown.</p><a href="/methodology">Read the methodology</a></section>'
    if site.layout=='lab-directory':
        toc='<aside>'+structure.contents(site,a)+'</aside>'
        main='<article>'+header+picture(v)+scope(site,a)+structure.compare_table(site,a)+structure.attribute_sections(site,a)+caution+variants(site,a)+reader_section(site,a,q)+'</article>'
        sidebar='<aside><h2>Compare before choosing</h2><a href="'+e(u('/compare',{'left':a['id']}))+'">Compare '+e(words.plural)+'</a>'+retailer_link(site,v)+structure.publication_sidebar(site,a)+'</aside>'
        body='<div class="columns">'+toc+main+sidebar+'</div>'
    elif site.layout=='editorial-magazine':
        part=q.get('part','overview')
        nav='<nav aria-label="Article pages">'+''.join(f'<a class="tag" href="{e(u(review_url(a),{"part":k}))}"'+(' aria-current="page"' if k==part else '')+f'>{label}</a>' for k,label in [('overview','1. Overview'),('specifications','2. '+words.facts_title),('readers','3. Reader responses')])+'</nav>'
        if part=='overview':content=picture(v)+scope(site,a)+'<section><h2>The review desk’s take</h2><p>Check the '+e(words.item)+' rather than relying on the name alone. This article records the product details and keeps reader opinions separate.</p></section>'+structure.compare_table(site,a)+grouped_sections(v)+caution+retailer_link(site,v)+f'<a class="button" href="{review_url(a)}?part=specifications">Continue to {e(words.facts_title.lower())}</a>'
        elif part=='specifications':content=scope(site,a)+grouped_sections(v)+variants(site,a)+f'<a href="{review_url(a)}?part=readers">Continue to reader responses</a>'
        else:content=reader_section(site,a,q)
        body=header+nav+'<div class="two"><article>'+content+'</article><aside><h2>From the same desk</h2>'+structure.publication_sidebar(site,a)+'<a href="'+e(u('/compare',{'left':a['id']}))+'">Compare '+e(words.plural)+'</a></aside></div>'
    else:
        description='<dl>'+''.join(f'<dt>{e(field_info(v["family"],k)[0])}</dt><dd>{e(fact_text(v,k))}</dd>' for k in v['facts'])+'</dl>'
        body='<div class="two"><div><section class="product-head">'+picture(v)+'<div>'+header+'<p class="score">'+mean(a)+'</p><p>'+str(len(a['reader_opinions']))+' reader ratings</p></div></section><details open><summary>'+e(words.facts_title)+'</summary>'+scope(site,a)+description+'</details>'+structure.community_stats(site,a)+reader_section(site,a,q)+'</div><aside>'+caution+variants(site,a)+retailer_link(site,v)+related(site,a)+'</aside></div>'
    return document(site,a['model_name']+' review','<main id="main">'+body+'</main>')


def variant(site,v):
    a=site.db.by_id[v['model_id']]
    words=vocabulary(v['family'])
    status='This is the '+words.item+' covered by the article.' if a['reviewed_sku']==v['sku'] else 'This '+words.item+' has catalog facts only; the article covers a different SKU.'
    return document(site,v['name'],'<main id="main"><h1>'+e(v['name'])+'</h1><p>'+status+'</p><p>SKU: '+e(v['sku'])+'</p>'+fact_table(v)+retailer_link(site,v)+'<p><a href="'+review_url(a)+'">Return to review</a></p></main>')


def comparison(site,q):
    words=common_vocabulary(site.db.families)
    opts=[('','Choose a reviewed '+words.item)]+[(a['id'],site.db.variants[a['reviewed_sku']]['name']) for a in site.db.find({})]
    form='<form action="/compare" method="get">'+select('left','First '+words.item,opts,q.get('left',''))+select('right','Second '+words.item,opts,q.get('right',''))+'<button>Compare</button></form>'
    body='<p>Compare reviewed '+e(words.plural)+' from the same category. Reader scores express opinions, not a universal winner.</p>'+form
    if q.get('left') and q.get('right'):
        aa=[site.db.by_id[q[k]] for k in ('left','right')]
        if aa[0]['family']!=aa[1]['family']:raise ValueError('Choose products from the same category')
        vs=[site.db.variants[a['reviewed_sku']] for a in aa];fields=sorted(set(vs[0]['facts'])|set(vs[1]['facts']))
        body+='<div class="scroll-table"><table class="facts"><caption>Side-by-side product details</caption><thead><tr><th scope="col">Attribute</th>'+''.join('<th scope="col"><a href="'+review_url(a)+'">'+e(a['model_name'])+'</a></th>' for a in aa)+'</tr></thead><tbody><tr><th scope="row">Reviewed SKU</th>'+''.join('<td>'+e(v['sku'])+'</td>' for v in vs)+'</tr>'
        for k in fields:body+='<tr><th scope="row">'+e(field_info(vs[0]['family'],k)[0])+'</th>'+''.join('<td>'+e(fact_text(v,k) if k in v['facts'] else 'Not reported')+'</td>' for v in vs)+'</tr>'
        body+='<tr><th scope="row">Reader average</th>'+''.join('<td>'+mean(a)+' ('+str(len(a['reader_opinions']))+' ratings)</td>' for a in aa)+'</tr></tbody></table></div>'
    return document(site,'Compare '+words.plural,'<main id="main"><h1>Compare '+e(words.plural)+'</h1>'+body+'</main>')


def methodology(site):
    return document(site,'Methodology','''<main id="main"><h1>How this publication works</h1><section><h2>Know which product was reviewed</h2><p>Each article covers one explicitly identified SKU. Other variants have separate specification pages. A result must not be transferred to another size, recipe, vintage or hardware configuration without evidence.</p></section><section><h2>Facts and opinions</h2><p>Specifications are reproduced from the generated product catalog. No independent laboratory tests, feeding trials, benchmark runs or tasting measurements have been performed. Unknown measurements remain unreported.</p><p>Reader ratings are fictional personal opinions. The displayed average uses every rating in the bounded corpus. Filtering or pagination does not change it. An empty corpus is not rated.</p></section><section><h2>Dates and coverage</h2><p>Review dates describe the publication record. They do not establish current retailer stock, checkout prices or delivery eligibility.</p></section><section><h2>Retailer links</h2><p>Retailer links, where present, identify a specific product option. Recheck the retailer’s current offer and final checkout conditions.</p></section></main>''')
