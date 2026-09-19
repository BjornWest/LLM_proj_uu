"""Fresh owned full-site snapshot; sequential posts with test-only cleanup."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from data.curation.expansion.webarena_posts.common import *


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--first-only', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    previous = inspect()
    command('docker', 'rm', '-f', NAME)
    command('docker', 'run', '-d', '--pull', 'never', '--name', NAME, '--label', 'intent.owner=curation-biography',
            '--label', 'intent.reset-scope=isolated-disposable', '-p', '127.0.0.1:19099:80', '-p', '127.0.0.1:19098:8877',
            '-e', 'WA_ENV_CTRL_EXTERNAL_SITE_URL=' + ORIGIN, '--memory', '2g', '--cpus', '2', IMAGE)
    for _ in range(60):
        try:
            sql('SELECT 1')
            command('docker', 'exec', NAME, 'env-ctrl', 'init', '--base-url', ORIGIN)
            break
        except subprocess.CalledProcessError:
            time.sleep(1)
    else:
        raise RuntimeError('Owned site did not initialize')
    baseline = latest_id()
    warm = []
    for path in ['/', '/submit']:
        response = urllib.request.urlopen(urllib.request.Request(ORIGIN + path,
            headers={'X-Postmill-Auto-Login': USER + ':test1234'}), timeout=90)
        assert response.status == 200
        html = response.read()
        filename = 'original-home.html' if path == '/' else 'original-submit.html'
        (args.output / filename).write_bytes(html)
        warm.append({'url': response.url, 'status': response.status, 'html': filename})
    (args.output / 'setup.json').write_text(json.dumps({'image': IMAGE, 'previous_container': previous,
        'container': inspect(), 'baseline_submission_id': baseline, 'original_pages': warm,
        'reset_scope': 'Only owned 19099/19098; fresh cached original container. Remove only new test-user posts between cases.'}, indent=2))
    tasks = json.loads((HERE / 'contracts.json').read_text())['tasks']
    cases = [(task['source_task_id'], variant) for task in tasks for variant in ['positive', 'wrong']]
    cases += [(630, variant) for variant in ['overwrite', 'duplicate', 'abandon', 'missing-evidence']]
    if args.first_only:
        cases = cases[:1]
    results = []
    env = dict(os.environ, CURATION_FROZEN_RUNTIME=str(ROOT / '.local/curation-expansion/frozen-runtime-v1'))
    for task_id, variant in cases:
        cleanup_created(baseline)
        output = args.output / f'{task_id}-{variant}'
        with (args.output / f'{task_id}-{variant}.log').open('x') as log:
            try:
                rc = subprocess.run([sys.executable, str(HERE / 'run_v2.py'), '--task', str(task_id), '--variant', variant,
                    '--output', str(output)], stdout=log, stderr=subprocess.STDOUT, env=env, timeout=240).returncode
            except subprocess.TimeoutExpired:
                rc = 124
        result = {'task_id': task_id, 'variant': variant, 'returncode': rc, 'report': str(output / 'report.json')}
        if (output / 'report.json').exists():
            result['result'] = json.loads((output / 'report.json').read_text())
        results.append(result)
        (args.output / 'report.json').write_text(json.dumps({'schema': 'webarena-post-suite-v2', 'cases': results,
            'complete': len(results) == len(cases), 'passed': all(row['returncode'] == 0 for row in results),
            'model_calls': 0, 'training_eligible': False}, indent=2))
        print(task_id, variant, rc, flush=True)
        if rc:
            raise SystemExit(rc)


if __name__ == '__main__':
    main()
