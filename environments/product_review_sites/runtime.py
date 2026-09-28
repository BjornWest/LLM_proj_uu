"""Read-only native HTML application; independent per-world server and identity."""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread, Lock
from urllib.parse import urlsplit, parse_qsl, unquote
import time,json
from environments.site_consent.runtime import ConsentUI,ROOT as CONSENT_ROOT
from .data import Catalog, LAYOUTS, NAMES, text
from .generate import stream
from . import render as ui


def site_name(seed, families, site_id='product-reviews'):
    names=NAMES[families[0]] if len(families)==1 else ('The Review Ledger','Product Fieldnotes','Review Atlas')
    return stream(seed,'publisher/'+site_id).choice(names)


def query(path,raw):
    pairs=parse_qsl(raw,keep_blank_values=True,strict_parsing=True,max_num_fields=128)
    q={}
    allowed={'family','stars','page'} if path=='/activity' else {'page'} if path in ('/contributors','/members') or path.startswith(('/contributors/','/members/')) else {'q','family','field','value','sort','page'} if path=='/catalog' else {'left','right'} if path=='/compare' else {'part','stars','sort','page'} if path.startswith('/reviews/') and '/opinions/' not in path else set()
    for key,value in pairs:
        facet=path=='/catalog' and key.startswith(('f.','x.','min.','max.'))
        if key not in allowed and not facet or len(value)>500 or len(key)>100:raise ValueError('Unsupported query')
        multi=facet and key.startswith(('f.','x.'))
        if multi:q.setdefault(key,[]).append(value)
        elif key in q:raise ValueError('Duplicate query parameter')
        else:q[key]=value
    if 'page' in q and (not q['page'].isascii() or not q['page'].isdigit() or not 1<=int(q['page'])<=10000):raise ValueError('Invalid page')
    if 'sort' in q and q['sort'] not in (('name','newest','rating') if path=='/catalog' else ('newest','lowest')):raise ValueError('Invalid sort')
    if 'stars' in q and q['stars'] not in ('','1','2','3','4','5'):raise ValueError('Invalid rating')
    if 'part' in q and q['part'] not in ('overview','specifications','readers'):raise ValueError('Invalid article section')
    return q


class Runtime:
    def __init__(self,public,port=0,*,families=None,layout='lab-directory',name=None,seed=0,site_id='product-reviews',page_size=12,related_count=4,bindings=None,consent_design=None,evidence=None,evidence_world=None,decorate=None):
        self.db=Catalog(public,families=families,bindings=bindings)
        if decorate is not None and not callable(decorate):raise ValueError("Page decorator must be callable")
        self.decorate=decorate
        self.evidence=None
        if evidence is not None:
            from .evidence_ui import Corpus
            if evidence_world is None:raise ValueError("Evidence requires its canonical catalog")
            self.evidence=Corpus(evidence_world,evidence,self.db)
        if layout not in LAYOUTS:raise ValueError('Unsupported layout')
        if type(page_size) is not int or not 4<=page_size<=24 or type(related_count) is not int or not 0<=related_count<=12:raise ValueError('Invalid density')
        if type(seed) is not int:raise ValueError('Integer seed required')
        self.name=text(name if name is not None else site_name(seed,self.db.families,site_id))
        if len(self.name)>80 or any(ord(c)<32 for c in self.name):raise ValueError('Invalid publisher name')
        self.layout=layout;self.page_size=page_size;self.related_count=related_count;self.site_id=text(site_id)
        self.consent=ConsentUI(consent_design) if consent_design is not None else None
        self._events=[];self._lock=Lock();outer=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                if outer.consent and self.path in ('/_consent/ui.js','/_consent/style.css'):
                    name=self.path.rsplit('/',1)[1];data=(CONSENT_ROOT/name).read_bytes()
                    self.send_response(200);self.send_header('Content-Type','text/javascript' if name.endswith('.js') else 'text/css')
                    self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data);return
                status=200
                try:
                    if len(self.path)>12000:raise ValueError('Request too long')
                    parts=urlsplit(self.path)
                    if parts.scheme or parts.netloc:raise ValueError('Absolute request target')
                    path=unquote(parts.path);q=query(path,parts.query)
                    if path=='/':body=ui.home(outer)
                    elif path=='/reader-panel' and outer.evidence is not None:body=outer.evidence.directory(outer)
                    elif path=='/catalog':body=ui.listing(outer,q)
                    elif path=='/methodology':body=ui.methodology(outer)
                    elif path in ('/activity','/contributors','/members') or path.startswith(('/contributors/','/members/')):body=ui.structure.archive(outer,path,q)
                    elif path=='/compare':
                        if any(q.get(k) and q[k] not in outer.db.by_id for k in ('left','right')):raise ValueError('Unknown reviewed configuration')
                        body=ui.comparison(outer,q)
                    elif path.startswith('/variants/') and path[len('/variants/'):] in outer.db.variants:
                        body=ui.variant(outer,outer.db.variants[path[len('/variants/'):]])
                    elif path.startswith('/reviews/'):
                        rest=path[len('/reviews/'):].split('/opinions/');a=outer.db.by_id.get(rest[0])
                        if not a:raise KeyError('Unknown review')
                        if len(rest)==1:body=ui.review(outer,a,q)
                        elif len(rest)==2:
                            c=next((c for c in a['reader_opinions'] if c['id']==rest[1]),None)
                            if c is None:raise KeyError('Unknown opinion')
                            body=ui.document(outer,c['title'],'<main id="main"><h1>Reader note</h1>'+ui.opinion(outer,a,c)+'<a href="'+ui.review_url(a)+'">Back to the review</a></main>')
                        else:raise KeyError('Unknown path')
                    else:raise KeyError('Unknown path')
                    if outer.evidence is not None:body=outer.evidence.decorate(body,path,q)
                    if outer.decorate is not None:body=outer.decorate(body)
                except KeyError:
                    status=404;body=ui.document(outer,'Not found','<main id="main"><h1>Page not found</h1><a href="/catalog">Browse reviews</a></main>')
                except (ValueError,UnicodeError):
                    status=400;body=ui.document(outer,'Invalid request','<main id="main"><h1>Invalid filter or comparison</h1><p>Choose valid configurations and filters.</p><a href="/catalog">Browse reviews</a></main>')
                cookie=None
                if outer.consent:
                    state,cookie=outer.consent.begin(self.headers.get('Cookie'))
                    body=outer.consent.inject(body,state)
                data=body.encode();self.send_response(status)
                if cookie:self.send_header('Set-Cookie',cookie)
                self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store')
                self.send_header('Content-Security-Policy',"default-src 'none'; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'self'" if outer.consent else "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'self'")
                self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data)
                with outer._lock:
                    outer._events.append({'time':time.time(),'path':self.path,'status':status})
                    if len(outer._events)>10000:del outer._events[:1000]
            def do_POST(self):
                if outer.consent and self.path=='/_consent/choose':
                    try:
                        length=int(self.headers.get('Content-Length','0'))
                        if not 0<length<=8192 or self.headers.get_content_type()!='application/json':raise ValueError('Invalid request')
                        origin=self.headers.get('Origin')
                        if origin and origin not in (outer.origin,outer.origin.replace('127.0.0.1','localhost')):
                            status,result=403,{'error':'Unexpected origin'}
                        else:status,result=outer.consent.commit(self.headers.get('Cookie'),json.loads(self.rfile.read(length)))
                    except (ValueError,UnicodeError):status,result=400,{'error':'Invalid consent request'}
                    data=json.dumps(result).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data);return
                self.send_response(405);self.send_header('Allow','GET');self.send_header('Content-Length','0');self.end_headers()
        self.server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
        self.origin=f'http://127.0.0.1:{self.server.server_port}'
        self.thread=Thread(target=self.server.serve_forever,kwargs={'poll_interval':.05},daemon=True);self.thread.start()
    def access_log(self):
        with self._lock:return deepcopy(self._events)
    def close(self):self.server.shutdown();self.server.server_close();self.thread.join(timeout=2)
    def __enter__(self):return self
    def __exit__(self,*_):self.close()
