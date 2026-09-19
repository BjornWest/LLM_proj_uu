"""Freeze an explicitly selected development runtime after scripted acceptance.

This does not assert per-task model success, training readiness, or full benchmark
coverage. Evidence paths and selected task IDs are supplied by the reviewer.
"""
import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def certify(package, fixtures, reports, task_ids, output):
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    manifest = json.loads((package / 'manifest.json').read_text())
    for name, expected in manifest['files'].items():
        path = package / name
        if not path.resolve().is_relative_to(package.resolve()) or path.is_symlink() or digest(path) != expected:
            raise ValueError('Packaged source differs from manifest')
    registry = json.loads((package / 'registry.json').read_text())
    rows = registry['tasks']
    ids = set(task_ids)
    if not ids or len(ids) != len(task_ids) or not ids.issubset({row['id'] for row in rows}):
        raise ValueError('Select distinct known task IDs explicitly')
    evidence = []
    for path in reports:
        report = json.loads(path.read_text())
        if report.get('passed') is not True or report.get('model_calls') != 0:
            raise ValueError('Expected passing zero-model-call acceptance evidence')
        evidence.append({'path': str(path), 'sha256': digest(path)})
    if not evidence:
        raise ValueError('Acceptance evidence required')
    source_hashes = {name.removeprefix('runtime/'): value for name, value in manifest['files'].items() if name.startswith('runtime/')}
    result = {'schema': 'expanded-worker-certification-v1', 'registry_sha256': digest(package / 'registry.json'),
              'source_sha256': source_hashes, 'fixture_sha256': {name: digest(fixtures / name) for name in ('build.json', 'catalog.json')},
              'runtime_options': {'action_timeout_ms': 30000},
              'tasks': {row['id']: row['revision'] for row in rows if row['id'] in ids},
              'package_manifest_sha256': digest(package / 'manifest.json'), 'acceptance': evidence,
              'scope': 'Development runtime adoption; representative scripted family checks, not per-task model certification',
              'training_eligible': False, 'model_calls': 0}
    with output.open('x') as stream:
        json.dump(result, stream, indent=2); stream.write('\n')
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--package', type=Path, required=True)
    p.add_argument('--fixtures', type=Path, required=True)
    p.add_argument('--report', type=Path, action='append', required=True)
    p.add_argument('--task', action='append', required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    result = certify(a.package, a.fixtures, a.report, a.task, a.output)
    print(json.dumps({'tasks': len(result['tasks']), 'sources': len(result['source_sha256']), 'sha256': digest(a.output)}))


if __name__ == '__main__': main()
