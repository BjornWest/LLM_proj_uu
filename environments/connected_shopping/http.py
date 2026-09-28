"""Small local page host with optional shared consent and private request diagnostics."""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread,Lock
from urllib.parse import urlsplit,parse_qsl,unquote
import json,time
from environments.site_consent.runtime import ConsentUI,ROOT


class Site:
    def __init__(self,render,*,consent_design=None,verification=None,action=None):
        self.render=render;self.consent=ConsentUI(consent_design) if consent_design else None
        self.verification=verification
        self.action=action
        self.events=[];self.lock=Lock();outer=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*a):pass
            def respond(self,status,body,mime='text/html; charset=utf-8',cookie=None):
                raw=body if isinstance(body,bytes) else body.encode();self.send_response(status)
                self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
                self.send_header('Content-Security-Policy',"default-src 'none'; img-src data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
                for value in ([cookie] if isinstance(cookie,str) else cookie or []):self.send_header('Set-Cookie',value)
                self.end_headers();self.wfile.write(raw)
                with outer.lock:outer.events.append({'sequence':len(outer.events)+1,'time':time.time(),'method':self.command,'path':self.path,'status':status})
            def do_GET(self):
                cookie=None
                try:
                    if self.path in ('/_consent/ui.js','/_consent/style.css') and outer.consent:
                        name=self.path.split('/')[-1];self.respond(200,(ROOT/name).read_bytes(),'text/javascript' if name.endswith('.js') else 'text/css');return
                    p=urlsplit(self.path)
                    if p.scheme or p.netloc or len(self.path)>8192:raise ValueError('Invalid target')
                    pairs=parse_qsl(p.query,keep_blank_values=True,strict_parsing=True,max_num_fields=30)
                    if len(dict(pairs))!=len(pairs):raise ValueError('Duplicate field')
                    if outer.verification:
                        blocked,cookie=outer.verification.begin(self.headers.get('Cookie'),unquote(p.path),target=self.path)
                        if blocked is not None:
                            self.respond(403,blocked,cookie=cookie);return
                    status,body=outer.render(unquote(p.path),dict(pairs),p.query)
                except (ValueError,UnicodeError):status,body=400,'<h1>Invalid request</h1><a href="/">Home</a>'
                except KeyError:status,body=404,'<h1>Page not found</h1><a href="/">Home</a>'
                if outer.consent:
                    state,consent_cookie=outer.consent.begin(self.headers.get('Cookie'));cookie=[v for v in (cookie,consent_cookie) if v];body=outer.consent.inject(body if '</body>' in body else '<html><body>'+body+'</body></html>',state)
                self.respond(status,body,cookie=cookie)
            def do_POST(self):
                if outer.verification:
                    blocked,cookie=outer.verification.begin(self.headers.get('Cookie'),urlsplit(self.path).path,target=self.path)
                    if blocked is not None:
                        self.respond(403,blocked,cookie=cookie);return
                if self.path=='/_consent/choose' and outer.consent:
                    try:
                        length=int(self.headers.get('Content-Length','0'));origin=self.headers.get('Origin')
                        if not 0<length<=8192 or self.headers.get_content_type()!='application/json':raise ValueError('Bad body')
                        if origin and origin not in (outer.origin,outer.origin.replace('127.0.0.1','localhost')):status,result=403,{'error':'Unexpected origin'}
                        else:status,result=outer.consent.commit(self.headers.get('Cookie'),json.loads(self.rfile.read(length)))
                    except (ValueError,UnicodeError):status,result=400,{'error':'Invalid consent request'}
                    self.respond(status,json.dumps(result),'application/json');return
                if outer.action is not None:
                    try:
                        p=urlsplit(self.path)
                        if p.scheme or p.netloc or p.query or len(self.path)>8192:raise ValueError('Invalid action target')
                        origin=self.headers.get('Origin')
                        if origin and origin not in (outer.origin,outer.origin.replace('127.0.0.1','localhost')):
                            self.respond(403,'<h1>Unexpected origin</h1>');return
                        if self.headers.get('Sec-Fetch-Site')=='cross-site':
                            self.respond(403,'<h1>Cross-site action refused</h1>');return
                        length=int(self.headers.get('Content-Length','0'))
                        if not 0<length<=8192 or self.headers.get_content_type()!='application/x-www-form-urlencoded':raise ValueError('Invalid form')
                        pairs=parse_qsl(self.rfile.read(length).decode('utf-8'),keep_blank_values=True,strict_parsing=True,max_num_fields=30)
                        if len(dict(pairs))!=len(pairs):raise ValueError('Duplicate form field')
                        status,body=outer.action(unquote(p.path),dict(pairs))
                    except (ValueError,UnicodeError):status,body=400,'<h1>Invalid action request</h1>'
                    except KeyError:status,body=404,'<h1>Action not found</h1>'
                    cookie=None
                    if outer.consent:
                        state,cookie=outer.consent.begin(self.headers.get('Cookie'))
                        body=outer.consent.inject(body if '</body>' in body else '<html><body>'+body+'</body></html>',state)
                    self.respond(status,body,cookie=cookie);return
                self.respond(405,'<h1>Action unavailable</h1><p>This catalog supports research; online ordering is not available.</p>')
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.origin=f'http://127.0.0.1:{self.server.server_port}'
        self.thread=Thread(target=self.server.serve_forever,kwargs={'poll_interval':.05},daemon=True);self.thread.start()
    def access_log(self):
        with self.lock:return deepcopy(self.events)
    def close(self):self.server.shutdown();self.server.server_close();self.thread.join(timeout=2)
    def __enter__(self):return self
    def __exit__(self,*_):self.close()
