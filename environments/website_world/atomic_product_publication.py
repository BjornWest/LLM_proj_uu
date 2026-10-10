"""Additive saved-world product tasks; publication needs a bounded window.

These source-preparation APIs do not certify a Git release, read extractor,
browser capture or the new consumer's whole-run effect authority.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from . import generation as shared, atomic_product_task as native
from .adapter import digest
from .generation_configs import execution_options

VERSION = 'website-atomic-product-publication-v1'
CAPTURE_CONTAINER = 'website-catalog-cart-publication-v1'
SCOPES = ('whole_run', 'observed_atomic_state')


def checked_scope(value):
    if type(value) is not str or value not in SCOPES:
        raise ValueError('Unknown atomic scoring scope')
    return value


def recipe_scope(output, manifest):
    """Authenticate every opt-in sidecar, including absence in old recipes."""
    output = Path(output)
    names = ('atomic-product-scoring-scope.private.json',
             'atomic-product-runtime-options.private.json', 'atomic-product-assets.private.json')
    records = {}
    files = manifest.get('files', {})
    for name in names:
        path = output/name
        if path.exists():
            payload = path.read_bytes()
            if files.get(name) != sha256(payload).hexdigest():
                raise ValueError('Atomic option sidecar is not manifest-bound: '+name)
            records[name] = json.loads(payload)
        elif name in files:
            raise ValueError('Manifest-bound atomic option sidecar is missing: '+name)
    scope = checked_scope(records.get(names[0], 'whole_run'))
    if scope == 'whole_run':
        if set(records) - {names[0]}:
            raise ValueError('Whole-run recipe cannot include scoped recorder sidecars')
    elif set(records) != set(names):
        raise ValueError('Scoped atomic recipe requires all three bound option sidecars')
    return scope


def recipe_marker():
    """Existing read-only capture container plus a distinct task extension.

    This marker does not approve the consumer's new source union or effects.
    The unchanged authority validates that union independently at startup/seal.
    """
    return {'recipe': CAPTURE_CONTAINER, 'atomic_product_recipe': VERSION}


def compile_packet(world, spec, *, catalog, bindings, checkout_domain,
                   scoring_scope="whole_run", runtime_options=None, asset_sha256=None):
    task = native.make(world, spec, catalog=catalog, bindings=bindings,
                       checkout_domain=checkout_domain)
    reference = native.reference(world, task, catalog=catalog, bindings=bindings,
                                 checkout_domain=checkout_domain)
    checked_scope(scoring_scope)
    if scoring_scope != 'whole_run':
        from .selector_action_capture import options as recorder_options
        if type(runtime_options) is not dict or set(runtime_options) != {'selector_capture'}:
            raise ValueError('Scoped atomic task requires its exact selector/task recorder')
        recorder = recorder_options(runtime_options['selector_capture'])
        rid, pid = task['retailer_id'], task['page_id']
        if (recorder is None or set(recorder) != {rid} or recorder[rid]['page_id'] != pid
                or recorder[rid].get('task_actions') is not True):
            raise ValueError('Scoped atomic recorder must target the exact native page')
        if (type(asset_sha256) is not dict or not {'shop.js','selector-action-capture.js'} <= set(asset_sha256)
                or any(type(n) is not str or type(h) is not str or len(h) != 64
                       or any(c not in '0123456789abcdef' for c in h) for n,h in asset_sha256.items())):
            raise ValueError('Pin actual scoped served assets')
    elif runtime_options is not None or asset_sha256 is not None:
        raise ValueError('Legacy whole-run atomic task has no scoped recorder')
    return {'task': task, 'reference': reference, 'catalog': deepcopy(catalog),
            'bindings': deepcopy(bindings)}


def prepare_saved(saved, output, *, spec, catalog, bindings,
                  expected_world_sha256, prepared_cart=None, answer_grading=None,
                  scoring_scope="whole_run", runtime_options=None, asset_sha256=None, user_message=None,
                  product_details_open=None, product_details_heading=None):
    """Fresh isolated recipe, literal saved world, no sampling or live repair.

    catalog/bindings must come from the saved composition's actual runtime;
    construction recomputes them and fails on any difference. No executable
    adoption follows until the exact Git consumer and capture are accepted.
    """
    from experiments.accepted_catalog_commerce.execution import Execution
    if product_details_open is not None and type(product_details_open) is not bool:
        raise ValueError('Product details setup requires a boolean')
    if product_details_heading is not None and (product_details_open is None or
            type(product_details_heading) is not str or not product_details_heading.strip()):
        raise ValueError('Product details heading requires a nonempty exact heading and open/closed choice')
    saved, output = Path(saved).resolve(), Path(output).resolve()
    world_path = saved / 'world.private.json'
    world_bytes = world_path.read_bytes()
    if sha256(world_bytes).hexdigest() != expected_world_sha256:
        raise ValueError('Saved world bytes changed')
    read = lambda name: json.loads((saved / name).read_bytes())
    world, domain = json.loads(world_bytes), read('checkout-domain.private.json')
    packet = compile_packet(world, spec, catalog=catalog, bindings=bindings, checkout_domain=domain,
        scoring_scope=scoring_scope, runtime_options=runtime_options, asset_sha256=asset_sha256)
    task = packet['task']
    if product_details_heading is not None and (task.get('public_fact') or {}).get('heading') != product_details_heading:
        raise ValueError('Product details heading differs from the native requested fact')
    message = task['user_message'] if user_message is None else user_message
    if type(message) is not str or not message.strip(): raise ValueError('Require nonempty public request')
    options = execution_options({'lazy_publication': True,
        'answer_grading': answer_grading or {'mode': 'off'}})
    if task['kind'].startswith('read_') and options['answer_grading']['mode'] != 'subscription-post-run':
        raise ValueError('Read tasks need automatic answer extraction before dispatch')
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
    # Default dispatch uses these reachable project sources too. The watch
    # module supplies read-only quota parsing/RPC; its scheduler is not invoked.
    dependencies += [root / 'experiments/external_agent/subscription_quota.py',
                     root / 'scripts/product_width_watch.py']
    for path in dependencies: sources[str(path.relative_to(root))] = sha256(path.read_bytes()).hexdigest()
    output.mkdir(parents=True, exist_ok=False)
    producer = Execution(validation='off').freeze(world, output / 'pin')
    (output / 'pin/world.private.json').write_bytes(world_bytes)
    producer['files']['world.private.json'] = expected_world_sha256
    (output / 'pin/manifest.json').write_text(json.dumps(producer, indent=2) + '\n')
    sources.update(producer['source_sha256'])
    for name, expected in sources.items():
        path = root / name
        payload = path.read_bytes()
        if sha256(payload).hexdigest() != expected: raise ValueError('Source changed: ' + name)
        target = output / 'pin/source-snapshot' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    records = {('presentation.json' if name == 'presentation.private.json' else name): read(name)
               for name in source_names if name != 'world.private.json'}
    setup = {'start': {'kind': 'product', 'offer_id': task['offer_id']},
             'selected_offer_id': task['setup']['selected_offer_id'],
             'prepared_cart': deepcopy(prepared_cart or [])}
    if product_details_open is not None:
        setup['product_details_open'] = product_details_open
    if product_details_heading is not None:
        setup['product_details_heading'] = product_details_heading
    records.update({'atomic-product-task.private.json': task,
        'atomic-product-reference.private.json': packet['reference'],
        'atomic-product-catalog.private.json': packet['catalog'],
        'atomic-product-bindings.private.json': packet['bindings'],
        'atomic-product-setup.private.json': setup, 'execution.private.json': options,
        'episode.json': {'task_id': task['task_id'], 'readable_origins': True,
            'start': task['start'], 'manual_task': {'user_message': message, 'memories': task['memories']}},
        'request.json': {'schema': VERSION, 'spec': deepcopy(spec), 'setup': setup,
            'original_inputs': original, 'world_draws': 0, 'scoring_scope': scoring_scope}})
    records['atomic-product-scoring-scope.private.json'] = scoring_scope
    if scoring_scope != 'whole_run':
        records['atomic-product-runtime-options.private.json'] = deepcopy(runtime_options)
        records['atomic-product-assets.private.json'] = deepcopy(asset_sha256)
    for name, value in records.items(): shared.save(output / name, value)
    for name in source_names:
        target = output / 'original-inputs' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = (saved / name).read_bytes()
        if sha256(payload).hexdigest() != original[str(saved / name)]:
            raise ValueError('Original changed during copy: ' + name)
        target.write_bytes(payload)
    for name, expected in original.items():
        if sha256(Path(name).read_bytes()).hexdigest() != expected: raise ValueError('Original changed: ' + name)
    for name, expected in sources.items():
        if (sha256((root/name).read_bytes()).hexdigest() != expected
                or sha256((output/'pin/source-snapshot'/name).read_bytes()).hexdigest() != expected):
            raise ValueError('Source changed before publication: ' + name)
    files = {str(p.relative_to(output)): sha256(p.read_bytes()).hexdigest()
             for p in output.rglob('*') if p.is_file() and not p.is_relative_to(output / 'pin/source-snapshot')}
    manifest = {'schema': 'website-world-generation-v2', **recipe_marker(),
        'world_id': world['world_id'], 'source_sha256': sources, 'files': files,
        'automatic_grader_supported': True, 'source_world_sha256': expected_world_sha256,
        'execution_policy': options, 'world_draws': 0,
        'effect_authority': ('unknown_broader_effects' if scoring_scope != 'whole_run' else 'exact_new_consumer_union_acceptance_required'),
        'config_sha256': digest(records['request.json'])}
    shared.save(output / 'manifest.json', manifest)
    return manifest
