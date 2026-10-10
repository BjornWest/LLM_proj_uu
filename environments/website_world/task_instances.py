"""Prepare and run saved-world task permutations from one JSON instance format.

No model, browser or world sampling happens during preparation. Native task
constructors and references are reused; public English is independently editable.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from . import saved_answer_publication as publication
from . import task_instance_adapters as adapters

VERSION = 'website-task-instance-v1'
PREPARED = 'website-prepared-task-instance-v1'


def _bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode()


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(payload)


def _hash(payload):
    return sha256(payload).hexdigest()


def _digest(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def load(path):
    """Reject duplicate JSON fields instead of silently changing the instance."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate task-instance key: ' + key)
            result[key] = value
        return result
    def nonfinite(value):
        raise ValueError('Nonfinite task-instance number: ' + value)
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique, parse_constant=nonfinite)


def validate(instance):
    required = {'schema', 'family', 'source', 'parameters', 'user_message', 'start'}
    if type(instance) is not dict or required - instance.keys() or instance.keys() - required - {'requirements', 'memories'}:
        raise ValueError('Use the versioned task-instance fields')
    if (instance['schema'] != VERSION or type(instance['family']) is not str
            or instance['family'] not in adapters.ADAPTERS):
        raise ValueError('Unsupported task-instance schema or family')
    source = instance['source']
    if (type(source) is not dict or set(source) != {'recipe', 'manifest_sha256'}
            or type(source['recipe']) is not str or not source['recipe'].strip()
            or not _digest(source['manifest_sha256'])):
        raise ValueError('Declare a saved recipe and its exact manifest SHA256')
    if type(instance['parameters']) is not dict or type(instance['start']) is not dict:
        raise ValueError('Parameters and start must be objects')
    if type(instance['user_message']) is not str or not instance['user_message'].strip():
        raise ValueError('Supply an authored nonempty public request')
    if 'memories' in instance and type(instance['memories']) is not list:
        raise ValueError('Memories must be the native public memory list')
    requirements = instance.get('requirements', {})
    if type(requirements) is not dict or set(requirements) - {'status', 'minimum_population'}:
        raise ValueError('Use status and minimum_population feasibility requirements')
    if 'status' in requirements and (type(requirements['status']) is not str
            or requirements['status'] not in {'match', 'no_match', 'summary', 'undefined', 'ready'}):
        raise ValueError('Unsupported required reference status')
    minimum = requirements.get('minimum_population', 0)
    if type(minimum) is not int or not 0 <= minimum <= 100000:
        raise ValueError('minimum_population must be a finite nonnegative integer')
    _bytes(instance)  # Reject non-JSON objects and nonfinite values at entry.
    return deepcopy(instance)


def _metrics(family, reference):
    if family == 'catalog_statistics':
        return {'status': 'summary' if reference['statistic_defined'] else 'undefined',
                'population': reference['population_count']}
    if family == 'catalog_review':
        return {'status': reference['status'], 'population': (reference['written_review_count']
            if 'written_review_count' in reference else reference['summary']['rating_count'])}
    if family == 'catalog_shortlist':
        return {'status': reference['status'], 'population': reference['population_count']}
    return {'status': reference['status'], 'population': len(reference['candidates'])}


def _recipe_matches(adapter, manifest):
    hook = getattr(adapter, 'recipe_matches', None)
    return hook(manifest) if hook is not None else manifest.get('recipe') == adapter.recipe


def _manifest_updates(adapter, prepared):
    hook = getattr(adapter, 'manifest_updates', None)
    updates = {} if hook is None else hook(prepared)
    if type(updates) is not dict or set(updates) & {
            'recipe', 'files', 'source_sha256', 'task_instance', 'original_recipe',
            'automatic_grading_attached', 'automatic_grader_supported',
            'task_kind', 'native_match_status', 'world_draws', 'model_runs', 'effects'}:
        raise ValueError('Adapter manifest flags cannot replace core bindings')
    _bytes(updates)
    return updates


def inspect(instance):
    """Construct the native instance and check feasibility without writing files.

    Unsuitable saved populations raise before publication. There is no redraw,
    conditioning, reference repair or automatic reduction of requirements.
    """
    instance = validate(instance)
    snapshot = publication.read_recipe(instance['source']['recipe'],
        expected_manifest_sha256=instance['source']['manifest_sha256'])
    _, manifest, buffers = snapshot
    adapter = adapters.ADAPTERS[instance['family']]
    if not _recipe_matches(adapter, manifest):
        raise ValueError('Source recipe is not the requested native family')
    read = lambda name: json.loads(buffers[name])
    world, surrounding = read('pin/world.private.json'), read('surrounding.private.json')
    task, reference, inventory = adapter.construct(world, surrounding, instance['parameters'], snapshot=snapshot)
    if instance.get('memories', task['memories']) != task['memories']:
        raise ValueError('This family cannot override native memory semantics')
    records, start = adapter.records(world, surrounding, task, reference, inventory,
        read('episode.json'), instance['start'], instance['user_message'],
        snapshot=snapshot, instance=instance)
    metrics_hook = getattr(adapter, 'metrics', None)
    metrics = metrics_hook(reference) if metrics_hook is not None else _metrics(instance['family'], reference)
    requirements = instance.get('requirements', {})
    if ('status' in requirements and metrics['status'] != requirements['status']
            or metrics['population'] < requirements.get('minimum_population', 0)):
        raise ValueError('Saved world does not satisfy task-instance feasibility requirements: ' + str(metrics))
    setup = {'schema': publication.VERSION, 'task_id': task['task_id'],
             'user_message': instance['user_message'], 'memories': deepcopy(task['memories']),
             'start': deepcopy(start)}
    return {'instance': instance, 'snapshot': snapshot, 'adapter': adapter, 'task': task,
            'reference': reference, 'records': records, 'setup': setup, 'metrics': metrics}


def prepare(instance, output):
    """One fresh derivative recipe, using the existing source freezer once.

    A small native-input container records replaced bytes and the exact parent
    manifest. The shared publisher then freezes current source dependencies;
    the world, surrounding pages, cart policies and corpus remain byte-identical.
    """
    prepared = inspect(instance)
    instance, adapter = prepared['instance'], prepared['adapter']
    saved, parent, buffers = prepared['snapshot']
    output = Path(output).resolve()
    if output == saved or output.is_relative_to(saved) or saved.is_relative_to(output):
        raise ValueError('Use a fresh output separate from the saved recipe')
    output.mkdir(parents=True, exist_ok=False)
    stage = output/'native-input'
    stage.mkdir()
    changed = {name: _bytes(value) for name, value in prepared['records'].items()}
    changed['task-instance.private.json'] = _bytes(instance)
    changed['instance-parent-manifest.private.json'] = (saved/'manifest.json').read_bytes()
    history = stage/'instance-history'/instance['source']['manifest_sha256']
    # The public setup is regenerated, not copied and then overwritten.
    omitted = {'saved-answer-setup.private.json'}
    for name, payload in buffers.items():
        if name in changed or name in omitted:
            _write(history/name, payload)
        if name not in omitted:
            _write(stage/name, changed.get(name, payload))
    for name, payload in changed.items():
        if name not in buffers:
            _write(stage/name, payload)
    native_manifest = {**deepcopy(parent), 'task_kind': prepared['task']['kind'],
        'native_match_status': prepared['metrics']['status'], 'automatic_grading_attached': False,
        'task_instance': {'schema': VERSION, 'family': instance['family'],
            'parent_recipe': str(saved), 'parent_manifest_sha256': instance['source']['manifest_sha256']},
        'files': {str(p.relative_to(stage)): publication.file_hash(p)
                  for p in stage.rglob('*') if p.is_file()}}
    if adapter.stem == 'catalog-review':
        # target_setup above independently establishes the direct review start.
        # Ordinary published review inputs need not already carry this extension.
        native_manifest['saved_review_recipe'] = 'website-saved-review-publication-v1'
    native_manifest.update(_manifest_updates(adapter, prepared))
    _write(stage/'manifest.json', _bytes(native_manifest))
    stage_hash = publication.file_hash(stage/'manifest.json')
    execution_hook = getattr(adapter, 'execution_overrides', None)
    execution_overrides = None if execution_hook is None else execution_hook(prepared)
    manifest = publication.prepare_saved(
        publication.read_recipe(stage, expected_manifest_sha256=stage_hash), output/'recipe',
        expected_manifest_sha256=stage_hash, setup=prepared['setup'],
        task_filename=adapter.task_file, adapter_file=__file__,
        dependency_records=(prepared['reference'], prepared['records'][adapter.inventory_file]),
        execution_overrides=execution_overrides)
    # Detect concurrent mutation of the original recipe, not just the derivative.
    publication.read_recipe(saved, expected_manifest_sha256=instance['source']['manifest_sha256'])
    recipe = output/'recipe'
    for name, payload in buffers.items():
        if name in changed or name in omitted or name == 'execution.private.json' or name.startswith('pin/'):
            continue
        if (recipe/name).read_bytes() != payload:
            raise ValueError('Unchanged saved artifact was not preserved: ' + name)
    if (recipe/'pin/world.private.json').read_bytes() != buffers['pin/world.private.json']:
        raise ValueError('Saved world bytes changed')
    receipt = {'schema': PREPARED, 'family': instance['family'], 'task_id': prepared['task']['task_id'],
        'recipe': 'recipe', 'manifest_sha256': publication.file_hash(recipe/'manifest.json'),
        'instance_sha256': publication.file_hash(recipe/'task-instance.private.json'),
        'world_sha256': _hash(buffers['pin/world.private.json']), 'metrics': prepared['metrics'],
        'world_draws': 0, 'model_runs': 0, 'automatic_grader_supported': manifest['automatic_grader_supported'],
        'runtime_acceptance': 'pending', 'effects': 'unknown'}
    _write(output/'prepared-instance.json', _bytes(receipt))
    return receipt


def run(output, run_directory, **options):
    """Dispatch the existing family runner, with its mandatory automatic grader."""
    output = Path(output).resolve()
    receipt = load(output/'prepared-instance.json')
    if receipt.get('schema') != PREPARED or receipt.get('recipe') != 'recipe':
        raise ValueError('Not a prepared task instance')
    recipe = output/'recipe'
    _, manifest, buffers = publication.read_recipe(recipe,
        expected_manifest_sha256=receipt['manifest_sha256'])
    if _hash(buffers['task-instance.private.json']) != receipt['instance_sha256']:
        raise ValueError('Prepared task-instance binding changed')
    instance = validate(json.loads(buffers['task-instance.private.json']))
    adapter = adapters.ADAPTERS[instance['family']]
    task = json.loads(buffers[adapter.task_file])
    if (instance['family'] != receipt['family'] or not _recipe_matches(adapter, manifest)
            or task['task_id'] != receipt['task_id']
            or _hash(buffers['pin/world.private.json']) != receipt['world_sha256']):
        raise ValueError('Prepared family/task/world binding changed')
    return adapter.run(recipe, run_directory, **options)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('instance', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    instance = load(args.instance)
    # Relative recipe paths are relative to the config file, not the shell cwd.
    source = instance.get('source', {}) if type(instance) is dict else {}
    if type(source) is dict and type(source.get('recipe')) is str:
        source['recipe'] = str((args.instance.resolve().parent/source['recipe']).resolve())
    if args.output:
        result = prepare(instance, args.output)
    else:
        checked = inspect(instance)
        result = {'task_id': checked['task']['task_id'], 'family': instance['family'],
                  'metrics': checked['metrics'], 'world_draws': 0}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
