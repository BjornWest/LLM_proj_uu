"""Additive memory recipes using the accepted feature freeze, with native public memories."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from experiments.accepted_catalog_commerce.execution import _bind
from . import feature_offer_publication as feature, memory_offer_generation as native
from . import memory_offer_execution  # include the complete execution closure

VERSION = 'website-memory-offer-publication-v1'
compile_request = _bind(feature.compile_request, native=native)


def generate(request, *, world_factory=None):
    config = compile_request(request)  # resolve recipient/defaults before any draw
    result = _bind(native.generate, compile_request=lambda _: config)(request, world_factory=world_factory)
    if config['requested_start'] is not None:
        result['resolved_configuration']['proxy_episode'] = deepcopy(result['resolved_configuration']['episode'])
        result['episode']['start'] = deepcopy(config['requested_start'])
        result['resolved_configuration']['episode']['start'] = deepcopy(config['requested_start'])
    task = result['memory_offer_task']
    scope = task['selection_task'].get('comparison_scope')
    if scope:
        result['episode']['shopping_scope'] = 'Products and retailer listings shown on ' + scope['site_name']
    result['resolved_configuration']['memory_offer_selection'] = deepcopy(config['spec'])
    result['memory_field_inventory'] = {k: deepcopy(getattr(config['inventory'], k))
        for k in ('concept_id', 'fields', 'publication', 'known_paths', 'source_hashes')}
    return result


def prepare(request, output, *, validation='off', answer_grading=None, lazy_publication=True):
    """Reuse the accepted new-output freeze; rename its fresh private task attachments.

    The feature generator's underlying task stays private implementation data.
    Only the native memory message/memories are authoritative for the episode.
    No historical files or module globals are modified.
    """
    def feature_shape(request, *, world_factory=None):
        result = generate(request, world_factory=world_factory)
        return {**result, 'feature_offer_task': result['memory_offer_task'],
            'feature_offer_reference': result['memory_offer_reference'],
            'feature_field_inventory': result['memory_field_inventory']}
    freeze = _bind(feature.prepare, __file__=__file__, VERSION=VERSION,
                   compile_request=compile_request, generate=feature_shape)
    manifest = freeze(request, output, validation=validation,
        answer_grading=answer_grading, lazy_publication=lazy_publication)
    output = Path(output).resolve()
    for old, new in (
            ('feature-offer-task.private.json', 'memory-offer-task.private.json'),
            ('feature-offer-reference.private.json', 'memory-offer-reference.private.json'),
            ('feature-field-inventory.private.json', 'memory-field-inventory.private.json')):
        if (output/new).exists():
            raise FileExistsError(output/new)
        (output/old).rename(output/new)
        expected = manifest['files'].pop(old)
        actual = sha256((output/new).read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError('Memory attachment bytes changed during freeze: '+new)
        manifest['files'][new] = actual
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+'\n')
    return manifest
