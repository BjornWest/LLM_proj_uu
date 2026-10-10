"""Freeze saved native address fixtures without sampling or modifying a world.

Prepared cart rows and presentation conditions are explicit pre-policy setup.
Native initial forms, full surrounding sites and original source files survive.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil

from experiments.accepted_catalog_commerce.execution import Execution, _bind
from . import atomic_shop_task as native
from . import generation as shared
from . import atomic_address_execution  # retain the additive execution closure
from .adapter import ROOT, digest
from .presentation import site_plan

VERSION = 'website-atomic-address-publication-v1'
ISOLATION = {'site.resetPolicy': ['preserve'], 'site.opaque': ['false'],
             'module.checkout': ['single']}


def compile_setup(world, spec, prepared_cart):
    task = native.make(world, spec)
    if type(prepared_cart) is not list or not prepared_cart:
        raise ValueError('Declare a nonempty prepared cart')
    retailer = next(r for r in world['retailers'] if r['retailer_id'] == task['retailer_id'])
    offers = {o['offer_id']: o for o in retailer['offers']}
    seen = set()
    for row in prepared_cart:
        if (type(row) is not dict or set(row) != {'offer_id', 'quantity'} or
                row['offer_id'] not in offers or type(row['quantity']) is not int or
                row['quantity'] <= 0 or row['offer_id'] in seen):
            raise ValueError('Use unique native target offers and positive integer quantities')
        seen.add(row['offer_id'])
        offer = offers[row['offer_id']]
        if not any(offer['stock_by_source'].values()) and not offer['supplier_order']['enabled']:
            raise ValueError('Unavailable offer cannot populate a prepared cart')
    return task


def prepare_saved(saved, output, *, spec, prepared_cart, expected_world_sha256,
                  fixture=None):
    """Fresh container only. Reuse accepted saved semantics; draw no worlds.

    The home descriptor is an internal base-constructor proxy. The additive
    episode replaces it with the declared cart URL before browser setup/policy.
    """
    saved, output = Path(saved).resolve(), Path(output).resolve()
    read = lambda name: json.loads((saved/name).read_bytes())
    world_path = saved/'world.private.json'
    if sha256(world_path.read_bytes()).hexdigest() != expected_world_sha256:
        raise ValueError('Saved world bytes differ from the released fixture')
    world = read('world.private.json')
    task = compile_setup(world, spec, prepared_cart)
    reference = native.reference(world, task)
    rid = task['retailer_id']
    source_names = ['world.private.json', 'presentation.private.json',
                    'surrounding.private.json', 'basket-plan.private.json',
                    'checkout-domain.private.json', 'request.json', 'resolved.json', 'audit.json']
    if (saved/'delivery-plan.private.json').exists():source_names.append('delivery-plan.private.json')
    original_pins = {str(saved/n): sha256((saved/n).read_bytes()).hexdigest() for n in source_names}
    if fixture is not None:
        fixture = Path(fixture).resolve()
        original_pins[str(fixture)] = sha256(fixture.read_bytes()).hexdigest()
    presentation = deepcopy(read('presentation.private.json'))
    presentation.setdefault('sites', {})[rid] = {'initial_form': 'producer', 'conditions': deepcopy(ISOLATION)}
    plan = read('basket-plan.private.json')
    from experiments.accepted_catalog_commerce import basket_quote, delivery_admission
    oracle = (delivery_admission.Oracle(world, plan, read('delivery-plan.private.json'))
              if 'delivery-plan.private.json' in source_names else basket_quote)
    compositions = {r['retailer_id']: site_plan(world, r, presentation,
        basket_policy=oracle.public_policy(plan, r['retailer_id'])) for r in world['retailers']}
    sources = shared.source_files()
    sources.update(_bind(shared.source_files, __file__=__file__)())
    # Runtime's private source inventory includes every local renderer/helper.
    sources.update({str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest()
                    for p in (ROOT/'environments/website_world').glob('*.py')})
    output.mkdir(parents=True, exist_ok=False)
    execution = Execution(validation='off')
    producer = execution.freeze(world, output/'pin')
    # Keep literal original world bytes as well as its semantic identity.
    shutil.copyfile(world_path, output/'pin/world.private.json')
    producer['files']['world.private.json'] = expected_world_sha256
    (output/'pin/manifest.json').write_text(json.dumps(producer, indent=2)+'\n')
    sources.update(producer['source_sha256'])
    for name, h in sources.items():
        source = ROOT/name
        if sha256(source.read_bytes()).hexdigest() != h:
            raise RuntimeError('Address consumer source changed during freeze: '+name)
        archive = output/'pin/source-snapshot'/name
        archive.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, archive)
    request = {'schema': VERSION, 'operation': 'saved_fixture_publication',
        'saved_directory': str(saved), 'seed': world['seed'], 'task': deepcopy(spec),
        'setup': {'start': {'kind': 'cart'}, 'prepared_cart': deepcopy(prepared_cart)},
        'presentation_conditions': deepcopy(ISOLATION), 'initial_form': 'producer',
        'original_sources': original_pins}
    episode = {'start': {'kind': 'retailer_home', 'retailer_id': rid},
        'readable_origins': True, 'task_id': task['task_id'],
        'manual_task': {'user_message': task['user_message'], 'memories': task['memories']},
        'shopping_scope': next(r['name'] for r in world['retailers'] if r['retailer_id'] == rid)}
    records = {'request.json': request, 'episode.json': episode,
        'presentation.json': presentation, 'compositions.private.json': compositions,
        'surrounding.private.json': read('surrounding.private.json'),
        'basket-plan.private.json': plan, 'checkout-domain.private.json': read('checkout-domain.private.json'),
        'atomic-address-task.private.json': task, 'atomic-address-reference.private.json': reference,
        # Container aliases retain existing raw capture/authority tooling.
        'catalog-cart-task.private.json': task, 'catalog-cart-reference.private.json': reference,
        'atomic-address-setup.private.json': request['setup'],
        'execution.private.json': {**execution.record(), 'answer_grading': {'mode': 'off'},
            'runtime_options': {'lazy_publication': True}, 'source_sha256': sources,
            'world_draws': 0, 'source_validation': 'exact saved fixture hash; native task and runtime validation retained'},
        'generation-config.private.json': {'request': request, 'config_sha256': digest(request),
            'task_source': 'native_structured_template', 'recipe': VERSION},
        'sampling-audit.private.json': {'operation': 'saved_fixture_publication',
            'world_draws': 0, 'native_world_unmodified': True, 'original_audit': read('audit.json')}}
    if 'delivery-plan.private.json' in source_names:records['delivery-plan.private.json'] = read('delivery-plan.private.json')
    for name, value in records.items():shared.save(output/name, value)
    for name in source_names:
        archive = output/'original-inputs'/name
        archive.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(saved/name, archive)
    if fixture is not None:shutil.copyfile(fixture, output/'original-inputs/fixture.json')
    for name, h in original_pins.items():
        if sha256(Path(name).read_bytes()).hexdigest() != h:raise RuntimeError('Original fixture changed: '+name)
    files = {str(p.relative_to(output)): sha256(p.read_bytes()).hexdigest()
             for p in output.rglob('*') if p.is_file() and 'source-snapshot' not in p.parts}
    manifest = {'schema': 'website-world-generation-v2',
        'recipe': 'website-catalog-cart-publication-v1', 'atomic_address_recipe': VERSION,
        'world_id': world['world_id'], 'task_kind': task['kind'], 'files': files,
        'source_sha256': sources, 'automatic_grader_supported': True,
        'effect_authority': 'exact_new_union_independent_acceptance_required',
        'source_world_sha256': expected_world_sha256, 'execution_policy': records['execution.private.json']}
    shared.save(output/'manifest.json', manifest)
    return manifest
