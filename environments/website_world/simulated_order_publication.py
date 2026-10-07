"""Freeze explicit saved ordering instances without sampling or truth repair.

Evaluation supplies the original natural request and memories verbatim. Frozen
historical inputs survive; all fresh retail pages retain surrounding content.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil

from . import generation as shared, simulated_order_task as native
from . import simulated_order_execution  # retain the execution source closure
from .adapter import ROOT, PublicAdapter, digest
from .basket import Baskets

VERSION = 'website-simulated-order-publication-v1'


def source_files():
    """Include consumer-only imports in the fresh immutable source closure."""
    sources = shared.source_files()
    sources.update({str(path.relative_to(ROOT)): sha256(path.read_bytes()).hexdigest()
        for path in (ROOT/'environments/website_world').glob('*.py')})
    for name, expected in simulated_order_execution.quota_sources().items():
        if name in sources and sources[name] != expected:
            raise ValueError('Ordering quota source conflicts with publication: '+name)
        sources[name] = expected
    return sources


def basket_context(world, plan, domain, delivery_plan=None):
    """Use the unchanged central oracle/domain; do not construct browser pages."""
    catalog = world['schema_version'] == 'accepted-catalog-commerce-world-v1'
    if catalog:
        from experiments.accepted_catalog_commerce import basket_quote as provider
        from . import catalog_checkout_domain as domain_provider
    else:
        from experiments.footwear_world_pilot import basket_quote as provider
        from . import checkout_domain as domain_provider
    oracle = provider
    if delivery_plan is not None:
        from experiments.accepted_catalog_commerce import delivery_admission
        oracle = delivery_admission.Oracle(world, plan, delivery_plan)
    adapter = PublicAdapter(world, basket_plan=plan, oracle=oracle)
    return Baskets(adapter, plan, domain=domain, oracle=oracle,
                   domain_provider=domain_provider, delivery_plan=delivery_plan)


def prepare_saved(saved, output, *, spec, expected_world_sha256):
    """One fresh container around an exact saved world; no manufacture or retry.

    The initial consumer has no ordinary pre-policy coupon setup. A non-null
    fixed setup coupon is rejected explicitly rather than written into storage.
    References retain all admitted choices, ties and natural no-match unchanged.
    """
    saved, output = Path(saved).resolve(), Path(output).resolve()
    read = lambda name: json.loads((saved/name).read_bytes())
    world_path = next((path for path in (saved/'world.private.json', saved/'pin/world.private.json',
                                        saved/'pin/world.json') if path.is_file()), None)
    if world_path is None:
        raise ValueError('Saved packet has no native world artifact')
    if sha256(world_path.read_bytes()).hexdigest() != expected_world_sha256:
        raise ValueError('Saved world bytes differ from the declared input')
    world = json.loads(world_path.read_bytes())
    source_names = ['presentation.private.json' if (saved/'presentation.private.json').exists()
                    else 'presentation.json', 'surrounding.private.json',
                    'basket-plan.private.json', 'checkout-domain.private.json']
    if (saved/'delivery-plan.private.json').exists():
        source_names.append('delivery-plan.private.json')
    original = {str(world_path): expected_world_sha256,
        **{str(saved/name): sha256((saved/name).read_bytes()).hexdigest() for name in source_names}}
    presentation = read(source_names[0])
    surrounding = read('surrounding.private.json')
    plan, domain = read('basket-plan.private.json'), read('checkout-domain.private.json')
    delivery_plan = read('delivery-plan.private.json') if 'delivery-plan.private.json' in source_names else None
    baskets = basket_context(world, plan, domain, delivery_plan)
    task = native.make(baskets, spec)
    if task['coupon_code'] is not None:
        raise ValueError('Initial ordering publication has no fixed setup coupon support')
    reference = native.reference(baskets, task)
    setup = {'start': {'kind': 'cart'}, 'prepared_cart': [{
        'offer_id': spec['offer_id'], 'quantity': spec['quantity']}]}
    rid = task['retailer_id']
    from .presentation import site_plan
    compositions = {retailer['retailer_id']: site_plan(world, retailer, presentation,
        basket_policy=baskets.oracle.public_policy(plan, retailer['retailer_id']))
        for retailer in world['retailers']}
    catalog = world['schema_version'] == 'accepted-catalog-commerce-world-v1'
    if catalog:
        from experiments.accepted_catalog_commerce.execution import Execution
        execution = Execution(validation='off')
        execution_record = execution.record()
    else:
        execution_record = {'validation': 'native_plan_domain_task_reference',
                            'source_validation': 'fresh_exact_source_closure'}
    sources = source_files()
    output.mkdir(parents=True, exist_ok=False)
    if catalog:
        producer = execution.freeze(world, output/'pin')
        shutil.copyfile(world_path, output/'pin/world.private.json')
        producer['files']['world.private.json'] = expected_world_sha256
        (output/'pin/manifest.json').write_text(json.dumps(producer, indent=2, allow_nan=False)+'\n')
        for name, expected in producer['source_sha256'].items():
            if name in sources and sources[name] != expected:
                raise ValueError('Producer/Website source conflict during ordering freeze')
            sources[name] = expected
    else:
        (output/'pin').mkdir()
        shutil.copyfile(world_path, output/'pin/world.json')
        shared.save(output/'pin/manifest.json', {'schema': shared.VERSION, 'world_id': world['world_id'],
            'files': {'world.json': expected_world_sha256}, 'current_source_sha256': sources})
    for name, expected in sources.items():
        source = (ROOT/name).resolve()
        if not source.is_relative_to(ROOT) or sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError('Ordering source changed during freeze: '+name)
        archive = output/'pin/source-snapshot'/name
        archive.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, archive)
    request = {'schema': VERSION, 'operation': 'saved_world_publication',
        'saved_directory': str(saved), 'task': deepcopy(spec), 'original_sources': original,
        'world_draws': 0, 'source_world_sha256': expected_world_sha256}
    episode = {'start': {'kind': 'retailer_home', 'retailer_id': rid},
        'readable_origins': True, 'task_id': task['task_id'],
        'manual_task': {'user_message': task['user_message'], 'memories': task['memories']},
        'shopping_scope': next(r['name'] for r in world['retailers'] if r['retailer_id'] == rid)}
    records = {'request.json': request, 'episode.json': episode, 'presentation.json': presentation,
        'compositions.private.json': compositions, 'surrounding.private.json': surrounding,
        'basket-plan.private.json': plan, 'checkout-domain.private.json': domain,
        'simulated-order-task.private.json': task, 'simulated-order-reference.private.json': reference,
        'simulated-order-setup.private.json': setup,
        'execution.private.json': {**execution_record, 'answer_grading': {'mode': 'off'},
            'runtime_options': {'lazy_publication': catalog}, 'source_sha256': sources,
            'state_grading': 'prospective_once_only_native_order_grade', 'world_draws': 0},
        'generation-config.private.json': {'request': request, 'config_sha256': digest(request),
            'task_source': 'native_structured_template_with_verbatim_authored_request', 'recipe': VERSION},
        'sampling-audit.private.json': {'operation': 'saved_world_publication', 'world_draws': 0,
            'native_world_unmodified': True, 'source_world_sha256': expected_world_sha256}}
    if delivery_plan is not None:
        records['delivery-plan.private.json'] = delivery_plan
    if not catalog:
        records['reference.private.json'] = world['reference']
    for name, value in records.items():
        shared.save(output/name, value)
    inputs = output/'original-inputs'
    inputs.mkdir()
    for name, expected in original.items():
        source = Path(name)
        if sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError('Original saved input changed during ordering freeze')
        shutil.copyfile(source, inputs/source.name)
    manifest = {'schema': 'website-world-generation-v2' if catalog else shared.VERSION,
        'recipe': VERSION, 'simulated_order_recipe': VERSION, 'world_id': world['world_id'],
        'task_kind': task['kind'], 'files': {
            str(path.relative_to(output)): sha256(path.read_bytes()).hexdigest()
            for path in output.rglob('*') if path.is_file() and 'source-snapshot' not in path.parts},
        'source_sha256': sources, 'automatic_grader_supported': True,
        'effect_authority': 'exact_new_union_independent_acceptance_required',
        'native_reference_status': reference['status'], 'source_world_sha256': expected_world_sha256,
        'execution_policy': records['execution.private.json']}
    shared.save(output/'manifest.json', manifest)
    return manifest
