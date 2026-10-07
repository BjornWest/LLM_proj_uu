"""Opt-in compound recipes; native truth never certifies public readiness."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

from experiments.accepted_catalog_commerce.execution import _bind
from . import feature_offer_publication as feature
from . import catalog_compare_review_generation as native
from . import catalog_compare_review_execution  # include the additive execution closure
from .generation_configs import execution_options

VERSION = 'website-catalog-compare-review-publication-v1'
compile_request = native.compile_request


def _inventory(inventory):
    return {key: deepcopy(getattr(inventory, key)) for key in
            ('concept_id', 'fields', 'publication', 'known_paths', 'source_hashes')}


def generate(request, *, world_factory=None):
    config = compile_request(request)
    result = _bind(native.generate, compile_request=lambda _: config)(
        request, world_factory=world_factory)
    result['compare_review_field_inventory'] = _inventory(config['inventory'])
    reviews = config['review_inventory']
    result['compare_review_topic_inventory'] = {
        'concept_id': reviews.concept_id, 'topics': deepcopy(reviews.topics),
        'legacy': reviews.legacy, 'source_hashes': deepcopy(reviews.source_hashes),
        'field_inventory': _inventory(reviews.fields)}
    task = result['catalog_compare_review_task']
    result['required_obligations'] = deepcopy(task['required_obligations']) if task else []
    return result


def prepare(request, output, *, validation='off', answer_grading=None, lazy_publication=True):
    """Freeze one draw, including unsupported bindings and exact private roles.

    The inherited writer's temporary feature-shaped fields are all replaced.
    No proxy task, fallback product selection or public-sufficiency assertion is
    introduced. Readiness requires a separately accepted runtime audit.
    """
    options = execution_options({'validation': validation, 'answer_grading': answer_grading,
                                 'lazy_publication': lazy_publication})
    if options['answer_grading']['mode'] != 'subscription-post-run':
        raise ValueError('Attach automatic compound answer grading before preparation')
    sampled = []
    def feature_shape(request, *, world_factory=None):
        result = generate(request, world_factory=world_factory)
        sampled.append(result)
        return {**result,
            'feature_offer_task': result['catalog_compare_review_task'] or {'kind': native.native.KIND},
            # The old writer reads a match-status key; the compound reference
            # has no such key. This temporary envelope is replaced below with
            # the exact unchanged native reference, including authoritative null.
            'feature_offer_reference': {'status': result['compare_review_task_binding']['status'],
                **(result['catalog_compare_review_reference'] or {})},
            'feature_field_inventory': result['compare_review_field_inventory']}
    def writer_config(request):
        config = compile_request(request)
        # The historical writer knows only a field inventory. Include the
        # separately pinned review vocabulary/data without mutating either one.
        hashes = {**config['inventory'].source_hashes, **config['review_inventory'].source_hashes}
        for name in set(config['inventory'].source_hashes) & set(config['review_inventory'].source_hashes):
            if config['inventory'].source_hashes[name] != config['review_inventory'].source_hashes[name]:
                raise ValueError('Conflicting comparison/review declaration source: '+name)
        return {**config, 'inventory': SimpleNamespace(source_hashes=hashes)}
    freeze = _bind(feature.prepare, __file__=__file__, VERSION=VERSION,
                   compile_request=writer_config, generate=feature_shape)
    manifest = freeze(request, output, validation=validation,
                      answer_grading=answer_grading, lazy_publication=lazy_publication)
    if len(sampled) != 1:
        raise ValueError('Compound publication requires exactly one native draw')
    result, output = sampled[0], Path(output).resolve()
    for old, new, key in (
        ('feature-offer-task.private.json', 'catalog-compare-review-task.private.json', 'catalog_compare_review_task'),
        ('feature-offer-reference.private.json', 'catalog-compare-review-reference.private.json', 'catalog_compare_review_reference'),
        ('feature-field-inventory.private.json', 'compare-review-field-inventory.private.json', 'compare_review_field_inventory')):
        if (output/new).exists():
            raise FileExistsError(output/new)
        (output/old).rename(output/new)
        (output/new).write_text(json.dumps(result[key], indent=2, ensure_ascii=False, allow_nan=False)+'\n')
        manifest['files'].pop(old)
        manifest['files'][new] = sha256((output/new).read_bytes()).hexdigest()
    for name, key in (
        ('compare-review-binding.private.json', 'compare_review_task_binding'),
        ('compare-review-topic-inventory.private.json', 'compare_review_topic_inventory'),
        ('required-obligations.private.json', 'required_obligations')):
        feature.unified.shared.save(output/name, result[key])
        manifest['files'][name] = sha256((output/name).read_bytes()).hexdigest()
    manifest.update(compare_review_binding_status=result['compare_review_task_binding']['status'],
        automatic_grader_supported=result['compare_review_task_binding']['status'] == 'bound',
        public_readiness='requires_separate_runtime_audit',
        evidence_coverage='not_inferred_from_native_truth')
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False)+'\n')
    return manifest
