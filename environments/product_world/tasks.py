"""Bind task references to canonical models, without access to offers or layout."""
import copy
import hashlib
import json

from environments.shopping_intent.generator import generate, QUERY_PRESETS, stream
from environments.shopping_intent.render import render
from .generator import rng
from .validation import validate_catalog


def generate_task(catalog, seed=0, family='random', query='cheapest', **options):
    validate_catalog(catalog)
    groups = catalog['public']['product_groups']
    available = sorted({g['family'] for g in groups})
    resolved_query = stream(seed, 'query').choice(sorted(QUERY_PRESETS)) if query == 'random' else query
    if resolved_query not in QUERY_PRESETS: raise ValueError('Unknown query')
    count = QUERY_PRESETS[resolved_query]['line_count']
    selector = rng(seed, 'task-family-binding')
    if family == 'random':
        if len(available) < count: raise ValueError('Catalog lacks distinct families for this query; choose another query, not a replacement world')
        selected = selector.sample(available, count)
    else:
        selected = [x.strip() for x in family.split(',')]
        if len(selected) != len(set(selected)) or set(selected) - set(available): raise ValueError('Requested family absent or duplicated')
        if len(selected) == 1 and count > 1:
            others = [x for x in available if x not in selected]
            if len(others) < count - 1: raise ValueError('Catalog lacks distinct families for this query')
            selected += selector.sample(others, count - 1)
    bundle = generate(seed, ','.join(selected), query=query, **options)
    bindings = []
    for line in bundle['request']['lines']:
        if line['model'] is None: continue
        candidates = sorted((g for g in groups if g['family'] == line['family_id']), key=lambda g: g['group_id'])
        group = rng(seed, 'task-model-binding/' + line['id']).choice(candidates)
        model = {'id': group['group_id'], 'name': group['name']}
        for projection in ('request', 'initial_accessible_task', 'resolved_task'):
            next(l for l in bundle[projection]['lines'] if l['id'] == line['id'])['model'] = copy.deepcopy(model)
        bindings.append({'line_id': line['id'], 'model_id': group['group_id']})
    bundle['public'], bundle['authoring']['message_segments'] = render(bundle['request'], bundle['memory_facts'], bundle['prose_seed'])
    semantic = {k: bundle[k] for k in ('request', 'memory_facts', 'resolved_task')}
    semantic['hidden_user_specifications'] = [{k: v for k, v in h.items() if k != 'reply'} for h in bundle['hidden_user_specifications']]
    bundle['semantic_sha256'] = hashlib.sha256(json.dumps(semantic, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    bundle['catalog_binding'] = {'schema_version': 'catalog-intent-binding-v1', 'catalog_sha256': catalog['catalog_sha256'],
        'models': bindings, 'method': 'uniform model within selected family; no requirement, price, stock or feasibility filtering',
        'budget_reference': 'existing family reference priors in shopping_intent; not realized offer prices'}
    return bundle
