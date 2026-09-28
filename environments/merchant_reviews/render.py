"""Server-rendered review directory and merchant profiles. No remote assets/scripts."""
from html import escape
from urllib.parse import urlencode,quote
from decimal import Decimal,ROUND_HALF_UP
from .data import TOPICS

REVIEW_PAGE_SIZE=20


def e(value):return escape(str(value),quote=True)
def label(value):return str(value).replace('_',' ').capitalize()
def company_url(c):return '/review/'+quote(c['company_id'],safe='')
def review_url(r):return '/reviews/'+quote(r['review_id'],safe='')
def url(path,query):return path+('?' + urlencode({k:v for k,v in query.items() if v not in ('',None)}) if any(v not in ('',None) for v in query.values()) else '')
def average(c):
    reviews=c['reviews']
    return str((Decimal(sum(r['stars'] for r in reviews))/len(reviews)).quantize(Decimal('.1'),rounding=ROUND_HALF_UP)) if reviews else 'Not rated'

STYLE='''<style>
*{box-sizing:border-box}body{margin:0;background:#f5f5f1;color:#202622;font:16px/1.55 system-ui,sans-serif}a{color:#2454a4;text-underline-offset:3px}header{background:#20221f;color:white;padding:16px max(20px,6vw);display:flex;align-items:center;gap:30px;flex-wrap:wrap}header a{color:white;text-decoration:none}.brand{font-weight:750;font-size:25px}.brand:before{content:'✦';color:#45d3a4;margin-right:8px}header nav{display:flex;gap:24px}input,select,button{font:inherit;padding:11px;border:1px solid #aaa;border-radius:5px}button,.button{background:#275cc8;color:white;border:0;border-radius:24px;padding:12px 22px;cursor:pointer}input[type=search]{min-width:0;flex:1}form.search{display:flex;gap:8px;max-width:670px}header .search{flex:1;min-width:230px}label{display:grid;gap:5px}.wrap,main{max-width:1200px;margin:auto;padding:28px 20px}.hero{text-align:center;background:#fdfbf1;padding:70px 20px}.hero h1{font-size:clamp(30px,4vw,48px);margin:0 0 12px}.hero p{font-size:21px}.hero form{margin:30px auto}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}.card{border:1px solid #dedfd9;background:white;border-radius:12px;padding:24px;min-width:0}.card h3{margin:.4rem 0}.categories{display:flex;flex-wrap:wrap;gap:12px;padding:0;list-style:none}.categories a{display:block;padding:12px 18px;border:1px solid #ccc;border-radius:24px;background:white}.company-heading{background:white;border-radius:22px;padding:32px;margin-bottom:22px}.company-heading h1{font-size:36px;margin:.2rem 0}.domain{color:#5e625d;overflow-wrap:anywhere}.stars{display:inline-flex;gap:3px;font-size:18px;vertical-align:middle}.stars span{display:inline-block;background:#087e60;color:white;padding:0 4px}.stars .empty{background:#cbd0cb}.score{font-size:44px;font-weight:750;margin:0}.subnav{display:flex;gap:24px;border-top:1px solid #ddd;padding-top:18px;margin-top:20px}.columns{display:grid;grid-template-columns:minmax(0,2fr) minmax(280px,1fr);gap:24px;align-items:start}.columns aside{display:grid;gap:18px}.distribution{display:grid;gap:12px}.distribution a{display:grid;grid-template-columns:55px 1fr 85px;align-items:center;gap:8px;color:inherit}.distribution meter{width:100%;height:18px}.filters{display:flex;flex-wrap:wrap;gap:12px;align-items:end;background:#eee;padding:18px;margin:20px 0}.filters label{flex:1;min-width:130px}.review-list{display:grid;gap:18px}.review-header{display:flex;align-items:center;gap:12px}.avatar{background:#e2e9dd;border-radius:50%;padding:12px;font-weight:700}.review-date{font-size:14px;color:#626962}.review h3{font-size:19px}.review-body{white-space:pre-line;overflow-wrap:anywhere}.review details{margin-top:18px;background:#f4f6f2;padding:14px;border-left:3px solid #a6b39e}.review summary{cursor:pointer;font-weight:600}.review small{display:block;margin:12px 0;color:#5d635a}.pagination{display:flex;gap:16px;align-items:center;margin:28px 0}.pagination a{border:1px solid #aaa;padding:8px 14px;background:white;border-radius:5px}.muted{color:#60665e}.highlights{margin:20px 0}.highlights .grid{grid-template-columns:repeat(2,minmax(0,1fr))}.highlights p{overflow-wrap:anywhere}footer{background:#22251f;color:white;margin-top:40px;padding:35px max(20px,6vw)}footer a{color:white}footer nav{display:flex;gap:24px;flex-wrap:wrap}.results{display:grid;gap:18px}.empty{padding:30px;border:1px dashed #aaa;background:white}.skip{position:absolute;left:-9999px}.skip:focus{left:10px;background:white;z-index:3}.heading-row{display:flex;align-items:center;justify-content:space-between;gap:20px}a:focus-visible,button:focus-visible,summary:focus-visible{outline:3px solid #dd9711;outline-offset:3px}@media(max-width:800px){.columns{grid-template-columns:1fr}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.highlights .grid{grid-template-columns:1fr}}@media(max-width:480px){.grid{grid-template-columns:1fr}header{gap:14px}.hero{padding:40px 18px}.subnav{gap:12px}.card{padding:18px}form.search{flex-wrap:wrap}.company-heading{padding:20px}}
</style>'''


def search_form(query='',name='Search companies',category=''):
    return f'<form class="search" action="/search" method="get"><label style="flex:1">{e(name)}<input type="search" name="q" value="{e(query)}" placeholder="Company name, website or category"></label><button type="submit">Search</button></form>'


def document(title,body,site_name="Omdömeskollen"):
    return f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)} | {e(site_name)}</title>{STYLE}</head><body><a class="skip" href="#main">Skip to content</a><header><a class="brand" href="/">{e(site_name)}</a>{search_form(name="Find a company")}<nav aria-label="Primary"><a href="/categories">Categories</a><a href="/about">How reviews work</a></nav></header>{body}<footer><nav aria-label="Footer"><a href="/">Explore reviews</a><a href="/categories">All categories</a><a href="/about">About ratings and reviews</a></nav><p>Synthetic merchant-review directory. Reviews describe individual experiences, not guarantees about your next purchase.</p></footer></body></html>'


def stars(value):
    return '<span class="stars" role="img" aria-label="'+str(value)+' out of 5 stars">'+''.join('<span'+(' class="empty"' if i>value else '')+' aria-hidden="true">★</span>' for i in range(1,6))+'</span>'


def company_card(c):
    return f'<article class="card"><h3><a href="{company_url(c)}">{e(c["name"])}</a></h3><p class="domain">{e(c["domain"])}</p><p>{e(c["category"])}</p><p><strong>{average(c)}</strong>{" / 5" if c["reviews"] else ""} · {len(c["reviews"])} reviews</p><a href="{company_url(c)}">Read reviews</a></article>'


def review_card(c,r,full=True):
    reply=r['company_reply'];reply_html=''; heading_id=('title-' if full else 'preview-title-')+r['review_id']
    if reply:
        reply_html=f'<details><summary>Reply from {e(c["name"])}</summary><time datetime="{e(reply["published_date"])}">{e(reply["published_date"])}</time><p>{e(reply["body"])}</p></details>'
    return f'<article class="card review" aria-labelledby="{e(heading_id)}"><div class="review-header"><span class="avatar" aria-hidden="true">{e(r["reviewer"]["handle"][:2].upper())}</span><div><strong>{e(r["reviewer"]["handle"])}</strong><div class="review-date">Published <time datetime="{e(r["published_date"])}">{e(r["published_date"])}</time></div></div></div><p>{stars(r["stars"])}</p><h3 id="{e(heading_id)}"><a href="{review_url(r)}">{e(r["title"])}</a></h3><p class="review-body">{e(r["body"] if full else r["body"][:180]+("…" if len(r["body"])>180 else ""))}</p><small>Experience date: <time datetime="{e(r["experience_date"])}">{e(r["experience_date"])}</time> · {e(label(r["topic"]))}</small>{reply_html if full else ""}<a href="{review_url(r)}">Read this review</a></article>'


def categories(db):return sorted({c['category'] for c in db.companies})
def category_links(db):return '<ul class="categories">'+''.join(f'<li><a href="{e(url("/search",{"category":c}))}">{e(c)}</a></li>' for c in categories(db))+'</ul>'


def home(db):
    body='<main id="main" style="max-width:none;padding:0"><section class="hero"><h1>Read the experience behind the rating</h1><p>Find companies. Compare experiences. Make your own choice.</p>'+search_form(name='Search company or category')+'<a href="/about">What can reviews tell you?</a></section><div class="wrap"><h2>Explore by category</h2>'+category_links(db)
    for category in categories(db)[:4]:
        rows=db.search({'category':category,'sort':'rating'})[:3]
        body+=f'<section><div class="heading-row"><h2>{e(category)}</h2><a href="{e(url("/search",{"category":category}))}">See all</a></div><div class="grid">'+''.join(company_card(c) for c in rows)+'</div></section>'
    latest=sorted(db.by_review.values(),key=lambda pair:(pair[1]['published_date'],pair[1]['review_id']),reverse=True)[:6]
    body+='<section><h2>Recent experiences</h2><div class="grid">'+''.join('<section><p>Review of <a href="'+company_url(c)+'">'+e(c['name'])+'</a></p>'+review_card(c,r,False)+'</section>' for c,r in latest)+'</div></section></div></main>'
    return document('Company reviews',body,db.site_name)


def select(name,title,values,current):
    return f'<label>{e(title)}<select name="{e(name)}">'+''.join(f'<option value="{e(v)}"'+(' selected' if str(v)==current else '')+f'>{e(t)}</option>' for v,t in values)+'</select></label>'


def pages(path,query,count,per_page):
    total=max(1,(count+per_page-1)//per_page);page=min(int(query.get('page','1')),total)
    links=[]
    if page>1:links.append(f'<a rel="prev" href="{e(url(path,{**query,"page":page-1}))}">Previous</a>')
    links.append(f'<span>Page {page} of {total}</span>')
    if page<total:links.append(f'<a rel="next" href="{e(url(path,{**query,"page":page+1}))}">Next</a>')
    return page,'<nav class="pagination" aria-label="Pagination">'+''.join(links)+'</nav>'


def search(db,q):
    rows=db.search(q);page,pagination=pages('/search',q,len(rows),8)
    form='<form class="filters" method="get" action="/search"><label>Company or website<input type="search" name="q" value="'+e(q.get('q',''))+'"></label>'+select('category','Category',[('','All categories')]+[(c,c) for c in categories(db)],q.get('category',''))+select('sort','Sort companies',[('name','Company name'),('rating','Highest average rating'),('count','Most reviews')],q.get('sort','name'))+'<button type="submit">Search companies</button></form>'
    body=f'<main id="main"><h1>Companies ({len(rows)})</h1>{form}<div class="results">'+(''.join(company_card(c) for c in rows[(page-1)*8:page*8]) or '<p class="empty">No companies match your search. Try a company name, domain or another category.</p>')+'</div>'+pagination+'</main>'
    return document('Search companies',body,db.site_name)


def profile(db,c,q):
    stats=c['statistics'];n=len(c['reviews']);path=company_url(c)
    distribution='<div class="distribution">'
    for i in range(5,0,-1):
        count=stats['star_counts'][str(i)];pct=round(100*count/n) if n else 0
        distribution+=f'<a href="{e(url(path,{**q,"stars":str(i),"page":None}))}#reviews" aria-label="{i}-star reviews ({count})"><span>{i}-star</span><meter min="0" max="{max(1,n)}" value="{count}" aria-label="{i}-star count"></meter><span>{count} ({pct}%)</span></a>'
    distribution+='</div>'
    bound=db.bindings.get(c['company_id']);visit=f'<a class="button" href="{e(bound)}">Visit website</a>' if bound else ''
    heading=f'<section class="company-heading" id="summary"><p><a href="{e(url("/search",{"category":c["category"]}))}">{e(c["category"])}</a></p><h1>{e(c["name"])} reviews</h1><p class="domain">{e(c["domain"])}</p><p><strong>{average(c)}</strong>{" / 5" if n else ""} · {n} reviews</p>{visit}<nav class="subnav" aria-label="Company sections"><a href="#summary">Summary</a><a href="#about-company">About</a><a href="#reviews">Reviews</a></nav></section>'
    previews=db.reviews(c['company_id'],{})[:4]
    highlights='<section class="highlights"><h2>Recent reviewer experiences</h2><div class="grid">'+''.join(review_card(c,r,False) for r in previews)+'</div></section>' if previews else ''
    about=f'<section class="card" id="about-company"><h2>Company details</h2><p>{e(c["name"])} · {e(c["category"])}</p><p class="domain">Website identity: {e(c["domain"])}</p>{visit}</section>'
    rows=db.reviews(c['company_id'],q);page,pagination=pages(path,q,len(rows),REVIEW_PAGE_SIZE)
    form=f'<form class="filters" method="get" action="{path}#reviews"><label>Search reviews<input type="search" name="q" value="{e(q.get("q",""))}"></label>'+select('stars','Rating',[('','All ratings')]+[(str(i),str(i)+' stars') for i in range(5,0,-1)],q.get('stars',''))+select('topic','Topic',[('','All topics')]+[(t,label(t)) for t in TOPICS],q.get('topic',''))+select('period','Published',[('','Any time'),('30','Last 30 days'),('90','Last 90 days'),('365','Last 12 months')],q.get('period',''))+select('sort','Sort reviews',[('newest','Most recent'),('oldest','Oldest first'),('lowest','Lowest rating'),('highest','Highest rating')],q.get('sort','newest'))+'<button type="submit">Apply filters</button>'+f'<a href="{path}#reviews">Clear filters</a></form>'
    listing=f'<section id="reviews"><h2>All reviews ({n})</h2><p>{len(rows)} matching reviews · Published through {e(db.as_of)}</p>{form}<div class="review-list">'+(''.join(review_card(c,r) for r in rows[(page-1)*REVIEW_PAGE_SIZE:page*REVIEW_PAGE_SIZE]) or '<p class="empty">No reviews match these filters.</p>')+'</div>'+pagination+'</section>'
    sidebar=f'<aside aria-label="Company rating and related companies"><section class="card"><h2>Review average</h2><p class="score">{average(c)}</p><p>{n} reviews across all ratings</p>{distribution}<p><a href="/about">How is this average calculated?</a></p></section><section class="card"><h2>Company replies</h2><p>{sum(r["company_reply"] is not None for r in c["reviews"])} of {n} reviews have a company reply.</p></section><section><h2>Other companies to explore</h2>'+'</section></aside>'
    # Keep related profiles real, bounded and independent of hidden merchant quality.
    related=[other for other in db.companies if other['company_id']!=c['company_id']]
    related.sort(key=lambda other:(other['category']!=c['category'],other['company_id']))
    sidebar=sidebar.replace('<section><h2>Other companies to explore</h2></section>','<section><h2>Other companies to explore</h2>'+''.join(company_card(other) for other in related[:3])+'</section>')
    return document(c['name']+' reviews','<main id="main">'+heading+'<div class="columns"><div>'+highlights+about+listing+'</div>'+sidebar+'</div></main>',db.site_name)


def about(site_name="Omdömeskollen"):
    return document('How reviews work','''<main id="main"><h1>How ratings and reviews work</h1><section class="card"><h2>One corpus, one average</h2><p>The company average is the arithmetic mean of every review in this directory, shown to one decimal place. It is not Trustpilot’s proprietary TrustScore. Filtering or changing pages does not change that overall average. A company with no reviews is not rated.</p><h2>Read beyond the average</h2><p>Look at review counts, dates, topics and individual experiences. A small sample or an old experience may not tell you what will happen with your order. Company replies are responses, not independent proof that an issue was resolved.</p><h2>About this directory</h2><p>Companies and reviews in this local research site are fictional. This version supports reading and comparing reviews, not submitting reviews or operating customer accounts.</p></section><p><a href="/categories">Explore companies by category</a></p></main>''',site_name)
