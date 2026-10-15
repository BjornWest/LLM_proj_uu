"""Explicit new compact pins backed by a shared immutable source bundle."""
from pathlib import Path
import json

from . import model, basket_quote, package_export, source_bundle
from experiments import source_binding

VERSION = 'accepted-catalog-commerce-pin-v2'
ARTIFACTS = {'world.private.json', 'basket-plan.private.json',
             'accepted-entries.private.json', 'generation-input.private.json'}


def freeze(world, output, *, source_store, serialization='compact'):
    if serialization != 'compact':
        raise ValueError('V2 pins require compact world serialization')
    model.validate(world)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    sources = model.pin_sources(world)
    bundle = source_bundle.capture(sources, repository_root=package_export.ROOT, store=source_store)
    ledger = json.loads(package_export.LEDGER.read_text())
    artifacts = {'world.private.json': world, 'basket-plan.private.json': basket_quote.make_plan(world),
        'accepted-entries.private.json': {cid: ledger[cid]
            for cid in world['provenance']['accepted_package_gates'] if cid not in package_export.PILOTS},
        'generation-input.private.json': {'seed': world['seed'], 'concept_ids': world['config']['concept_ids'],
            'tasks': world['concentration_concepts'], 'controls': world['controls'],
            'city_id': world['user_location']['city_id'],
            'review_count': len(world['products'][0]['reviews']) if world['products'] else 0}}
    for name, value in artifacts.items():
        formatting = {'separators': (',', ':')} if name == 'world.private.json' else {'indent': 2}
        (output/name).write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, **formatting) + '\n')
    manifest = {'schema_version': VERSION, 'world_id': world['world_id'],
        'status': 'producer_candidate_consumer_acceptance_pending',
        'files': {n: package_export.digest_file(output/n) for n in artifacts},
        'source_sha256': sources, 'source_bundle': bundle, 'serialization': serialization,
        'summary': world['summary'], 'source_bytes': sum((package_export.ROOT/n).stat().st_size for n in sources),
        'model_inference_calls': 0, 'purchases': 0, 'limitations': world['limitations']}
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    return manifest


def load(output, *, source_store):
    output = Path(output).resolve()
    manifest = json.loads((output/'manifest.json').read_text())
    if manifest.get('schema_version') != VERSION or manifest.get('serialization') != 'compact':
        raise ValueError('Unsupported producer pin')
    if not isinstance(manifest.get('files'), dict) or set(manifest['files']) != ARTIFACTS:
        raise ValueError('Incomplete producer artifacts')
    for name, expected in manifest['files'].items():
        path = (output/name).resolve()
        if not path.is_relative_to(output) or package_export.digest_file(path) != expected:
            raise ValueError('Commerce pin artifact changed: ' + name)
    descriptor = manifest['source_bundle']
    if descriptor.get('schema_version') != source_bundle.VERSION:
        raise ValueError('Unsupported source bundle')
    bundle = source_bundle.open_bundle(descriptor['bundle_id'], store=source_store)
    if bundle.descriptor != descriptor or descriptor['source_sha256'] != manifest['source_sha256']:
        raise ValueError('Commerce source bundle binding changed')
    declared = manifest['source_sha256']
    manifest['source_sha256'], drift = source_binding.check(
        package_export.ROOT, declared, error='Commerce source changed: ',
        digest=package_export.digest_file, locate=source_bundle._path)
    if drift:
        manifest['source_binding'] = {'mode': source_binding.mode(), 'declared_source_sha256': declared,
                                      'code_drift': drift}
    world = json.loads((output/'world.private.json').read_text())
    model.validate(world)
    if world['world_id'] != manifest['world_id']:
        raise ValueError('Commerce pin identity differs')
    return world, manifest
