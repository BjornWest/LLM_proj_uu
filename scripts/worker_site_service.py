"""Dedicated worker-only lease proxy with fixed private grader state operations.

Reuses reviewed forwarding/revocation/reset logic without modifying the manual
service. Proxy credentials stay outside browser request headers/HAR. Admission
is a private task/revision allowlist; no caller supplies SQL or container names.
"""
import argparse
import base64
from copy import deepcopy
import hashlib
import hmac
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import threading
import subprocess
from urllib.parse import urlsplit
if __package__:
    from .browse_pool_server import Pool, handler
    from .worker_site_clones import inspect
    from .worker_site_state import StateReader
else:
    from browse_pool_server import Pool, handler
    from worker_site_clones import inspect
    from worker_site_state import StateReader

OPERATIONS={'webarena.votes':{'forum.vote_state'},'webarena.posts':{'forum.submission_ids','forum.posts_since'},'webarena.wishlist':{'shopping.wishlist_state'}}

class WorkerPool(Pool):
    def __init__(self,*args,reader_factory=StateReader,**kwargs):
        super().__init__(*args,**kwargs);self.reader_factory=reader_factory
    def reset_command(self,slot):
        super().reset_command(slot)
        site=slot['config']['site_id'].removeprefix('webarena-')
        slot['container_id']=inspect(site,self.config['browser_origin'])['Id']
    def identity(self,slot):
        return {'instance_id':slot.get('container_id'),'reset_id':str(slot['generation'])+':'+str(slot.get('reset_report_sha256')),
                'session_id':slot['session'],'generation':slot['generation'],'container_id':slot.get('container_id'),
                'image_id':slot['config']['image_id'],'reset_report_sha256':slot.get('reset_report_sha256')}
    def control(self,op,value):
        if not isinstance(value,dict):return 400,{'error':'Invalid request'}
        if op=='acquire':
            if set(value)!={'task_id','revision','session_id'}:return 400,{'error':'Exact task revision required'}
            if not all(isinstance(value[k],str) for k in value):return 400,{'error':'Invalid task identity'}
            task=self.config['tasks'].get(value['task_id'])
            if not task or value['revision']!=task['revision']:return 409,{'error':'Task is not admitted'}
            with self.cv:
                status,result=super().control(op,{'site_id':task['site_id'],'session_id':value['session_id']})
                if status!=200:return status,result
                slot=self.slots[task['site_id']];slot.update(task=deepcopy(task),baseline=None,started=self.clock());slot['deadline']=self.clock()+900
                return 200,{**result,'task_id':value['task_id'],'revision':value['revision'],'target_id':task.get('target_id'),'identity':self.identity(slot),
                    'worker_source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),Path(__file__).with_name('worker_site_state.py'),Path(__file__).with_name('worker_site_clones.py')]},
                    'browser_proxy':{'server':self.config['proxy_origin'],'username':slot['session'],'password':result['lease_token']}}
        if op in ('state','renew'):
            if set(value)!=({'lease_token','operation'} if op=='state' else {'lease_token'}):return 400,{'error':'Invalid scoped operation'}
            if not isinstance(value['lease_token'],str) or (op=='state' and not isinstance(value['operation'],str)):
                return 400,{'error':'Invalid scoped operation'}
            slot=self.enter(value['lease_token'])
            if slot is None:return 410,{'error':'Lease unavailable'}
            try:
                with self.cv:
                    if op=='renew':
                        if self.clock()-slot['started']>=7200:self.revoke(slot,'maximum_job_duration');return 410,{'error':'Job duration exceeded'}
                        slot['deadline']=self.clock()+900;return 200,{'identity':self.identity(slot)}
                    operation=value['operation'];family=slot['task']['family']
                    if operation not in OPERATIONS.get(family,set()):return 403,{'error':'State operation is not allowed for this task'}
                    reader=self.reader_factory(slot['config']['site_id'].removeprefix('webarena-'),slot['container_id'],self.config['browser_origin'])
                    if operation=='forum.submission_ids':
                        current=reader.submission_ids()
                        if slot['baseline'] is None:slot['baseline']=list(current)
                        result=current
                    elif operation=='forum.posts_since':
                        if slot['baseline'] is None:return 409,{'error':'No lease-bound initial IDs'}
                        result=reader.posts_since(slot['baseline'])
                    elif operation=='forum.vote_state':result=reader.vote_state(slot['task']['target_id'])
                    else:result=reader.wishlist_state()
                    return 200,{'identity':self.identity(slot),'operation':operation,'value':result}
            finally:self.leave(slot)
        if op not in ('release','status'):return 404,{'error':'Unsupported worker operation'}
        return super().control(op,value)


def worker_handler(pool,token):
    Base=handler(pool,token)
    class Handler(Base):
        def handle_request(self):
            if self.path.startswith('/_control/'):
                try:return super().handle_request()
                except (OSError,RuntimeError,subprocess.SubprocessError):return self.send(503,{'error':'Worker state operation failed'})
            auth=self.headers.get('Proxy-Authorization','')
            try:
                if not auth.startswith('Basic '):raise ValueError('Proxy auth required')
                user,secret=base64.b64decode(auth[6:],validate=True).decode().split(':',1)
            except (ValueError,UnicodeError):
                self.send_response(407);self.send_header('Proxy-Authenticate','Basic realm="Worker environment"');self.send_header('Content-Length','0');self.send_header('Connection','close');self.end_headers();self.close_connection=True;return
            slot=pool.enter(secret)
            if slot is None:return self.send(410,{'error':'Worker lease revoked'})
            try:
                if not hmac.compare_digest(user.encode(),slot['session'].encode()):return self.send(403,{'error':'Wrong worker session'})
                try:u=urlsplit(self.path);base=urlsplit(pool.config['browser_origin'])
                except ValueError:return self.send(400,{'error':'Invalid URL'})
                if u.username or u.password or u.fragment or (u.scheme,u.netloc)!=(base.scheme,base.netloc):return self.send(403,{'error':'Outside worker site'})
                path=u.path or '/'
                if path.startswith('//') or path.startswith('/_control/'):return self.send(403,{'error':'Reserved path'})
                self.path=path+('?' + u.query if u.query else '')
                for name in ['X-Daylight-Lease','Host']:
                    if name in self.headers:del self.headers[name]
                self.headers['X-Daylight-Lease']=secret;self.headers['Host']=base.netloc
                return super().handle_request()
            finally:pool.leave(slot)
        do_GET=do_HEAD=do_POST=do_PUT=do_PATCH=do_DELETE=do_OPTIONS=handle_request
        def do_CONNECT(self):self.send(403,{'error':'External tunnels are not permitted'})
    return Handler

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--state',type=Path,required=True);p.add_argument('--token-file',type=Path,required=True);p.add_argument('--bind',default='127.0.0.1');p.add_argument('--port',type=int,default=8897);a=p.parse_args()
    config=json.loads(a.config.read_text());token=a.token_file.read_text().strip()
    if len(token)<43:raise ValueError('Strong private control token required')
    pool=WorkerPool(config,a.state);pool.initialize();server=ThreadingHTTPServer((a.bind,a.port),worker_handler(pool,token))
    def sweep():
        while True:
            import time
            time.sleep(5);pool.expire()
    threading.Thread(target=sweep,daemon=True).start()
    try:server.serve_forever()
    finally:server.server_close();pool.close()
