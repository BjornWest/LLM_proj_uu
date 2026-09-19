"""Export ONLY public launch metadata; no contracts, answers or setup state."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from data.curation.worker_integration.bindings import load_registry


def project(registry_path, catalog_path):
    registry = load_registry(registry_path)
    catalog_raw = catalog_path.read_bytes()
    if hashlib.sha256(catalog_raw).hexdigest() != registry['catalog_sha256']:
        raise ValueError('Runtime and public catalog differ')
    catalog = json.loads(catalog_raw)
    public = {row['id']: row for row in catalog['tasks']}
    sites = {row['id']: row for row in catalog['sites']}
    if set(public) != {row['id'] for row in registry['tasks']} or len(public) != 203:
        raise ValueError('Expected exact 203-task coverage')
    tasks = []
    for row in registry['tasks']:
        display = public[row['id']]; site = sites[display['site_id']]
        if display['goal'] != row['policy_input']['goal']:
            raise ValueError('Task goals differ')
        tasks.append({'id': row['id'], 'title': row['id'] + ' · ' + site['name'],
                      'goal': display['goal'], 'revision': row['revision'], 'expanded': True,
                      'custom_goal': False, 'condition': display['condition'],
                      'site_id': site['id'], 'site_name': site['name'], 'collection': display['dataset'],
                      'collection_name': 'TrickyArena' if display['dataset'] == 'trickyarena' else 'WebArena',
                      'development_only': True, 'verification_scope': 'Scoped task verifier; unknown fields remain unknown.',
                      'execution_limits': {'max_steps': row['profile']['max_steps'], 'max_input_bytes': 1000000},
                      'grading_phase': row['grading_phase']})
    return {'schema': 'expanded-team-tasks-v1', 'catalog_sha256': registry['catalog_sha256'],
            'runtime_registry_sha256': hashlib.sha256(registry_path.read_bytes()).hexdigest(),
            'tasks': tasks}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--registry', type=Path, required=True)
    p.add_argument('--catalog', type=Path, default=ROOT / 'data/curation/expansion/hosted-review-catalog.json')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    with args.output.open('x') as stream:
        json.dump(project(args.registry, args.catalog), stream, indent=2, ensure_ascii=False); stream.write('\n')


if __name__ == '__main__': main()
