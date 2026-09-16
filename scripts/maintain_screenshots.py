"""Deduplicate completed screenshots and report usage; never delete retained media.

No browser, model or network calls. Docker helpers use an already-installed image
with network disabled. Missing scopes make the report incomplete, not healthy.
"""
import argparse
import fcntl
import html
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from screenshot_storage import scan, LIMIT

REPO = Path(__file__).resolve().parents[1]
IMAGE = 'intent-browser-worker:full-sites-v2'
VOLUMES = {'hosted_manual': 'worker_manual-data', 'hosted_worker': 'worker_worker-data'}


def docker_command(volume, *, writable=False):
    # Inspect first: a typo/missing volume must not silently create an empty one.
    subprocess.run(['docker', 'volume', 'inspect', volume], check=True, capture_output=True, timeout=30)
    return ['docker', 'run', '--rm', '--pull', 'never', '--network', 'none', '--read-only',
            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--user', '10001:10001',
            '--memory', '256m', '--cpus', '0.5', '--entrypoint', 'python3',
            '--mount', f'type=volume,source={volume},target=/scan' + ('' if writable else ',readonly'),
            '--mount', f'type=bind,source={REPO / "scripts/screenshot_storage.py"},target=/tool.py,readonly', IMAGE]


def docker_scan(volume, apply):
    result = subprocess.run(docker_command(volume, writable=apply) +
                            ['/tool.py', '/scan', '--pool', '/scan/.screenshot-objects'] +
                            (['--apply'] if apply else []), capture_output=True, text=True, timeout=600)
    # scan returns a report even on a per-file failure.
    if result.stdout.strip():
        return json.loads(result.stdout)
    raise RuntimeError(f'Docker scan failed ({result.returncode}): {result.stderr[-1500:]}')


def database_upper_bound():
    # Do not copy/query live SQLite. Count its storage incl WAL as a conservative
    # upper bound on published base64 screenshots/ZIP parts that are not deduped.
    program = "import os,json; from pathlib import Path; print(json.dumps({'allocated_bytes':sum(p.stat().st_blocks*512 for p in Path('/scan').iterdir() if p.is_file() and not p.is_symlink())}))"
    result = subprocess.run(docker_command('worker_control-data') + ['-c', program],
                            check=True, capture_output=True, text=True, timeout=60)
    return json.loads(result.stdout)['allocated_bytes']


def summarize(scopes, database_bytes, errors):
    complete = not errors and all(s.get('ok') for s in scopes.values()) and database_bytes is not None
    raw = sum(s['physical_png_bytes_after_including_pool'] for s in scopes.values())
    archives = sum(s['archive_png_compressed_bytes'] for s in scopes.values())
    total = raw + archives + (database_bytes or 0)
    return {'schema_version': 1, 'scanned_at': time.time(), 'complete': complete,
            'threshold_bytes': LIMIT, 'retention_deletion': False,
            'physical_png_bytes': raw, 'archive_png_compressed_bytes': archives,
            'control_database_upper_bound_bytes': database_bytes,
            'monitored_budget_bytes': total,
            'review_required': total >= LIMIT if complete else None,
            'status': 'incomplete' if not complete else 'review_required' if total >= LIMIT else 'below_threshold',
            'scopes': scopes, 'errors': errors,
            'excluded': ['External machines and their backups', 'Local .local/ diagnostic copies and cached fixtures',
                         'Non-PNG media; no deduplication inside ZIPs or SQLite']}


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
    try:
        with temporary.open('x') as stream:
            stream.write(text); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def render(report):
    def mb(value): return 'unknown' if value is None else f'{value / 1_000_000:,.1f} MB'
    rows = ''.join('<tr>' + ''.join('<td>'+html.escape(str(v))+'</td>' for v in
                [name, s['png_files'], s['unique_images'], mb(s['logical_png_bytes']),
                 mb(s['physical_png_bytes_after_including_pool']), s['linked_files']]) + '</tr>'
                for name, s in report['scopes'].items())
    return f'''<!doctype html><meta charset="utf-8"><title>Screenshot storage</title>
<style>body{{font:17px system-ui;max-width:1000px;margin:40px auto;padding:20px}}td,th{{text-align:left;padding:10px;border-bottom:1px solid #ddd}}table{{border-collapse:collapse}}small{{color:#555}}</style>
<h1>Screenshot storage: {html.escape(report['status'])}</h1>
<p>Monitored budget: <strong>{mb(report['monitored_budget_bytes'])} / 20,000 MB</strong>.
Threshold requests a retention review; nothing is automatically deleted.</p>
<p>Updated {time.strftime('%Y-%m-%d %H:%M:%S UTC',time.gmtime(report['scanned_at']))}.
An old timestamp means the monitor has stopped; it is not a live gauge.</p>
<table><tr><th>Scope</th><th>Image paths</th><th>Byte hashes</th><th>Logical</th><th>Allocated incl pool</th><th>New links</th></tr>{rows}</table>
<p>Existing ZIP image entries: {mb(report['archive_png_compressed_bytes'])}; entire control database upper bound: {mb(report['control_database_upper_bound_bytes'])}.
ZIPs and published SQLite records remain unchanged. Scopes are separate filesystem pools; hash totals are not global unique counts.</p>
<p>Every original path remains readable. Reference counts and orphan pool bytes are recorded in the private JSON report. Shared images are stored once per filesystem, owner and read permissions.</p>
<p>Outside this budget: external machines, backups, local diagnostic copies/cached fixtures and non-PNG media.</p>
<pre>{html.escape(json.dumps(report['errors'],indent=2)) if report['errors'] else ''}</pre>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Link closed screenshots; default is inventory only')
    args = parser.parse_args()
    output = REPO / '.local/screenshot-storage'; output.mkdir(parents=True, exist_ok=True)
    with (output/'maintenance.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        scopes, errors = {}, []
        for name, collect in [('local_runs', lambda: scan(REPO/'runs', output/'objects', apply=args.apply))] + [
                (name, lambda volume=volume: docker_scan(volume, args.apply)) for name, volume in VOLUMES.items()]:
            try:
                scopes[name] = collect()
                if not scopes[name]['ok']: errors.append({'scope':name, 'error':'Scan contains file errors'})
            except Exception as e:
                errors.append({'scope':name, 'error':str(e)})
        database_bytes = None
        try: database_bytes = database_upper_bound()
        except Exception as e: errors.append({'scope':'control_database','error':str(e)})
        report = summarize(scopes, database_bytes, errors)
        atomic_write(output/'report.json', json.dumps(report, indent=2)+'\n')
        atomic_write(REPO/'.local/review/screenshot-storage.html', render(report))
        print(json.dumps({k:v for k,v in report.items() if k not in ('scopes',)}))
        if not report['complete']: sys.exit(1)

if __name__ == '__main__': main()
