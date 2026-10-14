"""Single shared capacity poller and bounded SSH-return observation journal.

No W&B credentials or cloud calls. The workstation reads the remote append-only
journal/observer RPC and owns its sole W&B writer. The existing reviewed capacity
parent owns retirement, cancellation and cleanup verification semantics.
"""
from contextlib import contextmanager
from pathlib import Path
import hmac
import json
import os
import selectors
import socket
import threading
import time
import uuid


def append(path, value):
    with Path(path).open('a') as f:
        f.write(json.dumps(value, ensure_ascii=False, allow_nan=False)+'\n')


class ObserverJournal:
    def __init__(self, observer, poller, output, *, stop_event, interval=1):
        self.observer, self.poller, self.output = observer, poller, Path(output)
        self.stop = stop_event
        self.interval, self.cursor, self.observer_id = interval, 0, observer.observer_id
        self.epoch = uuid.uuid4().hex
        self.failure = None
        self.finished = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def read(self, *, after=0, observer_id=None, epoch=None, limit=120):
        if epoch is not None and epoch != self.epoch:
            raise ValueError('Observer transport epoch changed')
        if after and epoch != self.epoch:
            raise ValueError('Nonzero cursor requires exact epoch')
        value = self.observer.read(after=after, limit=limit, observer_id=observer_id)
        return {**value, 'epoch': self.epoch, 'poller': self.poller.status()}

    def drain(self):
        value = self.read(after=self.cursor, observer_id=self.observer_id, epoch=self.epoch)
        append(self.output, {'schema': 'qwen-serving-journal-batch-v1', 'after': self.cursor, **value})
        if value['rows']:
            self.cursor = value['rows'][-1]['seq']
        return value

    def _run(self):
        try:
            while not self.finished.wait(self.interval):
                self.drain()
            self.drain()
        except BaseException as e:
            self.failure = e
            self.stop.set()  # Transport loss is infrastructure failure, never a verdict.

    def close(self):
        self.finished.set()
        self.thread.join(5)
        if self.thread.is_alive():
            raise RuntimeError('Serving journal failed to terminate')
        if self.failure is not None:
            raise RuntimeError('Serving journal failed') from self.failure


class ObserverRPC:
    """Private read-only AF_UNIX service, bounded to 120 rows per response."""
    def __init__(self, journal, directory):
        self.journal = journal
        self.path = Path(directory)/'observer.sock'
        self.listener = socket.socket(socket.AF_UNIX)
        self.listener.bind(str(self.path));os.chmod(self.path, 0o600)
        self.listener.listen(4);self.listener.settimeout(.2)
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True);self.thread.start()

    def _run(self):
        while not self.stop.is_set():
            try:
                connection, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                if self.stop.is_set():return
                raise
            with connection:
                connection.settimeout(2)
                try:
                    raw = b''
                    while b'\n' not in raw:
                        part = connection.recv(8193-len(raw))
                        if not part:raise ValueError('Observer client disconnected')
                        raw += part
                        if not raw or len(raw)>8192:raise ValueError('Bounded observer frame required')
                    if raw.count(b'\n') != 1 or not raw.endswith(b'\n'):
                        raise ValueError('One observer frame required')
                    request = json.loads(raw)
                    if (not isinstance(request, dict) or request.get('op') != 'read'
                            or set(request)-{'op','after','observer_id','epoch','limit'}):
                        raise ValueError('Read-only observer operation required')
                    value = self.journal.read(**{k:v for k,v in request.items() if k!='op'})
                    reply = {'status':'ok','value':value}
                except Exception as e:
                    reply = {'status':'error','type':type(e).__name__,'message':str(e)}
                try:connection.sendall((json.dumps(reply,allow_nan=False)+'\n').encode())
                except OSError:pass

    def close(self):
        self.stop.set();self.listener.close();self.thread.join(4)
        if self.thread.is_alive():raise RuntimeError('Observer RPC failed to terminate')
        self.path.unlink(missing_ok=True)


class RuntimeLimitsRPC:
    """Authenticated parent-only updates across queue and generation admission.

    The queue lock fences pump/finish while the controller performs its CAS.
    Decreasing targets drains existing lifecycles; no actor or request is canceled.
    """
    def __init__(self, queue, controller, directory, output, *, stop_event, deadline):
        self.queue, self.controller = queue, controller
        self.stop, self.deadline = stop_event, deadline
        self.output = Path(output)
        self.token = uuid.uuid4().hex + uuid.uuid4().hex
        self.path = Path(directory) / 'runtime-limits.sock'
        self.finished = threading.Event()
        self.listener = socket.socket(socket.AF_UNIX)
        self.listener.bind(str(self.path)); os.chmod(self.path, 0o600)
        self.listener.listen(4); self.listener.settimeout(.2)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _open(self):
        if self.finished.is_set() or self.stop.is_set() or time.monotonic() >= self.deadline:
            raise RuntimeError('Runtime limits endpoint is closed or expired')

    def limits(self):
        with self.queue.condition:
            self._open()
            q = self.queue.snapshot()
            value = self.controller.limits()
            if q['target'] != value['max_active_episodes']:
                raise RuntimeError('Queue and controller admission targets differ')
            return {**value, 'queue': q}

    def update_limits(self, *, max_active_episodes, max_generation_requests, expected_revision):
        with self.queue.condition:
            self._open()
            self.queue.validate_target(max_active_episodes)
            value = self.controller.update_limits(max_active_episodes=max_active_episodes,
                max_generation_requests=max_generation_requests, expected_revision=expected_revision)
            # Queue target validation and mutation share this same lock. CAS
            # rejection above leaves both admission mechanisms unchanged.
            self.queue.set_target(max_active_episodes)
            result = {**value, 'queue': self.queue.snapshot()}
            try:
                append(self.output, {'event': 'runtime_limits_updated', **result})
            except OSError as error:
                self.stop.set()
                raise RuntimeError('Limits update applied but journal failed; suite stopped') from error
            return result

    def _request(self, request):
        if (type(request) is not dict or type(request.get('token')) is not str
                or not hmac.compare_digest(request['token'], self.token)):
            raise ValueError('Private runtime control capability required')
        if request.get('op') == 'limits' and set(request) == {'op', 'token'}:
            return self.limits()
        if (request.get('op') == 'update_limits' and set(request) ==
                {'op', 'token', 'max_active_episodes', 'max_generation_requests', 'expected_revision'}):
            return self.update_limits(**{k:v for k,v in request.items() if k not in ('op','token')})
        raise ValueError('Use limits or exact revision-bound update_limits fields')

    def _run(self):
        while not self.finished.is_set():
            try:
                connection, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                if self.finished.is_set(): return
                self.stop.set(); return
            with connection:
                end = time.monotonic() + 2
                try:
                    raw = b''
                    while b'\n' not in raw:
                        connection.settimeout(max(.001, end-time.monotonic()))
                        if time.monotonic() >= end: raise TimeoutError('Runtime control frame deadline')
                        part = connection.recv(8193-len(raw))
                        if not part: raise ValueError('Runtime control disconnected')
                        raw += part
                        if len(raw)>8192: raise ValueError('Bounded runtime control frame required')
                    if raw.count(b'\n') != 1 or not raw.endswith(b'\n'):
                        raise ValueError('One runtime control frame required')
                    def unique(pairs):
                        result = {}
                        for key,value in pairs:
                            if key in result: raise ValueError('Duplicate runtime control field')
                            result[key] = value
                        return result
                    request = json.loads(raw, object_pairs_hook=unique)
                    result = self._request(request)
                    reply = {'status':'ok','value':result}
                except Exception as e:
                    reply = {'status':'error','type':type(e).__name__,'message':str(e)}
                try:
                    connection.settimeout(2)
                    connection.sendall((json.dumps(reply,allow_nan=False)+'\n').encode())
                except OSError: pass

    def descriptor(self):
        return {'schema':'qwen-runtime-limits-private-v1','path':str(self.path),'token':self.token}

    def close(self):
        self.finished.set();self.listener.close();self.thread.join(5)
        if self.thread.is_alive(): raise RuntimeError('Runtime limits RPC failed to terminate')
        self.path.unlink(missing_ok=True)


class ScriptedMetrics:
    """Explicit model-free metrics fixture; never a serving/readiness proof."""
    def __init__(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != '/metrics':
                    self.send_error(404); return
                label='{model_name="scripted",engine="0"}'
                rows=[('vllm:num_requests_waiting',0),('vllm:num_requests_running',0),
                    ('vllm:kv_cache_usage_perc',.1),('vllm:num_preemptions_total',0),
                    ('vllm:generation_tokens_total',0)]
                body='\n'.join(f'{key}{label} {value}' for key,value in rows)+'\n'
                for reason in ('capacity','deferred'):
                    body+=f'vllm:num_requests_waiting_by_reason{{model_name="scripted",engine="0",reason="{reason}"}} 0\n'
                raw=body.encode();self.send_response(200)
                self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            def log_message(self,*args): pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.raw=f'http://127.0.0.1:{self.server.server_port}'

    def close(self):
        self.server.shutdown();self.server.server_close();self.thread.join(3)
        if self.thread.is_alive(): raise RuntimeError('Scripted metrics fixture failed to stop')


class CapacityHost:
    """Bridge private child Unix connections to the reviewed capacity RPC.

    Socketpairs stay in the supervisor; no FD inheritance through systemd/WSL
    launcher is assumed. One selector thread per launched case forwards bytes,
    never interprets or reconstructs the reviewed RPC protocol.
    """
    def __init__(self, *, rpc, control, telemetry, source, output, case_ids, cap,
                 deadline, stop_event, directory, qualification):
        self.rpc, self.stop, self.directory = rpc, stop_event, Path(directory)
        self.case_isolation = source.get('runtime_mode') == 'qwen-private-v1'
        self.pairs = {}
        self.listeners, self.tokens, self.relays = {}, {}, {}
        self.controller=self.parent=self.observer=self.poller=self.journal=self.observer_rpc=self.limits_rpc=None
        self.deadline = deadline
        self.cleanup_grace = source.get('shutdown_grace_seconds',30)
        if type(self.cleanup_grace) is not int or not 1 <= self.cleanup_grace <= 120:
            raise ValueError('Capacity relay cleanup grace must be1..120 seconds')
        try:
            for ident in case_ids:self.pairs[ident]=socket.socketpair()
            limits = source.get('runtime_limits')
            ceiling = None if limits is None else {
                'max_active_episodes':limits['max_active_ceiling'],
                'max_generation_requests':limits['max_generation_ceiling']}
            config = control.ParkingConfig(max_active_episodes=cap,
                max_generation_requests=cap if limits is None else limits['initial_generation_requests'], fresh_seconds=3)
            self.controller = (control.EpisodeCapacityController(config) if limits is None else
                control.EpisodeCapacityController(config, limits_ceiling=ceiling))
            self.parent = rpc.CapacityParent(self.controller,
                {i:p[0] for i,p in self.pairs.items()}, deadline=deadline, suite_stop_event=stop_event).start()
            self.observer = telemetry.ServingTelemetry(session_id=qualification.session,
                model=qualification.identity['model'], model_revision=qualification.identity['serving_revision'])
            self.poller = control.SharedMetricsPoller(qualification.raw+'/metrics',
                model=qualification.identity['model'], interval=1, timeout=2,
                on_snapshot=self.controller.observe, on_scrape=self.observer.observe)
            self.poller.start()
            self.journal = ObserverJournal(self.observer,self.poller,Path(output)/'serving-telemetry.jsonl',stop_event=stop_event)
            self.observer_rpc = ObserverRPC(self.journal,directory)
            for ident in case_ids:
                listener=socket.socket(socket.AF_UNIX);listener.bind(str(self.directory/(ident+'-capacity.sock')))
                listener.listen(1);listener.settimeout(.2);self.listeners[ident]=listener
                self.tokens[ident]=uuid.uuid4().hex+uuid.uuid4().hex
            self.deadline = deadline
        except BaseException as primary:
            try:self.close()
            except BaseException as closing:primary.add_note('Host initialization cleanup failed: '+repr(closing))
            raise

    def bind_limits(self, queue, output):
        if self.limits_rpc is not None: raise RuntimeError('Runtime limits endpoint already bound')
        self.limits_rpc = RuntimeLimitsRPC(queue, self.controller, self.directory,
            Path(output)/'runtime-limits-events.jsonl',stop_event=self.stop,deadline=self.deadline)
        path = Path(output)/'runtime-limits-private.json'
        try:
            fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
            with os.fdopen(fd,'w') as stream:
                json.dump(self.limits_rpc.descriptor(),stream);stream.write('\n')
        except BaseException:
            self.limits_rpc.close();self.limits_rpc=None
            raise

    def child_binding(self, ident):
        return {'path':str(self.directory/(ident+'-capacity.sock')),'token':self.tokens[ident],
                'deadline_utc':time.time()+self.deadline-time.monotonic()}

    def begin_relay(self, ident):
        errors=[]
        def relay():
            listener=self.listeners[ident];remote=None;local=self.pairs[ident][1]
            try:
                while not self.stop.is_set() and time.monotonic()<self.deadline:
                    try:remote,_=listener.accept();break
                    except socket.timeout:continue
                if remote is None:return
                remote.settimeout(5)
                raw=b''
                while not raw.endswith(b'\n'):
                    data=remote.recv(1)
                    if not data or len(raw)>256:raise ValueError('Missing capacity binding')
                    raw+=data
                if not hmac.compare_digest(raw.rstrip(b'\n').decode(),self.tokens[ident]):
                    raise ValueError('Foreign capacity capability')
                remote.sendall(b'OK\n');remote.setblocking(False);local.setblocking(False)
                drain_deadline = None
                with selectors.DefaultSelector() as selector:
                    selector.register(remote,selectors.EVENT_READ,local)
                    selector.register(local,selectors.EVENT_READ,remote)
                    while True:
                        now=time.monotonic()
                        if self.stop.is_set() and drain_deadline is None:
                            drain_deadline=now+self.cleanup_grace
                        if now >= self.deadline or (drain_deadline is not None and now >= drain_deadline):return
                        # A stop blocks new admission, but an established peer
                        # must still deliver its final exact release and ack.
                        for key,_ in selector.select(.2):
                            try:data=key.fileobj.recv(65536)
                            except BlockingIOError:continue
                            if not data:return
                            # Buffered send has a finite limit; never allow an unbounded blocked writer.
                            target=key.data;target.settimeout(2)
                            try:target.sendall(data)
                            finally:target.setblocking(False)
            except BaseException as e:
                errors.append(e)
                if not self.case_isolation:self.stop.set()
            finally:
                if remote:remote.close()
                local.close()
        thread=threading.Thread(target=relay,daemon=True);self.relays[ident]=(thread,errors);thread.start()

    def activate(self, ident, *, priority):
        if self.limits_rpc is None:
            self.parent.activate(ident,priority=priority)
            return
        # A target can be lowered while an already-admitted actor is still
        # setting up its environment. Preserve that actor; park before its
        # controller registration rather than rejecting or canceling it.
        q = self.limits_rpc.queue
        with q.condition:
            while True:
                self.limits_rpc._open()
                value = self.controller.limits()
                if value['active_episodes'] < value['max_active_episodes']:
                    self.parent.activate(ident,priority=priority)
                    return
                q.condition.wait(.1)

    def finish(self, ident, *, verify_cleanup, record_terminal):
        self.parent.finish_after_cleanup(ident,verify_cleanup=verify_cleanup,
                                         record_terminal=record_terminal,timeout=5)

    def finish_failed_case(self, ident, *, verify_cleanup, record_terminal):
        """Isolate a fully cleaned case; never release an uncertain sent request."""
        status = self.controller.status()
        row = status['episodes'].get(ident)
        if (self.stop.is_set() or self.parent.closed or self.parent.stop_cause is not None
                or self.parent.cleanup_failures or status['telemetry_fresh'] is not True
                or row is not None and row['request_id'] is not None
                or ident in self.parent.errors or self.relays.get(ident, (None, []))[1]
                or self.journal.failure is not None or not self.poller.thread.is_alive()):
            raise RuntimeError('Shared health or exact case request cleanup is unverified')
        self.finish(ident, verify_cleanup=verify_cleanup, record_terminal=record_terminal)

    def quarantine_case(self, ident, error):
        self.parent.quarantine_after_failure(ident,error)

    def finish_isolated_case(self, ident, *, verify_cleanup, record_terminal):
        self.parent.finish_after_cleanup(ident,verify_cleanup=verify_cleanup,
            record_terminal=record_terminal,timeout=5,abort_cohort_on_failure=False)

    def failed(self, ident, error, *, infrastructure=True):
        self.parent.abort_after_failure(ident,error,infrastructure=infrastructure)

    def close(self):
        errors=[]
        def attempt(function):
            try:function()
            except BaseException as e:errors.append(e)
        for resource in (self.limits_rpc,self.observer_rpc,self.poller,self.journal,self.parent,self.controller):
            if resource is not None:attempt(resource.close)
        for listener in self.listeners.values():attempt(listener.close)
        for pair in self.pairs.values():
            for endpoint in pair:attempt(endpoint.close)
        for thread,issues in self.relays.values():
            thread.join(3)
            if thread.is_alive():errors.append(RuntimeError('Capacity relay did not terminate'))
            errors.extend(issues)
        if errors:raise BaseExceptionGroup('Capacity/observer cleanup failed',errors)


def connect_client(rpc, binding, *, deadline, on_event=None):
    connection=socket.socket(socket.AF_UNIX);connection.settimeout(min(5,deadline-time.monotonic()))
    try:
        connection.connect(binding['path']);connection.sendall((binding['token']+'\n').encode())
        answer=b''
        while not answer.endswith(b'\n'):
            part=connection.recv(1)
            if not part or len(answer)>32:raise ValueError('Capacity relay rejected binding')
            answer+=part
        if answer!=b'OK\n':raise ValueError('Capacity relay rejected binding')
        return rpc.CapacityClient(connection,deadline=deadline,on_event=on_event)
    except BaseException:
        connection.close();raise


def runtime_limits_request(descriptor, operation, **limits):
    """SSH-local client; capability is read from a private file, never argv."""
    path = Path(descriptor)
    info = path.lstat()
    import stat
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600):
        raise ValueError('Owner-only regular runtime control descriptor required')
    value = json.loads(path.read_bytes())
    if (type(value) is not dict or set(value) != {'schema','path','token'}
            or value['schema'] != 'qwen-runtime-limits-private-v1'
            or type(value['path']) is not str or type(value['token']) is not str):
        raise ValueError('Exact private runtime control descriptor required')
    if operation not in ('limits','update_limits'):
        raise ValueError('Unsupported runtime control operation')
    request = {'op':operation,'token':value['token'],**limits}
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(4);connection.connect(value['path'])
        connection.sendall((json.dumps(request,allow_nan=False)+'\n').encode())
        raw = b''
        end = time.monotonic()+4
        while b'\n' not in raw:
            remaining = end-time.monotonic()
            if remaining <= 0: raise TimeoutError('Runtime control response deadline')
            connection.settimeout(remaining)
            part = connection.recv(8193-len(raw))
            if not part: raise RuntimeError('Runtime control closed without reply')
            raw += part
            if len(raw)>8192: raise ValueError('Runtime control response exceeds limit')
        if not raw.endswith(b'\n') or raw.count(b'\n') != 1:
            raise ValueError('One runtime control response required')
        result = json.loads(raw)
        if result.get('status') != 'ok':
            raise RuntimeError('Runtime control rejected: '+str(result.get('message')))
        return result['value']


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Private SSH-local suite admission control')
    parser.add_argument('--descriptor',required=True)
    parser.add_argument('operation',choices=['limits','update_limits'])
    parser.add_argument('--max-active-episodes',type=int)
    parser.add_argument('--max-generation-requests',type=int)
    parser.add_argument('--expected-revision',type=int)
    args=parser.parse_args()
    fields={'max_active_episodes':args.max_active_episodes,
        'max_generation_requests':args.max_generation_requests,'expected_revision':args.expected_revision}
    if args.operation=='limits':
        if any(v is not None for v in fields.values()):parser.error('limits accepts no update fields')
        fields={}
    elif any(v is None for v in fields.values()):parser.error('update_limits requires both targets and expected revision')
    print(json.dumps(runtime_limits_request(args.descriptor,args.operation,**fields),allow_nan=False))
