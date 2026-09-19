"""Bounded parallel HTTP ranges for large, pinned-size public dataset archives.

Version3 supports reviewed exact-source prefixes and final identity checks.
Version2 added fail-closed completed-chunk/archive resume checks.
Uses download_assets' approved manifest. No automatic retries. Each range retains
its partial prefix; restart requests only remaining bytes. A source ETag/range
mismatch stops that range. Completed archives are SHA256 hashed on assembly.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import threading
import time

import requests
from data.curation.expansion.download_assets import validate_plan, write_state

CHUNK = 32 * 1024 * 1024


def validate_range(response, asset, start, end):
    if response.status_code != 206:
        raise ValueError(f'Range not honored: HTTP {response.status_code}')
    expected = f'bytes {start}-{end}/{asset.get("source_bytes",asset["bytes"])}'
    if response.headers.get('Content-Range') != expected:
        raise ValueError('Wrong Content-Range')
    if response.headers.get('ETag') != asset['etag']:
        raise ValueError('Source ETag changed')
    if int(response.headers.get('Content-Length', -1)) != end - start + 1:
        raise ValueError('Range size mismatch')
    if response.headers.get('Content-Encoding', 'identity') != 'identity':
        raise ValueError('Unexpected content encoding')


def file_sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as source:
        while data:=source.read(4*1024*1024):digest.update(data)
    return digest.hexdigest()


def verify_completed(path, entry, expected_bytes):
    if path.is_symlink() or not path.is_file():raise ValueError('Completed path is not a regular file')
    if entry.get('status')!='complete' or not entry.get('sha256'):raise ValueError('Missing completed fingerprint')
    if path.stat().st_size!=expected_bytes:raise ValueError('Completed size changed')
    if file_sha(path)!=entry['sha256']:raise ValueError('Completed content changed')


def run(plan_path, dest, workers=8):
    plan_bytes = plan_path.read_bytes()
    plan = json.loads(plan_bytes)
    total = validate_plan(plan)
    for asset in plan['assets']:
        source_size=asset.get('source_bytes',asset['bytes'])
        if type(source_size) is not int or source_size<asset['bytes'] or asset.get('source_range_start',0)!=0:
            raise ValueError('Only exact source prefixes are supported')
    if not 1 <= workers <= 16:
        raise ValueError('Use 1–16 concurrent ranges')
    dest.mkdir(parents=True, exist_ok=True)
    with (dest/'ranges.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        ledger = dest/'ranges-ledger.json'
        plan_hash = hashlib.sha256(plan_bytes).hexdigest()
        if ledger.exists():
            state = json.loads(ledger.read_text())
            if state.get('chunk_bytes') != CHUNK:raise ValueError('Cannot change range boundaries for existing downloads')
            if state['plan_sha256'] != plan_hash:
                raise ValueError('Cannot change manifest for existing downloads')
        else:
            state = {'schema_version': 1, 'plan_sha256': plan_hash,
                     'reserved_bytes': total, 'limit_bytes': plan['limit_bytes'],
                     'chunk_bytes': CHUNK, 'assets': {}}
        state.setdefault('implementations',[]).append({'sha256':file_sha(Path(__file__)), 'started_at':time.time(),'workers':workers})
        mutex = threading.Lock()
        write_state(ledger, state)
        for asset in plan['assets']:
            name = asset['filename']
            parts = dest/(name+'.ranges')
            parts.mkdir(exist_ok=True)
            record = state['assets'].setdefault(name, {'status': 'in_progress', 'expected_bytes': asset['bytes'], 'chunks': {}})
            if record['status'] == 'complete':
                verify_completed(dest/name,record,asset['bytes'])
                if asset.get('expected_sha256') and record['sha256']!=asset['expected_sha256']:raise ValueError('Completed identity differs from expected source')
                continue
            write_state(ledger, state)
            def fetch(start):
                end = min(start + CHUNK, asset['bytes']) - 1
                size = end - start + 1
                path = parts/str(start)
                if path.is_symlink() or (path.exists() and not path.is_file()):
                    raise ValueError('Non-regular chunk path')
                offset = path.stat().st_size if path.exists() else 0
                if offset > size:
                    raise ValueError('Oversized chunk')
                with mutex:
                    if path.exists() and str(start) not in record['chunks']:
                        raise ValueError('Untracked chunk')
                    previous=record['chunks'].get(str(start),{})
                    if previous.get('status')=='complete':
                        verify_completed(path,previous,size)
                        return
                    record['chunks'][str(start)] = {'bytes': offset, 'status': 'in_progress'}
                    write_state(ledger, state)
                if offset < size:
                    headers = {'Range': f'bytes={start+offset}-{end}', 'If-Range': asset['etag'], 'Accept-Encoding': 'identity'}
                    with requests.get(asset['url'], headers=headers, stream=True, timeout=(30, 120)) as r:
                        validate_range(r, asset, start+offset, end)
                        with path.open('ab' if path.exists() else 'xb') as out:
                            for chunk in r.iter_content(256 * 1024):
                                if offset + len(chunk) > size:
                                    raise ValueError('Response exceeded range')
                                out.write(chunk)
                                offset += len(chunk)
                            out.flush()
                            os.fsync(out.fileno())
                if offset != size:
                    raise ValueError('Truncated range')
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                with mutex:
                    record['chunks'][str(start)] = {'bytes': offset, 'status': 'complete', 'sha256': digest}
                    record['completed_bytes'] = sum(c['bytes'] for c in record['chunks'].values() if c['status'] == 'complete')
                    record['updated_at'] = time.time()
                    write_state(ledger, state)
                    print(json.dumps({'asset': name, 'completed_bytes': record['completed_bytes'], 'expected_bytes': asset['bytes']}), flush=True)
            with ThreadPoolExecutor(max_workers=workers) as pool:
                # Bound pending work too; do not schedule the whole archive after an error.
                starts = iter(range(0, asset['bytes'], CHUNK))
                pending = {pool.submit(fetch, start) for start in [next(starts, None) for _ in range(workers)] if start is not None}
                while pending:
                    done = next(as_completed(pending))
                    pending.remove(done)
                    done.result()
                    start = next(starts, None)
                    if start is not None:
                        pending.add(pool.submit(fetch, start))
            target = dest/name
            if target.exists() or target.is_symlink():
                raise FileExistsError('Archive target exists without completed ledger; preserve and review it')
            hasher = hashlib.sha256()
            with target.open('xb') as out:
                for start in range(0, asset['bytes'], CHUNK):
                    path = parts/str(start)
                    content = path.read_bytes()
                    if hashlib.sha256(content).hexdigest() != record['chunks'][str(start)]['sha256']:
                        raise ValueError('Chunk changed before assembly')
                    out.write(content)
                    hasher.update(content)
                out.flush()
                os.fsync(out.fileno())
            if asset.get('expected_sha256') and hasher.hexdigest()!=asset['expected_sha256']:
                record.update(status='identity_failed',sha256=hasher.hexdigest(),finished_at=time.time())
                write_state(ledger,state)
                raise ValueError('Downloaded bytes do not match pinned whole-file identity; preserve and inspect')
            record.update(status='complete', sha256=hasher.hexdigest(), finished_at=time.time())
            write_state(ledger, state)
            print(json.dumps({'asset': name, 'status': 'complete', 'sha256': record['sha256']}), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--destination', type=Path, required=True)
    p.add_argument('--workers', type=int, default=8)
    args = p.parse_args()
    run(args.plan, args.destination, args.workers)
