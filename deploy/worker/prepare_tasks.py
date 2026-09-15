"""Generate a private fixed dispatch registry, or export exact reviewed Tricky fixtures.

No downloads, server changes, model calls or overwrite of existing outputs.
The curation catalog is input evidence, never policy input or a public asset.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
CHAOS = ('confirmshaming', 'drip-pricing', 'archive-vs-delete', 'revoke-current-only',
         'drop-database', 'transfer-by-not-clicking-save', 'force-push')
KINDS = {'P07': ('tricky', 'tricky'), 'P10': ('privacy', 'tricky-privacy'),
         'P11': ('membership', 'tricky-membership')}
MODULES = {'tricky': 'tricky.py', 'privacy': 'tricky_privacy.py',
           'membership': 'tricky_membership.py', 'authorized': 'tricky_authorized.py'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def exclusive(path, value):
    path = Path(path)
    if os.path.lexists(path):
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write('\n')


def registry(catalog):
    raw = json.loads(catalog.read_text())
    entries = {row['id']: row for row in raw['entries']}
    if len(entries) != 14:
        raise ValueError('Expected exactly fourteen distinct reviewed conditions')
    specs = [('chaos-'+task, 'chaos/'+task+'/native', 'chaos', None, task) for task in CHAOS]
    specs += [('tricky-'+candidate.lower()+'-'+condition, 'tricky/'+candidate+'/'+condition, kind, build,
               'no_added_injection' if condition == 'clean' else 'one_selected_injection')
              for candidate, (kind, build) in KINDS.items() for condition in ('clean', 'injected')]
    specs += [('synthetic-dev-w01', 'synthetic/DEV-W01/authorized-warranty', 'authorized', 'tricky', None)]
    output = []
    for id, source_id, kind, build, selector in specs:
        row = entries[source_id]
        goal = row['goal']
        expected_mode = 'resolve_after_session_prepare' if kind == 'chaos' else 'fixed'
        if goal['mode'] != expected_mode or kind != 'chaos' and not isinstance(goal['text'], str):
            raise ValueError('Unexpected trusted goal mode')
        expected_selector = {'task_id': selector} if kind == 'chaos' else {} if kind == 'authorized' else {'condition': selector}
        if row['adapter_selector'] != expected_selector:
            raise ValueError('Catalog adapter selector differs from fixed dispatch table')
        checks = row['verifier']['source_sha256']
        checks = checks if isinstance(checks, dict) else {'intent_browser/'+MODULES[kind]: checks}
        if any(sha(ROOT/p) != h for p, h in checks.items()):
            raise ValueError('Catalog verifier differs from current source')
        if build and sha(ROOT/'.local'/build/'build.json') != row['fixture']['build_manifest_sha256']:
            raise ValueError('Catalog build manifest differs from fixture')
        value = {'id': id, 'catalog_id': source_id, 'title': row['title'], 'site': row['source'],
                 'condition': source_id.rsplit('/', 1)[1], 'goal': goal.get('text'),
                 'goal_mode': goal['mode'], 'custom_goal': False, 'kind': kind, 'selector': selector,
                 'build': build, 'build_sha256': row['fixture'].get('build_manifest_sha256'),
                 'source_sha256': checks, 'verification_scope': row['verifier']['scope'],
                 'development_only': True, 'training_eligible': False}
        value['revision'] = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        output.append(value)
    return {'schema_version': 1, 'catalog_sha256': sha(catalog),
            'pilot_manifest_sha256': sha(ROOT/'data/curation/pilot_manifest.json'),
            'authorized_contract_sha256': sha(ROOT/'config/authorized_warranty_contract.json'), 'tasks': output}


def export(registry_path, output):
    if os.path.lexists(output):
        raise FileExistsError(output)
    config = json.loads(registry_path.read_text())
    inputs = {}
    for source, destination, expected in [
        (ROOT/'data/curation/pilot_manifest.json', 'pilot_manifest.json', config['pilot_manifest_sha256']),
        (ROOT/'config/authorized_warranty_contract.json', 'authorized_warranty_contract.json', config['authorized_contract_sha256'])]:
        if sha(source) != expected:
            raise ValueError('Pinned private manifest/contract changed')
        inputs[destination] = (source, expected)
    builds = {task['build']: task['build_sha256'] for task in config['tasks'] if task['build']}
    for build, expected in builds.items():
        base = ROOT/'.local'/build
        if sha(base/'build.json') != expected:
            raise ValueError('Pinned build changed')
        manifest = json.loads((base/'build.json').read_text())
        names = {'build.json': expected, **{'dist/'+p: h for p, h in manifest['dist_sha256'].items()}}
        for field, name in [('catalog_sha256', 'catalog.json'), ('appointments_sha256', 'appointments.json')]:
            if field in manifest:
                names[name] = manifest[field]
        for name, h in names.items():
            file = base/name
            if file.is_symlink() or not file.resolve().is_relative_to(base.resolve()) or sha(file) != h:
                raise ValueError('Invalid fixture path or file hash: '+name)
            inputs[build+'/'+name] = (file, h)
    # Exclusive destination, no state/logs/caches/certification copied into the fixtures.
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir()
    for name, (source, expected) in inputs.items():
        target = output/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if sha(target) != expected or sha(source) != expected:
            raise ValueError('Source changed while exporting')
    report = {'schema_version': 1, 'registry_sha256': sha(registry_path),
              'files_sha256': {name: h for name, (_, h) in inputs.items()},
              'readiness': False, 'source_unchanged': True,
              'scope': 'Copied bytes only; lifecycle/grading acceptance remains separate.'}
    exclusive(output/'package.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['registry', 'export'])
    parser.add_argument('--catalog', type=Path, default=ROOT/'data/curation/hosted_task_catalog.json')
    parser.add_argument('--registry', type=Path, default=ROOT/'config/team_tasks.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.path.lexists(args.output):
        raise FileExistsError(args.output)
    if args.operation == 'registry':
        result = registry(args.catalog)
        exclusive(args.output, result)
        print(json.dumps({'tasks': len(result['tasks']), 'output': str(args.output)}))
    else:
        result = export(args.registry, args.output)
        print(json.dumps({'files': len(result['files_sha256']), 'output': str(args.output), 'readiness': False}))


if __name__ == '__main__':
    main()
