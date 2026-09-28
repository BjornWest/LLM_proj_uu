"""Read-only loopback application; no account, payment or external HTTP dependencies."""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread,Lock
from urllib.parse import urlsplit,parse_qsl,unquote
import time
from .data import ReviewCatalog,TOPICS
from . import render as ui


def query_for(path,text):
    pairs=parse_qsl(text,keep_blank_values=True,strict_parsing=True,max_num_fields=12)
    if len(dict(pairs))!=len(pairs):raise ValueError('Duplicate query parameter')
    q=dict(pairs)
    allowed={'q','category','sort','page'} if path=='/search' else {'q','stars','topic','period','sort','page'} if path.startswith('/review/') else set()
    if set(q)-allowed or any(len(v)>300 for v in q.values()):raise ValueError('Invalid query')
    if 'page' in q and (not q['page'].isascii() or not q['page'].isdigit() or not 1<=int(q['page'])<=10000):raise ValueError('Invalid page')
    if 'sort' in q and q['sort'] not in (('name','rating','count') if path=='/search' else ('newest','oldest','lowest','highest')):raise ValueError('Invalid sort')
    for key,values in [('stars',('', '1','2','3','4','5')),('topic',('',*TOPICS)),('period',('','30','90','365'))]:
        if key in q and q[key] not in values:raise ValueError('Invalid filter')
    return q


class Runtime:
    def __init__(self,public,port=0,website_bindings=None,*,site_name="Omdömeskollen"):
        self.catalog=ReviewCatalog(public,website_bindings,site_name=site_name);self._events=[];self._lock=Lock()
        outer=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                status=200
                try:
                    if len(self.path)>4000:raise ValueError('Request too long')
                    u=urlsplit(self.path)
                    if u.scheme or u.netloc:raise ValueError('Absolute request target')
                    path=unquote(u.path);q=query_for(path,u.query)
                    db=outer.catalog
                    if path=='/':body=ui.home(db)
                    elif path=='/search':body=ui.search(db,q)
                    elif path=='/categories':body=ui.document('Categories','<main id="main"><h1>Browse companies by category</h1>'+ui.category_links(db)+'</main>',db.site_name)
                    elif path=='/about':body=ui.about(db.site_name)
                    elif path.startswith('/review/') and path[len('/review/'):] in db.by_id:body=ui.profile(db,db.by_id[path[len('/review/'):]],q)
                    elif path.startswith('/reviews/') and path[len('/reviews/'):] in db.by_review:
                        c,r=db.by_review[path[len('/reviews/'):]]
                        body=ui.document(r['title'],'<main id="main"><p><a href="'+ui.company_url(c)+'">All reviews of '+ui.e(c['name'])+'</a></p><h1>Customer experience</h1>'+ui.review_card(c,r)+'</main>',db.site_name)
                    else:status=404;body=ui.document('Not found','<main id="main"><h1>Page not found</h1><a href="/">Find a company</a></main>',outer.catalog.site_name)
                except (ValueError,UnicodeError):
                    status=400;body=ui.document('Invalid request','<main id="main"><h1>Invalid search or filter</h1><a href="/">Start again</a></main>',outer.catalog.site_name)
                data=body.encode();self.send_response(status)
                self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(data)))
                self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
                self.send_header('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'self'")
                self.end_headers();self.wfile.write(data)
                with outer._lock:
                    outer._events.append({'time':time.time(),'path':self.path,'status':status})
                    if len(outer._events)>10000:del outer._events[:1000]
            def do_POST(self):
                self.send_response(405);self.send_header('Allow','GET');self.send_header('Content-Length','0');self.end_headers()
        self.server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
        self.origin=f'http://127.0.0.1:{self.server.server_port}'
        self.thread=Thread(target=self.server.serve_forever,kwargs={'poll_interval':.05},daemon=True);self.thread.start()
    def access_log(self):
        with self._lock:return deepcopy(self._events)
    def close(self):self.server.shutdown();self.server.server_close();self.thread.join(timeout=2)
    def __enter__(self):return self
    def __exit__(self,*_):self.close()
