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


class CapacityTransportTimeout(CapacityChannelError):
    """Our IPC timeout, distinct from a Python signal-handler TimeoutError."""


class CapacityDispatchRetired(CapacityChannelError):
    """Admission ended intentionally, without cancelling the episode."""


class CapacitySuiteStopped(CapacityChannelError):
    """The parent cohort stopped; no further active admission is allowed."""


class CapacityParentError(CapacityChannelError):
    """Typed parent diagnostic, without requiring message-string parsing."""
    def __init__(self, reply):
        self.reply = dict(reply)
        self.parent_error_type = reply['error_type']
        self.parent_reason = reply['reason']
        self.telemetry_fresh = reply['telemetry_fresh']
        super().__init__(f"Parent {self.parent_error_type}: {reply['message']}; telemetry_fresh={self.telemetry_fresh}")

    def __reduce__(self):
        return type(self), (self.reply,), dict(self.__dict__)


def _socket_call(function, *args):
    try:
        return function(*args)
    except TimeoutError as exc:
        # These calls are builtin socket operations. A socket timeout originates
        # in this frame; a Python signal handler adds its own traceback frame.
        # Never convert that foreign control-flow exception into a recoverable
        # channel fault, even when its text is also "timed out".
        if exc.__traceback__.tb_next is None:
            raise CapacityTransportTimeout(str(exc)) from exc
        raise


def _send(connection, value):
    data = json.dumps(value, allow_nan=False).encode()
    if len(data) > 4096:
        raise CapacityChannelError('Capacity frame too large')
    _socket_call(connection.sendall, struct.pack('!I', len(data)) + data)


def _receive(connection, *, deadline=None, clock=time.monotonic):
    def exact(n, eof=False):
        data = bytearray()
        while len(data) < n:
            if deadline is not None:
                remaining = deadline - clock()
                if remaining <= 0:
                    raise CapacityTransportTimeout('Capacity receive deadline expired')
                connection.settimeout(remaining)
            part = _socket_call(connection.recv, n - len(data))
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
    def __init__(self, controller, connections, *, deadline, clock=time.monotonic,
                 suite_stop_event=None):
        if not connections or any(type(k) is not str or not k for k in connections):
            raise ValueError('Expected finite unique run/case IDs')
        if not math.isfinite(deadline) or deadline <= clock():
            raise ValueError('Expected future caller/rental deadline')
        if not callable(getattr(controller, 'retire_dispatch', None)):
            raise ValueError('Reviewed retire_dispatch controller API required')
        # Use the exception from the controller's own frozen namespace; importing
        # another module copy would miss its retirement wake. No target import.
        acquire = getattr(controller, 'acquire_turn', None)
        acquire = getattr(acquire, '__func__', acquire)
        namespace = getattr(acquire, '__globals__', {})
        if namespace.get('EpisodeCapacityController') is not type(controller):
            raise ValueError('Direct reviewed controller namespace required; wrappers are unqualified')
        self.turn_cancelled_type = namespace.get('TurnCancelled')
        if (not isinstance(self.turn_cancelled_type, type)
                or not issubclass(self.turn_cancelled_type, Exception)
                or self.turn_cancelled_type.__module__ != type(controller).__module__):
            raise ValueError('Reviewed controller TurnCancelled namespace required')
        if suite_stop_event is not None and not isinstance(suite_stop_event, threading.Event):
            raise ValueError('Shared suite stop event must be threading.Event')
        self.suite_stop_event = suite_stop_event if suite_stop_event is not None else threading.Event()
        self.cleanup_failures = {}
        self.quarantined = {}
        self.stop_cause = None
        self.secondary_exits = deque(maxlen=2048)
        self.shutdown_requested = {}
        self.draining = set()
        self.controller, self.deadline, self.clock = controller, deadline, clock
        self.connections = dict(connections)
        self.active, self.finished, self.threads = set(), set(), {}
        self.errors = {}
        self.ending, self.ended, self.finishing = set(), set(), set()
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
            if self.suite_stop_event.is_set():
                raise CapacitySuiteStopped('Suite stopped before capacity activation')
            if (self.closed
                    or case not in self.connections or case in self.active
                    or case in self.finished or case in self.finishing
                    or case in self.ending or case in self.ended
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
                    with self.lock:
                        if self.suite_stop_event.is_set():
                            raise CapacitySuiteStopped('Suite stopped before generation acquisition')
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
                            if self.suite_stop_event.is_set():
                                stop.set();return
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
                            row = self.controller.status()['episodes'][case]
                            if self.suite_stop_event.is_set():
                                raise CapacitySuiteStopped('Suite stopped during generation acquisition') from exc
                            if (isinstance(exc, self.turn_cancelled_type)
                                    and row['dispatch_retired'] and not row['cancelled']):
                                raise CapacityDispatchRetired('Episode dispatch retired') from exc
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
                    with self.lock:
                        row = self.controller.status()['episodes'][case]
                        if self.suite_stop_event.is_set() or stop.is_set() or row['dispatch_retired'] or row['cancelled']:
                            # Permit has not been sent, so no HTTP work exists.
                            self.controller.release_turn(case, request_id)
                            if self.suite_stop_event.is_set():
                                raise CapacitySuiteStopped('Suite stopped before generation permit')
                            if row['dispatch_retired'] and not row['cancelled']:
                                raise CapacityDispatchRetired('Episode dispatch retired before permit')
                            raise CapacityChannelError('Child disconnected/cancelled before permit')
                        # Serialize the last check and send with cohort abort.
                        # Failed sends still retain possibly-sent HTTP ownership.
                        _send(connection, {'type': 'permit', 'request_id': request_id,
                            'acquire_wait_seconds':acquire_wait_seconds})
                elif value.get('type') == 'release':
                    if set(value) != {'type', 'request_id'} or type(value['request_id']) is not str:
                        raise CapacityChannelError('Invalid release frame')
                    # Serialize exact release + acknowledgement with abort's
                    # decision to close an idle channel. Otherwise cancellation
                    # can observe request_id=None and destroy its pending ack.
                    with self.lock:
                        self.controller.release_turn(case, value['request_id'])
                        connection.settimeout(5)
                        _send(connection, {'type': 'released', 'request_id': value['request_id']})
                else:
                    raise CapacityChannelError('Unknown capacity operation')
        except Exception as exc:
            failed = True
            row = self.controller.status()['episodes'].get(case, {})
            reason = ('cohort_abort' if isinstance(exc, CapacitySuiteStopped) else
                'explicit_cancellation' if row.get('cancelled') else
                'dispatch_retirement' if isinstance(exc, CapacityDispatchRetired) else
                'rental_deadline' if isinstance(exc, (TimeoutError, CapacityTransportTimeout))
                    and self.clock() >= self.deadline else 'channel_failure')
            with self.lock:
                requested = self.shutdown_requested.get(case)
                cause = self.stop_cause
                if requested in ('explicit_cancellation','cohort_abort','infrastructure_abort','parent_close'):
                    reason = requested
                elif case in self.cleanup_failures or (cause and case == cause['case'] and cause['infrastructure']):
                    reason = 'infrastructure_abort'
                self.errors[case] = {'type': type(exc).__name__, 'message': str(exc), 'reason': reason}
            try:
                _send(connection, {'type': 'error', 'error_type':type(exc).__name__,
                    'message': str(exc)[:500], 'reason':reason,
                    'telemetry_fresh':self.controller.status()['telemetry_fresh']})
            except (OSError, CapacityChannelError):
                pass
        finally:
            with self.lock:
                self.ending.add(case)
                registered = case in self.active and case not in self.finished
                finishing = case in self.finishing
                requested = self.shutdown_requested.get(case)
                cause = self.stop_cause
                cleanup_failure = self.cleanup_failures.get(case)
                protected_root = bool(case in self.quarantined or cleanup_failure or (cause and cause['infrastructure'] and case == cause['case']))
            if registered:
                self.controller.retire_dispatch(case)
            if registered and not finishing:
                row = self.controller.status()['episodes'][case]
                retirement_wake = self.errors.get(case, {}).get('reason') == 'dispatch_retirement'
                if not protected_root and ((failed and not retirement_wake) or row['request_id'] is not None):
                    if not failed and row['request_id'] is not None:
                        with self.lock:
                            self.errors[case] = dict(type='CapacityChannelError',
                                message=('Capacity cleanup channel ended with an in-flight request' if case in self.draining
                                    else 'Parent stopped channel with an in-flight request' if requested
                                    else 'Child disconnected with an in-flight request'),
                                reason=requested if requested in ('explicit_cancellation','cohort_abort','parent_close')
                                    else 'cohort_abort' if requested else 'inflight_disconnect')
                    self._cancel_registered(case)
                elif protected_root and not failed and row['request_id'] is not None:
                    with self.lock:
                        evidence = cleanup_failure or self.quarantined.get(case) or cause
                        self.errors[case] = dict(type=evidence['type'],message=evidence['message'],
                            reason='infrastructure_abort')
            connection.close()
            # Observing ended guarantees the row is retired, not merely that
            # this thread is about to retire it. Never publish the inverse.
            with self.lock:self.ended.add(case)

    def _cancel_registered(self, case):
        row = self.controller.status()['episodes'].get(case)
        if row is not None and not row['done'] and not row['cancelled']:
            self.controller.cancel_episode(case)

    def _retire_registered(self, case):
        with self.lock:
            registered = case in self.active and case not in self.finished
        if registered:
            self.controller.retire_dispatch(case)

    def _shutdown(self, case, *, reason='parent_shutdown'):
        with self.lock:
            self.shutdown_requested.setdefault(case, reason)
            self.draining.discard(case)
        self.stops[case].set()
        try:
            self.connections[case].shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def cancel(self, case, *, cohort_abort=False):
        """Wake local wait; this does not establish remote HTTP cleanup."""
        with self.lock:
            if case not in self.connections:
                raise ValueError('Unknown case')
            cause = self.stop_cause
            if cohort_abort and (case in self.finishing or case in self.finished
                    or case in self.cleanup_failures
                    or (cause and cause['infrastructure'] and cause['case'] == case)):
                return
            registered = case in self.active and case not in self.finished
            # Serialize the cancellation decision with final-verification entry;
            # neither can pass its parent lock check and act after the other.
            if registered:
                self._cancel_registered(case)
                self.controller.retire_dispatch(case)
                if cohort_abort and not self.closed and self.controller.status()['episodes'][case]['request_id'] is not None:
                    # Keep the sent request accounted for, and preserve its
                    # release/ack path while buffered HTTP cleanup completes.
                    # Retirement/cancellation reject further acquisition. The
                    # outer child/relay watchdog bounds this drain; close()
                    # still contains a stuck peer without releasing its permit.
                    self.shutdown_requested.setdefault(case, 'cohort_abort')
                    self.draining.add(case)
                    self.stops[case].set()
                    return
        self._shutdown(case, reason='cohort_abort' if cohort_abort else 'explicit_cancellation')

    def finish_after_cleanup(self, case, *, verify_cleanup, record_terminal, timeout=5, abort_cohort_on_failure=True):
        """Trusted outer boundary after child exit, HTTP abort/drain and grading.

        Both callbacks must return literal True. ``record_terminal`` verifies
        persisted grade/projection or explicit infrastructure failure evidence;
        it must not demand a passing task verdict. Failed cleanup retains the
        controller permit and active episode. This is a final verification
        boundary. The default retains legacy cohort abort. Opt-in isolated
        failure quarantines only this case, preserving sent requests until
        trusted cleanup is verified; unrelated actors and refill continue.
        """
        if type(abort_cohort_on_failure) is not bool:
            raise ValueError('Explicit final-verification failure scope required')
        if not callable(verify_cleanup) or not callable(record_terminal):
            raise ValueError('Explicit cleanup and terminal evidence callbacks required')
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('Finite worker cleanup timeout required')
        with self.lock:
            if case not in self.connections or case in self.finished or case in self.finishing:
                raise ValueError('Duplicate episode finish')
            self.finishing.add(case)
        stage = 'worker_cleanup'
        try:
            # Dispatch retirement excludes ended actors from parking decisions
            # but never frees the active cap, a sent permit or a resume credit.
            self._retire_registered(case)
            self._shutdown(case)
            thread = self.threads.get(case)
            if thread:
                thread.join(timeout)
                if thread.is_alive():
                    raise TimeoutError('Capacity worker not stopped; ownership retained')
            stage = 'verify_cleanup'
            if verify_cleanup() is not True:
                raise CapacityChannelError('Cleanup/terminal evidence incomplete; ownership retained')
            stage = 'record_terminal'
            if record_terminal() is not True:
                raise CapacityChannelError('Cleanup/terminal evidence incomplete; ownership retained')
            stage = 'release_and_finish'
            with self.lock:
                if case in self.active:
                    row = self.controller.status()['episodes'][case]
                    if row['request_id'] is not None:
                        self.controller.release_turn(case, row['request_id'])
                    self.controller.finish_episode(case)
                self.finished.add(case)
                self.quarantined.pop(case, None)
        except BaseException as exc:
            # A diagnostic read must never replace the real verification failure
            # or prevent recording its ledger/stop. Retain unknown request IDs.
            request_id = None
            try:
                request_id = self.controller.status()['episodes'].get(case, {}).get('request_id')
            except BaseException as diagnostic:
                exc.add_note('Request ID diagnostic unavailable: '+type(diagnostic).__name__)
            with self.lock:
                # Parent-observed final verification failures are authoritative
                # for every actor, regardless of the first cohort stop cause.
                self.cleanup_failures.setdefault(case, dict(type=type(exc).__name__,
                    message=str(exc),stage=stage,request_id=request_id))
            if abort_cohort_on_failure:
                self.suite_stop_event.set()
                try:
                    self.abort_after_failure(case, exc, infrastructure=True)
                except BaseException as secondary:
                    exc.add_note('Abort cleanup also failed: '+type(secondary).__name__)
            else:
                self.quarantine_after_failure(case, exc)
            raise
        finally:
            with self.lock:self.finishing.discard(case)

    def quarantine_after_failure(self, case, error):
        """Retire only this actor; keep all uncertain permit/lifecycle ownership."""
        if case not in self.connections or not isinstance(error, BaseException):
            raise ValueError('Known case and actual failure required')
        with self.lock:
            self.quarantined.setdefault(case, dict(case=case,type=type(error).__name__,
                message=str(error),observed_monotonic=self.clock()))
        self._retire_registered(case)
        self._shutdown(case, reason='case_quarantine')

    def abort_after_failure(self, case, error, *, infrastructure):
        """Terminal stop with explicit caller-owned infrastructure classification.

        The trusted outer caller must invoke this on an exit path that cannot
        reach final verification. Use infrastructure=False for ordinary user or
        native cancellation. The first cause is retained; later exits are
        secondary, and never cancel an infrastructure root or a finishing row.
        This does not prove HTTP abort/drain, free any
        permit/cap, or finish an episode. Later cleanup never clears the stop.
        """
        if (case not in self.connections or not isinstance(error, BaseException)
                or type(infrastructure) is not bool):
            raise ValueError('Known case, actual failure and explicit infrastructure boolean required')
        with self.lock:
            exit_record = dict(case=case,type=type(error).__name__,message=str(error),
                infrastructure=infrastructure)
            if self.stop_cause is None:
                self.stop_cause = dict(exit_record)
            else:
                self.secondary_exits.append(exit_record)
            cause = dict(self.stop_cause)
            self.suite_stop_event.set()
        root = cause['case']
        if cause['infrastructure']:
            self._retire_registered(root)
            self._shutdown(root, reason='infrastructure_abort')
        else:
            self.cancel(root, cohort_abort=True)
        for other in self.connections:
            if other != root:self.cancel(other, cohort_abort=True)

    def close(self):
        # Shutdown wakes local RPC, but deliberately does not finish episodes or
        # release outstanding permits. The caller still owns verified cleanup.
        with self.lock:
            self.closed = True
        errors=[]
        def attempt(operation):
            try:operation()
            except BaseException as error:errors.append(error)
        for case in self.connections:
            with self.lock:reason='cohort_abort' if self.stop_cause else 'parent_close'
            attempt(lambda c=case,r=reason:self._shutdown(c,reason=r))
            attempt(lambda c=case:self.cancel(c,cohort_abort=True))
            attempt(self.connections[case].close)
        for thread in self.threads.values():
            def join(t=thread):
                t.join(5)
                if t.is_alive():raise TimeoutError('Capacity RPC worker did not stop')
            attempt(join)
        if errors:raise RuntimeError('Capacity parent close failures: '+'; '.join(type(e).__name__+': '+str(e)for e in errors)) from errors[0]



class CapacityClient:
    """One client shared by this case's policy and formatter wrappers."""
    def __init__(self, connection, *, deadline, clock=time.monotonic, on_event=None,
                 cleanup_timeout=5.0):
        if not math.isfinite(deadline) or deadline <= clock():
            raise ValueError('Future caller/rental deadline required')
        if on_event is not None and not callable(on_event):
            raise ValueError('Capacity event sink must be callable')
        if (type(cleanup_timeout) not in (int, float) or not math.isfinite(cleanup_timeout)
                or not 0 < cleanup_timeout <= 5):
            raise ValueError('IPC cleanup timeout must be a number in (0, 5] seconds')
        self.connection, self.deadline, self.clock = connection, deadline, clock
        self.lock = threading.Lock()
        self.sequence = 0
        self.broken = False
        self.events, self.infrastructure_error = deque(maxlen=2048), None
        self.on_event = on_event
        self.cleanup_timeout = cleanup_timeout

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
        end = self.clock() + (self.cleanup_timeout if releasing else remaining)
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
                    if (set(reply) != {'type','error_type','message','reason','telemetry_fresh'}
                            or type(reply['error_type']) is not str or type(reply['message']) is not str
                            or reply['reason'] not in ('explicit_cancellation','dispatch_retirement',
                                'rental_deadline','channel_failure','inflight_disconnect',
                                'cohort_abort','infrastructure_abort')
                            or type(reply['telemetry_fresh']) is not bool):
                        raise CapacityChannelError('Malformed parent error diagnostic')
                    error = CapacityParentError(reply)
                    try:
                        self._event(kind='capacity_parent_error', parent_error_type=reply['error_type'],
                            parent_reason=reply['reason'], telemetry_fresh=reply['telemetry_fresh'])
                    except BaseException as sink_error:
                        sink_error.capacity_parent_error = error
                        if sink_error.__cause__ is None:
                            raise sink_error from error
                        sink_error.add_note('Capacity parent diagnostic retained in capacity_parent_error; original sink cause preserved.')
                        raise
                    raise error
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
            try:
                self.parent.activate(self.episode_id, priority=self.priority)
            except CapacitySuiteStopped as exc:
                raise cancellation_type(str(exc)) from exc
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
