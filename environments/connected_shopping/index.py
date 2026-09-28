"""A bounded public web index. No task, memory, winner, or private world input."""
from copy import deepcopy
from html import escape
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread
from urllib.parse import urlsplit,parse_qsl,urlencode
import re,unicodedata

KINDS={'travel':'Travel and branches','retailer':'Stores','aggregator':'Price comparison','merchant_reviews':'Merchant reviews','product_reviews':'Product reviews'}

def tokens(value):
    text=unicodedata.normalize('NFKC',value).casefold().replace('_',' ').replace('-',' ')
    return re.findall(r'[^\W_]+',text,flags=re.UNICODE)


def e(value):return escape(str(value),quote=True)

def url(q):return '/search?'+urlencode({k:v for k,v in q.items() if v!=''})


class Catalog:
    def __init__(self,sites,documents):
        self.sites=deepcopy(sites);self.documents=deepcopy(documents);self.by_id={}
        for s in self.sites:
            if set(s)!={'site_id','kind','name','origin','families','description'} or s['kind'] not in KINDS:raise ValueError('Invalid public site record')
            if s['site_id'] in self.by_id or not all(isinstance(s[k],str) and s[k] for k in ('site_id','name','origin','description')):raise ValueError('Invalid identity')
            parsed=urlsplit(s['origin'])
            if parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','localhost') or not parsed.port or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment:raise ValueError('Expected bound local origin')
            if not isinstance(s['families'],list) or not all(isinstance(f,str) for f in s['families']):raise ValueError('Invalid families')
            self.by_id[s['site_id']]=s
        self.search_terms=[];seen=set()
        for d in self.documents:
            if set(d)!={'site_id','path','title','description','keywords'} or d['site_id'] not in self.by_id:raise ValueError('Invalid public document')
            if not all(isinstance(d[k],str) for k in ('path','title','description','keywords')):raise ValueError('Invalid document text')
            p=urlsplit(d['path'])
            if not d['path'].startswith('/') or d['path'].startswith('//') or p.scheme or p.netloc or '\\' in d['path'] or any(ord(c)<32 for c in d['path']):raise ValueError('Invalid local path')
            identity=(d['site_id'],d['path'])
            if identity in seen:raise ValueError('Duplicate indexed page')
            seen.add(identity);s=self.by_id[d['site_id']]
            self.search_terms.append(set(tokens(' '.join([d['title'],d['description'],d['keywords'],s['name'],s['description'],*s['families']]))))

    def search(self,q='',kind='',family=''):
        if kind and kind not in KINDS:raise ValueError('Unknown site type')
        words=set(tokens(q));rows=[]
        for doc,available in zip(self.documents,self.search_terms):
            site=self.by_id[doc['site_id']]
            if kind and site['kind']!=kind or family and family not in site['families']:continue
            if words and not words<=available:continue
            score=len(words & set(tokens(doc['title'])))
            rows.append((score,doc))
        # Lexical ranking only: never price, eligibility, task constraints, or an oracle.
        rows.sort(key=lambda x:(-x[0],x[1]['title'].casefold(),x[1]['site_id'],x[1]['path']))
        return [doc for _,doc in rows]

STYLE='''<style>body{font:17px/1.65 system-ui;margin:0;color:#20332e;background:#f5f6f4}header,footer{padding:22px 5vw;background:#e6eeea}main{max-width:1100px;margin:auto;padding:32px 22px}h1{font-size:36px}input,select,button{font:inherit;padding:10px;max-width:100%;box-sizing:border-box}form{display:flex;flex-wrap:wrap;gap:14px;align-items:end}label{display:grid;gap:4px}a{color:#165a85}button{background:#245a53;color:white;border:0}article{background:white;padding:20px;border:1px solid #d0dcd7;margin:16px 0}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}nav{display:flex;gap:18px;flex-wrap:wrap}.meta{font-size:14px;color:#51675d}article h2{margin:0}p,a{overflow-wrap:anywhere}@media(max-width:650px){.grid{display:block}}</style>'''


def render(db,path,q):
    form='<form action="/search" method="get"><label>Search sites and products<input type="search" name="q" value="'+e(q.get('q',''))+'"></label><label>Site type<select name="kind"><option value="">All sites</option>'+''.join('<option value="'+k+'"'+(' selected' if q.get('kind')==k else '')+'>'+v+'</option>' for k,v in KINDS.items())+'</select></label><button>Search</button></form>'
    body='<header><a href="/">Sökväg</a><nav aria-label="Discovery"><a href="/">Browse websites</a><a href="/search">Search all pages</a></nav></header><main><h1>Find stores, prices and reviews</h1>'+form
    if path=='/':
        for kind,label in KINDS.items():
            sites=[s for s in db.sites if s['kind']==kind]
            if not sites:continue
            body+='<section><h2>'+label+'</h2><div class="grid">'+''.join('<article><h3><a href="'+e(s['origin'])+'/">'+e(s['name'])+'</a></h3><p>'+e(s['description'])+'</p><p class="meta">'+e(', '.join(f.replace('_',' ') for f in s['families']))+'</p></article>' for s in sites)+'</div></section>'
    else:
        rows=db.search(q.get('q',''),q.get('kind',''));page=int(q.get('page','1'));size=20;total=max(1,(len(rows)+size-1)//size);page=min(page,total)
        body+='<h2>Search results ('+str(len(rows))+')</h2>'
        for d in rows[(page-1)*size:page*size]:
            s=db.by_id[d['site_id']];body+='<article><p class="meta">'+e(s['name'])+' · '+KINDS[s['kind']]+'</p><h3><a href="'+e(s['origin']+d['path'])+'">'+e(d['title'])+'</a></h3><p>'+e(d['description'])+'</p></article>'
        if not rows:body+='<p>No indexed pages match. Try a product name, SKU, category or store name.</p>'
        body+='<nav aria-label="Pagination"><span>Page '+str(page)+' of '+str(total)+'</span>'
        if page>1:body+='<a href="'+e(url({**q,'page':page-1}))+'">Previous</a>'
        if page<total:body+='<a href="'+e(url({**q,'page':page+1}))+'">Next</a>'
        body+='</nav>'
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sökväg — search and discover</title>'+STYLE+'</head><body>'+body+'</main><footer><p>Search the available stores and independent publications. Check product options and final delivery charges at the store.</p></footer></body></html>'


class Runtime:
    def __init__(self,sites,documents,port=0):
        self.catalog=Catalog(sites,documents);outer=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                try:
                    p=urlsplit(self.path)
                    if p.scheme or p.netloc or len(self.path)>3000:raise ValueError('Bad target')
                    if p.path not in ('/','/search'):status=404;html='<h1>Page not found</h1><a href="/">Search</a>'
                    else:
                        pairs=parse_qsl(p.query,keep_blank_values=True,strict_parsing=True,max_num_fields=3);q=dict(pairs)
                        if len(q)!=len(pairs) or set(q)-{'q','kind','page'} or len(q.get('q',''))>300:raise ValueError('Bad query')
                        if q.get('kind','') not in ('',*KINDS):raise ValueError('Bad type')
                        if 'page' in q and (not q['page'].isascii() or not q['page'].isdigit() or not 1<=int(q['page'])<=10000):raise ValueError('Bad page')
                        status=200;html=render(outer.catalog,p.path,q)
                except ValueError:status=400;html='<h1>Invalid search</h1><a href="/">Search</a>'
                body=html.encode();self.send_response(status);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'");self.end_headers();self.wfile.write(body)
        self.server=ThreadingHTTPServer(('127.0.0.1',port),Handler);self.origin=f'http://127.0.0.1:{self.server.server_port}'
        self.thread=Thread(target=self.server.serve_forever,kwargs={'poll_interval':.05},daemon=True);self.thread.start()
    def close(self):self.server.shutdown();self.server.server_close();self.thread.join(timeout=2)
    def __enter__(self):return self
    def __exit__(self,*_):self.close()
