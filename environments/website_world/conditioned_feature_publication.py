"""Publish finite conditioned feature worlds through the existing feature recipe.

The producer owns proposal selection and conditioned compositions. This caller
retains those records and uses the unchanged feature runtime and answer grader.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from experiments.accepted_catalog_commerce.execution import _bind
from . import conditioned_feature_generation as native, feature_offer_publication as feature

VERSION = 'website-conditioned-feature-publication-v1'


def compile_request(request):
    return native.compile_request(request)


def generate(request, *, world_factory=None):
    config = compile_request(request)
    result = _bind(native.generate, compile_request=lambda _: config)(
        request, world_factory=world_factory)
    result['feature_field_inventory'] = {
        k: deepcopy(getattr(config['inventory'], k)) for k in
        ('concept_id', 'fields', 'publication', 'known_paths', 'source_hashes')}
    return result


def prepare(request, output, *, validation='off', answer_grading=None,
            lazy_publication=True):
    sampled = []

    def generate_once(request, *, world_factory=None):
        result = generate(request, world_factory=world_factory)
        sampled.append(result)
        return result

    # Keep the feature recipe identity: its exact existing runtime consumes this
    # packet. The additional producer identity belongs to private metadata.
    freeze = _bind(feature.prepare, __file__=__file__,
                   compile_request=compile_request, generate=generate_once)
    manifest = freeze(request, output, validation=validation,
                      answer_grading=answer_grading, lazy_publication=lazy_publication)
    result = sampled[0]
    metadata = {
        'version': VERSION, 'producer_version': native.VERSION,
        'requirements': deepcopy(request.get('requirements', [])),
        'task_conditioning': deepcopy(result['audit']['task_conditioning']),
        'request_sha256': feature.unified.shared.digest(request),
        'reference_sha256': feature.unified.shared.digest(result['feature_offer_reference']),
        'compositions_sha256': feature.unified.shared.digest(result['compositions']),
        'public_exposure': 'unknown',
        'qualification': 'Conditioned generation is not evidence of policy observation.'}
    output = Path(output).resolve()
    name = 'feature-conditioning.private.json'
    if (output/name).exists():
        raise FileExistsError(output/name)
    feature.unified.shared.save(output/name, metadata)
    manifest['files'][name] = sha256((output/name).read_bytes()).hexdigest()
    manifest['conditioning_recipe'] = VERSION
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+'\n')
    return manifest
