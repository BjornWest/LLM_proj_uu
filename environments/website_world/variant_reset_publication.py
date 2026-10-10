"""Source-prepared saved-world reset recipes; no browser acceptance follows.

These source-preparation APIs do not certify a Git release, read extractor,
browser capture or the new consumer's whole-run effect authority.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil

from . import generation as shared, variant_reset_task as native
from .adapter import digest
from .generation_configs import execution_options

VERSION = 'website-variant-reset-publication-v1'
CAPTURE_CONTAINER = 'website-catalog-cart-publication-v1'
SCOPES = ('whole_run', 'observed_variant_cart_state')


def checked_scope(value):
    if type(value) is not str or value not in SCOPES:
        raise ValueError('Unknown reset scoring scope')
    return value


def recipe_marker():
    return {'recipe': CAPTURE_CONTAINER, 'variant_reset_recipe': VERSION}


def compile_packet(world, spec, *, catalog, bindings, checkout_domain,
                   runtime_options, asset_sha256, scoring_scope="whole_run"):
    from .page_option_order import options as order_options
    from .selector_action_capture import options as recorder_options
    if type(runtime_options) is not dict or not {'page_option_order', 'selector_capture'} <= set(runtime_options) or set(runtime_options) - {'page_option_order', 'selector_capture', 'review_presentation'}:
        raise ValueError('Declare only exact ordering/recorder and optional review presentation')
    task = native.make(world, spec, catalog=catalog, bindings=bindings, checkout_domain=checkout_domain)
    rid, pid = task['retailer_id'], task['page_id']
    ordering = order_options(runtime_options['page_option_order'])
    recorder = recorder_options(runtime_options['selector_capture'])
    if (ordering is None or set(ordering) != {rid} or set(ordering[rid]) != {pid}
            or ordering[rid][pid] != {'colour_key': spec['change_axis'], 'size_key': spec['preserve_axis']}
            or recorder is None or set(recorder) != {rid} or recorder[rid]['page_id'] != pid):
        raise ValueError('Reset presentation must target this exact native page and axes')
    checked_scope(scoring_scope)
    if scoring_scope != 'whole_run' and recorder[rid].get('task_actions') is not True:
        raise ValueError('Scoped reset requires actual task action capture')
    page = next(p for p in catalog['products'] if p['id'] == pid)
    axes = [a['key'] for a in page['options']]
    if axes.index(spec['change_axis']) > axes.index(spec['preserve_axis']):
        raise ValueError('Actual public catalog is not colour-before-size')
    if (type(asset_sha256) is not dict or not {'shop.js','selector-action-capture.js'} <= set(asset_sha256)
            or any(type(n) is not str or type(h) is not str or len(h)!=64 or any(c not in '0123456789abcdef' for c in h) for n,h in asset_sha256.items())):
        raise ValueError('Require full actual served-asset pins including observer')
    reference = native.reference(world, task, catalog=catalog, bindings=bindings, checkout_domain=checkout_domain)
    return {'task': task, 'reference': reference, 'catalog': deepcopy(catalog), 'bindings': deepcopy(bindings),
            'runtime_options': deepcopy(runtime_options), 'served_asset_sha256': deepcopy(asset_sha256)}


def prepare_saved(saved, output, *, spec, catalog, bindings,
                  expected_world_sha256, runtime_options, asset_sha256, prepared_cart=None, answer_grading=None,
                  scoring_scope="whole_run", user_message=None):
    """Fresh isolated recipe, literal saved world, no sampling or live repair.

    catalog/bindings must come from the saved composition's actual runtime;
    construction recomputes them and fails on any difference. No executable
    adoption follows until the exact Git consumer and capture are accepted.
    """
    from experiments.accepted_catalog_commerce.execution import Execution
    saved, output = Path(saved).resolve(), Path(output).resolve()
    world_path = saved / 'world.private.json'
    if sha256(world_path.read_bytes()).hexdigest() != expected_world_sha256:
        raise ValueError('Saved world bytes changed')
    read = lambda name: json.loads((saved / name).read_bytes())
    world, domain = read('world.private.json'), read('checkout-domain.private.json')
    packet = compile_packet(world, spec, catalog=catalog, bindings=bindings, checkout_domain=domain, runtime_options=runtime_options, asset_sha256=asset_sha256, scoring_scope=scoring_scope)
    task = packet['task']
    public_message = task['user_message'] if user_message is None else user_message
    if type(public_message) is not str or not public_message.strip():
        raise ValueError('Require a nonempty public request')
    options = execution_options({'lazy_publication': True,
        'answer_grading': answer_grading or {'mode': 'off'}})
    if options['answer_grading']['mode'] != 'subscription-post-run':
        raise ValueError('Reset tasks need automatic answer extraction before dispatch')
    if prepared_cart is not None and type(prepared_cart) is not list:
        raise ValueError('Prepared cart must be explicit rows')
    source_names = ['world.private.json', 'presentation.private.json', 'compositions.private.json',
                    'surrounding.private.json', 'basket-plan.private.json', 'checkout-domain.private.json']
    if (saved / 'delivery-plan.private.json').exists(): source_names.append('delivery-plan.private.json')
    original = {str(saved / name): sha256((saved / name).read_bytes()).hexdigest() for name in source_names}
    sources = shared.source_files()
    root = shared.ROOT
    policy = root / 'environments/product_world/data/product_feature_policies/catalogue_v2/manifest.json'
    dependencies = [policy, *[policy.parent / row['file'] for row in
                    json.loads(policy.read_bytes())['concepts'].values()],
                    root / 'intent_browser/assets/chat/chat.html',
                    root / 'intent_browser/assets/chat/LICENSE.browsergym.txt']
    dependencies += list(Path(__file__).parent.glob('*.py')) + list(Path(__file__).parent.glob('*.js'))
    from experiments.answer_grading import task_answer, listed_offer, extraction
    from scripts import trace_grades
    dependencies += [Path(m.__file__) for m in (task_answer, listed_offer, extraction, trace_grades)]
    dependencies += [root / 'experiments/external_agent/subscription_quota.py',
                     root / 'scripts/product_width_watch.py']
    for path in dependencies: sources[str(path.relative_to(root))] = sha256(path.read_bytes()).hexdigest()
    output.mkdir(parents=True, exist_ok=False)
    producer = Execution(validation='off').freeze(world, output / 'pin')
    shutil.copyfile(world_path, output / 'pin/world.private.json')
    producer['files']['world.private.json'] = expected_world_sha256
    (output / 'pin/manifest.json').write_text(json.dumps(producer, indent=2) + '\n')
    sources.update(producer['source_sha256'])
    for name, expected in sources.items():
        path = root / name
        if sha256(path.read_bytes()).hexdigest() != expected: raise ValueError('Source changed: ' + name)
        target = output / 'pin/source-snapshot' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    records = {('presentation.json' if name == 'presentation.private.json' else name): read(name)
               for name in source_names if name != 'world.private.json'}
    setup = {'start': {'kind': 'product', 'offer_id': task['start']['offer_id']},
             'selected_offer_id': task['setup']['selected_offer_id'],
             'prepared_cart': deepcopy(prepared_cart or [])}
    records.update({'variant-reset-runtime-options.private.json': packet['runtime_options'],
        'variant-reset-scoring-scope.private.json': scoring_scope,
        'variant-reset-assets.private.json': packet['served_asset_sha256'],
        'variant-reset-task.private.json': task,
        'variant-reset-reference.private.json': packet['reference'],
        'variant-reset-catalog.private.json': packet['catalog'],
        'variant-reset-bindings.private.json': packet['bindings'],
        'variant-reset-setup.private.json': setup, 'execution.private.json': options,
        'episode.json': {'task_id': task['task_id'], 'readable_origins': True,
            'start': task['start'], 'manual_task': {'user_message': public_message, 'memories': task['memories']}},
        'request.json': {'schema': VERSION, 'spec': deepcopy(spec), 'setup': setup,
            'original_inputs': original, 'world_draws': 0, 'scoring_scope': scoring_scope,
            'public_request': {'user_message': public_message, 'memories': task['memories']}}})
    for name, value in records.items(): shared.save(output / name, value)
    for name in source_names:
        target = output / 'original-inputs' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(saved / name, target)
    for name, expected in original.items():
        if sha256(Path(name).read_bytes()).hexdigest() != expected: raise ValueError('Original changed: ' + name)
    files = {str(p.relative_to(output)): sha256(p.read_bytes()).hexdigest()
             for p in output.rglob('*') if p.is_file() and not p.is_relative_to(output / 'pin/source-snapshot')}
    manifest = {'schema': 'website-world-generation-v2', **recipe_marker(),
        'world_id': world['world_id'], 'source_sha256': sources, 'files': files,
        'automatic_grader_supported': True, 'source_world_sha256': expected_world_sha256,
        'execution_policy': options, 'world_draws': 0,
        'effect_authority': ('unknown_broader_effects' if scoring_scope != 'whole_run'
                             else 'exact_new_consumer_union_acceptance_required'),
        'config_sha256': digest(records['request.json'])}
    shared.save(output / 'manifest.json', manifest)
    return manifest
