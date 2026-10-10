"""Additive feature recipes retaining natural address priors and drawn forms."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

from experiments.accepted_catalog_commerce.execution import _bind
from experiments.accepted_catalog_commerce.natural_address import NaturalAddressExecution
from . import natural_feature_generation as native, feature_offer_publication as feature

VERSION = 'website-natural-feature-publication-v1'


def compile_request(request):
    config = native.compile_request(request)
    return {**config, 'inventory': config['configuration']['inventory']}


def generate(request, *, world_factory=None):
    config = compile_request(request)
    result = _bind(native.generate, compile_request=lambda _: config)(
        request, world_factory=world_factory)
    result['feature_field_inventory'] = {
        k: deepcopy(getattr(config['inventory'], k)) for k in
        ('concept_id', 'fields', 'publication', 'known_paths', 'source_hashes')}
    return result


def _publication_execution(*, address_options, validation):
    """Give the existing freezer the released natural sampler dependency.

    Native generation still validates factory metadata. Consume only its exact
    declared address argument here; the producer draws the forms before return.
    """
    engine = NaturalAddressExecution(address_options=address_options, validation=validation)

    def generate(seed=0, *, address_options=None, **options):
        if address_options is not None and native.parameters(address_options) != engine.parameters:
            raise ValueError('Publication address priors changed after compilation')
        return engine.generate(seed, **options)

    return SimpleNamespace(generate=generate, freeze=engine.execution.freeze, record=engine.record)


def prepare(request, output, *, validation='off', answer_grading=None,
            lazy_publication=True):
    config = compile_request(request)
    execution = SimpleNamespace(**vars(feature.execution_generation))
    execution.prepare = _bind(execution.prepare, Execution=lambda *, validation:
        _publication_execution(address_options=config['address_options'], validation=validation))
    sampled = []

    def generate_once(request, *, world_factory=None):
        result = generate(request, world_factory=world_factory)
        sampled.append(result)
        return result

    # Keep the exact existing feature runtime and grader; the producer identity
    # and probability controls are private recipe metadata.
    freeze = _bind(feature.prepare, __file__=__file__, execution_generation=execution,
                   compile_request=compile_request, generate=generate_once)
    manifest = freeze(request, output, validation=validation,
                      answer_grading=answer_grading, lazy_publication=lazy_publication)
    result = sampled[0]
    metadata = {
        'version': VERSION, 'producer_version': native.VERSION,
        'address_options': deepcopy(config['address_options']),
        'natural_address': deepcopy(result['audit']['natural_address']),
        'requirements': deepcopy(request.get('requirements', [])),
        'task_conditioning': deepcopy(result['audit']['task_conditioning']),
        'request_sha256': feature.unified.shared.digest(request),
        'parameter_basis': 'Incorrect and missing probabilities are conditional on autofill; they may co-occur.',
        'initial_forms_repaired': False,
        'public_exposure': 'unknown'}
    output = Path(output).resolve()
    name = 'natural-address.private.json'
    if (output/name).exists():
        raise FileExistsError(output/name)
    feature.unified.shared.save(output/name, metadata)
    manifest['files'][name] = sha256((output/name).read_bytes()).hexdigest()
    manifest['natural_address_recipe'] = VERSION
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+'\n')
    return manifest
