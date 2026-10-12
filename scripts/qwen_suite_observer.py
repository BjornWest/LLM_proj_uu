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


class CapacityHost:
    """Bridge private child Unix connections to the reviewed capacity RPC.

    Socketpairs stay in the supervisor; no FD inheritance through systemd/WSL
    launcher is assumed. One selector thread per launched case forwards bytes,
    never interprets or reconstructs the reviewed RPC protocol.
    """
    def __init__(self, *, rpc, control, telemetry, source, output, case_ids, cap,
                 deadline, stop_event, directory, qualification):
        self.rpc, self.stop, self.directory = rpc, stop_event, Path(directory)
        self.pairs = {}
        self.listeners, self.tokens, self.relays = {}, {}, {}
        self.controller=self.parent=self.observer=self.poller=self.journal=self.observer_rpc=None
        self.deadline = deadline
        try:
            for ident in case_ids:self.pairs[ident]=socket.socketpair()
            self.controller = control.EpisodeCapacityController(control.ParkingConfig(
                max_active_episodes=cap, max_generation_requests=cap, fresh_seconds=3))
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

    def child_binding(self, ident):
        return {'path':str(self.directory/(ident+'-capacity.sock')),'token':self.tokens[ident]}

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
                with selectors.DefaultSelector() as selector:
                    selector.register(remote,selectors.EVENT_READ,local)
                    selector.register(local,selectors.EVENT_READ,remote)
                    while not self.stop.is_set() and time.monotonic()<self.deadline:
                        for key,_ in selector.select(.2):
                            try:data=key.fileobj.recv(65536)
                            except BlockingIOError:continue
                            if not data:return
                            # Buffered send has a finite limit; never allow an unbounded blocked writer.
                            target=key.data;target.settimeout(2)
                            try:target.sendall(data)
                            finally:target.setblocking(False)
            except BaseException as e:
                errors.append(e);self.stop.set()
            finally:
                if remote:remote.close()
                local.close()
        thread=threading.Thread(target=relay,daemon=True);self.relays[ident]=(thread,errors);thread.start()

    def activate(self, ident, *, priority):
        self.parent.activate(ident,priority=priority)

    def finish(self, ident, *, verify_cleanup, record_terminal):
        self.parent.finish_after_cleanup(ident,verify_cleanup=verify_cleanup,
                                         record_terminal=record_terminal,timeout=5)

    def failed(self, ident, error, *, infrastructure=True):
        self.parent.abort_after_failure(ident,error,infrastructure=infrastructure)

    def close(self):
        errors=[]
        def attempt(function):
            try:function()
            except BaseException as e:errors.append(e)
        for resource in (self.observer_rpc,self.poller,self.journal,self.parent,self.controller):
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
