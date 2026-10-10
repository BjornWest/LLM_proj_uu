"""Escaped carrier profiles over the exact public corpus; no private event reader."""
from copy import deepcopy
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from html import escape
from math import ceil
from urllib.parse import quote, urlencode, unquote

from environments.product_world.review_population import summarize_ratings

VERSION = 'website-carrier-review-pages-v1'
PAGE_SIZE = 12


def e(value): return escape(str(value), quote=True)
def title(value): return str(value).replace('_', ' ').capitalize()
def path(identifier): return '/carriers/'+quote(identifier, safe='')


def fields(value):
    """Render public service policies without inventing missing fields."""
    if isinstance(value, dict):
        return '<dl>'+''.join('<dt>'+e(title(k))+'</dt><dd>'+fields(v)+'</dd>' for k, v in value.items() if v is not None)+'</dl>'
    if isinstance(value, list):
        return '<ul>'+''.join('<li>'+fields(v)+'</li>' for v in value)+'</ul>'
    if isinstance(value, bool): return 'Yes' if value else 'No'
    return e(title(value) if isinstance(value, str) and '_' in value else value)


class CarrierReviewPages:
    def __init__(self, publication):
        self.publication = deepcopy(publication)
        self.profiles = {p['carrier']['carrier_id']: p for p in publication['profiles']}
        if len(self.profiles) != len(publication['profiles']): raise ValueError('Duplicate carrier profile')
        self.points = {p['point_id']: p for p in publication['collection_points']}

    def frame(self, heading, body):
        links = ''.join('<li><a href="'+path(cid)+'">'+e(p['carrier']['name'])+'</a></li>' for cid, p in self.profiles.items())
        return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>'+e(heading)+' · '+e(self.publication['name'])+'</title></head><body>'
            '<header><a href="/">'+e(self.publication['name'])+'</a><nav aria-label="Carrier profiles"><details><summary>Delivery companies</summary><ul>'+links+'</ul></details></nav></header>'
            '<main><h1>'+e(heading)+'</h1>'+body+'</main><footer><p>Customer reviews describe individual experiences. Published service terms do not guarantee a future delivery outcome.</p><a href="/">All carrier profiles</a></footer></body></html>')

    def point(self, point):
        hours = '<dl>'+''.join('<dt>'+e(day)+'</dt><dd>'+(', '.join(e(a)+'–'+e(b) for a,b in spans) if spans else 'Closed')+'</dd>' for day,spans in point['weekly_hours'].items())+'</dl>'
        travel = '<ul>'+''.join('<li>'+e(title(mode))+': approximately '+e(data['distance_km'])+' km, '+e(data['duration_minutes'])+' minutes</li>' for mode,data in point.get('travel',{}).items() if data.get('status')=='estimated')+'</ul>'
        return '<section data-point-id="'+e(point['point_id'])+'"><h3>'+e(point['name'])+'</h3><p>'+e(title(point['type']))+' · '+e(title(point['host_type']))+'</p><p>'+e(point['location']['city'])+', '+e(point['location']['country'])+'</p><p>'+('Access available all day, every day' if point['access_24_7'] else 'Access follows the opening hours')+'</p>'+hours+travel+'</section>'

    def query(self, value):
        if type(value) is not dict or set(value)-{'shipping_class','date_from','date_to','page','sort'}: raise ValueError('Unknown carrier review filter')
        config = {'shipping_class': value.get('shipping_class','all'), 'sort': value.get('sort','newest'), 'page': value.get('page','1')}
        if config['shipping_class'] not in ('all','regular','bulky') or config['sort'] not in ('newest','oldest'): raise ValueError('Invalid class or review order')
        raw = config['page']
        if type(raw) is not str or not raw.isascii() or not raw.isdecimal() or not 1 <= int(raw) <= 10000: raise ValueError('Invalid review page')
        config['page'] = int(raw)
        for key in ('date_from','date_to'):
            if value.get(key):
                v=value[key]
                if type(v) is not str or date.fromisoformat(v).isoformat()!=v: raise ValueError('Use explicit ISO review dates')
                config[key]=v
        if config.get('date_from','0001-01-01')>config.get('date_to','9999-12-31'): raise ValueError('Inverted review dates')
        return config

    def scope(self, cid, query):
        config=self.query(query);profile=self.profiles[cid]
        rows=[deepcopy(r) for r in profile['reviews'] if (config['shipping_class']=='all' or r['shipping_class']==config['shipping_class']) and r['date']>=config.get('date_from','0001-01-01') and r['date']<=config.get('date_to','9999-12-31')]
        rows.sort(key=lambda r:(r['date'],r['review_id']),reverse=config['sort']=='newest')
        return config,rows

    def profile(self, cid, query):
        config,rows=self.scope(cid,query);carrier=self.profiles[cid]['carrier'];pages=max(1,ceil(len(rows)/PAGE_SIZE))
        if config['page']>pages: raise ValueError('Review page outside scoped corpus')
        options=''.join('<option value="'+value+'"'+(' selected' if value==config['shipping_class'] else '')+'>'+e(title(value))+'</option>' for value in ['all','regular','bulky'])
        sort=''.join('<option value="'+value+'"'+(' selected' if value==config['sort'] else '')+'>'+e(title(value))+'</option>' for value in ['newest','oldest'])
        form='<form method="get" action="'+path(cid)+'"><fieldset><legend>Review scope</legend><label>Shipping class<select name="shipping_class">'+options+'</select></label><label>From date<input type="date" name="date_from" value="'+e(config.get('date_from',''))+'"></label><label>Through date<input type="date" name="date_to" value="'+e(config.get('date_to',''))+'"></label><label>Review order<select name="sort">'+sort+'</select></label><button>Apply review filters</button></fieldset></form>'
        summary=summarize_ratings([{'rating':r['stars'],'text':r['text'] or ''} for r in rows]);mean=str((Decimal(summary['rating_sum'])/summary['rating_count']).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)) if rows else 'Undefined — no ratings'
        stats='<section aria-label="Scoped ratings"><h2>Ratings in this scope</h2><dl><dt>Ratings</dt><dd>'+str(summary['rating_count'])+'</dd><dt>Written reviews</dt><dd>'+str(summary['written_review_count'])+'</dd><dt>Ratings without text</dt><dd>'+str(summary['rating_only_count'])+'</dd><dt>Mean stars</dt><dd>'+mean+'</dd></dl><ul>'+''.join('<li>'+str(n)+' stars: '+str(summary['star_counts'][str(n)])+'</li>' for n in range(1,6))+'</ul><p>Regular shipping includes collection as well as home delivery. Topic opinions require written comments.</p></section>'
        page_rows=rows[(config['page']-1)*PAGE_SIZE:config['page']*PAGE_SIZE]
        reviews=''.join('<article data-review-id="'+e(r['review_id'])+'"><h3>'+e(r.get('reviewer_name') or r['reviewer_id'])+'</h3><p><time datetime="'+e(r['date'])+'">'+e(r['date'])+'</time> · '+str(r['stars'])+' stars · '+e(r['shipping_class'])+' · '+e(r['service_id'])+'</p>'+('<p>'+e(r['text'])+'</p>' if (r['text'] or '').strip() else '<p>Rating only — no written comment</p>')+'</article>' for r in page_rows)
        paging='<nav aria-label="Review pages">'+''.join('<a href="'+path(cid)+'?'+e(urlencode({**config,'page':n}))+'"'+(' aria-current="page"' if n==config['page'] else '')+'>Page '+str(n)+'</a> ' for n in range(1,pages+1))+'</nav>'
        policies='<details><summary>Published tracking and delivery policies</summary>'+''.join('<p>'+e(t)+'</p>' for t in carrier.get('policy_text',[]))+fields(carrier.get('tracking',{}))+fields(carrier.get('notifications',{}))+'</details>'
        if not any(carrier.get(k) for k in ['policy_text','tracking','notifications']):policies=''
        services='<section><h2>Services</h2>'+''.join('<details><summary>'+e(title(s['shipping_class']))+' service</summary>'+fields(s)+'</details>' for s in carrier['services'])+'</section>'
        points='<details><summary>Collection locations</summary>'+''.join(self.point(self.points[pid]) for pid in carrier.get('collection_point_ids',[]))+'</details>'
        if not carrier.get('collection_point_ids'):points=''
        return self.frame(carrier['name'],form+stats+'<section><h2>Customer ratings and reviews</h2>'+reviews+paging+'</section>'+policies+services+points)

    def page(self, route, query):
        if route=='/api/publication':
            if query: raise ValueError('No filters on canonical public export')
            import json
            return 200,json.dumps(self.publication,ensure_ascii=False),'application/json; charset=utf-8'
        if route=='/':
            if query: raise ValueError('Choose a carrier profile before filtering')
            body='<p>Browse published customer ratings, dated reviews and service policies.</p><ul>'+''.join('<li><a href="'+path(cid)+'">'+e(p['carrier']['name'])+'</a> · '+str(len(p['reviews']))+' ratings</li>' for cid,p in self.profiles.items())+'</ul><details><summary>All collection locations</summary>'+''.join(self.point(p) for p in self.points.values())+'</details>'
            return 200,self.frame('Delivery company reviews',body),'text/html; charset=utf-8'
        if route.startswith('/carriers/'):
            cid=unquote(route[len('/carriers/'):])
            if cid in self.profiles:return 200,self.profile(cid,query),'text/html; charset=utf-8'
        raise KeyError('Unknown carrier profile route')
