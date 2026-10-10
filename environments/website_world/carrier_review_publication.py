"""Freeze carrier tasks and the complete public profile corpus additively."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from experiments.accepted_catalog_commerce.execution import _bind
from . import feature_offer_publication as feature, carrier_review_generation as native
from . import carrier_review_execution  # retain the complete execution source closure

VERSION = 'website-carrier-review-publication-v1'
compile_request = native.compile_request


def generate(request, *, world_factory=None):
    config = compile_request(request)
    result = _bind(native.generate, compile_request=lambda _: config)(request, world_factory=world_factory)
    result['carrier_review_inventory'] = {'source_hashes': deepcopy(config['inventory'].source_hashes)}
    result['resolved_configuration']['carrier_review_selection'] = deepcopy(config['selection'])
    return result


def prepare(request, output, *, validation='off', answer_grading=None, lazy_publication=True):
    """Reuse the accepted new-output freeze without changing pages or shared recipes.

    Unsupported subjects/publications stay frozen and cannot launch. Temporary
    feature-shaped records serve only the inherited writer, never the public task.
    """
    sampled = []
    def feature_shape(request, *, world_factory=None):
        result = generate(request, world_factory=world_factory)
        sampled.append(result)
        return {**result,
            'feature_offer_task': result['carrier_review_task'] or {'kind': native.native.KIND},
            'feature_offer_reference': result['carrier_review_reference'] or
                {'status': result['carrier_review_binding']['status']},
            'feature_field_inventory': result['carrier_review_inventory']}
    freeze = _bind(feature.prepare, __file__=__file__, VERSION=VERSION,
                   compile_request=compile_request, generate=feature_shape)
    manifest = freeze(request, output, validation=validation,
        answer_grading=answer_grading, lazy_publication=lazy_publication)
    output = Path(output).resolve()
    for old, new, key in (
            ('feature-offer-task.private.json', 'carrier-review-task.private.json', 'carrier_review_task'),
            ('feature-offer-reference.private.json', 'carrier-review-reference.private.json', 'carrier_review_reference'),
            ('feature-field-inventory.private.json', 'carrier-review-inventory.private.json', 'carrier_review_inventory')):
        if (output/new).exists():
            raise FileExistsError(output/new)
        (output/old).rename(output/new)
        # Authoritative nulls are retained for unsupported carrier subjects.
        (output/new).write_text(json.dumps(sampled[0][key], indent=2, ensure_ascii=False)+'\n')
        manifest['files'].pop(old)
        manifest['files'][new] = sha256((output/new).read_bytes()).hexdigest()
    name = 'carrier-review-binding.private.json'
    feature.unified.shared.save(output/name, sampled[0]['carrier_review_binding'])
    manifest['files'][name] = sha256((output/name).read_bytes()).hexdigest()
    manifest['carrier_review_binding_status'] = sampled[0]['carrier_review_binding']['status']
    manifest['automatic_grader_supported'] = sampled[0]['carrier_review_task'] is not None
    name = 'carrier-publication.private.json'
    feature.unified.shared.save(output/name, sampled[0]['carrier_review_publication'])
    manifest['files'][name] = sha256((output/name).read_bytes()).hexdigest()
    manifest['carrier_publication_adoption'] = 'Runtime must validate and mount all carrier profiles before task launch'
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+'\n')
    return manifest
