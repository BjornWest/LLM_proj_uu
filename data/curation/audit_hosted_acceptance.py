"""Read saved worker acceptance evidence; never run a browser or a model.

Checks publication/identity and complete ZIP contents independently of the
acceptance driver. Does not recompute task grades or certify deployment.
"""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[2]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(path.read_text())


def audit(folder):
    report = read(folder / 'report.json')
    registry_path = ROOT / 'config/team_tasks.json'
    registry = read(registry_path)
    tasks = {t['id']: t for t in registry['tasks']}
    control_path = folder / 'store/daylight/harness/control-v1.json'
    jobs = read(control_path)['jobs']
    checks = {
        'catalog_hash': registry['catalog_sha256'] == sha((ROOT / 'data/curation/hosted_task_catalog.json').read_bytes()),
        'registry_hash': report['source_sha256']['config/team_tasks.json'] == sha(registry_path.read_bytes()),
        'exact_case_coverage': sorted(r['case'] for r in report['cases']) == sorted(t + '-' + polarity for t in tasks for polarity in ('positive', 'negative')),
    }
    rows = []
    for row in report['cases']:
        directory = Path(row['episode'])
        job = jobs[row['job']]
        task = tasks[row['task']]
        initial = read(directory / 'initial-state.json')
        goal = initial['resolved_goal']
        recorded = read(directory / 'task.json')
        summary = read(directory / 'episode.json')
        evaluation = read(directory / 'evaluation.json')
        steps = [json.loads(s) for s in (directory / 'steps.jsonl').read_text().splitlines()]
        events = [json.loads(s)['event'] for s in (directory / 'events.jsonl').read_text().splitlines()]
        artifacts = folder / 'store/daylight/harness/artifacts' / row['job']
        chunks = []
        artifact_checks = []
        artifact_hashes = {}
        for name, metadata in job['artifacts'].items():
            packed = read(artifacts / (name + '.json'))
            body = base64.b64decode(packed['data'], validate=True)
            artifact_hashes[name] = sha(body)
            artifact_checks.append(len(body) == packed['size'] == metadata['size'] and sha(body) == packed['sha256'] == metadata['sha256'])
            if name in job['trace_parts']:
                continue
            original = directory / name
            artifact_checks.append(original.is_file() and original.read_bytes() == body)
        for name in job['trace_parts']:
            chunks.append(base64.b64decode(read(artifacts / (name + '.json'))['data'], validate=True))
        archive_bytes = b''.join(chunks)
        original_files = {str(Path(directory.name) / p.relative_to(directory)): p for p in directory.rglob('*') if p.is_file()}
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            names = archive.namelist()
            exact_set = len(names) == len(set(names)) and set(names) == set(original_files)
            exact_bytes = exact_set and all(archive.read(name) == p.read_bytes() for name, p in original_files.items())
        case_checks = {
            'identity': job['id'] == row['job'] and job['task'] == row['task'] and job['episode'] == directory.name,
            'revision': job['task_revision'] == task['revision'] == recorded['team_task']['revision'],
            'catalog_identity': recorded['team_task']['catalog_id'] == task['catalog_id'],
            'registry_identity': recorded['team_task']['registry_sha256'] == sha(registry_path.read_bytes()),
            'display_goal': job['goal'] == goal == job['resolved_goal'],
            'fixed_goal': task['goal'] is None or task['goal'] == goal,
            'every_decision_goal': bool(steps) and all(s['messages'][-1]['content'].startswith('USER GOAL: ' + goal + '\nRecent actions:') for s in steps),
            'evaluation_preserved': evaluation == summary['evaluation'] == row['evaluation'] == job['evaluation'],
            'expected_outcome': evaluation['safe_success'] is row['case'].endswith('-positive'),
            'scripted': job['mode'] == 'rehearsal' and all(s.get('model_request') is None for s in steps),
            'no_reservations': job['reservations'] == [],
            'evaluate_before_close': events.index('evaluation_completed') < events.index('environment_close_started'),
            'terminal': job['status'] == 'finished' and job['error'] is None,
            'published_artifact_bytes': bool(artifact_checks) and all(artifact_checks),
            'zip_exact_file_set': exact_set,
            'zip_exact_bytes': exact_bytes,
            'no_symlinks': not any(p.is_symlink() for p in directory.rglob('*')),
        }
        rows.append({'case': row['case'], 'checks': case_checks, 'passed': all(case_checks.values()),
                     'safe_success': evaluation['safe_success'], 'injection_exposed': evaluation['injection_exposed'],
                     'injection_avoided': evaluation['injection_avoided'], 'decisions': len(steps),
                     'zip_file_count': len(original_files), 'zip_sha256': sha(archive_bytes),
                     'published_artifact_sha256': artifact_hashes,
                     'original_file_sha256': {name: sha(p.read_bytes()) for name, p in original_files.items()}})
    return {'schema_version': 1, 'scope': 'Saved local transport evidence only; no browser/model calls, no grader recomputation, no deployment certification.',
            'input_report': str(folder / 'report.json'), 'input_report_sha256': sha((folder / 'report.json').read_bytes()),
            'control_sha256': sha(control_path.read_bytes()), 'audit_source_sha256': sha(Path(__file__).read_bytes()),
            'reported_sources_match_current': {name: sha((ROOT / name).read_bytes()) == expected for name, expected in report['source_sha256'].items()},
            'checks': checks, 'cases': rows, 'passed': all(checks.values()) and all(r['passed'] for r in rows),
            'limitations': ['Successful and rejected completed episodes only; technical-error/null-safe-success publication is not exercised by these 28 cases.',
                            'Full history bytes are retained; this audit does not add reload, cross-session or authorization-route browser tests.',
                            'Scripted drivers have privileged state access and are not model performance evidence.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error('Output already exists')
    result = audit(args.suite.resolve())
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps({'passed': result['passed'], 'cases': len(result['cases']), 'checks': result['checks'],
                      'failed': {r['case']: [k for k, v in r['checks'].items() if not v] for r in result['cases'] if not r['passed']}}))
    raise SystemExit(0 if result['passed'] else 1)
