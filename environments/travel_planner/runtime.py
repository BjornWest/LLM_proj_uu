"""Native HTML travel site. Public export only; no authoring or oracle endpoints."""
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html import escape
import json
import threading
from urllib.parse import parse_qs, urlencode, urlsplit, quote
from .data import Catalog

MODE_LABELS={'driving':'Car','cycling':'Bicycle','walking':'On foot'}

STYLE='''body{margin:0;background:#f5f4ee;color:#203432;font:16px/1.5 system-ui}header{background:#123c36;color:white;padding:22px max(24px,calc((100% - 1080px)/2));display:flex;align-items:center;justify-content:space-between}header a{color:white;text-decoration:none}.brand{font-size:25px;font-weight:750}main{max-width:1080px;margin:36px auto;padding:0 24px}h1{font-size:38px;line-height:1.2;margin:0 0 10px}h2{font-size:23px}.muted{color:#5a6f68}.panel,.place,.result{padding:24px;background:white;border:1px solid #dce2d9;border-radius:12px;margin:22px 0}.fields{display:flex;gap:14px;flex-wrap:wrap;align-items:end}label{display:grid;gap:7px;font-size:14px;flex:1;min-width:160px}input,select,button{font:inherit;padding:12px;border:1px solid #aebeb3;border-radius:6px;min-width:0}button,.button{background:#17604e;color:white;border:0;text-decoration:none;display:inline-block;padding:12px 18px;border-radius:6px;cursor:pointer}a{color:#145a46}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.place,.result{margin:0}.place h3{margin-top:0}.metric{font-size:32px;font-weight:700;display:block}.selected{border:2px solid #17604e}.tag{font-size:13px;background:#e7f1e7;border-radius:10px;padding:3px 8px}.error{background:#fff0de;padding:14px;border-radius:6px}footer{padding:28px 0;color:#52665d;font-size:13px}.pagination{display:flex;gap:24px;margin:24px 0}@media(max-width:650px){.grid{grid-template-columns:1fr}h1{font-size:30px}.fields{display:grid}header{padding:18px 24px}}'''


def duration(n):
    if n<60:return f'{n} min'
    h,m=divmod(n,60)
    return f'{h} hr'+(f' {m} min' if m else '')


def route_text(t):
    if t['status']!='estimated':
        return {'intercity_walking_not_modelled':'Walking estimate unavailable between these cities.',
                'intercity_cycling_not_modelled':'Cycling estimate unavailable between these cities.'}.get(t['reason'],'No travel estimate available for this journey.')
    return f"About {duration(t['duration_minutes'])} · {t['distance_km']:g} km"


def input_field(label,name,value='',placeholder=''):
    return f'<label>{escape(label)}<input name="{name}" value="{escape(value,quote=True)}" placeholder="{escape(placeholder,quote=True)}"></label>'


def select_field(label,name,options,value):
    return '<label>'+escape(label)+f'<select name="{name}" aria-label="{escape(label,quote=True)}">'+''.join(f'<option value="{escape(k,quote=True)}"'+(' selected' if k==value else '')+'>'+escape(v)+'</option>' for k,v in options)+'</select></label>'


def shell(base,body,title='Waymark — find your way'):
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title><style>{STYLE}</style><header><a class="brand" href="{base}">Waymark ↗</a><a href="{base}">Places &amp; journeys</a></header><main>{body}<footer>Estimated travel times exclude traffic, parking and opening hours. Walking and cycling estimates cover journeys within one city. Store stock and collection readiness should be checked with the retailer.</footer></main></html>'''


def home(catalog,base,args):
    origin=args.get('origin','Home');query=args.get('q','');mode=args.get('mode','driving');sort=args.get('sort','name')
    if mode not in catalog.public['modes'] or sort not in ('name','duration','distance'):raise ValueError('Choose a supported mode and sort order')
    try:page=int(args.get('page','1'))
    except ValueError:raise ValueError('Invalid page') from None
    if page<1:raise ValueError('Invalid page')
    fields=input_field('From','from',origin,'Home or a branch name')+input_field('To','to',args.get('to',''),'Branch name, city or place label')+select_field('Travel by','mode',[(k,v) for k,v in MODE_LABELS.items() if k in catalog.public['modes']],mode)
    body='<h1>A simpler way to get there.</h1><p class="muted">Find participating stores and compare journeys from your saved place or another branch.</p>'
    body+=f'<section class="panel"><h2>Plan a journey</h2><form action="{base}/journey" method="get"><div class="fields">{fields}<button>Find journey</button></div></form></section>'
    body+=f'<section><h2>Find a store</h2><form action="{base}" method="get"><div class="fields">'+input_field('Store, city or type','q',query,'Search branches')+input_field('Starting from','origin',origin)+select_field('Travel by','mode',[(k,v) for k,v in MODE_LABELS.items() if k in catalog.public['modes']],mode)+select_field('Sort results','sort',[('name','Name'),('duration','Travel time'),('distance','Travel distance')],sort)+'<button>Search places</button></div></form>'
    origins=catalog.resolve(origin)
    if len(origins)==1:resolved_origin=origins[0]
    else:
        resolved_origin=None
        body+='<p class="error">Choose a specific starting place to compare travel estimates. Use the journey form above to resolve the location.</p>'
    matches=catalog.search(query,kind='branch')
    if sort!='name' and resolved_origin:
        metric='duration_minutes' if sort=='duration' else 'distance_km'
        matches.sort(key=lambda p:(catalog.trip(resolved_origin['place_id'],p['place_id'],mode)[metric] is None,
            catalog.trip(resolved_origin['place_id'],p['place_id'],mode)[metric] or 0,p['place_id']))
    body+=f'<p class="muted">{len(matches)} matching '+('place' if len(matches)==1 else 'places')+'</p>'
    shown=matches[(page-1)*12:page*12]
    if not shown:body+='<p>No matching places on this page. Try a different branch name or city.</p>'
    body+='<div class="grid">'
    for p in shown:
        start=resolved_origin['place_id'] if resolved_origin else origin
        href=base+'/journey?'+urlencode({'from':start,'to':p['place_id'],'mode':mode})
        estimate=route_text(catalog.trip(start,p['place_id'],mode)) if resolved_origin else 'Choose a starting place for travel estimates.'
        body+=f'<article class="place" data-place="{escape(p["place_id"],quote=True)}"><h3>{escape(p["name"])}</h3><p>{escape(p["city"])}, {escape(p["country"])}</p><p class="estimate">{escape(estimate)}</p><a href="{escape(href,quote=True)}">Plan journey →</a></article>'
    body+='</div><nav class="pagination" aria-label="Search pages">'
    for number,label in ((page-1,'Previous'),(page+1,'Next')):
        if number>=1 and (number-1)*12<len(matches):body+=f'<a href="{base}?{escape(urlencode({**args,"page":number}),quote=True)}">{label}</a>'
    return shell(base,body+'</nav></section>')


def journey(catalog,base,args):
    mode=args.get('mode','driving')
    if mode not in catalog.public['modes']:raise ValueError('Choose car, bicycle or walking')
    queries=[args.get('from',''),args.get('to','')];matches=[catalog.resolve(q) for q in queries]
    if any(len(m)!=1 for m in matches):
        body='<h1>Choose your places</h1><p>Some names match more than one place. Select the branch you mean.</p>'
        fields=''
        for name,label,q,found in zip(('from','to'),('From','To'),queries,matches):
            if not found:
                fields+=input_field(label,name,q)+f'<p class="error">Location not found: {escape(q or "enter a place")}. Search a saved place or a participating branch.</p>'
            else:fields+=select_field(label,name,[(p['place_id'],p['label']) for p in found],found[0]['place_id'])
        body+=f'<form class="panel" action="{base}/journey"><div class="fields">{fields}'+select_field('Travel by','mode',[(k,v) for k,v in MODE_LABELS.items() if k in catalog.public['modes']],mode)+'<button>Confirm places</button></div></form>'
        return shell(base,body,'Choose places — Waymark')
    origin,destination=[m[0] for m in matches]
    body=f'<a href="{base}">← Places &amp; journeys</a><h1>Your journey</h1><p id="journey-places">{escape(origin["label"])} → {escape(destination["label"])}</p>'
    reverse=base+'/journey?'+urlencode({'from':destination['place_id'],'to':origin['place_id'],'mode':mode})
    body+=f'<p><a href="{escape(reverse,quote=True)}">Reverse journey</a></p><div class="grid">'
    for choice in [mode,*[m for m in MODE_LABELS if m != mode and m in catalog.public['modes']]]:
        label=MODE_LABELS[choice]
        t=catalog.trip(origin['place_id'],destination['place_id'],choice)
        body+=f'<article class="result'+(' selected' if choice==mode else '')+f'" data-mode="{choice}"><h2>{label}</h2>'
        if t['status']=='estimated':
            body+=f'<span class="metric">{duration(t["duration_minutes"])}</span><p>{t["distance_km"]:g} km · estimated</p>'
            if t['crossing_kinds']:body+='<p>Includes '+escape(', '.join(k.replace('_',' / ') for k in t['crossing_kinds']))+'.</p>'
            if origin['place_id']==destination['place_id']:body+='<p>Origin and destination are the same place.</p>'
        else:body+='<p class="unavailable">'+escape(route_text(t))+'</p>'
        body+='</article>'
    return shell(base,body+'</div>','Journey — Waymark')


class Runtime:
    def __init__(self,port=0):
        self.snapshots=OrderedDict();self.lock=threading.Lock();owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def respond(self,status,body,mime='text/html; charset=utf-8'):
                data=body.encode() if isinstance(body,str) else body
                self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)))
                self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data)
            def do_GET(self):
                parsed=urlsplit(self.path);parts=parsed.path.strip('/').split('/')
                with owner.lock:
                    if parsed.path=='/' and owner.snapshots:
                        id=next(reversed(owner.snapshots));self.send_response(302);self.send_header('Location','/w/'+id);self.end_headers();return
                    catalog=owner.snapshots.get(parts[1]) if len(parts)>=2 and parts[0]=='w' else None
                if catalog is None:self.respond(404,shell('/','<h1>Page not found</h1><p>This journey collection is unavailable.</p>'));return
                base='/w/'+parts[1];suffix='/'.join(parts[2:]);args={k:v[-1] for k,v in parse_qs(parsed.query,keep_blank_values=True).items()}
                try:
                    if suffix=='':body=home(catalog,base,args)
                    elif suffix=='journey':body=journey(catalog,base,args)
                    elif suffix=='api/places':
                        self.respond(200,json.dumps({'places':catalog.search(args.get('q',''))},ensure_ascii=False),'application/json; charset=utf-8');return
                    elif suffix=='api/journey':
                        a,b=catalog.resolve(args.get('from','')),catalog.resolve(args.get('to',''))
                        if len(a)!=1 or len(b)!=1:
                            self.respond(400,json.dumps({'error':'Choose unambiguous places','origins':a,'destinations':b},ensure_ascii=False),'application/json; charset=utf-8');return
                        self.respond(200,json.dumps(catalog.trip(a[0]['place_id'],b[0]['place_id'],args.get('mode','driving'))),'application/json; charset=utf-8');return
                    else:self.respond(404,shell(base,'<h1>Page not found</h1>'));return
                    self.respond(200,body)
                except (ValueError,KeyError) as e:self.respond(400,shell(base,'<h1>Check your search</h1><p>'+escape(str(e))+'</p>'))
        self.server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
        self.origin=f'http://localhost:{self.server.server_port}'
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)

    def register(self,export):
        if export['schema_version']!='travel-planner-export-v1':raise ValueError('Unsupported travel export')
        from environments.product_world.generator import digest
        if export['public_sha256']!=digest(export['public']):raise ValueError('Travel export digest mismatch')
        id=export['public_sha256'][:24];catalog=Catalog(export['public'])
        with self.lock:
            self.snapshots[id]=catalog;self.snapshots.move_to_end(id)
            while len(self.snapshots)>16 or (len(self.snapshots)>1 and sum(len(c.trips) for c in self.snapshots.values())>100000):
                self.snapshots.popitem(last=False)
        return self.origin+'/w/'+id

    def __enter__(self):self.thread.start();return self
    def __exit__(self,*args):self.server.shutdown();self.server.server_close();self.thread.join(timeout=5)
