"""Reference-inspired navigation and article depth using public facts only.

No lab measurements, merchant quotes or social relationships are synthesized here.
All counts refer to the publication's bounded, reviewed-SKU corpus.
"""
from collections import Counter
from urllib.parse import quote
from . import render as r
from .data import fact_text, field_info, pretty
from .facets import token


def person_url(kind, name):
    return '/' + kind + '/' + quote(name, safe='')


def topic_links(site, family, limit=6):
    links=[]
    for key, facet in site.db.facets().items():
        if facet['family'] != family or facet['kind']=='range':continue
        for value in facet['values'][:3]:
            label=field_info(family,key)[0]+': '+pretty(value)
            links.append('<a href="'+r.e(r.u('/catalog',{'family':family,'f.'+key:token(value)}))+'">'+r.e(label)+'</a>')
        if len(links)>=limit:break
    return links[:limit]


def discovery_nav(site):
    if site.layout=='community-feed':
        return '<nav class="topic-strip" aria-label="Explore community"><a href="/activity">All recent activity</a><a href="/members">Reader directory</a><a href="/catalog?sort=rating">Browse by rating</a><a href="/compare">Compare product details</a></nav>'
    groups=[]
    for family in site.db.families:
        links=topic_links(site,family)
        if links:groups.append('<details><summary>'+r.family_label(family)+' topics</summary><ul>'+''.join('<li>'+link+'</li>' for link in links)+'</ul><a href="'+r.e(r.u('/catalog',{'family':family}))+'">All '+r.family_label(family).lower()+' reviews</a></details>')
    if site.layout=='editorial-magazine':
        latest=site.db.find({'sort':'newest'})[:4]
        return '<div class="topic-strip">'+''.join(groups)+'</div><nav class="topic-strip" aria-label="Latest coverage"><strong>Latest coverage</strong>'+''.join('<a href="'+r.review_url(a)+'">'+r.e(a['model_name'])+'</a>' for a in latest)+'</nav>'
    return '<nav class="topic-strip" aria-label="Browse review topics">'+''.join(groups)+'<a href="/contributors">Meet the review desk</a></nav>'


def footer(site):
    cols=[('Explore', [('/catalog','All product reviews'),('/compare','Side-by-side comparisons'),('/activity','Recent reader notes')]),
          ('Publication', [('/contributors','Contributors'),('/members','Reader directory'),('/methodology','Facts, opinions and coverage')]),
          ('Categories', [(r.u('/catalog',{'family':f}),r.family_label(f)) for f in site.db.families])]
    return '<div class="grid">'+''.join('<section><h2>'+title+'</h2><ul>'+''.join('<li><a href="'+r.e(url)+'">'+r.e(label)+'</a></li>' for url,label in rows)+'</ul></section>' for title,rows in cols)+'</div>'


def peers(site,a):
    return [p for p in site.db.articles if p['family']==a['family'] and p['id']!=a['id']][:3]


def compare_table(site,a):
    rows=[a]+peers(site,a)
    variants=[site.db.variants[p['reviewed_sku']] for p in rows]
    fields=list(dict.fromkeys(k for v in variants for k in v['facts']))
    out='<section id="comparison"><h2>Comparison with other reviewed products</h2><p>Each column describes the exact option covered by its article. Ratings are reader opinions, not laboratory scores.</p><div class="scroll-table"><table class="facts"><caption>Reviewed products in this category</caption><thead><tr><th scope="col">Attribute</th>'
    out+=''.join('<th scope="col"><a href="'+r.review_url(p)+'">'+r.e(p['model_name'])+'</a></th>' for p in rows)+'</tr></thead><tbody>'
    out+='<tr><th scope="row">Reviewed SKU</th>'+''.join('<td>'+r.e(v['sku'])+'</td>' for v in variants)+'</tr>'
    for key in fields:
        out+='<tr><th scope="row">'+r.e(field_info(a['family'],key)[0])+'</th>'+''.join('<td>'+r.e(fact_text(v,key) if key in v['facts'] else 'Not reported')+'</td>' for v in variants)+'</tr>'
    out+='<tr><th scope="row">Reader average / 5</th>'+''.join('<td>'+r.mean(p)+'</td>' for p in rows)+'</tr>'
    out+='<tr><th scope="row">Reader ratings</th>'+''.join('<td>'+str(len(p['reader_opinions']))+'</td>' for p in rows)+'</tr></tbody></table></div></section>'
    return out


def attribute_sections(site,a):
    v=site.db.variants[a['reviewed_sku']]
    corpus=[site.db.variants[p['reviewed_sku']] for p in site.db.articles if p['family']==a['family']]
    out=[]
    for i,(title,keys) in enumerate(r.GROUPS[a['family']]):
        out.append('<section id="section-'+str(i)+'"><h2>'+r.e(title)+'</h2>')
        for key in keys:
            if key not in v['facts']:continue
            label=field_info(a['family'],key)[0];value=v['facts'][key]
            out.append('<section id="fact-'+r.e(key)+'"><h3>'+r.e(label)+'</h3><p>'+r.e(label)+': <strong>'+r.e(fact_text(v,key))+'</strong>.</p>')
            reported=[x['facts'][key] for x in corpus if key in x['facts']]
            # Complete exact values only; no lab-scale visual or inferred superiority.
            counts=Counter(token(x) for x in reported)
            n=counts[token(value)]
            out.append('<table class="facts"><caption>'+r.e(label)+' in this publication</caption><tbody><tr><th scope="row">This reviewed option</th><td>'+r.e(fact_text(v,key))+'</td></tr><tr><th scope="row">Same recorded value</th><td>'+str(n)+' of '+str(len(reported))+' reviewed options with this field</td></tr>')
            facet=site.db.facets().get(key)
            if facet and facet['kind']=='range' and reported:
                unit=field_info(a['family'],key)[1] or ''
                out.append('<tr><th scope="row">Recorded range</th><td>'+r.e(pretty(min(reported))+' – '+pretty(max(reported))+' '+unit)+'</td></tr>')
            out.append('</tbody></table>')
            # Link to real filters, including constituent values of a set.
            if facet:
                values=value if isinstance(value,list) else [value]
                links=[]
                for val in values:
                    q={'family':a['family']}
                    if facet['kind']=='range':q.update({'min.'+key:str(val),'max.'+key:str(val)})
                    else:q['f.'+key]=token(val)
                    links.append('<a href="'+r.e(r.u('/catalog',q))+'">Browse '+r.e(label.lower())+': '+r.e(pretty(val))+'</a>')
                out.append('<ul>'+''.join('<li>'+link+'</li>' for link in links)+'</ul>')
            out.append('</section>')
        out.append('</section>')
    extra=[k for k in v['facts'] if not any(k in keys for _,keys in r.GROUPS[a['family']])]
    if extra:out.append(r.fact_table(v,extra))
    return ''.join(out)


def contents(site,a, *, detailed=True):
    facts=site.db.variants[a["reviewed_sku"]]["facts"]
    groups=[]
    for i,(title,keys) in enumerate(r.GROUPS[a['family']]):
        nested='<ul>'+''.join('<li><a href="#fact-'+r.e(k)+'">'+r.e(field_info(a['family'],k)[0])+'</a></li>' for k in keys if k in facts)+'</ul>' if detailed else ''
        groups.append('<li><a href="#section-'+str(i)+'">'+r.e(title)+'</a>'+nested+'</li>')
    return '<nav aria-label="On this page"><h2>Contents</h2><ul><li><a href="#scope">Reviewed option</a></li><li><a href="#comparison">Comparison</a></li>'+''.join(groups)+'<li><a href="#limitations">Limitations</a></li><li><a href="#readers">Reader opinions</a></li></ul></nav>'


def publication_sidebar(site,a):
    author=person_url('contributors',a['author'])
    others=[x for x in site.db.find({'sort':'newest'}) if x['id']!=a['id']][:4]
    return '<section><h2>About the contributor</h2><p><a href="'+author+'">'+r.e(a['author'])+'</a></p><p>Browse this contributor’s published product coverage.</p></section><section><h2>Latest from the publication</h2><ol>'+''.join('<li><a href="'+r.review_url(x)+'">'+r.e(x['model_name'])+'</a><p><time>'+x['published']+'</time> · '+r.family_label(x['family'])+'</p></li>' for x in others)+'</ol></section>'+r.related(site,a)


def community_stats(site,a):
    notes=a['reader_opinions'];n=len(notes)
    members=len({c['handle'] for c in notes})
    dates=sorted(c['date'] for c in notes)
    out='<section id="activity-summary"><h2>Community snapshot</h2><dl><dt>Total ratings</dt><dd>'+str(n)+'</dd><dt>Contributing readers</dt><dd>'+str(members)+'</dd><dt>First recorded note</dt><dd>'+(dates[0] if dates else 'None')+'</dd><dt>Latest recorded note</dt><dd>'+(dates[-1] if dates else 'None')+'</dd></dl><nav aria-label="Product activity"><a href="#readers">Recent notes</a><a href="#rating-distribution">Rating breakdown</a><a href="'+r.e(r.u('/activity',{'family':a['family']}))+'">Category activity</a></nav></section>'
    out+='<section id="rating-distribution"><h2>Rating distribution</h2><ul>'
    for star in range(5,0,-1):
        count=a['reader_statistics']['histogram'][str(star)]
        out+='<li><a href="'+r.e(r.u(r.review_url(a),{'stars':star}))+'">'+str(star)+' stars · '+str(count)+' ratings</a><meter min="0" max="'+str(max(1,n))+'" value="'+str(count)+'" aria-label="'+str(star)+' star ratings"></meter></li>'
    out+='</ul></section><section><h2>Recent contributors</h2><ul>'+''.join('<li><a href="'+person_url('members',c['handle'])+'">'+r.e(c['handle'])+'</a> · '+c['date']+'</li>' for c in sorted(notes,key=lambda c:(c['date'],c['id']),reverse=True)[:6])+'</ul></section>'
    return out


def all_notes(site,q):
    family=q.get('family','');stars=q.get('stars','')
    if family and family not in site.db.families:raise ValueError('Unknown category')
    return sorted(((a,c) for a in site.db.articles for c in a['reader_opinions'] if (not family or a['family']==family) and (not stars or str(c['stars'])==stars)),key=lambda pair:(pair[1]['date'],pair[1]['id']),reverse=True)


def archive(site,path,q):
    """Read-only public contributor/member archives; never imply login or follows."""
    if path=='/activity':
        rows=all_notes(site,q);page,pages=r.pagination(path,q,len(rows),site.page_size)
        controls='<form action="/activity">'+r.select('family','Activity category',[('','All categories')]+[(f,r.family_label(f)) for f in site.db.families],q.get('family',''))+r.select('stars','Activity rating',[('','All ratings')]+[(str(i),str(i)+' stars') for i in range(1,6)],q.get('stars',''))+'<button>Filter activity</button></form>'
        body='<h1>Recent reader activity</h1>'+controls+'<p>'+str(len(rows))+' recorded notes</p>'+''.join(r.opinion(site,a,c) for a,c in rows[(page-1)*site.page_size:page*site.page_size])+pages
    else:
        kind=path.split('/')[1];name=path[len(kind)+2:]
        people=sorted({a['author'] for a in site.db.articles}) if kind=='contributors' else sorted({c['handle'] for a,c in all_notes(site,{})})
        if name:
            if name not in people:raise KeyError('Unknown profile')
            if kind=='contributors':
                rows=[a for a in site.db.find({'sort':'newest'}) if a['author']==name]
                page,pages=r.pagination(path,q,len(rows),site.page_size)
                body='<h1>'+r.e(name)+'</h1><p>'+str(len(rows))+' published reviews</p>'+''.join(r.card(site,a) for a in rows[(page-1)*site.page_size:page*site.page_size])+pages
            else:
                rows=[(a,c) for a,c in all_notes(site,{}) if c['handle']==name];page,pages=r.pagination(path,q,len(rows),site.page_size)
                body='<h1>'+r.e(name)+'</h1><p>'+str(len(rows))+' recorded reader notes. This archive describes published activity only.</p>'+''.join(r.opinion(site,a,c) for a,c in rows[(page-1)*site.page_size:page*site.page_size])+pages
        else:
            page,pages=r.pagination(path,q,len(people),site.page_size)
            body='<h1>'+('Contributors' if kind=='contributors' else 'Reader directory')+'</h1><ul>'+''.join('<li><a href="'+person_url(kind,p)+'">'+r.e(p)+'</a></li>' for p in people[(page-1)*site.page_size:page*site.page_size])+'</ul>'+pages
    return r.document(site,'Publication archive','<main id="main">'+body+'</main>')
