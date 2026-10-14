"""Ordered, bounded admission of independent episode lifecycles.

The caller owns each environment/process and its native grading/finalization.
Call admission.environment_ready() after setup, and admission.check_active()
before every provider dispatch. Neither method creates or resets environments.
"""
from dataclasses import dataclass
from math import isfinite
from threading import Condition, Event, RLock, Thread, get_ident


class QueueCancelled(RuntimeError):
    """The suite stopped before another episode action could be admitted."""


class AdmissionBlocked(QueueCancelled):
    """Only this warmed case is blocked by retained terminal reservations."""


class AdmissionError(RuntimeError):
    """The caller violated the declared lifecycle/admission protocol."""


@dataclass(frozen=True)
class QueueSettings:
    max_concurrent_episodes: int
    prewarm_count: int = 1
    start_order: tuple[str, ...] | None = None

    def validate(self, case_ids):
        ids = tuple(case_ids)
        if (not ids or any(type(i) is not str or not i for i in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError('Suite requires unique nonempty case IDs')
        if type(self.max_concurrent_episodes) is not int or self.max_concurrent_episodes < 1:
            raise ValueError('max_concurrent_episodes must be a positive integer')
        if type(self.prewarm_count) is not int or self.prewarm_count < 0:
            raise ValueError('prewarm_count must be a nonnegative integer')
        if self.start_order is not None and type(self.start_order) not in (tuple, list):
            raise ValueError('start_order must be a list or tuple of case IDs')
        order = ids if self.start_order is None else tuple(self.start_order)
        if len(order) != len(ids) or any(type(i) is not str for i in order) or set(order) != set(ids):
            raise ValueError('start_order must contain every selected case exactly once')
        return order


class EpisodeAdmission:
    """A case-owned gate; the ready hook parks the existing environment once."""
    def __init__(self, queue, ident):
        self._queue, self.case_id = queue, ident
        self._native_cancellation = None

    def environment_ready(self, ready=None):
        q = self._queue
        with q.condition:
            row = q.rows[self.case_id]
            if row['ready']:
                raise AdmissionError('Environment-ready hook called more than once')
            if q.stopped():
                raise QueueCancelled('Suite cancelled before environment admission')
            if ready is not None:
                if (type(ready.episode_id) is not str or not ready.episode_id
                        or type(ready.ready_monotonic) not in (int, float)
                        or not isfinite(ready.ready_monotonic) or ready.ready_monotonic < 0):
                    raise AdmissionError('Malformed immutable native readiness context')
                row['ready_context'] = dict(episode_id=ready.episode_id,
                    directory=str(ready.directory), ready_monotonic=ready.ready_monotonic)
            row['ready'] = True
            q.emit('environment_ready', self.case_id)
            q.condition.notify_all()
            while not row['active'] and not q.stopped():
                if q.blocked_by_quarantine():
                    row['blocked_admission']=True
                    q.emit('blocked_admission',self.case_id)
                    raise AdmissionBlocked('All active slots are terminal quarantines; no dispatch')
                q.condition.wait(.1)
            self._check_locked()
            q.emit('environment_activated', self.case_id)

    def _check_locked(self):
        q = self._queue
        row = q.rows[self.case_id]
        if q.stopped():
            raise QueueCancelled('Suite cancelled before dispatch')
        if not row['active'] or not row['ready'] or row['done']:
            raise AdmissionError('Provider dispatch requires a ready, active episode')

    def check_active(self):
        with self._queue.condition:
            self._check_locked()

    def quarantine(self, evidence):
        """Trusted parent reserves an uncertain case resource, without job stop."""
        if type(evidence) is not dict or not evidence:
            raise AdmissionError('Explicit case quarantine evidence required')
        q = self._queue
        with q.condition:
            row = q.rows[self.case_id]
            if not row['started'] or row.get('quarantine') is not None:
                raise AdmissionError('Invalid or duplicate case quarantine')
            row['quarantine'] = dict(evidence)
            q.emit('case_quarantined', self.case_id)
            q.condition.notify_all()

    def recover_quarantine(self, verify_cleanup):
        """No replay; clear only this reservation after caller-owned proof."""
        if not callable(verify_cleanup):
            raise AdmissionError('Trusted cleanup verification callback required')
        if verify_cleanup() is not True:
            return False
        q = self._queue
        with q.condition:
            row = q.rows[self.case_id]
            if row.get('quarantine') is None:
                raise AdmissionError('Case has no quarantine to recover')
            row['quarantine'] = None
            q.emit('case_quarantine_recovered', self.case_id)
            if row['done'] and q.running and not q.finished:
                q.pump()
            q.condition.notify_all()
        return True

    def runner_callback(self, cancellation_type):
        """Bind the native cancellation class from the caller's frozen namespace."""
        if (not isinstance(cancellation_type, type)
                or not issubclass(cancellation_type, Exception)):
            raise TypeError('Native cancellation must be an Exception class')
        self._native_cancellation = cancellation_type
        def callback(ready):
            try:
                self.environment_ready(ready)
            except QueueCancelled as error:
                raise cancellation_type(str(error)) from error
        return callback


class EpisodeQueueHandle:
    """Trusted parent control for an explicitly mutable admission target.

    Hold condition continuously across validate_target(), the controller CAS,
    and set_target(). set_target() applies that already validated transaction;
    it deliberately does not recheck an external stop Event after the CAS.
    A concurrent stop still prevents the pump from starting another actor.
    Neither method cancels or deactivates existing active or warmed episodes.
    """
    def __init__(self, queue):
        self._queue = queue
        self._validated_target = None

    @property
    def condition(self):
        return self._queue.condition

    def _require_lock(self):
        if not self.condition._is_owned():
            raise AdmissionError('Hold queue.condition throughout target validation and update')

    def validate_target(self, max_active_episodes):
        self._require_lock()
        self._validated_target = None
        q = self._queue
        if type(max_active_episodes) is not int or not 1 <= max_active_episodes <= q.ceiling:
            raise ValueError('Admission target must be a positive integer within the fixed ceiling')
        if q.stopped() or q.finished:
            raise QueueCancelled('Cannot update a stopped or finished queue')
        self._validated_target = (get_ident(), max_active_episodes)

    def set_target(self, max_active_episodes):
        """Apply a validated target while the parent's transaction lock is held.

        The caller must have called validate_target for this same value without
        releasing condition. Lifecycle completion cannot race that lock; an
        external stop may race the controller CAS, but never starts new actors.
        """
        self._require_lock()
        q = self._queue
        if self._validated_target != (get_ident(), max_active_episodes):
            raise AdmissionError('Validate this target in the same locked parent transaction first')
        # Structural preconditions do not change between validation and CAS.
        if type(max_active_episodes) is not int or not 1 <= max_active_episodes <= q.ceiling:
            raise ValueError('Admission target must be a positive integer within the fixed ceiling')
        if q.finished:
            raise QueueCancelled('Cannot update a finished queue')
        self._validated_target = None
        previous = q.target
        q.target = max_active_episodes
        if previous != q.target:
            q.emit('admission_target_changed', None)
        if q.running:
            q.pump()
        q.condition.notify_all()

    def snapshot(self):
        with self.condition:
            q = self._queue
            active, warm = q.counts()
            return dict(target=q.target, ceiling=q.ceiling, active=active,
                        warming_or_ready=warm, prewarm_count=q.settings.prewarm_count,
                        construction_ceiling=q.ceiling + q.settings.prewarm_count,
                        stopped=q.stopped(), finished=q.finished)


class _Queue:
    def __init__(self, cases, run_case, settings, stop_event, on_queue_ready=None,
                 max_concurrent_ceiling=None, isolate_case_errors=False):
        self.order = settings.validate(cases)
        if not callable(run_case):
            raise TypeError('run_case must be callable')
        if on_queue_ready is not None and not callable(on_queue_ready):
            raise TypeError('on_queue_ready must be callable')
        if max_concurrent_ceiling is not None:
            if on_queue_ready is None:
                raise ValueError('A mutable ceiling requires the opt-in queue-ready callback')
            if (type(max_concurrent_ceiling) is not int
                    or max_concurrent_ceiling < settings.max_concurrent_episodes):
                raise ValueError('Fixed ceiling must be an integer at least the initial target')
        if type(isolate_case_errors) is not bool:
            raise ValueError("Explicit boolean case error isolation required")
        self.isolate_case_errors = isolate_case_errors
        self.cases, self.run_case, self.settings = cases, run_case, settings
        self.condition = Condition(RLock())
        self.on_queue_ready = on_queue_ready
        self.target = settings.max_concurrent_episodes
        self.ceiling = self.target if max_concurrent_ceiling is None else max_concurrent_ceiling
        self.running, self.finished = False, False
        self.stop_event = stop_event if stop_event is not None else Event()
        self.rows = {i: dict(started=False, active=False, ready=False, done=False,
                            status='queued', result=None, error=None) for i in self.order}
        self.threads, self.events = [], []

    def stopped(self):
        return self.stop_event.is_set()

    def counts(self):
        live = [r for r in self.rows.values() if r['started'] and (not r['done'] or r.get('quarantine') is not None)]
        return sum(r['active'] for r in live), sum(not r['active'] for r in live)

    def blocked_by_quarantine(self):
        return (self.isolate_case_errors and self.counts()[0]>=self.target
                and not any(r["started"] and r["active"] and not r["done"] for r in self.rows.values())
                and any(r["active"] and r["done"] and r.get("quarantine") is not None for r in self.rows.values()))

    def emit(self, event, ident):
        active, warm = self.counts()
        self.events.append(dict(sequence=len(self.events), event=event, case=ident,
                                active=active, warming_or_ready=warm,
                                executing_active=sum(r['started'] and r['active'] and not r['done'] for r in self.rows.values()),
                                quarantined=sum(r.get('quarantine') is not None for r in self.rows.values())))
        if self.on_queue_ready is not None:
            self.events[-1].update(target=self.target, ceiling=self.ceiling)

    def start(self, ident, active):
        row = self.rows[ident]
        row.update(started=True, active=active, status='admitted' if active else 'warming')
        self.emit('admitted' if active else 'warmup_started', ident)
        try:
            thread = Thread(target=self.worker, args=(ident,), name='episode-'+ident)
            thread.start()
        except BaseException as exc:
            # Thread admission itself can fail (e.g. a PID/resource ceiling).
            # There is then no worker/finally block to release this row. Stop
            # further creation, wake parked workers, and retain the failure.
            row.update(done=True, status='failed',
                       error=dict(type=type(exc).__name__, message=str(exc)))
            if self.isolate_case_errors:
                row['quarantine']=None # No worker or case resource was created.
                row['error']['stage']='worker_creation'
            else:self.stop_event.set()
            self.emit('worker_start_failed', ident)
            self.condition.notify_all()
            return
        self.threads.append(thread)

    def pump(self):
        """Called only under the condition lock; record FIFO intent atomically."""
        if self.stopped() or self.blocked_by_quarantine():
            return
        for ident in self.order:
            if self.stopped():
                break
            if self.counts()[0] >= self.target:
                break
            row = self.rows[ident]
            if row['done'] or row['active'] or row.get('quarantine') is not None:
                continue
            if row['started']:
                row.update(active=True, status='admitted')
                self.emit('admitted', ident)
                self.condition.notify_all()
            else:
                self.start(ident, True)
        # Lowering drains preexisting actors. Do not construct another cold
        # environment until actual active admission is back within the target.
        if self.counts()[0] > self.target:
            return
        for ident in self.order:
            if self.stopped():
                break
            if self.counts()[1] >= self.settings.prewarm_count:
                break
            row = self.rows[ident]
            if not row['started'] and not row['done']:
                self.start(ident, False)

    def worker(self, ident):
        admission = EpisodeAdmission(self, ident)
        result, error, status = None, None, 'completed'
        try:
            result = self.run_case(self.cases[ident], admission)
            with self.condition:
                if not self.rows[ident]['ready']:
                    raise AdmissionError('Caller returned without environment-ready boundary')
                if not self.rows[ident]['active']:
                    if self.stopped():
                        status = 'cancelled'
                    else:
                        raise AdmissionError('Caller returned without episode admission')
        except AdmissionBlocked as exc:
            error,status=dict(type=type(exc).__name__,message=str(exc),stage='blocked_admission'),'blocked'
        except QueueCancelled as exc:
            error, status = str(exc), 'cancelled'
        except Exception as exc:
            error = dict(type=type(exc).__name__, message=str(exc))
            status = ('blocked' if self.rows[ident].get('blocked_admission') and not self.stopped() else
                      'cancelled' if self.stopped() and admission._native_cancellation is not None
                      and isinstance(exc, admission._native_cancellation) else 'failed')
        except BaseException as exc:
            # Do not silently strand a lease when a worker receives SystemExit.
            error, status = dict(type=type(exc).__name__, message=str(exc)), 'failed'
            if not self.isolate_case_errors:self.stop_event.set()
        finally:
            with self.condition:
                if self.isolate_case_errors and status in ('failed','blocked') and 'quarantine' not in self.rows[ident]:
                    # Unexpected callback/finalizer failure has no cleanup proof.
                    self.rows[ident]['quarantine']={'unverified_callback_failure':error}
                    self.emit('case_quarantined', ident)
                self.rows[ident].update(done=True, status=status, result=result, error=error)
                self.emit('lifecycle_finished', ident)
                self.pump()
                self.condition.notify_all()

    def run(self):
        try:
            if self.on_queue_ready is not None:
                # Expose the handle before initial admission. A callback may
                # adjust its initial target, but no actor starts before return.
                self.on_queue_ready(EpisodeQueueHandle(self))
            with self.condition:
                self.running = True
                self.pump()
                while any(r['started'] and not r['done'] for r in self.rows.values()):
                    self.condition.wait(.1)
                    if self.stopped():
                        self.condition.notify_all()
        except BaseException:
            self.stop_event.set()
            with self.condition:
                self.condition.notify_all()
            raise
        finally:
            # Caller startup/request watchdogs remain required. A thread does
            # not allow us to kill or finalize an independently owned process.
            for thread in self.threads:
                thread.join()
            with self.condition:
                self.running, self.finished = False, True
                for ident, row in self.rows.items():
                    if not row['started']:
                        blocked=any(r.get('quarantine') is not None for r in self.rows.values()) and not self.stopped()
                        row.update(done=True, status='blocked' if blocked else 'not_started')
                        self.emit('blocked_quarantine' if blocked else 'not_started', ident)
                self.condition.notify_all()
        with self.condition:
            result = dict(cases={i: dict(r) for i, r in self.rows.items()}, events=list(self.events),
                          start_order=list(self.order),
                          max_concurrent_episodes=self.settings.max_concurrent_episodes,
                          prewarm_count=self.settings.prewarm_count,
                          cancelled=self.stopped())
            if self.on_queue_ready is not None:
                result.update(admission_target=self.target, max_concurrent_ceiling=self.ceiling)
            return result


def run_ordered_suite(cases, run_case, *, max_concurrent_episodes, prewarm_count=1,
                      start_order=None, stop_event=None, on_queue_ready=None,
                      max_concurrent_ceiling=None, isolate_case_errors=False):
    """Execute each selected case once; cold entries do not call run_case.

    cases maps IDs to opaque frozen caller inputs. run_case(value, admission)
    owns setup, native execution, grading, publication and cleanup, returning
    only after that lifecycle has ended. Admission order is deterministic;
    actual ready times, first requests and completion times may differ.
    on_queue_ready(handle) opts into mutable target control before any actor
    starts; max_concurrent_ceiling is immutable and defaults to the initial
    target. The fixed total construction ceiling is that ceiling + prewarm_count.
    Updates must hold handle.condition across validate_target, controller CAS,
    and set_target. A reduction drains; it never cancels existing actors.
    """
    settings = QueueSettings(max_concurrent_episodes, prewarm_count, start_order)
    return _Queue(dict(cases), run_case, settings, stop_event,
                  on_queue_ready, max_concurrent_ceiling, isolate_case_errors).run()
