#!/usr/bin/env python3
"""Local cleanup watchdog for ONE already allocated Verda VM.

Plan is the default: no credentials, network, allocation or deletion. Watch
requires --execute and a bound existing-instance record. There is no create API.
Keep this process/workstation alive: Verda has no proven provider-enforced TTL.
"""
import argparse
import datetime as dt
import http.client
import json
import math
import os
from pathlib import Path
import signal
import socket
import sys
import tempfile
import threading
import time
from urllib.parse import urlencode
from uuid import UUID

UTC = dt.timezone.utc
API_HOST = 'api.verda.com'
MAX_RESPONSE = 2 << 20
STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT)


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('A timezone-qualified UTC timestamp is required')
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset() != dt.timedelta(0):
        raise ValueError('Use UTC timestamps with Z or +00:00')
    return parsed.timestamp()


def uuid(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError('Use a canonical UUID')
    return value


def validate(spec):
    uuid(spec['instance_id']); uuid(spec['run_id'])
    if spec['instance_id'] == spec['run_id']:
        raise ValueError('Run and instance IDs must be distinct')
    if not isinstance(spec['hostname'], str) or not 1 <= len(spec['hostname']) <= 253:
        raise ValueError('Missing expected hostname')
    if (spec['instance_type'] != '1RTXPRO6000.30V' or not isinstance(spec['location'], str)
            or not spec['location']):
        raise ValueError('This watchdog binds the selected RTX PRO instance type')
    start, end = timestamp(spec['allocation_started_at']), timestamp(spec['deadline'])
    created = timestamp(spec['provider_created_at'])
    if not 0 < end - start <= 86400 or not start <= created < end:
        raise ValueError('Deadline must follow allocation, at most24h, without a readiness reset')
    known, remove = spec['volume_ids'], spec['delete_volume_ids']
    if not isinstance(known, list) or not isinstance(remove, list):
        raise ValueError('Volume IDs must be explicit unique lists')
    for value in known + remove:
        uuid(value)
    if len(set(known)) != len(known) or len(set(remove)) != len(remove):
        raise ValueError('Volume IDs must be explicit unique lists')
    if not set(remove) <= set(known):
        raise ValueError('Only explicitly bound volumes can be removed')
    return spec


def plan(spec):
    validate(spec)
    return {'instance_id': spec['instance_id'], 'deadline': spec['deadline'],
            'allocation_started_at': spec['allocation_started_at'],
            'delete': {'action': 'delete', 'id': spec['instance_id'],
                       'volume_ids': spec['delete_volume_ids'], 'delete_permanently': True},
            'retained_volume_ids': sorted(set(spec['volume_ids']) - set(spec['delete_volume_ids'])),
            'no_create_API': True, 'provider_enforced_billing_cap': False}


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write((json.dumps(data, indent=2, allow_nan=False) + '\n').encode())
            stream.flush(); os.fsync(stream.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class APIError(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__('Verda HTTP ' + str(status))  # Never echo a response/token.


class ResponseError(OSError):
    """Retryable incomplete/malformed API exchange, distinct from ownership drift."""


class Client:
    def __init__(self, client_id, client_secret):
        if not client_id or not client_secret:
            raise ValueError('Verda credentials are missing')
        self._id, self._secret, self._token = client_id, client_secret, None

    def _call(self, method, path, body=None, *, authenticated=True, timeout=10):
        if not ((method == 'POST' and path == '/v1/oauth2/token' and not authenticated)
                or (method == 'GET' and path.startswith('/v1/instances?computeId=') and authenticated)
                or (method == 'PUT' and path == '/v1/instances' and authenticated
                    and isinstance(body, dict) and body.get('action') == 'delete')):
            raise ValueError('Unsupported Verda operation; this client cannot allocate')
        if not math.isfinite(timeout) or not 0 < timeout <= 10:
            raise ValueError('API timeout must be in (0,10] seconds')
        end = time.monotonic() + timeout
        if authenticated and self._token is None:
            auth = self._call('POST', '/v1/oauth2/token', {
                'grant_type': 'client_credentials', 'client_id': self._id,
                'client_secret': self._secret}, authenticated=False, timeout=timeout)
            token = auth.get('access_token') if isinstance(auth, dict) else None
            if not isinstance(token, str) or not token:
                raise ResponseError('Verda returned no access token')
            self._token = token
        # Authentication consumes the same call budget; never start another
        # full timeout after OAuth, including during deletion confirmation.
        timeout = end - time.monotonic()
        if timeout <= 0:
            raise TimeoutError('Verda API authentication deadline')
        conn = http.client.HTTPSConnection(API_HOST, timeout=timeout)
        timer = None
        try:
            conn.connect()
            if time.monotonic() >= end:
                raise TimeoutError('Verda API connection deadline')
            sock = conn.sock
            def abort():
                try:
                    # Do not invoke SSLSocket.shutdown: it clears _sslobj before
                    # shutdown, allowing a concurrent send to fall through to TCP.
                    socket.socket.shutdown(sock, socket.SHUT_RDWR)
                except OSError:
                    pass
            timer = threading.Timer(end - time.monotonic(), abort)
            timer.daemon = True; timer.start()
            headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
            if authenticated:
                headers['Authorization'] = 'Bearer ' + self._token
            conn.request(method, path, None if body is None else json.dumps(body).encode(), headers)
            response = conn.getresponse()
            raw = response.read(MAX_RESPONSE + 1)
            if not 200 <= response.status < 300:
                if response.status == 401:
                    self._token = None  # Re-authenticate on the next bounded read.
                raise APIError(response.status)  # Redirects are never followed.
            if len(raw) > MAX_RESPONSE:
                raise ResponseError('Verda response exceeds bound')
            if response.status == 204:
                return None
            if not raw or response.length not in (None, 0):
                raise ResponseError('Verda response body is incomplete')
            try:
                return json.loads(raw)
            except (ValueError, UnicodeError) as exc:
                raise ResponseError('Verda response is not complete JSON') from exc
        finally:
            if timer is not None:
                timer.cancel()
            conn.close()

    def instance(self, instance_id, *, timeout=10):
        uuid(instance_id)
        try:
            rows = self._call('GET', '/v1/instances?' + urlencode({'computeId': instance_id}), timeout=timeout)
        except APIError as exc:
            if exc.status == 404:
                return None
            raise
        if isinstance(rows, dict):  # API documents both single object and list.
            rows = [rows]
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ResponseError('Unexpected instance response')
        if any(row.get('id') is None for row in rows):
            raise ResponseError('Instance response is missing its identifier')
        selected = [row for row in rows if row.get('id') == instance_id]
        if len(selected) > 1 or any(row.get('id') != instance_id for row in rows):
            raise ValueError('Ambiguous instance lookup')
        return selected[0] if selected else None

    def delete(self, body, *, timeout=10):
        if body['action'] != 'delete':
            raise ValueError('Only instance deletion is supported')
        uuid(body['id'])
        data = self._call('PUT', '/v1/instances', body, timeout=timeout)
        if data is None:  # Documented204, or a JSON-null acknowledgement.
            return True
        if (not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict)
                or data[0].get('instanceId') != body['id'] or data[0].get('action') != 'delete'):
            raise ResponseError('Unexpected deletion acknowledgement')
        if data[0].get('status') != 'success':
            raise ResponseError('Verda did not accept deletion')
        return True


def identity(row, spec):
    if row.get('id') != spec['instance_id']:
        raise ValueError('Instance ID changed')
    if row.get('status') == 'notfound':
        return
    for key, expected in [('hostname', spec['hostname']), ('instance_type', spec['instance_type']),
                          ('location', spec['location'])]:
        if row.get(key) != expected:
            raise ValueError('Instance identity changed: ' + key)
    if timestamp(row['created_at']) != timestamp(spec['provider_created_at']):
        raise ValueError('Instance creation time differs from bound allocation')
    tags = row.get('tags')
    if not isinstance(tags, list) or sum(t.get('key') == 'run' and t.get('value') == spec['run_id']
                                       for t in tags if isinstance(t, dict)) != 1:
        raise ValueError('Instance run tag does not identify this allocation')


def cleanup(client, spec, receipt, *, reason, monotonic=time.monotonic, sleep=time.sleep,
            confirmation_seconds=60, ownership_observed=False, watch_error_type=None):
    """Delete only the bound VM. Acceptance is never a billing-stop receipt."""
    if type(ownership_observed) is not bool:
        raise ValueError('Ownership evidence must be an explicit boolean from a verified read')
    planned = plan(spec)
    state = {**planned, 'reason': reason, 'delete_accepted': False,
             'termination_confirmed': False, 'storage_policy_mismatch': False,
             'ownership_observed': bool(ownership_observed), 'delete_attempts': 0}
    if watch_error_type is not None:
        state['watch_error_type'] = watch_error_type
    if not math.isfinite(confirmation_seconds) or not 0 < confirmation_seconds <= 120:
        raise ValueError('Confirmation window must be finite and at most120s')
    start = monotonic(); end = start + confirmation_seconds
    attempts = 0
    absent_reads = 0
    def publish():
        # Billing cleanup must survive full/read-only/missing receipt storage.
        try:
            save(receipt, state)
            return True
        except Exception as exc:
            state.setdefault('receipt_error_types', []).append(type(exc).__name__)
            try:
                print('Verda receipt persistence failed; cleanup continues: ' + type(exc).__name__,
                      file=sys.stderr, flush=True)
            except Exception:
                pass  # A full disk/closed terminal must not block deletion either.
            return False
    publish()
    try:
        while monotonic() < end:
            try:
                row = client.instance(spec['instance_id'], timeout=min(10, max(.01, end - monotonic())))
                if row is None or row.get('status') == 'notfound':
                    # Wrong project credentials/wrong UUID can also yield404.
                    # Only a previously observed, owned VM can be confirmed gone.
                    state['unobserved_absence'] = not state['ownership_observed']
                    if not state['ownership_observed']:
                        break
                    absent_reads += 1
                    state['consecutive_absent_reads'] = absent_reads
                    if absent_reads >= 2:
                        state['termination_confirmed'] = True
                        break
                    sleep(min(2, max(0, end - monotonic())))
                    continue
                absent_reads = 0
                if row.get('id') != spec['instance_id']:
                    raise ValueError('Instance ID changed')
                if attempts and row.get('status') == 'deleting':
                    # Provider may detach disks/drop tags during deletion. We
                    # already bound ownership/storage before issuing this action.
                    sleep(min(2, max(0, end - monotonic())))
                    continue
                identity(row, spec)
                state['ownership_observed'] = True
                actual_volumes = set(row.get('volume_ids') or [])
                if row.get('os_volume_id'):
                    actual_volumes.add(row['os_volume_id'])
                body = dict(planned['delete'])
                if actual_volumes != set(spec['volume_ids']):
                    body['volume_ids'] = []  # Never delete an unbound disk.
                    state['storage_policy_mismatch'] = True
                state['actual_delete_body'] = body
                # Bounded cleanup retries are allowed; no allocation retry exists.
                # First read after an ambiguous DELETE resolves acceptance before
                # issuing another deletion against the same owned instance.
                if (row.get('status') != 'deleting' and attempts < 3
                        and monotonic() >= start + confirmation_seconds * attempts / 3):
                    attempts += 1
                    state['delete_attempts'] = attempts
                    publish()
                    state['delete_accepted'] = bool(client.delete(
                        body, timeout=min(10, max(.01, end - monotonic()))))
                publish()
            except (OSError, APIError, http.client.HTTPException) as exc:
                state.setdefault('transport_error_types', []).append(type(exc).__name__)
                publish()
            sleep(min(2, max(0, end - monotonic())))
    except Exception as exc:
        state['cleanup_error_type'] = type(exc).__name__
    persisted = publish()
    if not persisted or not state['termination_confirmed'] or state['storage_policy_mismatch']:
        # Report a useful outcome even when the receipt cannot be persisted.
        raise RuntimeError('Verda cleanup requires attention: termination_confirmed=' +
                           str(state['termination_confirmed']) + ', receipt_persisted=' + str(persisted) +
                           ', storage_policy_mismatch=' + str(state['storage_policy_mismatch']))
    return state


def watch(client, spec, receipt, *, finish_marker=None, wall=time.time,
          monotonic=time.monotonic, sleep=time.sleep, should_stop=lambda: False):
    validate(spec)
    end = timestamp(spec['deadline'])
    # Monotonic bound never extends if the wall clock moves backwards mid-run.
    mono_end = monotonic() + min(max(0, end - wall()),
                                end - timestamp(spec['allocation_started_at']))
    if monotonic() >= mono_end or wall() >= end:
        return cleanup(client, spec, receipt, reason='deadline', monotonic=monotonic, sleep=sleep)
    reason = 'deadline'
    observed = False; watch_error_type = None
    try:
        startup_end = min(mono_end, monotonic() + 30)
        while True:
            try:
                if should_stop():
                    raise KeyboardInterrupt
                row = client.instance(spec['instance_id'], timeout=min(10, max(.01, startup_end - monotonic())))
                break
            except (OSError, APIError, http.client.HTTPException):
                if monotonic() >= startup_end:
                    raise
                sleep(min(2, max(0, startup_end - monotonic())))
        if row is None or row.get('status') == 'notfound':
            raise ValueError('Bound instance has never been observed')
        identity(row, spec)
        observed = True
        save(receipt, {**plan(spec), 'status': 'watching', 'pid': os.getpid()})
        while wall() < end and monotonic() < mono_end:
            if should_stop():
                raise KeyboardInterrupt
            if finish_marker is not None and Path(finish_marker).exists():
                marker = json.loads(Path(finish_marker).read_text())
                if marker != {'run_id': spec['run_id'], 'instance_id': spec['instance_id']}:
                    raise ValueError('Local finish marker does not bind this allocation')
                reason = 'local_finish_marker'; break
            sleep(min(2, max(0, end - wall()), max(0, mono_end - monotonic())))
    except (KeyboardInterrupt, SystemExit):
        reason = 'signal'
    except Exception as exc:
        # Even a startup/marker failure attempts cleanup of the bound allocation.
        reason = 'watch_failed'
        watch_error_type = type(exc).__name__
    previous = {}
    if threading.current_thread() is threading.main_thread():
        previous = {sig: signal.signal(sig, signal.SIG_IGN) for sig in STOP_SIGNALS}
    try:
        result = cleanup(client, spec, receipt, reason=reason, monotonic=monotonic, sleep=sleep,
                         ownership_observed=observed, watch_error_type=watch_error_type)
        if reason == 'watch_failed':
            raise RuntimeError('Verda watch failed; bound instance cleanup is recorded')
        return result
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--spec', type=Path, required=True)
    p.add_argument('--execute', action='store_true')
    p.add_argument('--receipt', type=Path)
    p.add_argument('--env-file', type=Path)
    p.add_argument('--finish-marker', type=Path)
    args = p.parse_args()
    spec = validate(json.loads(args.spec.read_text()))
    if not args.execute:
        print(json.dumps(plan(spec), indent=2)); return
    if args.receipt is None:
        p.error('--execute requires a private --receipt')
    from dotenv import dotenv_values
    values = dotenv_values(args.env_file) if args.env_file else {}
    client = Client(os.environ.get('VERDA_CLIENT_ID') or values.get('VERDA_CLIENT_ID'),
                    os.environ.get('VERDA_CLIENT_SECRET') or values.get('VERDA_CLIENT_SECRET'))
    stop_requested = False
    def interrupted(signum, frame):
        nonlocal stop_requested
        # Signal handlers only set state. Multiple pending signals cannot raise
        # again while watch() hands over to cleanup or restores its handlers.
        stop_requested = True
    for sig in STOP_SIGNALS:
        signal.signal(sig, interrupted)
    result = watch(client, spec, args.receipt, finish_marker=args.finish_marker,
                   should_stop=lambda: stop_requested)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
