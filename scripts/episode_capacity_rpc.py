"""Case-owned generation gates for one parent capacity controller.

The parent supplies inherited socket pairs, activates cases at the existing
queue boundary, and finishes them after verified HTTP/process cleanup. No
network listener, process launcher, model retry or controller import is hidden
here. The controller and its metrics poller are owned by the outer caller.
"""
from contextlib import contextmanager
from collections import deque
import json
import math
import select
import socket
import struct
import threading
import time


class CapacityChannelError(RuntimeError):
    pass


def _send(connection, value):
    data = json.dumps(value, allow_nan=False).encode()
    if len(data) > 4096:
        raise CapacityChannelError('Capacity frame too large')
    connection.sendall(struct.pack('!I', len(data)) + data)


def _receive(connection, *, deadline=None, clock=time.monotonic):
    def exact(n, eof=False):
        data = bytearray()
        while len(data) < n:
            if deadline is not None:
                remaining = deadline - clock()
                if remaining <= 0:
                    raise TimeoutError('Capacity receive deadline expired')
                connection.settimeout(remaining)
            part = connection.recv(n - len(data))
            if not part:
                if eof and not data:
                    return None
                raise CapacityChannelError('Incomplete capacity frame')
            data.extend(part)
        return data
    header = exact(4, True)
    if header is None:
        return None
    size, = struct.unpack('!I', header)
    if not 0 < size <= 4096:
        raise CapacityChannelError('Invalid capacity frame length')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise CapacityChannelError('Duplicate capacity field')
            result[key] = value
        return result
    try:
        value = json.loads(exact(size), object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    except (ValueError, UnicodeError) as exc:
        raise CapacityChannelError('Malformed capacity JSON') from exc
    if type(value) is not dict:
        raise CapacityChannelError('Capacity frame must be an object')
    return value


class CapacityParent:
    """Independent per-case RPC threads; blocked acquisition cannot block release.

    ``connections`` is a finite caller-owned mapping of unique run/case IDs to
    sockets. Children have no register, finish, telemetry or foreign-case API.
    A disconnected child's permit is retained until the caller verifies cleanup.
    """
    def __init__(self, controller, connections, *, deadline, clock=time.monotonic):
        if not connections or any(type(k) is not str or not k for k in connections):
            raise ValueError('Expected finite unique run/case IDs')
        if not math.isfinite(deadline) or deadline <= clock():
            raise ValueError('Expected future caller/rental deadline')
        self.controller, self.deadline, self.clock = controller, deadline, clock
        self.connections = dict(connections)
        self.active, self.finished, self.threads = set(), set(), {}
        self.errors = {}
        self.ended, self.finishing = set(), set()
        self.stops = {case:threading.Event() for case in connections}
        self.lock = threading.Lock()
        self.closed = False
        self.started = False

    def start(self):
        with self.lock:
            if self.started or self.closed:
                raise ValueError('Parent already started/closed')
            self.started = True
        try:
            with self.lock:
                for case, connection in self.connections.items():
                    thread = threading.Thread(target=self._serve, args=(case, connection), daemon=True)
                    thread.start()
                    self.threads[case] = thread  # Never retain an unstarted thread.
        except BaseException:
            self.close()
            raise
        return self

    def activate(self, case, *, priority=0):
        """Call only after the real queue active admission, never during prewarm."""
        with self.lock:
            if (self.closed or case not in self.connections or case in self.active
                    or case in self.finished or case in self.finishing or case in self.ended
                    or case not in self.threads or not self.threads[case].is_alive()):
                raise ValueError('Invalid/duplicate parent activation')
            self.controller.register_episode(case, priority=priority)
            self.active.add(case)

    def _serve(self, case, connection):
        sequence = 0
        failed = False
        try:
            while True:
                row = self.controller.status()['episodes'].get(case, {})
                # Generation stops at the rental deadline; release/teardown
                # gets a short cleanup watchdog, without another generation.
                deadline = self.deadline + (5 if row.get('request_id') is not None else 0)
                value = _receive(connection, deadline=deadline, clock=self.clock)
                if value is None:
                    return
                with self.lock:
                    if case not in self.active or case in self.finished or self.closed:
                        raise CapacityChannelError('Case is not actively admitted')
                if value.get('type') == 'acquire':
                    if (set(value) != {'type', 'phase', 'sequence'}
                            or value['phase'] not in ('policy', 'formatter')
                            or type(value['sequence']) is not int
                            or value['sequence'] != sequence + 1):
                        raise CapacityChannelError('Invalid phase/sequence')
                    sequence = value['sequence']
                    request_id = f'{case}:{value["phase"]}:{sequence}'
                    remaining = self.deadline - self.clock()
                    if remaining <= 0:
                        raise TimeoutError('Caller/rental deadline expired')
                    stop, monitoring_done = self.stops[case], threading.Event()
                    wake_read, wake_write = socket.socketpair()
                    monitor_errors = []
                    def watch_wait():
                        try:
                            poll = select.poll()
                            poll.register(connection, select.POLLIN | select.POLLHUP | select.POLLERR)
                            poll.register(wake_read, select.POLLIN)
                        except Exception as exc:
                            monitor_errors.append(exc);stop.set()
                            return
                        last_fresh = None
                        while not monitoring_done.is_set() and not stop.is_set():
                            try:
                                events = poll.poll(25)
                                if any(fd == wake_read.fileno() for fd, _ in events):
                                    return
                                if any(fd == connection.fileno() for fd, _ in events):
                                    # No child frame is valid before its permit.
                                    # EOF or pipelining cancels this UNSENT wait.
                                    connection.recv(1, socket.MSG_PEEK | socket.MSG_DONTWAIT)
                                    stop.set()
                                    return
                                # Only an actual wait emits status. Fast grants
                                # wake this thread immediately without 25ms tax.
                                fresh = self.controller.status()['telemetry_fresh']
                                if fresh != last_fresh:
                                    _send(connection, {'type':'waiting', 'telemetry_fresh':fresh})
                                    last_fresh = fresh
                            except Exception as exc:
                                # A local poll/send defect is not evidence of
                                # peer EOF; retain its actual diagnostic.
                                monitor_errors.append(exc)
                                stop.set()
                    monitor = threading.Thread(target=watch_wait, daemon=True)
                    acquired = False
                    acquire_started = self.clock()
                    try:
                        monitor.start()
                        try:
                            self.controller.acquire_turn(case, request_id,
                                timeout=remaining, stop_event=stop)
                        except Exception as exc:
                            if monitor_errors:
                                raise CapacityChannelError('Capacity watcher failed: '+str(monitor_errors[0])) from exc
                            raise
                        acquired = True
                        acquire_wait_seconds = self.clock()-acquire_started
                    finally:
                        monitoring_done.set()
                        wake_write.sendall(b'1')
                        if monitor.ident is not None:
                            monitor.join(1)
                        wake_write.close();wake_read.close()
                    if monitor.is_alive() or monitor_errors:
                        if acquired:
                            self.controller.release_turn(case, request_id)
                        raise CapacityChannelError('Capacity watcher failed: '+
                            (str(monitor_errors[0]) if monitor_errors else 'did not stop'))
                    if stop.is_set():
                        # Permit has not been sent, so no HTTP request can exist.
                        self.controller.release_turn(case, request_id)
                        raise CapacityChannelError('Child disconnected/cancelled before permit')
                    # If this send fails, do not release possibly-sent HTTP work.
                    _send(connection, {'type': 'permit', 'request_id': request_id,
                        'acquire_wait_seconds':acquire_wait_seconds})
                elif value.get('type') == 'release':
                    if set(value) != {'type', 'request_id'} or type(value['request_id']) is not str:
                        raise CapacityChannelError('Invalid release frame')
                    self.controller.release_turn(case, value['request_id'])
                    _send(connection, {'type': 'released', 'request_id': value['request_id']})
                else:
                    raise CapacityChannelError('Unknown capacity operation')
        except Exception as exc:
            failed = True
            with self.lock:
                self.errors[case] = {'type': type(exc).__name__, 'message': str(exc)}
            try:
                _send(connection, {'type': 'error', 'error_type':type(exc).__name__,
                    'message': str(exc)[:500], 'telemetry_fresh':self.controller.status()['telemetry_fresh']})
            except OSError:
                pass
        finally:
            with self.lock:
                registered = case in self.active and case not in self.finished
                finishing = case in self.finishing
                self.ended.add(case)
            if registered and not finishing:
                row = self.controller.status()['episodes'][case]
                if failed or row['request_id'] is not None:
                    self._cancel_registered(case)
            connection.close()

    def _cancel_registered(self, case):
        row = self.controller.status()['episodes'].get(case)
        if row is not None and not row['done'] and not row['cancelled']:
            self.controller.cancel_episode(case)

    def _shutdown(self, case):
        self.stops[case].set()
        try:
            self.connections[case].shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def cancel(self, case):
        """Wake local wait; this does not establish remote HTTP cleanup."""
        with self.lock:
            if case not in self.connections:
                raise ValueError('Unknown case')
            registered = case in self.active and case not in self.finished
        if registered:
            self._cancel_registered(case)
        self._shutdown(case)

    def finish_after_cleanup(self, case, *, verify_cleanup, record_terminal, timeout=5):
        """Trusted outer boundary after child exit, HTTP abort/drain and grading.

        Both callbacks must return literal True. ``record_terminal`` verifies
        persisted grade/projection or explicit infrastructure failure evidence;
        it must not demand a passing task verdict. Failed cleanup retains the
        controller permit and active episode, and must block queue refill.
        """
        if not callable(verify_cleanup) or not callable(record_terminal):
            raise ValueError('Explicit cleanup and terminal evidence callbacks required')
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('Finite worker cleanup timeout required')
        with self.lock:
            if case not in self.connections or case in self.finished or case in self.finishing:
                raise ValueError('Duplicate episode finish')
            self.finishing.add(case)
        try:
            self._shutdown(case)
            thread = self.threads.get(case)
            if thread:
                thread.join(timeout)
                if thread.is_alive():
                    raise TimeoutError('Capacity worker not stopped; ownership retained')
            if verify_cleanup() is not True or record_terminal() is not True:
                raise CapacityChannelError('Cleanup/terminal evidence incomplete; ownership retained')
            with self.lock:
                if case in self.active:
                    row = self.controller.status()['episodes'][case]
                    if row['request_id'] is not None:
                        self.controller.release_turn(case, row['request_id'])
                    self.controller.finish_episode(case)
                self.finished.add(case)
        finally:
            with self.lock:self.finishing.discard(case)

    def close(self):
        # Shutdown wakes local RPC, but deliberately does not finish episodes or
        # release outstanding permits. The caller still owns verified cleanup.
        with self.lock:
            self.closed = True
        for case in self.connections:
            self.cancel(case)
            self.connections[case].close()
        for thread in self.threads.values():
            thread.join(5)
            if thread.is_alive():
                raise TimeoutError('Capacity RPC worker did not stop')


class CapacityClient:
    """One client shared by this case's policy and formatter wrappers."""
    def __init__(self, connection, *, deadline, clock=time.monotonic, on_event=None):
        if not math.isfinite(deadline) or deadline <= clock():
            raise ValueError('Future caller/rental deadline required')
        if on_event is not None and not callable(on_event):
            raise ValueError('Capacity event sink must be callable')
        self.connection, self.deadline, self.clock = connection, deadline, clock
        self.lock = threading.Lock()
        self.sequence = 0
        self.broken = False
        self.events, self.infrastructure_error = deque(maxlen=2048), None
        self.on_event = on_event

    def _event(self, **row):
        row.setdefault('observed_monotonic', self.clock())
        self.events.append(row)
        if self.on_event is not None:self.on_event(dict(row))

    def _exchange(self, frame):
        if self.broken:
            raise CapacityChannelError('Capacity channel is broken; no retry')
        remaining = self.deadline - self.clock()
        releasing = frame['type'] == 'release'
        if remaining <= 0 and not releasing:
            self.broken = True
            self.connection.close()
            raise TimeoutError('Caller/rental deadline expired')
        end = self.clock() + (5 if releasing else remaining)
        try:
            self.connection.settimeout(max(.001, end-self.clock()))
            _send(self.connection, frame)
            while True:
                reply = _receive(self.connection, deadline=end, clock=self.clock)
                if reply is None:
                    raise CapacityChannelError('Parent closed capacity channel')
                if reply.get('type') == 'waiting' and not releasing:
                    if set(reply) != {'type','telemetry_fresh'} or type(reply['telemetry_fresh']) is not bool:
                        raise CapacityChannelError('Malformed waiting status')
                    self._event(kind='capacity_wait_status', phase=frame['phase'],
                        sequence=frame['sequence'], **reply)
                    continue
                if reply.get('type') == 'error':
                    raise CapacityChannelError(f"Parent {reply.get('error_type')}: {reply.get('message')}; telemetry_fresh={reply.get('telemetry_fresh')}")
                return reply
        except BaseException:
            self.broken = True
            self.connection.close()
            raise

    @contextmanager
    def turn(self, phase):
        if phase not in ('policy', 'formatter'):
            raise ValueError('Expected policy or formatter phase')
        # Lock covers the entire nonstreaming call. Otherwise a second acquire
        # could block the release RPC of this case's preceding request.
        with self.lock:
            self.sequence += 1
            started = self.clock()
            try:
                reply = self._exchange({'type': 'acquire', 'phase': phase, 'sequence': self.sequence})
            except BaseException:
                try:self._event(kind='capacity_wait_failed', phase=phase,
                    sequence=self.sequence, wait_seconds=self.clock()-started)
                except Exception:pass  # Never mask the acquisition/control error.
                raise
            if (set(reply) != {'type', 'request_id', 'acquire_wait_seconds'}
                    or reply['type'] != 'permit' or type(reply['request_id']) is not str
                    or type(reply['acquire_wait_seconds']) not in (int,float)
                    or not math.isfinite(reply['acquire_wait_seconds'])
                    or reply['acquire_wait_seconds'] < 0):
                self.broken = True
                self.connection.close()
                raise CapacityChannelError('Malformed permit')
            request_id = reply['request_id']
            original = None
            try:
                self._event(kind='capacity_permit', phase=phase, request_id=request_id,
                    wait_seconds=self.clock()-started,
                    acquire_wait_seconds=reply['acquire_wait_seconds'])
                yield request_id
            except BaseException as exc:
                original = exc
                raise
            finally:
                try:
                    reply = self._exchange({'type': 'release', 'request_id': request_id})
                    if reply != {'type': 'released', 'request_id': request_id}:
                        raise CapacityChannelError('Malformed release acknowledgement')
                except BaseException as exc:
                    self.broken = True
                    self.connection.close()
                    self.infrastructure_error = {'kind':'capacity_release_failed',
                        'type':type(exc).__name__,'message':str(exc),'request_id':request_id}
                    try:self._event(**self.infrastructure_error)
                    except Exception as sink_error:self.infrastructure_error['event_sink_error']=str(sink_error)
                    # Control flow and watchdogs must stop the caller, never
                    # return a response whose action could execute afterwards.
                    # Only ordinary channel/I/O faults preserve a return value.
                    if isinstance(exc, TimeoutError) or not isinstance(exc, (OSError,CapacityChannelError)):
                        raise
                    if original is not None:original.add_note('Capacity release also failed: '+str(exc))
                    # Preserve a paid response or the original provider error.
                    # Further calls fail closed. Outer terminal must persist
                    # this infrastructure error and verify exact HTTP cleanup.

    def close(self):
        self.broken = True
        self.connection.close()


class ActiveCapacityAdmission:
    """Wrap the existing parent queue admission, preserving FIFO/prewarm.

    ``episode_id`` is the unique run/case ID bound to this child's capacity
    socket. The scheduler still owns lifecycle cleanup and cap accounting.
    This wraps the parent admission, not the child's native runner callback.
    """
    def __init__(self, admission, parent, episode_id, *, priority=0):
        self.admission, self.parent, self.episode_id = admission, parent, episode_id
        self.priority = priority

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self,'admission'), name)

    def environment_ready(self, ready=None):
        self.admission.environment_ready(ready)
        self.parent.activate(self.episode_id, priority=self.priority)

    def check_active(self):
        return self.admission.check_active()

    def runner_callback(self, cancellation_type):
        inner = self.admission.runner_callback(cancellation_type)
        def callback(ready):
            inner(ready)
            self.parent.activate(self.episode_id, priority=self.priority)
        return callback


class CapacityBackend:
    """Explicit native, synchronous buffered-completion proxy.

    The caller qualifies the wrapped backend's nonstreaming HTTP cleanup
    semantics. Background pipeline execution is intentionally unsupported in
    this first composition. Idempotent source/active/deadline and observation
    freshness guards run again AFTER parking, without charging budgets twice.
    """
    supports_native_tools = False
    supports_background_completion = False

    def __init__(self, backend, client, *, phase, guard, freshness_guard,
                 buffered_completion):
        if (buffered_completion is not True or phase not in ('policy', 'formatter')
                or not callable(guard) or not callable(freshness_guard)):
            raise ValueError('Qualified buffered backend and explicit guards required')
        self.backend, self.capacity, self.phase = backend, client, phase
        self.guard, self.freshness_guard = guard, freshness_guard
        self.supports_native_tools = callable(getattr(backend,'configure_tools',None))
        self.interrupted_completion = None

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self,'backend'), name)

    def complete(self, messages):
        self.guard()
        completion = None
        try:
            with self.capacity.turn(self.phase):
                self.guard()
                self.freshness_guard()
                completion = self.backend.complete(messages)
                return completion
        except BaseException as exc:
            if completion is not None:
                self.interrupted_completion = completion
                exc.add_note('Paid response retained in CapacityBackend.interrupted_completion; no action authorized by this interrupted return.')
            raise

    def close(self):
        self.backend.close()
