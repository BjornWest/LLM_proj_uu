"""Additive exact-SKU stock recipe; existing unified recipes are unchanged.

Targets are selected from manufactured models and variants before consulting
comparison coverage, prices or retailer stock. A failed binding is explicit and
never causes a new draw or selection of a different, available target.
Native grading/extraction adoption requires Product's separate callable release.
"""
from copy import deepcopy
from math import isfinite

from . import comparison_sku_task as task_api

VERSION = 'website-comparison-stock-generation-v1'
REQUEST_SCHEMA = 'website-world-generation-v2'
KIND = 'comparison_cheapest_exact_sku_stock'


def target_options(value):
    if type(value) is not dict:
        raise ValueError('Declare a manufactured target')
    if set(value) == {'sku_id'}:
        if type(value['sku_id']) is not str or not value['sku_id']:
            raise ValueError('Explicit SKU must be nonempty')
        return deepcopy(value)
    if set(value) - {'concept_id', 'selectors'} or 'concept_id' not in value:
        raise ValueError('Use an explicit SKU or a concept with optional selectors')
    if type(value['concept_id']) is not str or not value['concept_id']:
        raise ValueError('Concept must be nonempty')
    selectors = value.get('selectors', {})
    if type(selectors) is not dict or any(
            type(k) is not str or not k or type(v) not in (str, int, float, bool)
            or (type(v) is float and not isfinite(v)) for k, v in selectors.items()):
        raise ValueError('Selectors must be finite scalar values')
    return {'concept_id': value['concept_id'], 'selectors': deepcopy(selectors)}


def bind_target(world, target, *, seed):
    """Stable model-first/SKU-second draw, independent of commerce and coverage."""
    target = target_options(target)
    candidates = []
    for product in world['products']:
        public = product['public']
        if 'concept_id' in target and public['concept_id'] != target['concept_id']:
            continue
        skus = [sku for sku in public['skus'] if (
            sku['sku_id'] == target['sku_id'] if 'sku_id' in target else all(
                key in product['variant_fields'] and key in sku
                and type(sku[key]) is type(value) and sku[key] == value
                for key, value in target['selectors'].items()))]
        if skus:
            candidates.append((product, skus))
    ids = [s['sku_id'] for _, skus in candidates for s in skus]
    pids = [p['public']['product_id'] for p, _ in candidates]
    if len(set(ids)) != len(ids) or len(set(pids)) != len(pids):
        return {'status': 'ambiguous', 'reason': 'duplicate_manufactured_identity'}
    if not candidates:
        return {'status': 'empty', 'reason': 'no_matching_manufactured_sku'}
    product, skus = min(candidates, key=lambda pair: (
        task_api.digest([VERSION, seed, 'model', pair[0]['public']['product_id']]),
        pair[0]['public']['product_id']))
    sku = min(skus, key=lambda s: (
        task_api.digest([VERSION, seed, 'variant', s['sku_id']]), s['sku_id']))
    if sum(all(s[key] == sku[key] for key in product['variant_fields'])
           for s in product['public']['skus']) != 1:
        return {'status': 'ambiguous', 'reason': 'duplicate_variant_coordinates'}
    return {'status': 'bound', 'product_id': product['public']['product_id'],
            'sku_id': sku['sku_id'], 'selection': 'manufactured-model-then-variant',
            'target': target}


def compile_request(request):
    from . import unified_generation as unified
    if type(request) is not dict or request.get('schema') != REQUEST_SCHEMA:
        raise ValueError('Invalid comparison-stock recipe schema')
    selection = request.get('task')
    if type(selection) is not dict or set(selection) != {'kind', 'comparison_site_id', 'target'} or selection['kind'] != KIND:
        raise ValueError('Declare comparison scope and manufactured target')
    target = target_options(selection['target'])
    episode = request.get('episode', {})
    if type(episode) is not dict or set(episode) - {'start', 'readable_origins'}:
        raise ValueError('Unknown episode option')
    start = {'kind': 'comparison_home', 'comparison_site_id': selection['comparison_site_id']}
    if episode.get('start', start) != start:
        raise ValueError('This recipe starts at its named comparison home')
    proxy = deepcopy(request)
    proxy['schema'] = unified.VERSION
    proxy['task'] = {'user_message': 'Inspect the generated world.', 'memories': []}
    proxy['episode'] = {**episode, 'start': {'kind': 'directory'}}
    # Match existing task-concentration defaults, without changing explicit controls.
    if 'concept_id' in target:
        world = proxy.setdefault('world', {})
        if 'tasks' not in world:
            world['tasks'] = [target['concept_id']]
    config = unified.compile_request(proxy)
    surrounding = config['surrounding_options']
    if not surrounding['enabled'] or selection['comparison_site_id'] not in {
            f'comparison-{i:02d}' for i in range(surrounding['comparison_count'])}:
        raise ValueError('Named comparison site must be enabled')
    return {'request': deepcopy(request), 'proxy_request': proxy,
            'resolved_base': config, 'target': target, 'start': start}


def generate(request, *, world_factory=None):
    from . import unified_generation as unified
    config = compile_request(request)
    result = unified.generate(config['proxy_request'], world_factory=world_factory)
    binding = bind_target(result['world'], config['target'], seed=request['seed'])
    result['comparison_stock_binding'] = binding
    result['comparison_stock_request'] = deepcopy(request)
    result['resolved_configuration'].update(request=deepcopy(request),
        proxy_episode=deepcopy(result['resolved_configuration']['episode']),
        episode={**result['resolved_configuration']['episode'], 'start': deepcopy(config['start'])},
        task=deepcopy(request['task']),
        comparison_stock_selection={'target': deepcopy(config['target']), 'start': deepcopy(config['start'])})
    result['audit']['proxy_request_sha256'] = result['audit']['request_sha256']
    result['audit']['request_sha256'] = unified.shared.digest(request)
    result['episode']['start'] = config['start']
    # A failed binding cannot accidentally run the proxy's browsing task.
    result['episode'].pop('manual_task', None)
    if binding['status'] != 'bound':
        return result
    site = next(s for s in result['surrounding']['sites']
                if s['site_id'] == config['start']['comparison_site_id'])
    if binding['product_id'] not in site['product_ids']:
        binding.update(status='unpublished', reason='manufactured_target_absent_from_comparison')
        return result
    if not any(row['product_id'] == binding['product_id'] for row in site['listings']):
        binding.update(status='unpublished', reason='no_advertised_model_listing')
        return result
    product = next(p for p in result['world']['products']
                   if p['public']['product_id'] == binding['product_id'])
    if sum(p['public']['name'] == product['public']['name']
           for p in result['world']['products']) != 1:
        binding.update(status='ambiguous', reason='displayed_model_name')
        return result
    task = task_api.make(result['world'], result['surrounding'],
                         comparison_site_id=site['site_id'], sku_id=binding['sku_id'])
    result['comparison_stock_task'] = task
    result['comparison_stock_reference'] = task_api.reference(
        result['world'], result['surrounding'], task)
    result['episode'].update(task_id=task['task_id'], manual_task={
        'user_message': task['user_message'], 'memories': task['memories']})
    return result


def prepare(request, output, *, validation='off', answer_grading=None, lazy_publication=True):
    """Freeze through existing execution bodies with private dependency bindings."""
    from hashlib import sha256
    import json
    from pathlib import Path
    import shutil
    from types import SimpleNamespace
    from experiments.accepted_catalog_commerce.execution import _bind
    from . import execution_generation, unified_generation as unified, generation_configs
    from . import comparison_stock_execution  # include released consumer/grader closure
    config = compile_request(request)
    options = generation_configs.execution_options({'validation': validation,
        'answer_grading': answer_grading, 'lazy_publication': lazy_publication})
    # The old preparer retains its native freeze/config/source checks. Only this
    # call's generator binding accepts the new task; no module globals are patched.
    shim = SimpleNamespace(**vars(unified))
    sampled = []
    def generate_once(request, *, world_factory=None):
        result = generate(request, world_factory=world_factory)
        sampled.append(result)
        return result
    shim.generate = generate_once
    bound = _bind(execution_generation.prepare, unified=shim)
    additional = _bind(unified.shared.source_files, __file__=__file__)()
    additional.update(unified.shared.source_files())
    from scripts import trace_grades, product_width_watch
    for module in (trace_grades, product_width_watch):
        path = Path(module.__file__).resolve()
        additional[str(path.relative_to(unified.ROOT))] = sha256(path.read_bytes()).hexdigest()
    for path in (unified.ROOT/'experiments/external_agent').glob('*.mjs'):
        additional[str(path.relative_to(unified.ROOT))] = sha256(path.read_bytes()).hexdigest()
    manifest = bound(request, output, validation=validation, lazy_publication=lazy_publication)
    output = Path(output).resolve()
    result = sampled[0]
    binding = result['comparison_stock_binding']
    task = result.get('comparison_stock_task')
    if task is not None:
        reference = result['comparison_stock_reference']
        unified.shared.save(output/'comparison-stock-task.private.json', task)
        unified.shared.save(output/'comparison-stock-reference.private.json', reference)
    unified.shared.save(output/'comparison-stock-binding.private.json', binding)
    record = json.loads((output/'execution.private.json').read_text())
    record['answer_grading'] = options['answer_grading']
    record['source_sha256'].update(additional)
    (output/'execution.private.json').write_text(json.dumps(record, indent=2, ensure_ascii=False)+'\n')
    capture = json.loads((output/'generation-config.private.json').read_text())
    capture.update(execution=options, task_source='structured_template',
                   recipe=VERSION, config_sha256=generation_configs.digest({'request': request, 'execution': options}))
    (output/'generation-config.private.json').write_text(json.dumps(capture, indent=2, ensure_ascii=False)+'\n')
    for name, expected in additional.items():
        source = unified.ROOT/name
        if sha256(source.read_bytes()).hexdigest() != expected:
            raise RuntimeError('Source changed during comparison-stock freeze: '+name)
        target = output/'pin/source-snapshot'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    manifest['source_sha256'].update(additional)
    manifest.update(recipe=VERSION, task_kind=KIND, automatic_grader_supported=task is not None,
                    binding_status=binding['status'], execution_policy=record)
    for name in ('execution.private.json','generation-config.private.json',
                 'comparison-stock-binding.private.json','comparison-stock-task.private.json',
                 'comparison-stock-reference.private.json'):
        path = output/name
        if path.exists():
            manifest['files'][name] = sha256(path.read_bytes()).hexdigest()
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+'\n')
    return manifest


def bind_episode(runtime, result, profile, *, files, attachments=None):
    """Manual episode consumer until Product's grader/extractor is released."""
    if result['comparison_stock_binding']['status'] != 'bound':
        raise ValueError('Cannot launch an empty, ambiguous or unpublished target')
    task = result['comparison_stock_task']
    if task['world_id'] != runtime.world['world_id']:
        raise ValueError('Episode/runtime world mismatch')
    if task_api.reference(runtime.world, result['surrounding'], task) != result['comparison_stock_reference']:
        raise ValueError('Episode reference/source binding changed')
    if result['episode']['start'] != {'kind': 'comparison_home',
                                     'comparison_site_id': task['comparison_site_id']}:
        raise ValueError('Comparison-home start changed')
    public = task_api.bind_public(runtime, task)
    return task_api.episode_task(runtime, public, profile, files=files,
                                 attachments=attachments)
