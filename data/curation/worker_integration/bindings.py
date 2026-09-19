"""Build a portable private registry from the reviewed selection; no execution."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BINDINGS = ROOT / '.local/curation-expansion/sweep-inputs-203-v3.json'
DEFAULT_CATALOG = ROOT / 'data/curation/expansion/hosted-review-catalog.json'
SCHEMA = 'expanded-task-runtime-registry-v1'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def revision(row):
    return hashlib.sha256(json.dumps({k: v for k, v in row.items() if k != 'revision'},
                                    sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def checked_path(root, reference):
    path = (Path(root) / reference['path']).resolve()
    if not path.is_relative_to(Path(root).resolve()) or digest(path) != reference['sha256']:
        raise ValueError('Invalid private source: ' + reference['path'])
    return path


def contract_for(root, row):
    data = json.loads(checked_path(root, row['contract']).read_text())
    if isinstance(data, list):
        candidates = data
    else:
        candidates = data.get('tasks', [data])
    matches = [t for t in candidates if str(row['contract_row_id']) in
               {str(t.get('id')), str(t.get('task_id')), str(t.get('source_task_id'))}]
    if len(matches) != 1:
        raise ValueError('Ambiguous private contract: ' + row['id'])
    return matches[0]


def family(binding):
    impl = binding['implementation']
    if impl['type'] == 'existing_open_ended_read_only_task':
        return 'webarena.native_read_only'
    module = impl['factory']['module']
    if binding['dataset'] == 'trickyarena':
        if module.endswith('adopt_tricky_native'):
            return 'tricky.lookup' if impl['factory']['symbol'] == 'NativeLookup' else 'tricky.action'
        if module.endswith('tricky_original_remaining.tasks'):
            return 'tricky.remaining'
        return 'tricky.' + module.split('.tricky.', 1)[1]
    for name in ('biography_batch02', 'biography', 'votes', 'wishlist', 'posts', 'coupon'):
        if '.webarena_' + name + '.' in module:
            return 'webarena.' + name
    raise ValueError('Unsupported implementation: ' + module)


def build(bindings=DEFAULT_BINDINGS, catalog=DEFAULT_CATALOG, root=ROOT):
    source = json.loads(Path(bindings).read_text())
    public = json.loads(Path(catalog).read_text())
    public_rows = {r['id']: r for r in public['tasks']}
    if len(public_rows) != 203 or len(source['tasks']) != 203:
        raise ValueError('Expected exact reviewed 203-task selection')
    rows = []
    seen = set()
    for original in source['tasks']:
        task_id = original['id']
        if task_id in seen:
            raise ValueError('Duplicate task ID')
        seen.add(task_id)
        if original['policy_input']['goal'] != public_rows[task_id]['goal']:
            raise ValueError('Catalog goal mismatch: ' + task_id)
        fam = family(original)
        row = {'id': task_id, 'family': fam, 'site_id': public_rows[task_id]['site_id'],
               'policy_input': original['policy_input'], 'profile': original['validation_profile'],
               'contract': original['private_contract'], 'contract_row_id': original['private_contract_row_id'],
               'grading_phase': 'after_browser_close' if fam == 'webarena.native_read_only' else 'before_browser_close',
               'historical_binding_sha256': revision(original),
               'training_eligible': False, 'model_tested': False}
        row['profile'] = {k: v for k, v in row['profile'].items() if k != 'recorded_case_profile'}
        task = contract_for(root, row)
        goal = task.get('policy_input', {}).get('goal', task.get('intent'))
        if goal != row['policy_input']['goal']:
            raise ValueError('Private contract goal mismatch: ' + task_id)
        if fam.startswith('tricky.'):
            row['fixture'] = original['environment']
            factory = original['implementation']['factory']
            checked_path(root, factory['source'])
            row['historical_factory'] = factory
        else:
            row['site'] = original['sites'][0]
            row['source_task_id'] = int(task_id.split(':')[1])
            if fam == 'webarena.native_read_only':
                row['start_url_template'] = task['start_urls'][0]
            else:
                row['start_url_template'] = task.get('setup', {}).get('start_url', '__' + row['site'].upper() + '__')
        row['revision'] = revision(row)
        rows.append(row)
    if seen != set(public_rows):
        raise ValueError('Catalog coverage mismatch')
    return {'schema': SCHEMA, 'catalog_sha256': digest(catalog), 'historical_bindings_sha256': digest(bindings),
            'counts': dict(Counter(r['family'] for r in rows)), 'tasks': rows,
            'readiness': 'unvalidated_new_bridge; historical scripted evidence is not current execution'}


def load_registry(path):
    value = json.loads(Path(path).read_text())
    if value.get('schema') != SCHEMA:
        raise ValueError('Unknown registry schema')
    rows = value['tasks']
    if len({r['id'] for r in rows}) != len(rows) or any(r['revision'] != revision(r) for r in rows):
        raise ValueError('Registry identity mismatch')
    return value


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    # Preserve prior exports including dangling links; final exclusive creation handles races.
    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError(args.output)
    value = build()
    with args.output.open('x') as stream:
        json.dump(value, stream, indent=2); stream.write('\n')
    print(json.dumps({'tasks': len(value['tasks']), 'families': value['counts'], 'sha256': digest(args.output)}))


if __name__ == '__main__':
    main()
