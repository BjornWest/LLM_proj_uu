"""Export an allowlisted human review catalog; never register runnable jobs.

Private task contracts, answers, setup values and verifier inputs remain local.
The site links open ordinary inspection, not the task's initialized/evaluated run.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from data.curation.expansion.accepted_index import ROOT, collect

SITES = {
    ('trickyarena', 'shop'): ('tricky-shop', 'Tricky shopping', '/sites/tricky/shop'),
    ('trickyarena', 'health'): ('tricky-health', 'Tricky health records', '/sites/tricky/health'),
    ('trickyarena', 'news'): ('tricky-news', 'Tricky news', '/sites/tricky/news'),
    ('trickyarena', 'spotify'): ('tricky-music', 'Tricky music', '/sites/tricky/spotify'),
    ('webarena-verified', 'shopping'): ('webarena-shopping', 'WebArena shopping', None),
    ('webarena-verified', 'reddit'): ('webarena-forum', 'WebArena forum', None),
}


def public_task(row):
    if len(row['sites']) != 1:
        raise ValueError('Cross-site review needs an explicit mapping')
    key = row['dataset'], row['sites'][0]
    site_id, _, _ = SITES[key]
    if not isinstance(row['goal'], str) or not row['goal'].strip():
        raise ValueError('Missing reviewed goal')
    return {
        'id': row['id'], 'dataset': row['dataset'], 'site_id': site_id,
        'goal': row['goal'], 'origin': row['origin'],
        'template_id': row['template_id'], 'kind': row['kind'],
        'condition': row['condition'],
        'validation': 'independently_reviewed_scripted_development',
        'model_tested': False, 'training_eligible': False,
        'execution_available': False,
        'inspection_scope': 'Browse the original site. Opening it does not apply this task setup or run its verifier.',
    }


def original_webarena_path(source, site):
    starts = source['start_urls']
    prefix = {'shopping': '__SHOPPING__', 'reddit': '__REDDIT__'}[site]
    if len(starts) != 1 or not starts[0].startswith(prefix):
        raise ValueError('Unexpected source start URL')
    relative = starts[0][len(prefix):] or '/'
    parsed = urlsplit(relative)
    if not relative.startswith('/') or relative.startswith('//') or parsed.scheme or parsed.netloc or '\\' in relative:
        raise ValueError('Source start must stay on the selected site')
    return relative


def build():
    rows = collect()
    tasks = [public_task(row) for row in rows]
    source = {str(task['task_id']): task for task in json.loads((ROOT/'.local/webarena-verified/dataset.json').read_text())}
    for task, row in zip(tasks, rows):
        task['start_path'] = (original_webarena_path(source[row['source_task_id']], row['sites'][0])
                              if row['dataset'] == 'webarena-verified' else SITES[(row['dataset'], row['sites'][0])][2])
        task['task_setup_applied'] = False
    counts = Counter(task['site_id'] for task in tasks)
    manifest_path = ROOT/'environments/inspection_full/manifest.json'
    manifest = json.loads(manifest_path.read_text())
    local_build = json.loads((ROOT/'.local/tricky-full-v1/build.json').read_text())
    # Website inspection must use the reviewed compiled site, not another fixture.
    if manifest['site_revision'] != local_build['site_revision']:
        raise ValueError('Hosted/local Tricky site revisions differ')
    sites = []
    for (dataset, _), (site_id, name, client_url) in SITES.items():
        sites.append({'id': site_id, 'name': name, 'dataset': dataset,
            'task_count': counts[site_id], 'client_url': client_url,
            'manual_site_id': site_id if client_url is None else None,
            'site_revision': manifest['site_revision'] if client_url else None,
            'access': 'client_inspection' if client_url else 'authenticated_remote_browser_required'})
    return {'schema': 'browser-task-review-catalog-v1',
        'purpose': 'Human site/task review; not a model-job registry or readiness certificate.',
        'counts': dict(Counter(task['dataset'] for task in tasks)),
        'sites': sites, 'tasks': tasks,
        'provenance': {
            'accepted_index_sha256': hashlib.sha256((ROOT/'data/curation/expansion/accepted_index.py').read_bytes()).hexdigest(),
            'exporter_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'site_manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            'upstream_webarena_tasks_sha256': hashlib.sha256((ROOT/'.local/webarena-verified/dataset.json').read_bytes()).hexdigest(),
        }}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = build()
    with args.output.open('x') as output:
        json.dump(report, output, indent=2, ensure_ascii=False)
        output.write('\n')
    print(json.dumps({'output': str(args.output), 'counts': report['counts']}))
