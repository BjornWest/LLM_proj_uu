"""Additive frozen review-summary recipes over the existing review publications."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from experiments.accepted_catalog_commerce.execution import _bind
from . import feature_offer_publication as feature, catalog_review_generation as native
from . import catalog_review_execution  # retain the complete execution source closure

VERSION = 'website-catalog-review-publication-v1'
compile_request = native.compile_request


def generate(request, *, world_factory=None):
    config = compile_request(request)
    result = _bind(native.generate, compile_request=lambda _: config)(request, world_factory=world_factory)
    inventory = config['inventory']
    # ReviewInventory.fields is a FieldInventory, not its fields dictionary.
    result['review_topic_inventory'] = {
        'concept_id': inventory.concept_id, 'topics': deepcopy(inventory.topics),
        'legacy': inventory.legacy, 'source_hashes': deepcopy(inventory.source_hashes),
        'field_inventory': {k: deepcopy(getattr(inventory.fields, k)) for k in
            ('concept_id', 'fields', 'publication', 'known_paths', 'source_hashes')}}
    result['resolved_configuration']['review_selection'] = deepcopy(config['selection'])
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
            'feature_offer_task': result['catalog_review_task'] or {'kind': native.native.KIND},
            'feature_offer_reference': result['catalog_review_reference'] or
                {'status': result['review_task_binding']['status']},
            'feature_field_inventory': result['review_topic_inventory']}
    freeze = _bind(feature.prepare, __file__=__file__, VERSION=VERSION,
                   compile_request=compile_request, generate=feature_shape)
    manifest = freeze(request, output, validation=validation,
        answer_grading=answer_grading, lazy_publication=lazy_publication)
    output = Path(output).resolve()
    for old, new, key in (
            ('feature-offer-task.private.json', 'catalog-review-task.private.json', 'catalog_review_task'),
            ('feature-offer-reference.private.json', 'catalog-review-reference.private.json', 'catalog_review_reference'),
            ('feature-field-inventory.private.json', 'review-topic-inventory.private.json', 'review_topic_inventory')):
        if (output/new).exists():
            raise FileExistsError(output/new)
        (output/old).rename(output/new)
        # Authoritative nulls are retained for unsupported manufactured subjects.
        (output/new).write_text(json.dumps(sampled[0][key], indent=2, ensure_ascii=False)+'\n')
        manifest['files'].pop(old)
        manifest['files'][new] = sha256((output/new).read_bytes()).hexdigest()
    name = 'catalog-review-binding.private.json'
    feature.unified.shared.save(output/name, sampled[0]['review_task_binding'])
    manifest['files'][name] = sha256((output/name).read_bytes()).hexdigest()
    manifest['review_binding_status'] = sampled[0]['review_task_binding']['status']
    manifest['automatic_grader_supported'] = manifest['review_binding_status'] == 'bound'
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+'\n')
    return manifest
