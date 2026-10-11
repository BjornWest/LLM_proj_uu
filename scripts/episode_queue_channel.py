"""Small JSON control channel for case-owned, separately launched processes.

The caller owns subprocess startup, watchdogs, native result verification and
cleanup. Pass an inherited socket to the child; this module never launches a
process or executes a command received over the channel.
"""
import json
from math import isfinite
from pathlib import Path
import socket
import struct
from types import SimpleNamespace


class ChannelError(RuntimeError):
    pass


def _encode(value):
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
    if len(raw) > 16384:
        raise ChannelError('Admission frame exceeds 16384 bytes')
    return struct.pack('!I', len(raw)) + raw


def _send(connection, value):
    connection.sendall(_encode(value))


def _receive(connection):
    def exact(size, allow_eof=False):
        raw = bytearray()
        while len(raw) < size:
            part = connection.recv(size - len(raw))
            if not part:
                if allow_eof and not raw:
                    return None
                raise ChannelError('Incomplete admission frame')
            raw.extend(part)
        return bytes(raw)
    header = exact(4, True)
    if header is None:
        return None
    size, = struct.unpack('!I', header)
    if not 0 < size <= 16384:
        raise ChannelError('Invalid admission frame size')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ChannelError('Duplicate admission field')
            result[key] = value
        return result
    try:
        value = json.loads(exact(size), object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ChannelError('Nonfinite admission field')))
    except (ValueError, UnicodeError) as exc:
        raise ChannelError('Malformed admission JSON') from exc
    if type(value) is not dict:
        raise ChannelError('Admission frame must be an object')
    return value


class ChildAdmission:
    """Bind this callback and guard before importing/starting the case runner."""
    def __init__(self, connection, case_id, cancellation_type):
        if (type(case_id) is not str or not case_id or not isinstance(cancellation_type, type)
                or not issubclass(cancellation_type, Exception)):
            raise ValueError('Invalid child admission identity/cancellation class')
        self.connection, self.case_id, self.cancellation_type = connection, case_id, cancellation_type
        self.ready_sent = self.active = False

    def _reply(self, kind):
        value = _receive(self.connection)
        if value is None or value.get('case') != self.case_id:
            raise ChannelError('Parent admission channel closed or changed identity')
        if value.get('type') == 'cancel' and set(value) == {'case', 'type', 'reason'}:
            raise self.cancellation_type(str(value['reason']))
        if value != {'case': self.case_id, 'type': kind}:
            raise ChannelError('Unexpected parent admission reply')

    def environment_admission(self, ready):
        if self.ready_sent:
            raise ChannelError('Duplicate child ready boundary')
        self.ready_sent = True
        _send(self.connection, dict(case=self.case_id, type='ready',
            episode_id=ready.episode_id, directory=str(ready.directory),
            ready_monotonic=ready.ready_monotonic))
        self._reply('activate')
        self.active = True

    def before_dispatch(self):
        if not self.active:
            raise ChannelError('Provider dispatch before native environment activation')
        _send(self.connection, {'case': self.case_id, 'type': 'dispatch'})
        self._reply('allow')


def serve_admission(connection, admission, *, expected_run_root):
    """Serve one owned child through readiness and every guarded dispatch.

    Run this in the scheduler's case worker while the subprocess owns native
    execution. Child closes its socket after grading/cleanup; caller still
    verifies process completion and actual native/canonical/HTTP evidence.
    Use caller-owned socket/process watchdogs for stalled or partial frames.
    """
    root = Path(expected_run_root).resolve()
    ready = None
    dispatches = 0
    while True:
        value = _receive(connection)
        if value is None:
            if ready is None:
                raise ChannelError('Child closed before environment readiness')
            return {'ready': ready, 'guarded_dispatches': dispatches}
        if value.get('case') != admission.case_id:
            raise ChannelError('Foreign case admission frame')
        if value.get('type') == 'ready':
            if ready is not None or set(value) != {'case', 'type', 'episode_id', 'directory', 'ready_monotonic'}:
                raise ChannelError('Duplicate or malformed child readiness')
            if (type(value['episode_id']) is not str or not value['episode_id']
                    or type(value['directory']) is not str
                    or type(value['ready_monotonic']) not in (int, float)
                    or not isfinite(value['ready_monotonic']) or value['ready_monotonic'] < 0):
                raise ChannelError('Invalid child readiness fields')
            directory = Path(value['directory'])
            if not directory.is_absolute() or not directory.resolve().is_relative_to(root) or directory.resolve() == root:
                raise ChannelError('Child trace escaped its declared run root')
            ready = {k: value[k] for k in ('episode_id', 'directory', 'ready_monotonic')}
            try:
                admission.environment_ready(SimpleNamespace(**ready))
            except Exception as exc:
                _send(connection, {'case': admission.case_id, 'type': 'cancel', 'reason': str(exc)})
                raise
            _send(connection, {'case': admission.case_id, 'type': 'activate'})
        elif value == {'case': admission.case_id, 'type': 'dispatch'} and ready is not None:
            try:
                admission.check_active()
            except Exception as exc:
                _send(connection, {'case': admission.case_id, 'type': 'cancel', 'reason': str(exc)})
                raise
            dispatches += 1
            _send(connection, {'case': admission.case_id, 'type': 'allow'})
        else:
            raise ChannelError('Unknown admission transition')
