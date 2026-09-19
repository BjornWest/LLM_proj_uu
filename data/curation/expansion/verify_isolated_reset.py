"""Prove disposable forum state reset without touching shared WebArena instances.

Privileged scripted browser validation, zero model calls. Recreates ONLY the
curation compose service after checking its ownership label and no mounts.
"""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time

import requests

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = ROOT/'data/curation/expansion/compose.isolated.yaml'
CONTAINER = 'curation-webarena-expansion-v1-reddit-1'
ORIGIN = 'http://localhost:18999'


def command(*args):
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()


def inspect():
    data = json.loads(command('docker', 'inspect', CONTAINER))[0]
    if data['Config']['Labels'].get('intent.owner') != 'curation-expansion' or data['Mounts']:
        raise ValueError('Refuse to reset a non-owned or mounted database')
    return {key: data[key] for key in ('Id', 'Image', 'Created', 'Mounts')}


def ready():
    command('docker', 'exec', CONTAINER, 'env-ctrl', 'init', '--base-url', ORIGIN)
    for _ in range(60):
        try:
            if requests.get(ORIGIN, timeout=10).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    raise RuntimeError('Isolated forum did not become ready')


def biography_hash():
    # Database is used only for private verification, never for scripted actions.
    sql = "SELECT md5(COALESCE(biography,'')) FROM users WHERE username='MarvelsGrantMan136'"
    return command('docker', 'exec', CONTAINER, 'su', 'postgres', '-c', 'psql -d postmill -Atc "'+sql+'"')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    before = inspect()
    ready()
    initial = biography_hash()
    (a.output/'initial.json').write_text(json.dumps({'container': before, 'biography_md5': initial}, indent=2)+'\n')
    code = "import sys; import scripts.smoke_webarena_controls as s; s.SITES['reddit']['url']='http://localhost:18999'; sys.argv=['smoke','--site','reddit','--observation-limit','48000']; s.main()"
    proc = subprocess.run([str(ROOT/'.venv/bin/python'), '-c', code], cwd=ROOT, text=True, capture_output=True)
    (a.output/'scripted-browser.stdout').write_text(proc.stdout)
    (a.output/'scripted-browser.stderr').write_text(proc.stderr)
    changed = biography_hash()
    trace_match = re.search(r'^Trace: (.+)$', proc.stdout, re.MULTILINE)
    smoke = json.loads((Path(trace_match[1])/'control-smoke.json').read_text()) if trace_match else None
    # Infrastructure reset is a separate question from action reliability. A
    # navigation timeout can coexist with a later confirmed saved mutation.
    if changed == initial or not smoke or not smoke['checks'] or not all(c['passed'] for c in smoke['checks']):
        raise RuntimeError('Browser/DB evidence did not establish changed state; evidence retained')
    # Recheck exact identity immediately before removing only this disposable service.
    if inspect()['Id'] != before['Id']:
        raise RuntimeError('Container identity changed during rehearsal')
    command('docker', 'compose', '-f', str(COMPOSE), 'rm', '-s', '-f', 'reddit')
    command('docker', 'compose', '-f', str(COMPOSE), 'up', '-d', 'reddit')
    ready()
    after = inspect()
    restored = biography_hash()
    report = {'schema_version': 1, 'scope': 'Isolated whole-container reset after native BrowserGym task399 biography edit',
              'model_calls': 0, 'shared_instances_touched': False, 'before': before, 'after': after,
              'initial_biography_md5': initial, 'edited_biography_md5': changed, 'reset_biography_md5': restored,
              'browser_trace': str(Path(trace_match[1]).relative_to(ROOT)), 'browser_smoke_passed': smoke['passed'],
              'browser_action_error_count': smoke['summary']['action_error_count'], 'browser_process_exit_code': proc.returncode,
              'passed': initial == restored and initial != changed and before['Id'] != after['Id'],
              'source_sha256': {str(f.relative_to(ROOT)): hashlib.sha256(f.read_bytes()).hexdigest() for f in [Path(__file__), COMPOSE, ROOT/'scripts/smoke_webarena_controls.py']},
              'limitations': ['One account field/reset case, not every server-side state or service.', 'Reset pass does not promote browser smoke or task acceptance; browser errors are separately retained.', 'Cold re-creation is not optimized for high-concurrency training.']}
    (a.output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
