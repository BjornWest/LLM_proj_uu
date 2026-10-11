"""Ordered, bounded admission of independent episode lifecycles.

The caller owns each environment/process and its native grading/finalization.
Call admission.environment_ready() after setup, and admission.check_active()
before every provider dispatch. Neither method creates or resets environments.
"""
from dataclasses import dataclass
from math import isfinite
from threading import Condition, Event, Thread


class QueueCancelled(RuntimeError):
    """The suite stopped before another episode action could be admitted."""


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


class _Queue:
    def __init__(self, cases, run_case, settings, stop_event):
        self.order = settings.validate(cases)
        if not callable(run_case):
            raise TypeError('run_case must be callable')
        self.cases, self.run_case, self.settings = cases, run_case, settings
        self.condition = Condition()
        self.stop_event = stop_event if stop_event is not None else Event()
        self.rows = {i: dict(started=False, active=False, ready=False, done=False,
                            status='queued', result=None, error=None) for i in self.order}
        self.threads, self.events = [], []

    def stopped(self):
        return self.stop_event.is_set()

    def counts(self):
        live = [r for r in self.rows.values() if r['started'] and not r['done']]
        return sum(r['active'] for r in live), sum(not r['active'] for r in live)

    def emit(self, event, ident):
        active, warm = self.counts()
        self.events.append(dict(sequence=len(self.events), event=event, case=ident,
                                active=active, warming_or_ready=warm))

    def start(self, ident, active):
        row = self.rows[ident]
        row.update(started=True, active=active, status='admitted' if active else 'warming')
        self.emit('admitted' if active else 'warmup_started', ident)
        thread = Thread(target=self.worker, args=(ident,), name='episode-'+ident)
        try:
            thread.start()
        except BaseException as exc:
            # Thread admission itself can fail (e.g. a PID/resource ceiling).
            # There is then no worker/finally block to release this row. Stop
            # further creation, wake parked workers, and retain the failure.
            row.update(done=True, status='failed',
                       error=dict(type=type(exc).__name__, message=str(exc)))
            self.stop_event.set()
            self.emit('worker_start_failed', ident)
            self.condition.notify_all()
            return
        self.threads.append(thread)

    def pump(self):
        """Called only under the condition lock; record FIFO intent atomically."""
        if self.stopped():
            return
        for ident in self.order:
            if self.stopped():
                break
            if self.counts()[0] >= self.settings.max_concurrent_episodes:
                break
            row = self.rows[ident]
            if row['done'] or row['active']:
                continue
            if row['started']:
                row.update(active=True, status='admitted')
                self.emit('admitted', ident)
                self.condition.notify_all()
            else:
                self.start(ident, True)
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
        except QueueCancelled as exc:
            error, status = str(exc), 'cancelled'
        except Exception as exc:
            error = dict(type=type(exc).__name__, message=str(exc))
            status = ('cancelled' if self.stopped() and admission._native_cancellation is not None
                      and isinstance(exc, admission._native_cancellation) else 'failed')
        except BaseException as exc:
            # Do not silently strand a lease when a worker receives SystemExit.
            error, status = dict(type=type(exc).__name__, message=str(exc)), 'failed'
            self.stop_event.set()
        finally:
            with self.condition:
                self.rows[ident].update(done=True, status=status, result=result, error=error)
                self.emit('lifecycle_finished', ident)
                self.pump()
                self.condition.notify_all()

    def run(self):
        try:
            with self.condition:
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
            for ident, row in self.rows.items():
                if not row['started']:
                    row.update(done=True, status='not_started')
                    self.emit('not_started', ident)
            return dict(cases={i: dict(r) for i, r in self.rows.items()}, events=list(self.events),
                        start_order=list(self.order),
                        max_concurrent_episodes=self.settings.max_concurrent_episodes,
                        prewarm_count=self.settings.prewarm_count,
                        cancelled=self.stopped())


def run_ordered_suite(cases, run_case, *, max_concurrent_episodes, prewarm_count=1,
                      start_order=None, stop_event=None):
    """Execute each selected case once; cold entries do not call run_case.

    cases maps IDs to opaque frozen caller inputs. run_case(value, admission)
    owns setup, native execution, grading, publication and cleanup, returning
    only after that lifecycle has ended. Admission order is deterministic;
    actual ready times, first requests and completion times may differ.
    """
    settings = QueueSettings(max_concurrent_episodes, prewarm_count, start_order)
    return _Queue(dict(cases), run_case, settings, stop_event).run()
