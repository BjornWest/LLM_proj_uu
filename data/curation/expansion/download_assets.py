"""Download pinned-size dataset assets within an explicit byte reservation cap.

No automatic retries, extraction, deletion, or model calls. Run one process per
ledger; completed and partial downloads stay on disk. HTTP ranges permit a
manual restart without silently redownloading an existing prefix. Manifest
sizes/ETags must come from a reviewed source; ETags are not claimed SHA256s.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import time

import requests


def validate_plan(plan):
    if type(plan['limit_bytes']) is not int or plan['limit_bytes'] <= 0:
        raise ValueError('Invalid approved byte limit')
    names = set()
    total = plan.get('other_reserved_bytes', 0)
    if type(total) is not int or total < 0:
        raise ValueError('Invalid other reservations')
    for asset in plan['assets']:
        name = asset['filename']
        if name in names or Path(name).name != name or name in ('', '.', '..'):
            raise ValueError('Duplicate or unsafe filename')
        names.add(name)
        if type(asset['bytes']) is not int or asset['bytes'] <= 0:
            raise ValueError('Invalid asset size')
        if not asset['url'].startswith('https://') or not asset.get('etag'):
            raise ValueError('HTTPS source and pinned ETag required')
        total += asset['bytes']
    if total > plan['limit_bytes']:
        raise ValueError(f'Plan exceeds authorization: {total} > {plan["limit_bytes"]}')
    return total


def check_response(response, asset, offset):
    expected_status = 206 if offset else 200
    if response.status_code != expected_status:
        raise ValueError(f'Expected HTTP {expected_status}, got {response.status_code}')
    if response.headers.get('ETag') != asset['etag']:
        raise ValueError('Source ETag changed')
    if response.headers.get('Content-Encoding', 'identity') != 'identity':
        raise ValueError('Encoded response has unaccounted size')
    if int(response.headers.get('Content-Length', -1)) != asset['bytes'] - offset:
        raise ValueError('Response length differs from reservation')
    if offset:
        expected = f'bytes {offset}-{asset["bytes"]-1}/{asset["bytes"]}'
        if response.headers.get('Content-Range') != expected:
            raise ValueError('Server did not resume the exact remaining range')


def write_state(path, state):
    tmp = path.with_suffix('.tmp')
    with tmp.open('w') as out:
        json.dump(state, out, indent=2)
        out.write('\n')
        out.flush()
        os.fsync(out.fileno())
    os.replace(tmp, path)


def download(plan_path, destination):
    plan_bytes = plan_path.read_bytes()
    plan = json.loads(plan_bytes)
    total = validate_plan(plan)
    destination.mkdir(parents=True, exist_ok=True)
    with (destination / 'download.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        ledger = destination / 'download-ledger.json'
        digest = hashlib.sha256(plan_bytes).hexdigest()
        if ledger.exists():
            state = json.loads(ledger.read_text())
            if state['plan_sha256'] != digest:
                raise ValueError('Plan changed; preserve this ledger')
        else:
            state = {'schema_version': 1, 'plan_sha256': digest,
                     'limit_bytes': plan['limit_bytes'], 'reserved_bytes': total,
                     'accounting': 'HTTP asset body bytes; image reservations separate; no wire-overhead measurement',
                     'assets': {}}
        write_state(ledger, state)
        for asset in plan['assets']:
            path = destination / asset['filename']
            if path.is_symlink() or (path.exists() and not path.is_file()):
                raise ValueError('Asset path is not a regular file')
            previous = state['assets'].get(asset['filename'])
            if path.exists() and previous is None:
                raise ValueError('Untracked existing asset; do not adopt silently')
            offset = path.stat().st_size if path.exists() else 0
            if offset > asset['bytes']:
                raise ValueError('Local file exceeds pinned size')
            if offset == asset['bytes'] and previous and previous.get('status') == 'complete':
                print(json.dumps({'asset': path.name, 'status': 'already_complete'}), flush=True)
                continue
            record = state['assets'].setdefault(path.name, {'expected_bytes': asset['bytes'], 'etag': asset['etag']})
            record.update(status='in_progress', received_bytes=offset, started_at=time.time())
            write_state(ledger, state)
            hasher = hashlib.sha256()
            if offset:
                with path.open('rb') as prefix:
                    for chunk in iter(lambda: prefix.read(4 * 1024 * 1024), b''):
                        hasher.update(chunk)
            try:
                if offset < asset['bytes']:
                    headers = {'Accept-Encoding': 'identity'}
                    if offset:
                        headers.update({'Range': f'bytes={offset}-', 'If-Range': asset['etag']})
                    with requests.get(asset['url'], headers=headers, stream=True, timeout=(30, 120)) as response:
                        check_response(response, asset, offset)
                        checkpoint = time.monotonic()
                        with path.open('ab' if offset else 'xb') as out:
                            for chunk in response.iter_content(chunk_size=1024 * 1024):
                                if offset + len(chunk) > asset['bytes']:
                                    raise ValueError('Response exceeded pinned length')
                                out.write(chunk)
                                hasher.update(chunk)
                                offset += len(chunk)
                                if time.monotonic() - checkpoint >= 10:
                                    out.flush()
                                    record.update(received_bytes=offset, updated_at=time.time())
                                    write_state(ledger, state)
                                    print(json.dumps({'asset': path.name, 'received_bytes': offset, 'expected_bytes': asset['bytes']}), flush=True)
                                    checkpoint = time.monotonic()
                            out.flush()
                            os.fsync(out.fileno())
                if offset != asset['bytes']:
                    raise ValueError('Incomplete body')
                record.update(status='complete', received_bytes=offset, sha256=hasher.hexdigest(), finished_at=time.time())
                write_state(ledger, state)
                print(json.dumps({'asset': path.name, **record}), flush=True)
            except BaseException as exc:
                record.update(status='interrupted', received_bytes=offset, error=type(exc).__name__ + ': ' + str(exc), finished_at=time.time())
                write_state(ledger, state)
                raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    download(args.plan, args.destination)
