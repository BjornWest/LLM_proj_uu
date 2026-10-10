"""Additive saved-input link recipes; no sampler or shared entrypoint changes."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil

from . import generation as shared, variant_link_task as native
from . import variant_link_capability as capability
from .generation_configs import execution_options

VERSION = 'website-variant-link-publication-v1'


def public_request(task, episode):
    """Authenticate ordinary public prose while retaining native identity/start."""
    manual = episode.get('manual_task')
    if (type(manual) is not dict or set(manual) != {'user_message', 'memories'}
            or manual['memories'] != task['memories']
            or type(manual['user_message']) is not str or not manual['user_message'].strip()
            or episode != {'task_id': task['task_id'], 'readable_origins': True,
                           'start': task['start'], 'manual_task': manual}):
        raise ValueError('Frozen public request/memories/product start changed')
    return manual['user_message']


def compile_packet(*, world, spec, catalog, bindings, asset_sha256, acceptance):
    """Gate an actual privately accepted recipient packet before task authoring."""
    cap = capability.validate(acceptance, world=world, catalog=catalog,
                              bindings=bindings, asset_sha256=asset_sha256)
    task = native.make(world, spec, catalog=catalog, bindings=bindings, navigation_capability=cap)
    reference = native.reference(world, task, catalog=catalog, bindings=bindings, navigation_capability=cap)
    return {'task': task, 'reference': reference, 'navigation_capability': cap,
            'acceptance': deepcopy(acceptance), 'catalog': deepcopy(catalog),
            'bindings': deepcopy(bindings), 'served_asset_sha256': deepcopy(asset_sha256)}


def prepare_saved(saved, output, *, spec, expected_world_sha256, acceptance,
                  answer_grading, runtime_options=None, user_message=None):
    """Freeze a new container from accepted saved semantics, drawing no worlds.

    Preparation requires actual browser capability acceptance. Merely passing
    candidate data cannot create a runnable task. Execute this writer only in a
    coordinated bounded freeze window; source preparation does not call it.
    """
    saved, output = Path(saved).resolve(), Path(output).resolve()
    world_path = saved / 'world.private.json'
    if sha256(world_path.read_bytes()).hexdigest() != expected_world_sha256:
        raise ValueError('Original saved world changed')
    _, accepted = capability.read_pin(acceptance)
    evidence_path, evidence = capability.check_manifest(accepted['evidence_manifest'])
    read = lambda name: json.loads((evidence_path.parent / name).read_bytes())
    world = json.loads(world_path.read_bytes())
    packet = compile_packet(world=world, spec=spec, catalog=read('catalog.private.json'),
        bindings=read('bindings.private.json'), asset_sha256=read('served-assets.private.json'), acceptance=acceptance)
    public_message = packet['task']['user_message'] if user_message is None else user_message
    episode = {'task_id': packet['task']['task_id'], 'readable_origins': True,
        'start': deepcopy(packet['task']['start']),
        'manual_task': {'user_message': public_message, 'memories': deepcopy(packet['task']['memories'])}}
    public_request(packet['task'], episode)
    options = execution_options({'lazy_publication': True, 'answer_grading': answer_grading})
    if options['answer_grading']['mode'] == 'off':
        raise ValueError('Link episode publication requires an automatic answer grader')
    runtime_options = {} if runtime_options is None else deepcopy(runtime_options)
    if set(runtime_options) - {'review_presentation', 'page_option_order'}:
        raise ValueError('Only released review/option-order authoring overrides are supported')
    sources = shared.source_files()
    source_root = shared.ROOT
    # Explicit dependency closure: all reviewed policy members and chat assets.
    policy = source_root / 'environments/product_world/data/product_feature_policies/catalogue_v2/manifest.json'
    document = json.loads(policy.read_bytes())
    dependencies = [policy, *[policy.parent / row['file'] for row in document['concepts'].values()],
                    source_root / 'intent_browser/assets/chat/chat.html',
                    source_root / 'intent_browser/assets/chat/LICENSE.browsergym.txt']
    dependencies += list(Path(__file__).parent.glob('*.py'))
    dependencies += list(Path(__file__).parent.glob('*.js'))
    from scripts import trace_grades, product_width_watch
    from experiments.answer_grading import task_answer, listed_offer, extraction
    from experiments.external_agent import subscription_quota
    for module in (trace_grades, product_width_watch, subscription_quota,
                   task_answer, listed_offer, extraction):
        dependencies.append(Path(module.__file__))
    for path in dependencies:
        sources[str(path.relative_to(source_root))] = sha256(path.read_bytes()).hexdigest()
    from experiments.accepted_catalog_commerce.execution import Execution
    output.mkdir(parents=True, exist_ok=False)
    producer = Execution(validation='off').freeze(world, output / 'pin')
    shutil.copyfile(world_path, output / 'pin/world.private.json')
    producer['files']['world.private.json'] = expected_world_sha256
    # Execution.freeze already created this new container's producer manifest.
    # Only its literal-world hash changes; exclusive save is for new files.
    (output / 'pin/manifest.json').write_text(json.dumps(producer, indent=2) + '\n')
    sources.update(producer['source_sha256'])
    for path in dependencies:
        sources[str(path.relative_to(source_root))] = sha256(path.read_bytes()).hexdigest()
    for name, expected in sources.items():
        source = source_root / name
        if sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError('Consumer source changed during freeze: ' + name)
        target = output / 'pin/source-snapshot' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    names = ['presentation.private.json', 'compositions.private.json', 'surrounding.private.json',
             'basket-plan.private.json', 'checkout-domain.private.json']
    if (saved / 'delivery-plan.private.json').exists(): names.append('delivery-plan.private.json')
    records = {('presentation.json' if name == 'presentation.private.json' else name):
               json.loads((saved / name).read_bytes()) for name in names}
    records.update({'variant-link-task.private.json': packet['task'],
                    'variant-link-reference.private.json': packet['reference'],
                    'variant-link-capability.private.json': packet['navigation_capability'],
                    'variant-link-catalog.private.json': packet['catalog'],
                    'variant-link-bindings.private.json': packet['bindings'],
                    'variant-link-assets.private.json': packet['served_asset_sha256'],
                    'variant-link-acceptance.private.json': packet['acceptance'],
                    'variant-link-runtime-options.private.json': runtime_options,
                    'execution.private.json': options,
                    'episode.json': episode,
                    'request.json': {'schema': VERSION, 'operation': 'saved_fixture_publication',
                        'world_sha256': expected_world_sha256, 'spec': deepcopy(spec), 'acceptance': deepcopy(acceptance),
                        'source_directory': str(saved), 'world_draws': 0}})
    for name, value in records.items(): shared.save(output / name, value)
    # Copy the complete accepted witness packet into the new recipe too.
    archive = output / 'accepted-evidence'
    archive.mkdir()
    for name in evidence['files']:
        target = archive / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(evidence_path.parent / name, target)
    shutil.copyfile(evidence_path, archive / 'manifest.json')
    artifacts = {str(path.relative_to(output)): sha256(path.read_bytes()).hexdigest()
                 for path in output.rglob('*') if path.is_file() and not path.is_relative_to(output / 'pin/source-snapshot')}
    manifest = {'schema': 'website-world-generation-v2', 'recipe': VERSION,
                'world_id': world['world_id'], 'source_sha256': sources, 'files': artifacts,
                'automatic_grader_supported': True, 'world_draws': 0,
                'capability_acceptance': deepcopy(acceptance), 'runtime_options': runtime_options}
    shared.save(output / 'manifest.json', manifest)
    return manifest
