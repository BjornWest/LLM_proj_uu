"""Private WebArena lease proxy and reset broker; never exposes Docker to browsers.

Trusted local configuration pins clone/reset commands. HTTP callers can only
acquire/release known sites, not choose origins, commands, files or credentials.
Restart quarantines every slot until its full reset completes.
"""
import argparse
import fcntl
import hashlib
import hmac
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import subprocess
import threading
import time
from urllib.parse import urlsplit, urljoin
from uuid import UUID, uuid4

BROKER_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

def normalized_redirect(location, origin, path):
    # Python URL joining and browser WHATWG parsing disagree on malformed slash
    # forms. Reject ambiguous input AND forward only a validated absolute URL.
    if not location or any(ord(c)<=32 or c=='\\' for c in location):return None
    if location.startswith('//'):return None
    if ':' in location.split('/')[0] and not location.startswith('http://'):return None
    try:
        if location.startswith('http://') and not urlsplit(location).netloc:return None
        u=urlsplit(urljoin(origin+path,location));base=urlsplit(origin)
        if u.username or u.password or (u.scheme,u.netloc)!=(base.scheme,base.netloc):return None
        return u.geturl()
    except ValueError:return None

def allowed_redirect(location, origin, path):
    return normalized_redirect(location,origin,path) is not None

HOP = {'connection','keep-alive','proxy-authenticate','proxy-authorization','te','trailer','transfer-encoding','upgrade','content-length','x-daylight-lease','authorization','x-m2-customer-auto-login','x-postmill-auto-login'}
class Pool:
    def __init__(self, config, state, *, resetter=None, clock=time.monotonic):
        self.config=config; self.state=Path(state); self.state.mkdir(parents=True,exist_ok=True)
        self.lock_file=(self.state/'broker.lock').open('a')
        fcntl.flock(self.lock_file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        self.cv=threading.Condition();self.clock=clock;self.resetter=resetter or self.reset_command
        self.slots={s['site_id']:{'config':s,'status':'resetting','token':None,'active':0,'session':None,'generation':0} for s in config['sites']}
        if set(self.slots)!={'webarena-shopping','webarena-forum'}: raise ValueError('Exactly two reviewed sites required')
    def event(self,kind,site,**fields):
        with (self.state/'events.jsonl').open('a') as f:
            f.write(json.dumps({'at':time.time(),'event':kind,'site_id':site,**fields})+'\n')
    def reset_command(self, slot):
        spec=slot['config']
        helper=Path(spec['reset_helper'])
        if hashlib.sha256(helper.read_bytes()).hexdigest()!=spec['reset_helper_sha256']:raise ValueError('Reset helper changed')
        container_id=subprocess.check_output(['docker','inspect','--format','{{.Id}}',spec['container_name']],text=True,timeout=15).strip()
        output=str(self.state/'resets'/(spec['site_id']+'-'+uuid4().hex))
        argv=[arg.replace('{container_id}',container_id).replace('{output}',output) for arg in spec['reset_argv']]
        with (self.state/(spec['site_id']+'-reset.log')).open('ab') as log:
            subprocess.run(argv,check=True,timeout=240,stdin=subprocess.DEVNULL,stdout=log,stderr=log)
        report=Path(output,'report.json').read_bytes()
        if json.loads(report).get('passed') is not True:raise ValueError('Reset report failed')
        slot['reset_report_sha256']=hashlib.sha256(report).hexdigest()
    def reset(self, slot):
        site=slot['config']['site_id']
        try:
            with self.cv:
                drained=self.cv.wait_for(lambda:slot['active']==0,timeout=90)
                if not drained: raise TimeoutError('Prior requests remain in flight')
            self.resetter(slot)
            with self.cv:
                slot.update(status='ready',session=None);slot['generation']+=1
                self.event('reset_complete',site,generation=slot['generation'])
        except Exception as error:
            with self.cv:
                slot['status']='error';self.event('reset_failed',site,error=type(error).__name__)
    def initialize(self):
        for slot in self.slots.values():threading.Thread(target=self.reset,args=(slot,),daemon=True).start()
    def revoke(self,slot,reason):
        slot['token']=None;slot['status']='resetting'
        self.event('lease_revoked',slot['config']['site_id'],reason=reason,session_id=slot['session'])
        threading.Thread(target=self.reset,args=(slot,),daemon=True).start()
    def expire(self):
        with self.cv:
            for slot in self.slots.values():
                if slot['status']=='leased' and self.clock()>slot['deadline']: self.revoke(slot,'expired')
    def control(self,op,value):
        self.expire()
        with self.cv:
            if op=='status':return 200,{'sites':[{'site_id':k,'status':s['status'],'image_id':s['config']['image_id'],'generation':s['generation']} for k,s in self.slots.items()]}
            if op=='acquire':
                site=value.get('site_id');slot=self.slots.get(site)
                if not slot:return 400,{'error':'Unknown site'}
                try:UUID(value['session_id'])
                except (ValueError,KeyError,TypeError):return 400,{'error':'Invalid session'}
                if slot['status']!='ready':return (429 if slot['status'] in ('leased','resetting') else 503),{'error':'Site unavailable'}
                token=secrets.token_urlsafe(32)
                slot.update(status='leased',token=token,session=value['session_id'],deadline=self.clock()+1200)
                self.event('lease_acquired',site,session_id=slot['session'],generation=slot['generation'])
                return 200,{'site_id':site,'lease_token':token,'origin':self.config['browser_origin'],'image_id':slot['config']['image_id'],'generation':slot['generation'],'reset_report_sha256':slot.get('reset_report_sha256'),'broker_sha256':BROKER_SHA256}
            if op=='release':
                token=value.get('lease_token')
                if not isinstance(token,str) or not token:return 400,{'error':'Invalid lease'}
                for slot in self.slots.values():
                    if slot['token'] and hmac.compare_digest(slot['token'].encode(),token.encode()):self.revoke(slot,'released');break
                # Idempotent revocation does not reset a newly leased generation.
                return 200,{'released':True}
            return 404,{'error':'Unknown operation'}
    def enter(self,token):
        self.expire()
        with self.cv:
            for slot in self.slots.values():
                if slot['status']=='leased' and token and hmac.compare_digest(slot['token'].encode(),token.encode()):
                    slot['active']+=1;return slot
    def leave(self,slot):
        with self.cv:slot['active']-=1;self.cv.notify_all()
    def close(self):self.lock_file.close()


def handler(pool,admin_token):
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*args):pass
        def send(self,status,value):
            raw=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.end_headers();
            if self.command!='HEAD':self.wfile.write(raw)
        def handle_request(self):
            if 'Transfer-Encoding' in self.headers:return self.send(400,{'error':'Unsupported transfer'})
            try: size=int(self.headers.get('Content-Length','0'))
            except ValueError:return self.send(400,{'error':'Invalid size'})
            if not 0<=size<=8_000_000:return self.send(413,{'error':'Request too large'})
            self.connection.settimeout(30)
            if self.path.startswith('/_control/'):
                auth=self.headers.get('Authorization','')
                if not hmac.compare_digest(auth.encode(),'Bearer '.encode()+admin_token.encode()):return self.send(401,{'error':'Unauthorized'})
                if self.command!='POST' or size>4096:return self.send(400,{'error':'Invalid command'})
                try:value=json.loads(self.rfile.read(size));status,result=pool.control(self.path.removeprefix('/_control/'),value)
                except (ValueError,TypeError,KeyError):return self.send(400,{'error':'Invalid command'})
                return self.send(status,result)
            slot=pool.enter(self.headers.get('X-Daylight-Lease'))
            if slot is None:return self.send(410,{'error':'Browser lease expired or revoked'})
            upstream=None
            try:
                parsed=urlsplit(self.path)
                if parsed.scheme or parsed.netloc or not self.path.startswith('/') or self.path.startswith('//'):return self.send(400,{'error':'Invalid path'})
                target=urlsplit(slot['config']['upstream_origin'])
                upstream=HTTPConnection(target.hostname,target.port or 80,timeout=25)
                headers={k:v for k,v in self.headers.items() if k.lower() not in HOP}
                headers.update(slot['config'].get('account_headers',{}))
                raw=self.rfile.read(size) if size else None
                upstream.request(self.command,self.path,raw,headers)
                response=upstream.getresponse()
                locations=[v for k,v in response.getheaders() if k.lower()=='location']
                redirect=normalized_redirect(locations[0],pool.config['browser_origin'],self.path) if len(locations)==1 else None
                if locations and redirect is None:
                    pool.event('redirect_blocked',slot['config']['site_id'])
                    return self.send(502,{'error':'Website redirect left its isolated origin; no replay'})
                # No transparent redirects or replays. Bound a single asset reply.
                data=response.read(32_000_001)
                if len(data)>32_000_000:return self.send(502,{'error':'Response too large'})
                self.send_response(response.status)
                for name,value in response.getheaders():
                    if name.lower() not in HOP|{'cache-control'}:self.send_header(name,redirect if name.lower()=='location' else value)
                self.send_header('Cache-Control','private, no-store');self.send_header('Content-Length',str(len(data)));self.end_headers()
                if self.command!='HEAD':self.wfile.write(data)
            except (OSError,TimeoutError):
                self.close_connection=True
                # Never repeat a request whose upstream effects may already exist.
                try:self.send(502,{'error':'Site response failed; no replay'})
                except OSError:pass
            finally:
                if upstream:upstream.close()
                pool.leave(slot)
        do_GET=do_POST=do_PUT=do_PATCH=do_DELETE=do_HEAD=do_OPTIONS=handle_request
    return Handler

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,required=True);parser.add_argument('--state',type=Path,required=True);parser.add_argument('--token-file',type=Path,required=True);parser.add_argument('--bind',default='127.0.0.1');parser.add_argument('--port',type=int,default=8896);args=parser.parse_args()
    config=json.loads(args.config.read_text());token=args.token_file.read_text().strip()
    if len(token)<32:raise ValueError('Private broker token required')
    pool=Pool(config,args.state);pool.initialize();server=ThreadingHTTPServer((args.bind,args.port),handler(pool,token))
    def expire():
        while True:time.sleep(5);pool.expire()
    threading.Thread(target=expire,daemon=True).start()
    try:server.serve_forever()
    finally:server.server_close();pool.close()
