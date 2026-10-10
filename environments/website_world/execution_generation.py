"""Fresh website generation with explicit off/full producer validation.

Old request schemas, frozen producer sources and hosts remain unchanged.
Execution policy lives in a private receipt, not sampled facts/world identity.
"""
from hashlib import sha256
from types import SimpleNamespace
from pathlib import Path
import json
import shutil

from experiments.accepted_catalog_commerce.execution import Execution, _bind
from . import generation as shared, unified_generation as unified


def generate(request, *, validation='off'):
    execution = Execution(validation=validation)
    result = unified.generate(request, world_factory=execution.generate)
    result['execution'] = execution.record()
    return result


def prepare(request, output, *, validation='off', answer_grading=None, lazy_publication=False):
    from experiments.accepted_catalog_commerce import execution as commerce_execution
    from environments.product_world import execution as package_execution
    from environments.product_world import shared_state
    from experiments.world_sampling_defaults import execution as population_execution
    from . import listed_answer_execution
    runtime = listed_answer_execution.runtime_options({'lazy_publication': lazy_publication})
    grading = listed_answer_execution.options(answer_grading)
    if grading['mode'] != 'off' and request.get('task', {}).get('kind') != 'cheapest_available':
        raise ValueError('Post-run listed grading requires an explicit cheapest_available task')
    paths = [Path(__file__).resolve(), Path(commerce_execution.__file__).resolve(),
             Path(package_execution.__file__).resolve(),
             Path(shared_state.__file__).resolve(), Path(population_execution.__file__).resolve(),
             unified.ROOT / 'scripts/generate_website_world_execution.py']
    if lazy_publication:
        paths.append(Path(listed_answer_execution.__file__).resolve())
    if answer_grading is not None:
        from experiments.answer_grading import listed_offer
        from experiments.external_agent import backend as external_backend
        from experiments.external_agent import protocol as external_protocol
        paths.extend([Path(listed_answer_execution.__file__).resolve(), Path(listed_offer.__file__).resolve(),
                      Path(external_backend.__file__).resolve(), Path(external_protocol.__file__).resolve(),
                      unified.ROOT/'scripts/trace_grades.py'])
        paths.extend(Path(external_backend.__file__).parent.glob('*.mjs'))
    paths = list(dict.fromkeys(paths))
    sources = {str(p.relative_to(unified.ROOT)): sha256(p.read_bytes()).hexdigest() for p in paths}
    execution = Execution(validation=validation)
    producer = SimpleNamespace(freeze=execution.freeze, VERSION=unified.model.VERSION)
    prepare_bound = _bind(unified.prepare, model=producer,
                          generate=lambda request: unified.generate(request, world_factory=execution.generate))
    manifest = prepare_bound(request, output)
    # Add the new policy/adapter closure explicitly: old static source discovery
    # starts from the historical entrypoint and doesn't see this additive caller.
    output = Path(output)
    record = execution.record()
    if answer_grading is not None:
        record['answer_grading'] = grading
    if lazy_publication:
        record['runtime_options'] = runtime
    for path in paths:
        name = str(path.relative_to(unified.ROOT))
        if sha256(path.read_bytes()).hexdigest() != sources[name]:
            raise RuntimeError('Execution policy source changed during generation: ' + name)
        archive = output / 'pin/source-snapshot' / name
        archive.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, archive)
    record['source_sha256'] = sources
    shared.save(output / 'execution.private.json', record)
    manifest['files']['execution.private.json'] = sha256((output / 'execution.private.json').read_bytes()).hexdigest()
    from . import generation_configs
    config_path = output / 'generation-config.private.json'
    config_record = json.loads(config_path.read_text())
    config_record['execution'] = generation_configs.execution_options({
        'validation': validation, 'answer_grading': grading, **runtime})
    config_record['config_sha256'] = generation_configs.digest({
        'request': config_record['request'], 'execution': config_record['execution']})
    config_path.write_text(json.dumps(config_record, indent=2, ensure_ascii=False) + '\n')
    manifest['files'][config_path.name] = sha256(config_path.read_bytes()).hexdigest()
    manifest['source_sha256'].update(record['source_sha256'])
    manifest['execution_policy'] = record
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n')
    return manifest
