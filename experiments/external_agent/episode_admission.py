"""Kernel-held episode leases and durable admission for an explicit finite suite.

The ordinary exclusive subscription lock remains the default. An opted-in suite
holds that SAME lock shared plus one of a fixed set of exclusive episode leases.
The control lock serializes ledger updates and fresh quota checks, not inference.
Never delete/replace lock files or reset a suite ledger while episodes are live.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time

MAX_CONCURRENCY = 34
CONTROL_TIMEOUT = 20
# RPC: 5s connect + two 15s calls + websocket close allowance; leave
# headroom for local ledger I/O. Custom guard readers must also be bounded.
QUOTA_READ_ALLOWANCE = 50


@dataclass(frozen=True)
class EpisodeConcurrency:
    suite_id: str
    max_concurrent_episodes: int
    max_suite_episodes: int

    def __post_init__(self):
        if not isinstance(self.suite_id, str) or not self.suite_id.strip() or len(self.suite_id) > 200:
            raise ValueError('Declare a nonempty suite identity of at most 200 characters')
        if (type(self.max_concurrent_episodes) is not int or
                type(self.max_suite_episodes) is not int or
                not 1 <= self.max_concurrent_episodes <= self.max_suite_episodes <= MAX_CONCURRENCY):
            raise ValueError('Use explicit integer episode limits: 1 <= concurrency <= suite episodes <= 34')


def _write(path, record):
    """Atomic, fsynced ledger: a crashed attempt stays consumed, never retried."""
    fd, name = tempfile.mkstemp(prefix='.ledger-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(record, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class EpisodeLease:
    def __init__(self, lock_path, config=None, *, binding=None):
        self.lock_path = Path(lock_path).resolve()
        self.config = config
        self.binding = {'version': 1, **(binding or {})}
        if config is not None:
            self.binding.update(suite_id=config.suite_id,
                max_concurrent_episodes=config.max_concurrent_episodes,
                max_suite_episodes=config.max_suite_episodes)
        self.root = self.lock_path.with_name(self.lock_path.name + '.admission')
        self.barrier = self.slot = None
        self.episode_id = None

    @property
    def control_timeout(self):
        return CONTROL_TIMEOUT + (self.config.max_concurrent_episodes * QUOTA_READ_ALLOWANCE
                                  if self.config else 0)

    @contextmanager
    def _control(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / 'control.lock').open('a+') as gate:
            deadline = time.monotonic() + self.control_timeout
            while True:
                try:
                    fcntl.flock(gate, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Suite admission control is busy; no dispatch') from None
                    time.sleep(.01)
            try:
                yield
            finally:
                fcntl.flock(gate, fcntl.LOCK_UN)

    def _ledger(self):
        key = hashlib.sha256(self.config.suite_id.encode('utf8')).hexdigest()
        path = self.root / (key + '.json')
        if not path.exists():
            return path, {'binding': self.binding, 'episodes': {}, 'dispatches': 0}
        record = json.loads(path.read_text())
        if (record.get('binding') != self.binding or not isinstance(record.get('episodes'), dict) or
                type(record.get('dispatches')) is not int or record['dispatches'] < 0 or
                len(record['episodes']) > self.config.max_suite_episodes or
                any(not isinstance(key, str) or not isinstance(value, dict) or
                    type(value.get('dispatches')) is not int or value['dispatches'] < 0
                    for key, value in record['episodes'].items()) or
                sum(value['dispatches'] for value in record['episodes'].values()) != record['dispatches']):
            raise ValueError('Suite admission ledger is incompatible or malformed; no dispatch')
        return path, record

    def begin(self, episode_id):
        if not isinstance(episode_id, str) or not episode_id:
            raise ValueError('Missing episode identity')
        if self.barrier is not None or self.episode_id is not None:
            raise ValueError('Use a fresh episode lease')
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.barrier = self.lock_path.open('a')
        mode = fcntl.LOCK_EX if self.config is None else fcntl.LOCK_SH
        try:
            try:
                fcntl.flock(self.barrier, mode | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('Another external subscription episode is active') from None
            if self.config is None:
                self.episode_id = episode_id
                return {'concurrency': 1}
            free = []
            with self._control():
                try:
                    # Lock all free slots while checking active bindings. Slots
                    # left by dead processes are free regardless of stale text.
                    active = 0
                    for index in range(MAX_CONCURRENCY):
                        slot = (self.root / f'episode-{index:02d}.lock').open('a+')
                        try:
                            fcntl.flock(slot, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except BlockingIOError:
                            try:
                                slot.seek(0)
                                if json.load(slot)['binding'] != self.binding:
                                    raise ValueError('Another suite or incompatible episode cap is active')
                                active += 1
                            finally:
                                slot.close()
                        else:
                            free.append(slot)
                    if active >= self.config.max_concurrent_episodes:
                        raise ValueError('Concurrent episode allowance exhausted; no admission')
                    path, record = self._ledger()
                    if episode_id in record['episodes']:
                        raise ValueError('Episode identity already consumed; no automatic replay')
                    if len(record['episodes']) >= self.config.max_suite_episodes:
                        raise ValueError('Suite episode allowance exhausted; no admission')
                    self.slot = free.pop(0)
                    self.slot.seek(0)
                    self.slot.truncate()
                    json.dump({'binding': self.binding, 'episode_id': episode_id}, self.slot)
                    self.slot.flush()
                    # Persist consumption before returning admission. Crash
                    # releases the kernel lease but cannot restore the budget.
                    record['episodes'][episode_id] = {'dispatches': 0}
                    _write(path, record)
                    self.episode_id = episode_id
                    return {'concurrency': self.config.max_concurrent_episodes,
                            'suite_id': self.config.suite_id,
                            'max_suite_episodes': self.config.max_suite_episodes,
                            'suite_episodes_started': len(record['episodes']),
                            'admission_lock_wait_seconds': self.control_timeout,
                            'quota_read_allowance_seconds': QUOTA_READ_ALLOWANCE,
                            'admission_wait_seconds': self.control_timeout + QUOTA_READ_ALLOWANCE,
                            'admission_ledger': str(path), 'subscription_lock': str(self.lock_path)}
                finally:
                    # These probe locks must be gone BEFORE another admission
                    # acquires control; otherwise empty/stale free slots look
                    # like real active episodes to the next process.
                    for slot in free:
                        slot.close()
                    if self.episode_id is None and self.slot is not None:
                        self.slot.close()
                        self.slot = None
        except BaseException:
            self.close()
            raise

    def admit_dispatch(self, quota_guard, *, phase=None, session_id=None):
        if self.config is None or self.barrier is None or self.slot is None:
            raise ValueError('An active finite suite lease is required')
        with self._control():
            if quota_guard.remaining_floor != self.binding['quota_floor_percent']:
                raise ValueError('Subscription quota floor changed since admission; no dispatch')
            path, record = self._ledger()
            if self.episode_id not in record['episodes']:
                raise ValueError('Episode missing from suite ledger')
            phase_record = None
            if phase is not None:
                phase_record = record['episodes'][self.episode_id].get('phases', {}).get(phase)
                if (phase_record is None or phase_record.get('status') != 'active' or
                        phase_record.get('session_id') != session_id):
                    raise ValueError('Active phase identity mismatch; no dispatch')
                if phase == 'formatter' and phase_record['dispatches'] >= 1:
                    raise ValueError('Formatter allowance exhausted; no second dispatch')
            # Fresh reads/check receipts serialize across all suite processes.
            # Release the control lock before inference: in-flight usage cannot
            # be reserved exactly and is not represented as invented credits.
            # Full reads distinguish an explicitly absent window (null) from
            # missing/unknown data, before the guard writes an admitted receipt.
            quota_guard(require_complete_windows=True)
            record['dispatches'] += 1
            record['episodes'][self.episode_id]['dispatches'] += 1
            if phase_record is not None:
                phase_record['dispatches'] += 1
            _write(path, record)

    def phase_transition(self, phase, session_id, *, close=False):
        """One policy, then at most one isolated formatter for a case lease."""
        if phase not in ('policy', 'formatter') or self.slot is None:
            raise ValueError('Active suite lease and declared phase required')
        with self._control():
            path, record = self._ledger()
            phases = record['episodes'][self.episode_id].setdefault('phases', {})
            if close:
                if (phases.get(phase, {}).get('session_id') != session_id or
                        phases.get(phase, {}).get('status') != 'active'):
                    raise ValueError('Phase identity or lifecycle mismatch')
                phases[phase]['status'] = 'closed'
            else:
                if phase in phases or any(p['status'] == 'active' for p in phases.values()):
                    raise ValueError('Phase already consumed or another phase is active')
                if phase == 'formatter' and phases.get('policy', {}).get('status') != 'closed':
                    raise ValueError('Formatter requires the policy phase to be closed first')
                if any(p['session_id'] == session_id
                       for episode in record['episodes'].values()
                       for p in episode.get('phases', {}).values()):
                    raise ValueError('Suite phases require a fresh session/cache identity across all cases')
                phases[phase] = {'session_id': session_id, 'status': 'active', 'dispatches': 0}
            _write(path, record)

    def close(self):
        # Closing kernel leases also handles process death without PID guessing.
        if self.slot is not None:
            self.slot.close()
            self.slot = None
        if self.barrier is not None:
            self.barrier.close()
            self.barrier = None


class SuiteEpisode:
    """Case-owned lease: separate policy and optional one formatter backend.

    Caller keeps this object alive through post-policy grading and closes it in
    finally. Backend close ends only its phase. No policy/session reattachment.
    """
    def __init__(self, config, lock_path, quota_guard, *, model,
                 reasoning_effort='medium', formatter_reasoning_effort='low',
                 provider_output_limit=False):
        from .subscription_quota import SubscriptionQuotaGuard
        if not isinstance(config, EpisodeConcurrency):
            raise ValueError('Declare an explicit EpisodeConcurrency configuration')
        if not isinstance(quota_guard, SubscriptionQuotaGuard) or quota_guard.remaining_floor < 1:
            raise ValueError('Finite parallel suites require a subscription quota guard with floor >= 1%')
        self.config = config
        self.quota_guard = quota_guard
        self.binding = {'model': model, 'reasoning_effort': reasoning_effort,
                        'formatter_reasoning_effort': formatter_reasoning_effort,
                        'provider_output_limit': provider_output_limit,
                        'quota_floor_percent': quota_guard.remaining_floor,
                        'quota_contract': 'complete_nullable_windows_v1'}
        self.lease = EpisodeLease(lock_path, config, binding=self.binding)
        self.mutex = threading.Lock()
        self.phase = self.session_id = None
        self.metadata = None
        self.closed = False

    def begin_episode(self, case_id):
        with self.mutex:
            if self.closed or self.metadata is not None:
                raise ValueError('Use a fresh suite episode')
            self.metadata = self.lease.begin(case_id)
            return dict(self.metadata)

    def claim_phase(self, phase, session_id, *, model, reasoning_effort, provider_output_limit):
        with self.mutex:
            if self.closed or self.metadata is None or self.phase is not None:
                raise ValueError('Active suite episode without an in-flight phase required')
            expected = self.binding.get('formatter_reasoning_effort' if phase == 'formatter' else 'reasoning_effort')
            if (model != self.binding['model'] or reasoning_effort != expected or
                    provider_output_limit != self.binding['provider_output_limit']):
                raise ValueError('Backend differs from the suite phase transport binding')
            self.lease.phase_transition(phase, session_id)
            self.phase, self.session_id = phase, session_id
            return {**self.metadata, 'case_episode_id': self.lease.episode_id, 'episode_phase': phase}

    def finish_phase(self, phase, session_id):
        with self.mutex:
            if (self.phase, self.session_id) != (phase, session_id):
                raise ValueError('Phase identity or lifecycle mismatch')
            try:
                self.lease.phase_transition(phase, session_id, close=True)
            finally:
                # A failed durable transition must still permit terminal lease
                # cleanup. Its unclosed ledger blocks further phase adoption.
                self.phase = self.session_id = None

    def admit_dispatch(self, quota_guard):
        with self.mutex:
            if self.closed or self.phase is None or quota_guard is not self.quota_guard:
                raise ValueError('Suite phase or quota guard mismatch; no dispatch')
            self.lease.admit_dispatch(quota_guard, phase=self.phase, session_id=self.session_id)

    def close(self):
        with self.mutex:
            if self.phase is not None:
                raise ValueError('Close the active phase backend before releasing its case lease')
            self.lease.close()
            self.closed = True
